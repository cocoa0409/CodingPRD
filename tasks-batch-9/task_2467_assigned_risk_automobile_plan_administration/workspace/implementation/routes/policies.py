"""Policies: issuance, reclassification, cancellation, non-renewal and voluntary exit."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, days, new_row, touch, whole_days

bp = Blueprint("policies", __name__)

READ_ROLES = (
    "PlanAdministrator",
    "ComplianceExaminer",
    "ServicingCarrier",
    "ProducerAgent",
)
CANCEL_REASONS = (
    "NON_PAYMENT_OF_PREMIUM",
    "LICENSE_SUSPENDED",
    "MATERIAL_MISREPRESENTATION",
    "VEHICLE_NOT_GARAGED_IN_STATE",
    "INSURED_REQUEST",
    "PLAN_ORDERED",
)
INITIATED_BY_ROLE = {
    "ServicingCarrier": "CARRIER",
    "PlanAdministrator": "PLAN",
    "ProducerAgent": "INSURED",
}


@bp.post("/plan/policies")
def issue_policy():
    user_id, role = guards.authenticate(("ServicingCarrier",))
    data = guards.body()
    assignment_id = guards.req_str(data, "assignment_id")
    policy_number = guards.req_str(data, "policy_number", min_len=1, max_len=100)
    effective_date = guards.req_dt(data, "effective_date")
    expiration_date = guards.req_dt(data, "expiration_date")

    assignment = guards.need_assignment(assignment_id)
    guards.carrier_scope(role, user_id, assignment["carrier_id"])

    if assignment["status"] != "ACCEPTED":
        fail("ERR_INVALID_ASSIGNMENT_STATE")
    carrier = db.carriers[assignment["carrier_id"]]
    if domain.carrier_posture(carrier) == "SUSPENDED":
        fail("ERR_CARRIER_SUSPENDED")

    if expiration_date != effective_date + days(calc.DAYS_PER_YEAR):
        fail("ERR_POLICY_TERM_INVALID")
    if effective_date < db.clock:
        fail("ERR_POLICY_TERM_INVALID")

    application = db.applications[assignment["application_id"]]
    vehicle = db.vehicles[application["vehicle_id"]]

    # Half-open terms: adjacency is fine, any real intersection is not.
    for other in db.policies.values():
        other_application = db.applications.get(other["_application_id"])
        if other_application is None:
            continue
        if other_application["vehicle_id"] != vehicle["id"]:
            continue
        if effective_date < other["expiration_date"] and other["effective_date"] < expiration_date:
            fail("ERR_POLICY_TERM_OVERLAP")

    if vehicle["garaging_territory_code"] not in carrier["licensed_territories"]:
        fail("ERR_CARRIER_NOT_LICENSED_IN_TERRITORY")

    for other in db.policies.values():
        if other["policy_number"] == policy_number:
            fail("ERR_DUPLICATE_IDENTIFIER", "policy_number already exists.")

    row = new_row()
    row.update(
        {
            "assignment_id": assignment["id"],
            "carrier_id": carrier["id"],
            "policy_number": policy_number,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "policy_status": "IN_FORCE",
            "premium_settlement_status": "PREMIUM_OUTSTANDING",
            "surcharge_points_applied": 0,
            "surcharge_factor_applied": Decimal("1.00"),
            "premium_lines": {"BI": 0, "PD": 0, "UM": 0},
            "final_premium_cents": 0,
            "plan_expense_charge_cents": 0,
            "total_annual_charge_cents": 0,
            "premium_credited_cents": 0,
            "additional_premium_due_cents": 0,
            "refund_paid_cents": 0,
            "balance_due_cents": 0,
            "earned_premium_cents": 0,
            "refund_basis": None,
            "cancellation_reason_code": None,
            "cancellation_effective_date": None,
            "cancellation_initiated_by": None,
            "non_renewal_notice_count": 0,
            "non_renewal_effective_date": None,
            "rating_revision": 1,
            "reassignment_required": False,
            "_application_id": application["id"],
            "_current_assignment_id": assignment["id"],
        }
    )
    db.policies[row["id"]] = row

    domain.rate_policy(row)
    domain.sweep_deposit(application, row)
    domain.derive_money_axis(row)

    assignment["status"] = "POLICY_ISSUED"
    touch(assignment)
    application["status"] = "POLICY_ISSUED"
    touch(application)
    touch(carrier)
    return created(domain.policy_out(row))


@bp.get("/plan/policies")
def list_policies():
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    carrier_id = request.args.get("carrier_id")
    assignment_id = request.args.get("assignment_id")
    policy_status = request.args.get("policy_status")
    settlement = request.args.get("premium_settlement_status")

    rows = list(db.policies.values())
    if carrier_id is not None:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    if assignment_id is not None:
        rows = [r for r in rows if r["assignment_id"] == assignment_id]
    if policy_status is not None:
        rows = [r for r in rows if r["policy_status"] == policy_status]
    if settlement is not None:
        rows = [r for r in rows if r["premium_settlement_status"] == settlement]

    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.policy_out(r) for r in page], limit, offset, total)


@bp.get("/plan/policies/<policy_id>")
def read_policy(policy_id):
    guards.authenticate(READ_ROLES)
    policy = guards.need_policy(policy_id)
    return ok(domain.policy_out(policy))


@bp.post("/plan/policies/<policy_id>/reclassification")
def reclassify(policy_id):
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    expected_policy_version = guards.req_int(data, "expected_policy_version", minimum=0)
    driver_class = guards.req_enum(data, "reclassified_driver_class", guards.DRIVER_CLASSES)
    guards.req_dt(data, "reclassification_effective_date")
    policy = guards.need_policy(policy_id)

    if policy["policy_status"] != "IN_FORCE":
        fail("ERR_INVALID_POLICY_STATE")
    if expected_policy_version != policy["version"]:
        fail("ERR_STALE_POLICY_VERSION")

    application = domain.policy_application(policy)
    applicant = db.applicants[application["applicant_id"]]

    policy["rating_revision"] += 1
    domain.rate_policy(policy, driver_class=driver_class)

    total = policy["total_annual_charge_cents"]
    credited = policy["premium_credited_cents"]
    if total < credited:
        policy["refund_paid_cents"] += credited - total
        policy["premium_credited_cents"] = total
    domain.derive_money_axis(policy)

    applicant["driver_class"] = driver_class
    touch(applicant)
    touch(policy)
    return ok(domain.policy_out(policy))


@bp.post("/plan/policies/<policy_id>/cancellation")
def cancel_policy(policy_id):
    user_id, role = guards.authenticate(
        ("ServicingCarrier", "PlanAdministrator", "ProducerAgent")
    )
    data = guards.body()
    reason_code = guards.req_enum(data, "cancellation_reason_code", CANCEL_REASONS)
    cancellation_effective_date = guards.req_dt(data, "cancellation_effective_date")
    policy = guards.need_policy(policy_id)

    application = domain.policy_application(policy)
    guards.carrier_scope(role, user_id, policy["carrier_id"])
    guards.producer_scope(role, user_id, application["producer_id"])

    if policy["policy_status"] != "IN_FORCE":
        fail("ERR_INVALID_POLICY_STATE")
    if domain.policy_freeze_active(policy):
        fail("ERR_COMPLAINT_FREEZE_ACTIVE")

    elapsed = whole_days(cancellation_effective_date, policy["effective_date"])
    # PRD §3.x states the term-bound rule first and introduces the reason-code
    # restriction as a *further* restriction keyed on how far into the term the
    # cancellation falls, so the date must be inside the term before the elapsed
    # term position can restrict the reason code.
    if (
        cancellation_effective_date < policy["effective_date"]
        or cancellation_effective_date > policy["expiration_date"]
        or cancellation_effective_date < db.clock
    ):
        fail("ERR_CANCEL_DATE_OUT_OF_TERM")
    if elapsed > calc.FIRST_PERIOD_CANCEL_DAYS and reason_code not in calc.RESTRICTED_LATE_TERM_REASONS:
        fail("ERR_CANCEL_REASON_NOT_PERMITTED")

    initiated_by = INITIATED_BY_ROLE[role]
    refund_basis = "SHORT_RATE" if initiated_by == "INSURED" else "PRO_RATA"
    days_in_force = max(0, elapsed)
    earned = calc.earned_premium(
        policy["total_annual_charge_cents"], days_in_force, refund_basis
    )
    credited = policy["premium_credited_cents"]
    refund_delta = max(0, credited - earned)
    balance_due = max(0, earned - credited)

    policy["policy_status"] = "CANCELLED"
    policy["cancellation_reason_code"] = reason_code
    policy["cancellation_effective_date"] = cancellation_effective_date
    policy["cancellation_initiated_by"] = initiated_by
    policy["refund_basis"] = refund_basis
    policy["earned_premium_cents"] = earned
    policy["refund_paid_cents"] += refund_delta
    policy["balance_due_cents"] = balance_due
    policy["premium_credited_cents"] = min(credited, earned)
    policy["additional_premium_due_cents"] = 0
    if refund_delta > 0:
        policy["premium_settlement_status"] = "REFUND_ISSUED"
    elif balance_due > 0:
        policy["premium_settlement_status"] = "BALANCE_DUE_AT_CANCELLATION"
    else:
        policy["premium_settlement_status"] = "PAID_IN_FULL"
    touch(policy)

    domain.close_policy_assignment(policy)
    application["status"] = "CLOSED_CANCELLED"
    touch(application)
    domain.bubble_exit_complete(db.carriers.get(policy["carrier_id"]))
    return ok(domain.policy_out(policy))


@bp.post("/plan/policies/<policy_id>/non-renewal-notice")
def non_renewal_notice(policy_id):
    user_id, role = guards.authenticate(("ServicingCarrier",))
    data = guards.body()
    guards.req_str(data, "reason_note", min_len=1, max_len=2000)
    policy = guards.need_policy(policy_id)
    guards.carrier_scope(role, user_id, policy["carrier_id"])

    if policy["policy_status"] != "IN_FORCE" or policy["non_renewal_notice_count"] != 0:
        fail("ERR_INVALID_POLICY_STATE")
    if domain.policy_freeze_active(policy):
        fail("ERR_COMPLAINT_FREEZE_ACTIVE")
    if db.clock > policy["expiration_date"] - days(calc.NON_RENEWAL_NOTICE_LEAD_DAYS):
        fail("ERR_NON_RENEWAL_NOTICE_TOO_LATE")
    carrier = db.carriers[policy["carrier_id"]]
    if carrier["non_renewal_count_current_period"] >= calc.NON_RENEWAL_PERIOD_CAP:
        fail("ERR_NON_RENEWAL_QUOTA_EXCEEDED")

    policy["policy_status"] = "NON_RENEWAL_PENDING"
    policy["non_renewal_notice_count"] = 1
    policy["non_renewal_effective_date"] = policy["expiration_date"]
    touch(policy)
    carrier["non_renewal_count_current_period"] += 1
    touch(carrier)
    return ok(domain.policy_out(policy))


@bp.post("/plan/policies/<policy_id>/voluntary-exit")
def voluntary_exit(policy_id):
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    guards.opt_str(data, "exit_note", max_len=2000)
    policy = guards.need_policy(policy_id)

    if policy["policy_status"] != "IN_FORCE":
        fail("ERR_INVALID_POLICY_STATE")
    for claim in db.claims.values():
        if claim["policy_id"] == policy["id"] and claim["status"] in ("OPEN", "ACKNOWLEDGED"):
            fail("ERR_OPEN_CLAIM_BLOCKS_EXIT")

    application = domain.policy_application(policy)
    applicant = db.applicants[application["applicant_id"]]
    if domain.applicant_clean_years(applicant) < calc.VOLUNTARY_EXIT_MIN_CLEAN_YEARS:
        fail("ERR_CLEAN_YEARS_INSUFFICIENT")

    policy["policy_status"] = "EXITED_TO_VOLUNTARY"
    touch(policy)
    applicant["voluntary_market_eligible"] = True
    touch(applicant)

    domain.close_policy_assignment(policy)
    application["status"] = "CLOSED_EXITED"
    touch(application)

    vehicle = db.vehicles[application["vehicle_id"]]
    period = domain.current_period()
    underserved = period["underserved_territories"] if period else []
    credit = (
        calc.UNDERSERVED_CREDIT_MULTIPLIER
        if vehicle["garaging_territory_code"] in underserved
        else calc.STANDARD_CREDIT_UNITS
    )
    carrier = db.carriers[policy["carrier_id"]]
    carrier["voluntary_credit_units"] = calc.dec1(
        carrier["voluntary_credit_units"] + credit
    )
    touch(carrier)
    domain.bubble_exit_complete(carrier)
    return ok(domain.policy_out(policy))

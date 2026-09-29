"""Applications: submission, declinations, deposits, MVR, cure and certification."""

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, days, new_row, touch

bp = Blueprint("applications", __name__)

READ_ROLES = (
    "PlanAdministrator",
    "ComplianceExaminer",
    "ProducerAgent",
    "ServicingCarrier",
)
PRODUCER_ROLES = ("ProducerAgent", "PlanAdministrator")
REJECTION_REASONS = (
    "UNACCEPTABLE_DRIVING_RECORD",
    "UNDERWRITING_GUIDELINES",
    "NO_APPETITE_TERRITORY",
    "PRIOR_CANCELLATION",
)


@bp.post("/plan/applications")
def create_application():
    guards.authenticate(PRODUCER_ROLES)
    data = guards.body()
    applicant_id = guards.req_str(data, "applicant_id")
    producer_id = guards.req_str(data, "producer_id")
    vehicle_id = guards.req_str(data, "vehicle_id")
    requested_effective_date = guards.req_dt(data, "requested_effective_date")
    declared_violations = guards.req_violations(data, "declared_violations")

    applicant = guards.need_applicant(applicant_id)
    producer = guards.need_producer(producer_id)
    vehicle = guards.need_vehicle(vehicle_id)

    if vehicle["applicant_id"] != applicant["id"]:
        fail("ERR_VEHICLE_APPLICANT_MISMATCH")
    if producer["status"] != "ACTIVE":
        fail("ERR_PRODUCER_SUSPENDED")
    if applicant["territory_code"] not in producer["appointed_territories"]:
        fail("ERR_PRODUCER_TERRITORY_NOT_APPOINTED")

    row = new_row()
    row.update(
        {
            "applicant_id": applicant["id"],
            "producer_id": producer["id"],
            "vehicle_id": vehicle["id"],
            "intake_sequence": db.next_intake_sequence(),
            "requested_effective_date": requested_effective_date,
            "declared_violations": declared_violations,
            "verified_violations": None,
            "mvr_verified_at": None,
            "status": "SUBMITTED",
            "cure_count": 0,
            "certified_at": None,
            "certified_by_user_id": None,
            "rejection_reason_code": None,
            "surcharge_points_estimated": 0,
            "estimated_annual_premium_cents": 0,
            "estimated_expense_charge_cents": 0,
            "estimated_total_charge_cents": 0,
            "required_deposit_cents": 0,
            "deposit_paid_total_cents": 0,
            "deposit_balance_cents": 0,
            "_cure_note": None,
        }
    )
    db.applications[row["id"]] = row
    domain.recompute_estimate(row)
    domain.recompute_required_deposit(row)
    return created(domain.application_out(row))


@bp.get("/plan/applications")
def list_applications():
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    applicant_id = request.args.get("applicant_id")
    producer_id = request.args.get("producer_id")
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")

    rows = list(db.applications.values())
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if producer_id is not None:
        rows = [r for r in rows if r["producer_id"] == producer_id]
    if vehicle_id is not None:
        rows = [r for r in rows if r["vehicle_id"] == vehicle_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = domain.sort_applications(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.application_out(r) for r in page], limit, offset, total)


@bp.get("/plan/applications/<application_id>")
def read_application(application_id):
    guards.authenticate(READ_ROLES)
    application = guards.need_application(application_id)
    return ok(domain.application_out(application))


# --------------------------------------------------------- market rejections
@bp.post("/plan/applications/<application_id>/market-rejections")
def create_market_rejection(application_id):
    user_id, role = guards.authenticate(PRODUCER_ROLES)
    data = guards.body()
    naic_code = guards.req_str(
        data, "rejecting_carrier_naic_code", exact_len=5, pattern=r"^\d{5}$"
    )
    rejection_date = guards.req_dt(data, "rejection_date")
    reason_code = guards.req_enum(data, "reason_code", REJECTION_REASONS)
    document_reference = guards.req_str(data, "document_reference", min_len=1, max_len=200)
    application = guards.need_application(application_id)
    guards.producer_scope(role, user_id, application["producer_id"])

    known = any(c["naic_code"] == naic_code for c in db.carriers.values())
    if not known:
        fail("ERR_REJECTING_CARRIER_UNKNOWN")

    lower = db.clock - days(calc.VOLUNTARY_REJECTION_LOOKBACK_DAYS)
    for existing in db.market_rejections.values():
        if existing["application_id"] != application["id"]:
            continue
        if existing["rejecting_carrier_naic_code"] != naic_code:
            continue
        if lower <= existing["rejection_date"] <= db.clock:
            fail("ERR_DUPLICATE_REJECTING_CARRIER")

    row = new_row(versioned=False)
    row.update(
        {
            "application_id": application["id"],
            "rejecting_carrier_naic_code": naic_code,
            "rejection_date": rejection_date,
            "reason_code": reason_code,
            "document_reference": document_reference,
        }
    )
    db.market_rejections[row["id"]] = row
    # distinct_rejection_count is re-derived on read against the 90-day window.
    touch(application)
    return created(domain.market_rejection_out(row))


@bp.get("/plan/applications/<application_id>/market-rejections")
def list_market_rejections(application_id):
    guards.authenticate(("PlanAdministrator", "ComplianceExaminer", "ProducerAgent"))
    limit, offset = guards.pagination()
    application = guards.need_application(application_id)

    rows = [
        r
        for r in db.market_rejections.values()
        if r["application_id"] == application["id"]
    ]
    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.market_rejection_out(r) for r in page], limit, offset, total)


# ------------------------------------------------------------------ deposits
@bp.post("/plan/applications/<application_id>/deposit")
def record_deposit(application_id):
    user_id, role = guards.authenticate(PRODUCER_ROLES)
    data = guards.body()
    amount_cents = guards.req_int(data, "amount_cents")
    application = guards.need_application(application_id)
    guards.producer_scope(role, user_id, application["producer_id"])

    if amount_cents < 1:
        fail("ERR_DEPOSIT_AMOUNT_INVALID")

    application["deposit_paid_total_cents"] += amount_cents
    application["deposit_balance_cents"] += amount_cents
    domain.recompute_required_deposit(application)

    policy = domain.application_policy(application)
    if policy is not None:
        moved = domain.sweep_deposit(application, policy)
        domain.derive_money_axis(policy)
        if moved:
            touch(policy)
    touch(application)
    return ok(domain.application_out(application))


# ---------------------------------------------------------- MVR verification
@bp.post("/plan/applications/<application_id>/mvr-verification")
def mvr_verification(application_id):
    guards.authenticate(("ComplianceExaminer",))
    data = guards.body()
    verified_violations = guards.req_violations(data, "verified_violations")
    application = guards.need_application(application_id)

    if application["status"] != "SUBMITTED":
        fail("ERR_INVALID_APPLICATION_STATE")

    application["verified_violations"] = verified_violations
    application["mvr_verified_at"] = db.clock
    domain.recompute_estimate(application)
    domain.recompute_required_deposit(application)
    touch(application)
    # The applicant's chargeable-event history just changed.
    touch(db.applicants[application["applicant_id"]])
    return ok(domain.application_out(application))


# ------------------------------------------------------ eligibility decision
@bp.post("/plan/applications/<application_id>/certification")
def certification(application_id):
    user_id, _role = guards.authenticate(("ComplianceExaminer",))
    data = guards.body()
    decision = guards.req_enum(data, "decision", ("CERTIFY", "REJECT"))
    rejection_reason_code = guards.opt_str(data, "rejection_reason_code", max_len=100)
    application = guards.need_application(application_id)

    if application["status"] != "SUBMITTED":
        fail("ERR_INVALID_APPLICATION_STATE")
    if application["mvr_verified_at"] is None:
        fail("ERR_MVR_NOT_VERIFIED")

    if decision == "REJECT":
        application["status"] = "REJECTED"
        application["rejection_reason_code"] = rejection_reason_code
        application["certified_by_user_id"] = user_id
        touch(application)
        return ok(domain.application_out(application))

    if domain.app_distinct_rejection_count(application) < calc.MIN_DISTINCT_REJECTIONS:
        fail("ERR_INSUFFICIENT_MARKET_REJECTIONS")
    period = domain.open_period_for_clock()
    if period is None:
        fail("ERR_INVALID_PERIOD_STATE", "No OPEN plan period contains the clock.")
    if application["deposit_paid_total_cents"] < application["required_deposit_cents"]:
        fail("ERR_DEPOSIT_BELOW_REQUIRED")

    application["status"] = "CERTIFIED_AWAITING_ASSIGNMENT"
    application["certified_at"] = db.clock
    application["certified_by_user_id"] = user_id
    domain.recompute_estimate(application, rating_date=db.clock)
    touch(application)
    # total_assignable_units rose, so every ACTIVE carrier's quota target moved.
    touch(period)
    return ok(domain.application_out(application))


# ------------------------------------------------------- cure round-trip
@bp.post("/plan/applications/<application_id>/cure-return")
def cure_return(application_id):
    guards.authenticate(("ComplianceExaminer",))
    data = guards.body()
    cure_note = guards.req_str(data, "cure_note", min_len=1, max_len=2000)
    application = guards.need_application(application_id)

    if application["status"] != "SUBMITTED":
        fail("ERR_INVALID_APPLICATION_STATE")
    if application["cure_count"] >= calc.CURE_LIMIT:
        fail("ERR_CURE_LIMIT_EXCEEDED")

    application["status"] = "RETURNED_FOR_CURE"
    application["_cure_note"] = cure_note
    touch(application)
    return ok(domain.application_out(application))


@bp.post("/plan/applications/<application_id>/resubmission")
def resubmission(application_id):
    user_id, role = guards.authenticate(PRODUCER_ROLES)
    data = guards.body()
    declared_violations = guards.opt_violations(data, "declared_violations")
    requested_effective_date = guards.opt_dt(data, "requested_effective_date")
    application = guards.need_application(application_id)
    guards.producer_scope(role, user_id, application["producer_id"])

    if application["status"] != "RETURNED_FOR_CURE":
        fail("ERR_INVALID_APPLICATION_STATE")
    producer = db.producers[application["producer_id"]]
    if producer["status"] != "ACTIVE":
        fail("ERR_PRODUCER_SUSPENDED")

    if declared_violations is not None:
        application["declared_violations"] = declared_violations
    if requested_effective_date is not None:
        application["requested_effective_date"] = requested_effective_date
    application["status"] = "SUBMITTED"
    application["cure_count"] += 1
    # The cure may have changed the very record the examiner verified.
    application["verified_violations"] = None
    application["mvr_verified_at"] = None
    domain.recompute_estimate(application)
    domain.recompute_required_deposit(application)
    touch(application)
    return ok(domain.application_out(application))

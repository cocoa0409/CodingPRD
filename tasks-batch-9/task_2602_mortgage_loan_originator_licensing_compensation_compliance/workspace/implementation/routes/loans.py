"""The application pipeline and the compensation dimension (PRD 3.4, 3.5, 3.7).

A LoanApplication carries two independent state dimensions on one row: `status`
for origination and `compensation_status` for the commission ledger.
"""
from flask import Blueprint, g

import serializers
from db import create, db, sort_key, touch
from errors import ApiError
from middleware import ALL_ROLES, endpoint, identity_from_body, require_identity
from response import created, ok, paginated
from routes.common import filters, gate, get_or_404, get_referenced, listing, matches
from services import audit, authority, calc, cascade
from validators import Body, STATE_RE, body_fk, raw_body

bp = Blueprint("loans", __name__)

PRODUCT_TYPES = ("FIXED_30", "FIXED_15", "ARM_5_1", "FHA_30", "VA_30")
MIN_REQUESTED_CENTS = 1000000
MAX_REQUESTED_CENTS = 500000000
MIN_RATE_BPS = 100
MAX_RATE_BPS = 2000
RESOLVED_INVESTIGATION_STATUSES = ("UNSUBSTANTIATED", "REMEDIATED")


def _accrue_provisional(loan, originator, plan):
    """Create the single PROVISIONAL ledger line for a loan (PRD 3.5)."""
    amount, units = calc.provisional_inputs(loan)
    tier, base, impact, accrued = calc.accrual_line(plan, loan, amount, units)
    record = create(db.compensation_records, {
        "loan_application_id": loan["id"],
        "originator_id": originator["id"],
        "compensation_plan_id": plan["id"],
        "variant": "PROVISIONAL",
        "tier_bps_adder": tier,
        "base_comp_cents": base,
        "comp_impact_cents": impact,
        "accrued_cents": accrued,
        "paid_cents": 0,
        "clawback_cents": 0,
        "days_held": None,
        "recapture_pct": None,
        "status": "ACCRUED",
        "reconciled_at": None,
    })
    audit.append("CompensationRecord", record["id"], "COMP_ACCRUED",
                 {"loan_application_id": loan["id"],
                  "variant": "PROVISIONAL",
                  "tier_bps_adder": tier,
                  "accrued_cents": accrued})
    return record


@bp.route("/loan-applications", methods=["POST"])
@endpoint("Originator")
def take_application():
    raw = raw_body()
    identity_from_body(raw, "originator_id")
    originator_ref = body_fk(raw, "originator_id")
    originator = None
    if originator_ref is not None:
        originator = get_referenced(db.originators, originator_ref)
    body = Body(raw)
    body.string("originator_id")
    state_code = body.string("state_code", pattern=STATE_RE)
    borrower_reference = body.string("borrower_reference", min_len=1, max_len=40)
    product_type = body.enum("product_type", PRODUCT_TYPES)
    requested_amount_cents = body.integer("requested_amount_cents",
                                          minimum=MIN_REQUESTED_CENTS,
                                          maximum=MAX_REQUESTED_CENTS)
    par_rate_bps = body.integer("par_rate_bps", minimum=MIN_RATE_BPS, maximum=MAX_RATE_BPS)

    # Priorities 13 -> 14 -> 15, evaluated at the logical clock instant.
    failure = authority.authority_probe(originator, state_code)
    if failure is not None:
        raise ApiError(failure)

    row = create(db.loan_applications, {
        "originator_id": originator["id"],
        "compensation_plan_id": None,
        "state_code": state_code,
        "borrower_reference": borrower_reference,
        "application_taken_at": db.clock,
        "product_type": product_type,
        "requested_amount_cents": requested_amount_cents,
        "par_rate_bps": par_rate_bps,
        "note_rate_bps": None,
        "locked_amount_cents": None,
        "funded_amount_cents": None,
        "funded_at": None,
        "payoff_date": None,
        "lender_paid_comp_cents": 0,
        "borrower_paid_comp_cents": 0,
        "file_quality_score": 0,
        "hours_worked_pct": 0,
        "status": "TAKEN",
        "compensation_status": "NOT_APPLICABLE",
        "authority_flag": "VERIFIED",
        "closed_unit_index": None,
    })
    audit.append("LoanApplication", row["id"], "APPLICATION_TAKEN",
                 {"originator_id": originator["id"],
                  "state_code": state_code,
                  "product_type": product_type,
                  "requested_amount_cents": requested_amount_cents})
    return created(serializers.loan_application(row))


@bp.route("/loan-applications", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_applications():
    active = filters("originator_id", "compensation_plan_id", "state_code", "status",
                     "compensation_status")
    rows = listing(db.loan_applications, lambda r: matches(r, active))
    return paginated(rows, serializers.loan_application)


@bp.route("/loan-applications/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_application(row_id):
    row = get_or_404(db.loan_applications, row_id)
    return ok(serializers.loan_application(row))


@bp.route("/loan-applications/<row_id>/lock", methods=["POST"])
@endpoint("Originator")
def lock_application(row_id):
    loan = get_or_404(db.loan_applications, row_id)
    require_identity(loan["originator_id"])
    body = Body(raw_body())
    note_rate_bps = body.integer("note_rate_bps", minimum=0)
    locked_amount_cents = body.integer("locked_amount_cents", minimum=0)
    gate("LoanApplication", loan, ("TAKEN",))

    # Authority is re-verified from scratch: time has passed since intake.
    # Priorities 13 -> 14 -> 15 of PRD 2.9 are named for this endpoint, so they
    # answer ahead of the unnumbered authority_flag precondition below.
    originator = db.originators[loan["originator_id"]]
    failure = authority.authority_probe(originator, loan["state_code"])
    if failure is not None:
        raise ApiError(failure)
    if loan["authority_flag"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    loan["status"] = "LOCKED"
    loan["note_rate_bps"] = note_rate_bps
    loan["locked_amount_cents"] = locked_amount_cents
    # compensation_status is deliberately untouched: the dimensions are independent.
    touch(loan)
    return ok(serializers.loan_application(loan))


@bp.route("/loan-applications/<row_id>/close", methods=["POST"])
@endpoint("LoanOperations")
def close_application(row_id):
    loan = get_or_404(db.loan_applications, row_id)
    body = Body(raw_body())
    funded_amount_cents = body.integer("funded_amount_cents", minimum=0)
    funded_at = body.datetime("funded_at")
    lender_paid_comp_cents = body.integer("lender_paid_comp_cents", minimum=0)
    borrower_paid_comp_cents = body.integer("borrower_paid_comp_cents", minimum=0)
    file_quality_score = body.integer("file_quality_score", minimum=0, maximum=100)
    hours_worked_pct = body.integer("hours_worked_pct", minimum=0, maximum=100)
    gate("LoanApplication", loan, ("LOCKED",))

    originator = db.originators[loan["originator_id"]]
    dual = lender_paid_comp_cents > 0 and borrower_paid_comp_cents > 0

    # Priority 20 runs ahead of the plan checks and ahead of the fee cap.
    if dual and originator["monitoring_status"] == "ELEVATED":
        raise ApiError("ERR_DUAL_COMPENSATION_PROHIBITED")

    plan_id = originator["compensation_plan_id"]
    plan = db.compensation_plans.get(plan_id) if plan_id is not None else None
    if plan is not None:
        if plan["status"] != "ACTIVE":
            raise ApiError("ERR_PLAN_NOT_ACTIVE")
        # The assignment interval is CLOSED at both ends and must contain funded_at.
        start = plan["assignment_effective_from"]
        end = plan["assignment_effective_to"]
        if start is None or end is None or funded_at < start or funded_at > end:
            raise ApiError("ERR_PLAN_NOT_ACTIVE")
    if plan is None:
        raise ApiError("ERR_NO_ACTIVE_COMP_PLAN")
    if lender_paid_comp_cents + borrower_paid_comp_cents > plan["max_fee_cents"]:
        raise ApiError("ERR_COMP_CAP_EXCEEDED")

    already_closed = len([l for l in db.loan_applications.values()
                          if l["originator_id"] == originator["id"]
                          and l["status"] in calc.CLOSED_STATUSES])
    loan["status"] = "CLOSED"
    loan["funded_amount_cents"] = funded_amount_cents
    loan["funded_at"] = funded_at
    loan["lender_paid_comp_cents"] = lender_paid_comp_cents
    loan["borrower_paid_comp_cents"] = borrower_paid_comp_cents
    loan["file_quality_score"] = file_quality_score
    loan["hours_worked_pct"] = hours_worked_pct
    # The plan is pinned so a later reassignment cannot re-govern this file.
    loan["compensation_plan_id"] = plan["id"]
    loan["closed_unit_index"] = already_closed + 1
    touch(loan)

    if loan["authority_flag"] == "VERIFIED":
        loan["compensation_status"] = "ACCRUED"
        _accrue_provisional(loan, originator, plan)
    else:
        # Commission is withheld, not accrued: no ledger line at all.
        loan["compensation_status"] = "PENDING"

    calc.recompute_exposure(originator)
    touch(originator)
    return ok(serializers.loan_application(loan))


@bp.route("/loan-applications/<row_id>/payoff", methods=["POST"])
@endpoint("LoanOperations")
def payoff_application(row_id):
    loan = get_or_404(db.loan_applications, row_id)
    body = Body(raw_body())
    payoff_date = body.datetime("payoff_date")
    gate("LoanApplication", loan, ("CLOSED",))
    if loan["funded_at"] is None or payoff_date < loan["funded_at"]:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    loan["status"] = "PAID_OFF"
    loan["payoff_date"] = payoff_date
    touch(loan)
    cascade.payoff_clawback(loan, payoff_date)
    return ok(serializers.loan_application(loan))


@bp.route("/loan-applications/<row_id>/withdraw", methods=["POST"])
@endpoint("Originator")
def withdraw_application(row_id):
    loan = get_or_404(db.loan_applications, row_id)
    require_identity(loan["originator_id"])
    gate("LoanApplication", loan, ("TAKEN", "LOCKED"))
    loan["status"] = "WITHDRAWN"
    loan["compensation_status"] = "NOT_APPLICABLE"
    touch(loan)
    exceptions = [e for e in db.pricing_exceptions.values()
                  if e["loan_application_id"] == loan["id"] and e["status"] == "SUBMITTED"]
    exceptions.sort(key=sort_key)
    for exception in exceptions:
        exception["status"] = "WITHDRAWN"
        touch(exception)
    return ok(serializers.loan_application(loan))


@bp.route("/loan-applications/<row_id>/compensation-release", methods=["POST"])
@endpoint("ComplianceOfficer")
def release_compensation(row_id):
    loan = get_or_404(db.loan_applications, row_id)
    gate("LoanApplication", loan, calc.CLOSED_STATUSES)
    if loan["compensation_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Cross-aggregate guard: every investigation on this loan must have cleared.
    for investigation in db.investigations.values():
        if investigation["loan_application_id"] != loan["id"]:
            continue
        if investigation["status"] not in RESOLVED_INVESTIGATION_STATUSES:
            raise ApiError("ERR_UNLICENSED_ACTIVITY_OPEN")

    originator = db.originators[loan["originator_id"]]
    plan = db.compensation_plans.get(loan["compensation_plan_id"])
    loan["authority_flag"] = "VERIFIED"
    loan["compensation_status"] = "ACCRUED"
    touch(loan)
    if plan is not None:
        _accrue_provisional(loan, originator, plan)
    calc.recompute_exposure(originator)
    touch(originator)
    return ok(serializers.loan_application(loan))

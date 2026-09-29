"""Pricing exceptions, documented justification and concession absorption
(PRD 3.6)."""
from flask import Blueprint, g

import serializers
from db import create, db, touch
from errors import ApiError
from middleware import ALL_ROLES, endpoint, require_identity
from response import created, ok, paginated
from routes.common import filters, gate, get_or_404, listing, matches
from services import audit, calc
from validators import Body, raw_body

bp = Blueprint("pricing", __name__)

REASON_CODES = ("COMPETITIVE_MATCH", "SERVICE_ISSUE", "PRICING_ERROR",
                "UNDERWRITING_DELAY", "RELATIONSHIP_PRICING")
DECISIONS = ("APPROVE", "DENY")
HEAVY_REASON = "PRICING_ERROR"
HEAVY_JUSTIFICATION_MIN = 120
MIN_RATE_BPS = 100
MAX_RATE_BPS = 2000
MIN_CONCESSION_CENTS = 1
MAX_CONCESSION_CENTS = 2000000


@bp.route("/loan-applications/<loan_id>/pricing-exceptions", methods=["POST"])
@endpoint("Originator")
def file_exception(loan_id):
    loan = get_or_404(db.loan_applications, loan_id)
    require_identity(loan["originator_id"])
    body = Body(raw_body())
    requested_rate_bps = body.integer("requested_rate_bps", minimum=MIN_RATE_BPS,
                                      maximum=MAX_RATE_BPS)
    concession_cents = body.integer("concession_cents", minimum=MIN_CONCESSION_CENTS,
                                    maximum=MAX_CONCESSION_CENTS)
    reason_code = body.enum("reason_code", REASON_CODES)
    justification_text = body.string("justification_text", min_len=40, max_len=2000)

    # The loan must be LOCKED so that locked_amount_cents is non-null.
    gate("LoanApplication", loan, ("LOCKED",))

    # Priority 19 is reported ahead of priority 34.
    if reason_code == HEAVY_REASON and len(justification_text) < HEAVY_JUSTIFICATION_MIN:
        raise ApiError("ERR_JUSTIFICATION_INSUFFICIENT")
    if concession_cents > calc.concession_cap_cents(loan["locked_amount_cents"]):
        raise ApiError("ERR_CONCESSION_EXCEEDS_CAP")

    originator = db.originators[loan["originator_id"]]
    row = create(db.pricing_exceptions, {
        "loan_application_id": loan["id"],
        "requested_by_user_id": g.user_id,
        "requested_rate_bps": requested_rate_bps,
        "concession_cents": concession_cents,
        "reason_code": reason_code,
        "justification_text": justification_text,
        "status": "SUBMITTED",
        "requires_second_approval": originator["monitoring_status"] == "ELEVATED",
        "decided_by_user_id": None,
        "second_decided_by_user_id": None,
        "decided_at": None,
        "decision_note": None,
        "comp_impact_cents": 0,
    })
    return created(serializers.pricing_exception(row))


@bp.route("/pricing-exceptions", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_exceptions():
    active = filters("loan_application_id", "status")
    rows = listing(db.pricing_exceptions, lambda r: matches(r, active))
    return paginated(rows, serializers.pricing_exception)


@bp.route("/pricing-exceptions/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_exception(row_id):
    row = get_or_404(db.pricing_exceptions, row_id)
    return ok(serializers.pricing_exception(row))


@bp.route("/pricing-exceptions/<row_id>/decisions", methods=["POST"])
@endpoint("ComplianceOfficer")
def decide_exception(row_id):
    exception = get_or_404(db.pricing_exceptions, row_id)
    body = Body(raw_body())
    decision = body.enum("decision", DECISIONS)
    decision_note = body.string("decision_note", min_len=1, max_len=2000)
    second_approver = body.string("second_approver_user_id", required=False, default=None,
                                  max_len=64)
    gate("PricingException", exception, ("SUBMITTED",))

    loan = db.loan_applications.get(exception["loan_application_id"])
    detail = {"decision": decision, "decision_note": decision_note}

    if decision == "DENY":
        # A denial must always be recordable, whatever became of the file.
        if g.user_id == exception["requested_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        exception["status"] = "DENIED"
        exception["decided_by_user_id"] = g.user_id
        exception["decided_at"] = db.clock
        exception["decision_note"] = decision_note
        touch(exception)
        audit.append("PricingException", exception["id"], "EXCEPTION_DECIDED", detail)
        return ok(serializers.pricing_exception(exception))

    if loan is None or loan["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Priority 17 is reported ahead of priority 18.
    if g.user_id == exception["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if exception["requires_second_approval"]:
        if second_approver is not None and second_approver.strip() != "":
            if second_approver in (g.user_id, exception["requested_by_user_id"]):
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        else:
            raise ApiError("ERR_SECOND_APPROVAL_REQUIRED")

    originator = db.originators[loan["originator_id"]]
    plan = db.compensation_plans.get(originator["compensation_plan_id"]) \
        if originator["compensation_plan_id"] is not None else None
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    comp_impact, net_comp = calc.pricing_exception_impact(plan, loan, exception)
    exception["status"] = "APPROVED"
    exception["decided_by_user_id"] = g.user_id
    exception["decided_at"] = db.clock
    exception["decision_note"] = decision_note
    exception["second_decided_by_user_id"] = (
        second_approver if exception["requires_second_approval"] else None)
    exception["comp_impact_cents"] = comp_impact
    touch(exception)
    calc.recompute_exposure(originator)
    touch(originator)
    detail["comp_impact_cents"] = comp_impact
    detail["net_comp_cents"] = net_comp
    audit.append("PricingException", exception["id"], "EXCEPTION_DECIDED", detail)
    return ok(serializers.pricing_exception(exception))


@bp.route("/pricing-exceptions/<row_id>/withdraw", methods=["POST"])
@endpoint("Originator")
def withdraw_exception(row_id):
    exception = get_or_404(db.pricing_exceptions, row_id)
    require_identity(exception["requested_by_user_id"])
    gate("PricingException", exception, ("SUBMITTED",))
    exception["status"] = "WITHDRAWN"
    touch(exception)
    return ok(serializers.pricing_exception(exception))

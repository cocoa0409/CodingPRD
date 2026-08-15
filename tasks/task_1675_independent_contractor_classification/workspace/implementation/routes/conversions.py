"""ConversionCase endpoints."""

from flask import Blueprint, request

from db import store, new_id
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_CONVERSION_NOT_POSSIBLE,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_engagement_or_404, compute_lookback,
)

bp = Blueprint("conversions", __name__)

NON_TERMINAL_ENGAGEMENT = {
    "DRAFT", "INTAKE_SUBMITTED", "CLASSIFIED", "UNDER_REVIEW",
    "INFO_REQUESTED", "APPROVAL_PENDING", "APPROVED",
}


@bp.route("/api/engagements/<eid>/conversions", methods=["POST"])
def create_conversion(eid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    quarters = body.get("lookback_quarters")
    if not isinstance(quarters, list) or len(quarters) != 4:
        raise ApiError(ERR_INVALID_REQUEST, 400, "lookback_quarters must have exactly 4 entries")
    for q in quarters:
        if not isinstance(q, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid quarter entry")
        if not isinstance(q.get("quarter_label"), str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "quarter_label is required")
        fee = q.get("service_fee_cents")
        if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "service_fee_cents must be an integer >= 0")

    eng = get_engagement_or_404(eid)
    if eng["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_CONVERSION_NOT_POSSIBLE, 409,
                       "Conversion requires ACTIVE or SUSPENDED engagement")

    w2_total, delta = compute_lookback(quarters)
    case = {
        "id": new_id(),
        "engagement_id": eid,
        "lookback_quarters": quarters,
        "w2_equivalent_total_cents": w2_total,
        "lookback_delta_cents": delta,
        "offer_salary_cents": None,
        "status": "INITIATED",
    }
    stamp_new(case)
    store.conversions[case["id"]] = case
    return success(case, status=201)


@bp.route("/api/engagements/<eid>/conversions", methods=["GET"])
def list_conversions(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    items = [c for c in store.conversions.values() if c["engagement_id"] == eid]
    items.sort(key=lambda c: c["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/conversions/<cid>/extend-offer", methods=["POST"])
def extend_offer(cid):
    require_auth(["HRApprover"])
    body = request.get_json(silent=True) or {}
    salary = body.get("offer_salary_cents")
    if salary is None or not isinstance(salary, int) or isinstance(salary, bool) or salary < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "offer_salary_cents must be an integer >= 0")
    case = store.conversions.get(cid)
    if case is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Conversion case not found")
    if case["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409, "extend-offer requires INITIATED")
    case["offer_salary_cents"] = salary
    case["status"] = "OFFER_EXTENDED"
    touch(case)
    return success(case)


@bp.route("/api/conversions/<cid>/record-decision", methods=["POST"])
def record_decision(cid):
    require_auth(["EngagementManager"])
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("ACCEPTED", "DECLINED", "RESCINDED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "decision must be ACCEPTED, DECLINED, or RESCINDED")
    case = store.conversions.get(cid)
    if case is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Conversion case not found")
    if case["status"] != "OFFER_EXTENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "record-decision requires OFFER_EXTENDED")

    if decision == "DECLINED":
        case["status"] = "DECLINED"
        touch(case)
        return success(case)
    if decision == "RESCINDED":
        case["status"] = "RESCINDED"
        touch(case)
        return success(case)

    # ACCEPTED — engagement must be ACTIVE
    eng = store.engagements.get(case["engagement_id"])
    if eng is None or eng["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement must be ACTIVE to accept conversion")

    case["status"] = "COMPLETED"
    touch(case)

    # cascade link 1: engagement ACTIVE -> CONVERTED
    eng["status"] = "CONVERTED"
    touch(eng)

    # cascade link 2: contractor standing -> CONVERTED_TO_EMPLOYEE
    contractor = store.contractors.get(eng["contractor_id"])
    if contractor is not None and contractor["standing_status"] != "CONVERTED_TO_EMPLOYEE":
        contractor["standing_status"] = "CONVERTED_TO_EMPLOYEE"
        touch(contractor)

    # cascade link 3: other non-terminal engagements of same contractor -> REJECTED
    for other in store.engagements.values():
        if other["id"] == eng["id"]:
            continue
        if other["contractor_id"] != eng["contractor_id"]:
            continue
        if other["status"] in NON_TERMINAL_ENGAGEMENT:
            other["status"] = "REJECTED"
            touch(other)

    return success(case)

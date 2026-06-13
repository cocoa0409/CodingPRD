from flask import Blueprint

from db import store, now_iso
import errors
import middleware
import response
from services import validate
from services.entities import get_activity_category
from services.serialize import public, public_list

bp = Blueprint("activity_categories", __name__)


@bp.route("/activity-categories", methods=["POST"])
def create_activity_category():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    data = validate.body()

    # well-formedness (400)
    code = validate.require_str(data, "code")
    risk_tier = validate.require(data, "risk_tier")
    activity_base_risk = validate.require(data, "activity_base_risk")
    required_inspection_count = validate.require(data, "required_inspection_count")
    requires_zoning_check = validate.require_bool(data, "requires_zoning_check")
    term_months = validate.require(data, "term_months")
    allowed_zones = validate.require_array(data, "allowed_zones")

    # type checks (400)
    if isinstance(activity_base_risk, bool) or not isinstance(activity_base_risk, int):
        raise errors.invalid_request("activity_base_risk must be an integer")
    if isinstance(required_inspection_count, bool) or not isinstance(required_inspection_count, int):
        raise errors.invalid_request("required_inspection_count must be an integer")
    if isinstance(risk_tier, bool) or not isinstance(risk_tier, str):
        raise errors.invalid_request("risk_tier must be a string")
    if isinstance(term_months, bool) or not isinstance(term_months, int):
        raise errors.invalid_request("term_months must be an integer")
    for z in allowed_zones:
        if not isinstance(z, str):
            raise errors.invalid_request("allowed_zones must be an array of strings")

    # semantic bounds (422)
    if risk_tier not in validate.RISK_TIERS:
        raise errors.validation("risk_tier must be one of LOW, MEDIUM, HIGH")
    if term_months not in validate.TERM_MONTHS:
        raise errors.validation("term_months must be one of 12, 24, 36")
    if activity_base_risk < 0 or activity_base_risk > 40:
        raise errors.validation("activity_base_risk must be within 0..40")
    if required_inspection_count < 0 or required_inspection_count > 5:
        raise errors.validation("required_inspection_count must be within 0..5")
    if len(allowed_zones) == 0:
        raise errors.validation("allowed_zones must be non-empty")

    # uniqueness (409) — business rule tier
    for cat in store.activity_categories.values():
        if cat["code"] == code:
            raise errors.ApiError(errors.ERR_DUPLICATE_ACTIVITY_CODE, 409,
                                  "Activity code already exists")

    rec = {
        "id": store.new_id(),
        "created_at": now_iso(),
        "code": code,
        "risk_tier": risk_tier,
        "activity_base_risk": activity_base_risk,
        "required_inspection_count": required_inspection_count,
        "requires_zoning_check": requires_zoning_check,
        "term_months": term_months,
        "allowed_zones": list(allowed_zones),
    }
    store.activity_categories[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@bp.route("/activity-categories/<cid>", methods=["GET"])
def get_one(cid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "InspectionOfficer", "Applicant"])
    rec = get_activity_category(cid)
    return response.object_response(public(rec), 200)


@bp.route("/activity-categories", methods=["GET"])
def list_all():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "InspectionOfficer", "Applicant"])
    limit, offset = middleware.parse_pagination()
    items = sorted(store.activity_categories.values(), key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)

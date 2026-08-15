"""Properties and the logical-clock endpoint."""

from flask import Blueprint, request

from clock import set_now
from db import store
from errors import ApiError, ERR_PROPERTY_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_role
from response import ok, ok_list, parse_pagination, paginate
from services.validation import (
    compute_posture,
    get_json_body,
    new_entity,
    not_found,
    req_enum,
    req_str,
    run_lazy_effects,
)

bp = Blueprint("properties", __name__)

SALE_SHARE_DESIGNATIONS = ("SELLS_AND_SHARES", "SHARES_ONLY", "NO_SALE_NO_SHARE")


def _with_posture(prop):
    """Posture is computed: FROZEN while any sweep of the property is ESCALATED."""
    prop["posture"] = compute_posture(prop["id"])
    return prop


@bp.post("/v1/properties")
def create_property():
    require_role("PrivacyAdmin")
    body = get_json_body()
    name = req_str(body, "name")
    designation = req_enum(body, "sale_share_designation", SALE_SHARE_DESIGNATIONS)
    prop = new_entity(
        {
            "name": name,
            "sale_share_designation": designation,
            "posture": "NORMAL",
            "granted_purpose_count": 0,
        }
    )
    store["properties"][prop["id"]] = prop
    return ok(prop, 201)


@bp.get("/v1/properties")
def list_properties():
    require_role("Any")
    run_lazy_effects()
    limit, offset = parse_pagination(request.args)
    page, total = paginate(list(store["properties"].values()), limit, offset)
    return ok_list([_with_posture(p) for p in page], total, limit, offset)


@bp.get("/v1/properties/<id>")
def get_property(id):
    require_role("Any")
    # Lazy deadline escalation must be reflected on read (PRD §2.4).
    run_lazy_effects()
    prop = store["properties"].get(id)
    if prop is None:
        not_found("properties", ERR_PROPERTY_NOT_FOUND)
    return ok(_with_posture(prop))


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    require_role("PrivacyAdmin")
    body = get_json_body()
    iso = req_str(body, "to_iso8601")
    try:
        current = set_now(iso)
    except (ValueError, TypeError):
        raise ApiError(
            ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime", 400
        )
    # Clock-set evaluates lazy compliance effects at the new instant (§2.4).
    run_lazy_effects()
    return ok({"current_utc": current}, 200)

"""Property endpoints (PRD §3.1)."""

from flask import Blueprint

from db import store
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body, parse_pagination
from response import object_response, array_response
from services import validate
from services.domain import _common_create_fields, public
from services.listing import paginate

bp = Blueprint("properties", __name__)

ALL_ROLES = {
    "PlatformAdmin",
    "ClientContact",
    "Inspector",
    "MitigationDesigner",
    "CrewLead",
    "ComplianceOfficer",
}
FOUNDATIONS = {"SLAB", "BASEMENT", "CRAWLSPACE"}


@bp.route("/properties", methods=["POST"])
def create_property():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "ClientContact"})
    body = get_json_body()

    address_line = validate.require_string(body, "address_line")
    foundation_type = validate.require_enum(body, "foundation_type", FOUNDATIONS)
    floor_area_sqft = validate.require_int(body, "floor_area_sqft", minimum=1)
    is_ret = validate.optional_bool(body, "is_real_estate_transaction", False)

    # closing_deadline_utc required when is_real_estate_transaction is true (PRD §3.1).
    if is_ret:
        closing = validate.require_datetime(body, "closing_deadline_utc")
    else:
        closing = validate.optional_datetime(body, "closing_deadline_utc", None)

    entity = _common_create_fields()
    entity.update(
        {
            "address_line": address_line,
            "foundation_type": foundation_type,
            "floor_area_sqft": floor_area_sqft,
            "is_real_estate_transaction": is_ret,
            "closing_deadline_utc": _fmt(closing),
            "_closing_dt": closing,
            "posture": "OPEN",
            "latest_result_pci_l": None,
            "open_test_count": 0,
        }
    )
    store.properties[entity["id"]] = entity
    return object_response(public(entity), 201)


@bp.route("/properties/<property_id>", methods=["GET"])
def get_property(property_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    prop = store.properties.get(property_id)
    if prop is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Property not found.")
    return object_response(public(prop), 200)


@bp.route("/properties", methods=["GET"])
def list_properties():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "ClientContact"})
    limit, offset = parse_pagination()
    items, total = paginate(store.properties, {}, limit, offset)
    return array_response(items, limit, offset, total, 200)


def _fmt(dt):
    if dt is None:
        return None
    from db import format_iso8601_millis
    return format_iso8601_millis(dt)

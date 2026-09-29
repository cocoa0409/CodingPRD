"""AccessZone endpoints (PRD 3.1)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc
from errors import ApiError
from middleware import ANY_ROLE, auth, f_enum, f_int, f_number, f_str, get_body, q
from response import ok
from services.domain import get_or_404, zones_of_event
from routes._common import filter_eq, paginated

bp = Blueprint("zones", __name__)


@bp.route("/events/<event_id>/access-zones", methods=["POST"])
def create_zone(event_id):
    auth(("VenueAdmin",))
    body = get_body()
    zone_code = f_str(body, "zone_code", allow_empty=False)
    level = f_enum(body, "required_entitlement_level", ("GA", "PREMIUM", "BACK_OF_HOUSE"))
    fire_code_capacity = f_int(body, "fire_code_capacity", minimum=1)
    face_value_reference_cents = f_int(body, "face_value_reference_cents", minimum=0)
    credential_capacity = f_int(body, "credential_capacity", required=False, default=0, minimum=0)
    comp_discount_pct = f_number(
        body, "comp_discount_pct", required=False, default=0.85, minimum=0, maximum=1
    )

    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    if event["status"] != "DRAFT":
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    for zone in zones_of_event(event_id):
        if zone["zone_code"] == zone_code:
            raise ApiError("ERR_DUPLICATE_CODE", "zone_code is already used in this event.")

    rec = base_record()
    rec["event_id"] = event_id
    rec["zone_code"] = zone_code
    rec["required_entitlement_level"] = level
    rec["fire_code_capacity"] = fire_code_capacity
    rec["credential_capacity"] = credential_capacity
    rec["face_value_reference_cents"] = face_value_reference_cents
    rec["comp_discount_pct"] = comp_discount_pct
    rec["occupancy_count"] = 0
    rec["issued_entitlement_count"] = 0
    rec["posture"] = "OPEN"
    rec["comp_forgone_cents"] = 0
    db.zones[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.route("/access-zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    auth(ANY_ROLE)
    zone = get_or_404(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    return ok(public(zone))


@bp.route("/access-zones", methods=["GET"])
def list_zones():
    auth(ANY_ROLE)
    rows = sort_created_asc(list(db.zones.values()))
    rows = filter_eq(rows, "event_id", q("event_id"))
    rows = filter_eq(rows, "posture", q("posture"))
    rows = filter_eq(rows, "required_entitlement_level", q("required_entitlement_level"))
    return paginated(rows)

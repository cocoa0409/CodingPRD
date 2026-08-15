"""ZoneAccessEvent endpoints — append-only audit log (SCAFFOLD 1.5, PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_BADGE_NOT_FOUND,
    ERR_ACCESS_EVENT_NOT_FOUND, ERR_BADGE_ACCESS_DENIED,
    ERR_BADGE_WINDOW_VIOLATION, ERR_GATE_SEQUENCE_VIOLATION,
    ERR_CROSS_ZONE_REFERENCE,
)
from middleware import authorized
from response import success_object, success_list
from serializers import event_view
from services import wall_now, CLOCK
from util import new_id, parse_dt
from validate import (
    get_body, reject_unknown_fields, req_str, req_enum, opt_datetime,
    require_path, require_body_fk, parse_pagination,
)

bp = Blueprint("access_events", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/zones/access-events", methods=["POST"])
def create_event():
    caller = authorized(["GateOfficer"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "badge_id", "direction", "occurred_at"})
    zone_id = req_str(body, "zone_id")
    zone = require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")
    badge_id = req_str(body, "badge_id")
    badge = require_body_fk("access_badges", badge_id, ERR_BADGE_NOT_FOUND, "badge_id")
    direction = req_enum(body, "direction", {"IN", "OUT"})
    occurred_raw = opt_datetime(body, "occurred_at")
    occurred_at = parse_dt(occurred_raw) if occurred_raw is not None else CLOCK.now()

    # Safety prohibition (priority 7): badge must be ACTIVE.
    if badge["status"] != "ACTIVE":
        raise_error(ERR_BADGE_ACCESS_DENIED, "badge is not ACTIVE")

    # Temporal (priority 8): occurred_at inside the closed validity window,
    # and strict IN/OUT alternation per badge starting with IN.
    if not (badge["valid_from"] <= occurred_at <= badge["valid_until"]):
        raise_error(ERR_BADGE_WINDOW_VIOLATION,
                    "occurred_at falls outside the badge validity window")
    in_count = 0
    out_count = 0
    for ev in db["access_events"].values():
        if ev["badge_id"] == badge["id"]:
            if ev["direction"] == "IN":
                in_count += 1
            else:
                out_count += 1
    if direction == "IN":
        if in_count != out_count:
            raise_error(ERR_GATE_SEQUENCE_VIOLATION,
                        "IN requires count(IN) == count(OUT)")
    else:
        if in_count != out_count + 1:
            raise_error(ERR_GATE_SEQUENCE_VIOLATION,
                        "OUT requires count(IN) == count(OUT) + 1")

    # Referential (priority 10): event zone == badge zone.
    if badge["zone_id"] != zone["id"]:
        raise_error(ERR_CROSS_ZONE_REFERENCE, "gate event zone must equal the badge's zone")

    event = {
        "id": new_id(),
        "zone_id": zone["id"],
        "badge_id": badge["id"],
        "direction": direction,
        "occurred_at": occurred_at,
        "created_at": wall_now(),
    }
    db["access_events"][event["id"]] = event
    return success_object(event_view(event), status=201)


@bp.route("/zones/access-events", methods=["GET"])
def list_events():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    badge_id = request.args.get("badge_id")
    direction = request.args.get("direction")
    items = sorted(db["access_events"].values(), key=lambda e: (e["created_at"], e["id"]))
    if zone_id is not None:
        items = [e for e in items if e["zone_id"] == zone_id]
    if badge_id is not None:
        items = [e for e in items if e["badge_id"] == badge_id]
    if direction is not None:
        items = [e for e in items if e["direction"] == direction]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([event_view(e) for e in page], total, limit, offset)


@bp.route("/zones/access-events/<eventId>", methods=["GET"])
def get_event(eventId):
    authorized(ALL_ROLES)
    event = require_path("access_events", eventId, ERR_ACCESS_EVENT_NOT_FOUND)
    return success_object(event_view(event))

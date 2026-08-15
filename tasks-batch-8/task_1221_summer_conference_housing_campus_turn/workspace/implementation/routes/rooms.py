"""Room reads, turn-task listing, and damage reporting (PRD 3.8)."""
from flask import Blueprint, request

from authz import ADMIN, FACILITIES, ALL_ROLES, require_roles
from db import store
from errors import invalid_request
from respond import success
from serialize import ser_damage_assessment, ser_room, ser_turn_task
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, req_field,
    req_str, sorted_by_creation,
)
from calc import damage_estimate_total

bp = Blueprint("rooms", __name__)


@bp.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    require_roles(ALL_ROLES)
    return success(ser_room(get_or_404(store.rooms, rid)))


@bp.route("/rooms/<rid>/turn-tasks", methods=["GET"])
def list_room_turn_tasks(rid):
    require_roles(ALL_ROLES)
    get_or_404(store.rooms, rid)
    status = request.args.get("status")
    items = [t for t in store.turn_tasks.values()
             if t["room_id"] == rid and (status is None or t["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_turn_task(t) for t in page], response_type="array", pagination=pagination)


def validate_line_items(raw):
    if not isinstance(raw, list):
        raise invalid_request("line_items must be an array")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise invalid_request("each line item must be an object")
        for field in ("description", "quantity", "unit_replacement_cost_cents", "fixture_age_months"):
            if field not in entry or entry[field] is None:
                raise invalid_request("line item missing field: %s" % field)
        if not isinstance(entry["description"], str):
            raise invalid_request("line item description must be a string")
        for field in ("quantity", "unit_replacement_cost_cents", "fixture_age_months"):
            v = entry[field]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise invalid_request("line item %s must be a non-negative integer" % field)
        items.append({
            "description": entry["description"],
            "quantity": entry["quantity"],
            "unit_replacement_cost_cents": entry["unit_replacement_cost_cents"],
            "fixture_age_months": entry["fixture_age_months"],
        })
    return items


@bp.route("/rooms/<rid>/damage-assessments", methods=["POST"])
def report_damage(rid):
    require_roles([FACILITIES, ADMIN])
    room = get_or_404(store.rooms, rid)
    data = json_body()
    group_id = req_str(data, "group_id")
    if group_id not in store.groups:
        raise invalid_request("group_id does not reference an existing conference group")
    line_items = validate_line_items(req_field(data, "line_items"))
    d = {
        "id": new_id(),
        "_seq": next(store.seq),
        "room_id": room["id"],
        "group_id": group_id,
        "line_items": line_items,
        "estimate_total_cents": damage_estimate_total(line_items),
        "assessed_total_cents": None,
        "assessed_at": None,
        "dispute_reason": None,
        "status": "REPORTED",
    }
    d.update(new_common_fields())
    store.damage_assessments[d["id"]] = d
    return success(ser_damage_assessment(d), status=201)

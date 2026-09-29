"""Dropoff lines and the screening ladder (PRD §3.7)."""

from flask import Blueprint, request

import serializers
from calc import ZERO, cents, dec
from common import list_response
from envelope import ok
from errors import ApiError
from rollups import lines_of_appointment, lines_of_resident, refresh_world
from store import new_row, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    req_num,
    req_str,
)

bp = Blueprint("dropoff_lines", __name__)


def resolve_disposition(appointment, category, net_weight_kg):
    """The four-rung ladder — the first rung that matches wins outright."""
    if category["acceptance_policy"] == "REJECTED_ALWAYS":
        return "REJECTED_PROHIBITED", "PROHIBITED_MATERIAL"

    resident_ytd = ZERO
    for line in lines_of_resident(appointment["resident_id"]):
        if line["disposition"] != "ACCEPTED":
            continue
        if line["material_category_id"] != category["id"]:
            continue
        resident_ytd += dec(line["net_weight_kg"])
    if resident_ytd + net_weight_kg > dec(category["max_kg_per_resident_per_year"]):
        return "REJECTED_OVER_ANNUAL_LIMIT", "ANNUAL_LIMIT"

    appointment_total = ZERO
    for line in lines_of_appointment(appointment["id"]):
        if line["disposition"] != "ACCEPTED":
            continue
        if line["material_category_id"] != category["id"]:
            continue
        appointment_total += dec(line["net_weight_kg"])
    if appointment_total + net_weight_kg > dec(category["max_kg_per_resident_per_event"]):
        return "REJECTED_OVER_EVENT_LIMIT", "EVENT_LIMIT"

    return "ACCEPTED", None


@bp.post("/hhw/dropoff-lines")
def create_dropoff_line():
    user_id, role = context()
    authorize(role, ["UnloadTech"])
    payload = body()
    appointment_id = req_str(payload, "appointment_id")
    material_category_id = req_str(payload, "material_category_id")
    declared_kg = req_num(payload, "declared_kg", gte=0)
    net_weight_kg = req_num(payload, "net_weight_kg", gt=0)

    appointment = lookup("appointment", appointment_id)
    category = lookup("material_category", material_category_id)

    # Rung 9 — a line may only be recorded against an unloading vehicle at an
    # event that is in progress.
    event = store.events.get(appointment["event_id"])
    if event is None or event["lifecycle_status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The collection event is not in progress.")
    if appointment["status"] != "UNLOADING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The appointment is not unloading.")

    disposition, reason = resolve_disposition(appointment, category, net_weight_kg)
    if disposition == "ACCEPTED":
        estimate = cents(net_weight_kg * dec(category["disposal_rate_cents_per_kg"]))
    else:
        estimate = 0

    row = new_row({
        "appointment_id": appointment["id"],
        "material_category_id": category["id"],
        "container_id": None,
        "declared_kg": declared_kg,
        "net_weight_kg": net_weight_kg,
        "disposition": disposition,
        "rejection_reason_code": reason,
        "estimated_disposal_cost_cents": estimate,
        "screened_by_user_id": user_id,
    })
    store.dropoff_lines[row["id"]] = row
    refresh_world()
    return ok(serializers.dropoff_line(row), 201)


@bp.get("/hhw/dropoff-lines")
def list_dropoff_lines():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "appointment_id": request.args.get("appointment_id"),
        "material_category_id": request.args.get("material_category_id"),
        "container_id": request.args.get("container_id"),
        "disposition": request.args.get("disposition"),
    }
    return list_response(request.args, list(store.dropoff_lines.values()),
                         serializers.dropoff_line, filters)


@bp.get("/hhw/dropoff-lines/<line_id>")
def read_dropoff_line(line_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.dropoff_line(lookup("dropoff_line", line_id)))

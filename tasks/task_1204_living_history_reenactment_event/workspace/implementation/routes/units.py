"""Unit endpoints: register (bootstrap), read, vet, suspend, list."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_event, get_unit, own_unit_scope
from response import success
from services import cascades
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import body, opt_int, opt_str, req_enum, req_str

bp = Blueprint("units", __name__)

UNIT_TYPES = ("MILITARY", "CIVILIAN", "ARTILLERY")
UNIT_READ_ROLES = ["UnitCommander", "EventOrganizer", "AuthenticityOfficer", "SafetyOfficer"]


@bp.post("/units")
def create_unit():
    uid, _ = authenticate(["UnitCommander"], creation=True)
    data = body(request)
    # Existence (priority 3) of the referenced event, when the reference is present.
    ev = get_event(data["event_id"]) if data.get("event_id") else None
    if ev is None:
        fail("ERR_VALIDATION", "missing required field: event_id")
    # Posture (priority 5)
    if ev["event_posture"] not in ("REGISTRATION_OPEN", "PUBLISHED"):
        fail("ERR_INVALID_EVENT_POSTURE", "unit registration requires REGISTRATION_OPEN or PUBLISHED")
    # Body shape (priority 7)
    name = req_str(data, "name")
    unit_type = req_enum(data, "unit_type", UNIT_TYPES)
    portrayal_name = req_str(data, "portrayal_name")
    headcount = opt_int(data, "headcount_estimate", 0, minimum=0)
    # Bootstrap: the registering commander's X-User-ID becomes the unit id.
    rec = new_record(record_id=uid)
    rec.update(
        event_id=ev["id"],
        name=name,
        unit_type=unit_type,
        portrayal_name=portrayal_name,
        headcount_estimate=headcount,
        status="SUBMITTED",
        vet_notes=None,
    )
    db.units[rec["id"]] = rec
    return success(serializers.unit(rec), 201)


@bp.get("/units/<unit_id>")
def read_unit(unit_id):
    uid, role = authenticate(UNIT_READ_ROLES)
    u = get_unit(unit_id)
    if role == "UnitCommander":
        own_unit_scope(uid, u["id"])
    return success(serializers.unit(u), 200)


@bp.post("/units/<unit_id>/vet")
def vet_unit(unit_id):
    authenticate(["EventOrganizer"])
    u = get_unit(unit_id)
    if u["status"] not in ("SUBMITTED", "SUSPENDED"):
        fail("ERR_INVALID_UNIT_STATUS", f"unit in {u['status']} cannot be vetted")
    data = body(request)
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    notes = opt_str(data, "notes")
    if u["status"] == "SUBMITTED":
        u["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    else:  # SUSPENDED reinstatement only via APPROVE
        if decision != "APPROVE":
            fail("ERR_INVALID_UNIT_STATUS", "a SUSPENDED unit can only be reinstated with APPROVE")
        u["status"] = "APPROVED"
    u["vet_notes"] = notes
    touch(u)
    return success(serializers.unit(u), 200)


@bp.post("/units/<unit_id>/suspend")
def suspend_unit(unit_id):
    authenticate(["EventOrganizer"])
    u = get_unit(unit_id)
    if u["status"] != "APPROVED":
        fail("ERR_INVALID_UNIT_STATUS", "only an APPROVED unit can be suspended")
    cascades.suspend_unit(u)
    return success(serializers.unit(u), 200)


@bp.get("/events/<event_id>/units")
def list_units(event_id):
    authenticate(["EventOrganizer", "AuthenticityOfficer", "SafetyOfficer"])
    ev = get_event(event_id)
    items = sorted_all(u for u in db.units.values() if u["event_id"] == ev["id"])
    page, meta = paginate(items)
    return success([serializers.unit(u) for u in page], 200, pagination=meta)

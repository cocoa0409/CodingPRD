"""Operator registration/suspension, crew members, and the logical clock."""

from flask import Blueprint, request

from auth import require_roles
from db import store, new_record, bump
from errors import err
from response import ok, ok_list, serialize, serialize_list, sort_created
from services import (EVENT_CANCELLABLE, cancel_event, check_operator_active)
from validation import validate_schema, parse_pagination, paginate, parse_datetime

bp = Blueprint("operators", __name__)

LICENSE_CLASSES = {"DISPLAY_1_3G", "PROXIMATE_1_4G"}
CERT_LEVELS = {"TRAINEE", "SHOOTER", "LEAD_OPERATOR"}


@bp.post("/pyro/_clock/set_current_utc")
def set_clock():
    require_roles("SystemAdmin")
    vals = validate_schema(request.get_json(silent=True),
                           [("to_iso8601", "dt", True, None)])
    store.clock = vals["to_iso8601"]
    # Clock-derived postures (Magazine.posture) are computed on read, so
    # advancing the clock already "recomputes" them everywhere.
    return ok({"current_utc": serialize({"t": store.clock})["t"]})


@bp.post("/pyro/operators")
def create_operator():
    require_roles("SystemAdmin")
    vals = validate_schema(request.get_json(silent=True), [
        ("legal_name", "str", True, None),
        ("atf_license_number", "str", True, None),
        ("license_class", "enum", True, LICENSE_CLASSES),
        ("license_valid_from", "dt", True, None),
        ("license_expires_at", "dt", True, None),
    ])
    for op in store.operators.values():
        if op["atf_license_number"] == vals["atf_license_number"]:
            err("ERR_VALIDATION", "atf_license_number must be unique across operators")
    rec = new_record()
    rec.update({
        "legal_name": vals["legal_name"],
        "atf_license_number": vals["atf_license_number"],
        "license_class": vals["license_class"],
        "license_valid_from": vals["license_valid_from"],
        "license_expires_at": vals["license_expires_at"],
        "status": "ACTIVE",
        "suspended_reason": None,
    })
    store.operators[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/pyro/operators/<op_id>")
def get_operator(op_id):
    uid, role = require_roles("SystemAdmin", "Operator")
    op = store.operators.get(op_id)
    if op is None:
        err("ERR_NOT_FOUND", f"operator {op_id} not found")
    if role == "Operator" and op["id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "operator may only read its own record")
    return ok(serialize(op))


@bp.post("/pyro/operators/<op_id>/suspend")
def suspend_operator(op_id):
    require_roles("SystemAdmin")
    vals = validate_schema(request.get_json(silent=True),
                           [("reason", "str", True, None)])
    op = store.operators.get(op_id)
    if op is None:
        err("ERR_NOT_FOUND", f"operator {op_id} not found")
    if op["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "operator is not ACTIVE")
    op["status"] = "SUSPENDED"
    op["suspended_reason"] = vals["reason"]
    bump(op)
    # Depth-3 cascade: every non-terminal display of this operator is cancelled
    # with the full per-event cancellation cascade (posts release, applications
    # withdraw, auto-RETURN movements, magazine mass recompute).
    for ev in list(store.displays.values()):
        if ev["operator_id"] == op["id"] and ev["status"] in EVENT_CANCELLABLE:
            cancel_event(ev, "OPERATOR_SUSPENDED")
    return ok(serialize(op))


@bp.post("/pyro/operators/<op_id>/crew-members")
def create_crew_member(op_id):
    uid, _ = require_roles("Operator")
    vals = validate_schema(request.get_json(silent=True), [
        ("full_name", "str", True, None),
        ("cert_level", "enum", True, CERT_LEVELS),
        ("cert_expires_at", "dt", True, None),
        ("hazmat_endorsed", "bool", False, None),
    ])
    op = store.operators.get(op_id)
    if op is None:
        err("ERR_NOT_FOUND", f"operator {op_id} not found")
    if op_id != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "path operator must equal X-User-ID")
    check_operator_active(uid)
    # Certification must not already be expired at registration.
    if vals["cert_expires_at"] <= store.clock:
        err("ERR_CERT_NOT_VALID", "certification is already expired")
    rec = new_record()
    rec.update({
        "operator_id": op_id,
        "full_name": vals["full_name"],
        "cert_level": vals["cert_level"],
        "cert_expires_at": vals["cert_expires_at"],
        "hazmat_endorsed": vals["hazmat_endorsed"] if vals["hazmat_endorsed"] is not None else False,
    })
    store.crew_members[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/pyro/operators/<op_id>/crew-members")
def list_crew_members(op_id):
    uid, role = require_roles("Operator", "SystemAdmin")
    op = store.operators.get(op_id)
    if op is None:
        err("ERR_NOT_FOUND", f"operator {op_id} not found")
    if role == "Operator" and op_id != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", "operator may only list its own crew")
    limit, offset = parse_pagination(request.args)
    recs = [c for c in store.crew_members.values() if c["operator_id"] == op_id]
    cert = request.args.get("cert_level")
    if cert is not None:
        recs = [c for c in recs if c["cert_level"] == cert]
    recs = sort_created(recs)
    return ok_list(serialize_list(paginate(recs, limit, offset)), len(recs),
                   limit, offset)

"""Platform endpoints: logical clock, scanner units, shelf slots."""

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list, parse_pagination, iso_ts
from util import (
    get_body,
    require_fields,
    reject_unknown,
    as_str,
    as_int,
    as_enum,
    parse_iso8601,
    make_entity,
)
from services.serializers import scanner_unit_view, shelf_slot_view, scan_session_view, shelf_assignment_view
from services.custody import disposition_sweep

bp = Blueprint("platform", __name__)

ALL_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk", "ClientUser",
)
STAFF_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk",
)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock(_user_id, _role):
    body = get_body()
    require_fields(body, ["to_iso8601"])
    reject_unknown(body, {"to_iso8601"})
    dt = parse_iso8601(body["to_iso8601"], "to_iso8601")
    db.current_utc = dt
    disposition_sweep()
    return success_object({"current_utc": iso_ts(db.current_utc)})


# ---------------- Scanner units ----------------

@bp.route("/scanner-units", methods=["POST"])
@require_roles("PlatformAdmin")
def create_scanner_unit(_user_id, _role):
    body = get_body()
    require_fields(body, ["scanner_code", "capacity_pages_per_session"])
    reject_unknown(body, {"scanner_code", "capacity_pages_per_session"})
    scanner_code = as_str(body["scanner_code"], "scanner_code")
    capacity = as_int(body["capacity_pages_per_session"], "capacity_pages_per_session", minimum=1)
    for s in db.scanner_units.values():
        if s["scanner_code"] == scanner_code:
            raise ApiError(ERR_INVALID_STATE, "scanner_code already exists", 409)
    unit = make_entity(
        {
            "scanner_code": scanner_code,
            "capacity_pages_per_session": capacity,
            "status": "AVAILABLE",
        }
    )
    db.scanner_units[unit["id"]] = unit
    return success_object(scanner_unit_view(unit), status=201)


@bp.route("/scanner-units", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_scanner_units(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    items = sorted(db.scanner_units.values(), key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([scanner_unit_view(s) for s in page], limit, offset, total)


@bp.route("/scanner-units/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_scanner_unit(id, _user_id, _role):
    unit = db.scanner_units.get(id)
    if not unit:
        raise ApiError(ERR_NOT_FOUND, "Scanner unit not found", 404)
    return success_object(scanner_unit_view(unit))


@bp.route("/scanner-units/<id>/maintenance", methods=["POST"])
@require_roles("PlatformAdmin")
def scanner_maintenance(id, _user_id, _role):
    unit = db.scanner_units.get(id)
    if not unit:
        raise ApiError(ERR_NOT_FOUND, "Scanner unit not found", 404)
    body = get_body()
    require_fields(body, ["status"])
    reject_unknown(body, {"status"})
    status = as_enum(body["status"], "status", {"AVAILABLE", "MAINTENANCE"})
    unit["status"] = status
    from util import bump

    bump(unit)
    return success_object(scanner_unit_view(unit))


@bp.route("/scanner-units/<id>/scan-sessions", methods=["GET"])
@require_roles(*STAFF_ROLES)
def scanner_sessions(id, _user_id, _role):
    unit = db.scanner_units.get(id)
    if not unit:
        raise ApiError(ERR_NOT_FOUND, "Scanner unit not found", 404)
    limit, offset = parse_pagination(request.args)
    items = [s for s in db.scan_sessions.values() if s["scanner_id"] == id]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([scan_session_view(s) for s in page], limit, offset, total)


# ---------------- Shelf slots ----------------

@bp.route("/shelf-slots", methods=["POST"])
@require_roles("PlatformAdmin")
def create_shelf_slot(_user_id, _role):
    body = get_body()
    require_fields(body, ["shelf_code", "zone", "capacity_grams"])
    reject_unknown(body, {"shelf_code", "zone", "capacity_grams"})
    shelf_code = as_str(body["shelf_code"], "shelf_code")
    zone = as_enum(body["zone"], "zone", {"GENERAL", "VAULT"})
    capacity = as_int(body["capacity_grams"], "capacity_grams", minimum=1)
    for s in db.shelf_slots.values():
        if s["shelf_code"] == shelf_code:
            raise ApiError(ERR_INVALID_STATE, "shelf_code already exists", 409)
    slot = make_entity(
        {
            "shelf_code": shelf_code,
            "zone": zone,
            "capacity_grams": capacity,
            "occupied_weight_grams": 0,
        }
    )
    db.shelf_slots[slot["id"]] = slot
    return success_object(shelf_slot_view(slot), status=201)


@bp.route("/shelf-slots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_shelf_slots(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    zone = request.args.get("zone")
    items = list(db.shelf_slots.values())
    if zone is not None:
        items = [s for s in items if s["zone"] == zone]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([shelf_slot_view(s) for s in page], limit, offset, total)


@bp.route("/shelf-slots/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_shelf_slot(id, _user_id, _role):
    slot = db.shelf_slots.get(id)
    if not slot:
        raise ApiError(ERR_NOT_FOUND, "Shelf slot not found", 404)
    return success_object(shelf_slot_view(slot))


@bp.route("/shelf-slots/<id>/shelf-assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def shelf_slot_assignments(id, _user_id, _role):
    slot = db.shelf_slots.get(id)
    if not slot:
        raise ApiError(ERR_NOT_FOUND, "Shelf slot not found", 404)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [a for a in db.shelf_assignments.values() if a["shelf_slot_id"] == id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([shelf_assignment_view(a) for a in page], limit, offset, total)

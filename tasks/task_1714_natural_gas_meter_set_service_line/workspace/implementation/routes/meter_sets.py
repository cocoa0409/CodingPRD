"""MeterSet endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_METER_SET,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_METER_SIZE_UNAVAILABLE,
    ERR_SERVICE_LINE_NOT_INSTALLED,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    require_fields,
    require_roles,
    require_str,
    spine_at_least,
)
from response import success_list, success_object
from services.calculations import meter_sizing
from services.domain import get_application, get_meter_set, meter_set_for_application, touch

bp = Blueprint("meter_sets", __name__)


@bp.route("/meter-sets", methods=["POST"])
def create_meter_set():
    require_roles("MeterTechnician")
    body = get_body()
    require_fields(body, "service_application_id")
    app = get_application(body["service_application_id"])
    check_app_mutable(app)
    existing = meter_set_for_application(app["id"])
    if existing is not None:
        raise_error(ERR_DUPLICATE_METER_SET, "A non-CANCELLED meter set already exists")
    now = db.now_iso()
    ms = {
        "id": new_id(),
        "service_application_id": app["id"],
        "meter_model": None,
        "regulator_model": None,
        "serial_number": None,
        "installed_by_user_id": None,
        "installed_at": None,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.meter_sets[ms["id"]] = ms
    return success_object(ms, 201)


@bp.route("/meter-sets/<mid>", methods=["GET"])
def get_one_meter_set(mid):
    require_roles(*ANY_ROLE)
    return success_object(get_meter_set(mid))


@bp.route("/meter-sets", methods=["GET"])
def list_meter_sets():
    require_roles(*ANY_ROLE)
    records = list(db.meter_sets.values())
    app_id = request.args.get("service_application_id")
    if app_id is not None:
        records = [m for m in records if m["service_application_id"] == app_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/meter-sets/<mid>/size", methods=["POST"])
def size_meter_set(mid):
    require_roles("DesignEngineer")
    ms = get_meter_set(mid)
    app = get_application(ms["service_application_id"])
    check_app_mutable(app)
    if ms["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, "Only PLANNED meter sets can be sized")
    if not spine_at_least(app, "LOAD_CONFIRMED"):
        raise_error(ERR_INVALID_STATE, "Loads must be locked (LOAD_CONFIRMED or later) before sizing")
    selected = meter_sizing(app["diversity_adjusted_load_cfph"], app["pressure_class_requested"])
    if selected is None:
        raise_error(ERR_METER_SIZE_UNAVAILABLE, "No meter model covers the diversity-adjusted load")
    ms["meter_model"], ms["regulator_model"] = selected
    ms["status"] = "SIZED"
    touch(ms)
    return success_object(ms)


@bp.route("/meter-sets/<mid>/mark-ordered", methods=["POST"])
def mark_ordered(mid):
    require_roles("MeterTechnician")
    ms = get_meter_set(mid)
    app = get_application(ms["service_application_id"])
    body = get_body()
    require_fields(body, "serial_number")
    serial = require_str(body, "serial_number")
    check_app_mutable(app)
    if ms["status"] != "SIZED":
        raise_error(ERR_INVALID_STATE, "Only SIZED meter sets can be marked ordered")
    ms["serial_number"] = serial
    ms["status"] = "ORDERED"
    touch(ms)
    return success_object(ms)


@bp.route("/meter-sets/<mid>/install", methods=["POST"])
def install(mid):
    user_id, _ = require_roles("MeterTechnician")
    ms = get_meter_set(mid)
    app = get_application(ms["service_application_id"])
    check_app_mutable(app)
    if ms["status"] != "ORDERED":
        raise_error(ERR_INVALID_STATE, "Only ORDERED meter sets can be installed")
    if app["status"] != "SERVICE_INSTALLED":
        raise_error(ERR_SERVICE_LINE_NOT_INSTALLED, "Application must be at SERVICE_INSTALLED")
    ms["installed_by_user_id"] = user_id
    ms["installed_at"] = db.now_iso()
    ms["status"] = "INSTALLED"
    touch(ms)
    app["status"] = "METER_WORK"
    touch(app)
    return success_object(ms)


@bp.route("/meter-sets/<mid>/mark-repaired", methods=["POST"])
def mark_repaired(mid):
    require_roles("MeterTechnician")
    ms = get_meter_set(mid)
    app = get_application(ms["service_application_id"])
    check_app_mutable(app)
    if ms["status"] != "REPAIR":
        raise_error(ERR_INVALID_STATE, "Only meter sets in REPAIR can be marked repaired")
    ms["status"] = "INSTALLED"
    touch(ms)
    return success_object(ms)

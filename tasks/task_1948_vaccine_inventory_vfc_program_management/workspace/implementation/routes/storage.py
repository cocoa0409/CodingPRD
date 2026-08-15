"""Storage units, temperature readings, and excursions (PRD §3.2, §3.3)."""

from flask import Blueprint, request

import db
from errors import invalid_state, ApiError, ERR_EXCURSION_STILL_OPEN
from middleware import get_auth, ALL_ROLES, ROLE_VACCINE_MANAGER
from response import success_object, paginate
from services import excursions as excursion_svc
from services.validate import (
    require_body, require_string, require_number, require_enum, require_datetime,
    get_or_404, ENUM_UNIT_KIND,
)

bp = Blueprint("storage", __name__)


def serialize_unit(unit):
    return {
        "id": unit["id"],
        "created_at": unit["created_at"],
        "updated_at": unit["updated_at"],
        "version": unit["version"],
        "provider_site_id": unit["provider_site_id"],
        "unit_label": unit["unit_label"],
        "unit_kind": unit["unit_kind"],
        "min_temp_c": unit["min_temp_c"],
        "max_temp_c": unit["max_temp_c"],
        "active_excursion_id": unit["active_excursion_id"],
        "is_quarantined": unit["active_excursion_id"] is not None,
    }


def serialize_reading(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "storage_unit_id": r["storage_unit_id"],
        "recorded_at": r["recorded_at"],
        "temperature_c": r["temperature_c"],
        "is_out_of_range": r["is_out_of_range"],
    }


def serialize_excursion(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "storage_unit_id": e["storage_unit_id"],
        "opened_at": e["opened_at"],
        "closed_at": e["closed_at"],
        "peak_temperature_c": e["peak_temperature_c"],
        "duration_minutes": e["duration_minutes"],
        "status": e["status"],
        "resolution_notes": e["resolution_notes"],
        "doses_written_off": e["doses_written_off"],
    }


# ----------------------------- Storage Units -------------------------------

@bp.route("/provider-sites/<site_id>/storage-units", methods=["POST"])
def create_storage_unit(site_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    unit_label = require_string(body, "unit_label")
    unit_kind = require_enum(body, "unit_kind", ENUM_UNIT_KIND)
    min_temp_c = require_number(body, "min_temp_c")
    max_temp_c = require_number(body, "max_temp_c")

    now = db.now_ts()
    unit = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "unit_label": unit_label,
        "unit_kind": unit_kind,
        "min_temp_c": min_temp_c,
        "max_temp_c": max_temp_c,
        "active_excursion_id": None,
    }
    db.storage_units[unit["id"]] = unit
    return success_object(serialize_unit(unit), 201)


@bp.route("/provider-sites/<site_id>/storage-units", methods=["GET"])
def list_storage_units(site_id):
    get_auth(ALL_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [u for u in db.storage_units.values() if u["provider_site_id"] == site["id"]]
    items.sort(key=lambda u: (u["created_at"], u["id"]))
    return paginate([serialize_unit(u) for u in items], request.args)


@bp.route("/storage-units/<unit_id>", methods=["GET"])
def get_storage_unit(unit_id):
    get_auth(ALL_ROLES)
    unit = get_or_404(db.storage_units, unit_id, "storage unit")
    return success_object(serialize_unit(unit))


@bp.route("/storage-units", methods=["GET"])
def list_storage_units_global():
    get_auth(ALL_ROLES)
    items = list(db.storage_units.values())
    site_filter = request.args.get("provider_site_id")
    excursion_filter = request.args.get("active_excursion_id")
    if site_filter is not None:
        items = [u for u in items if u["provider_site_id"] == site_filter]
    if excursion_filter is not None:
        items = [u for u in items if u["active_excursion_id"] == excursion_filter]
    items.sort(key=lambda u: (u["created_at"], u["id"]))
    return paginate([serialize_unit(u) for u in items], request.args)


# --------------------------- Temperature Readings --------------------------

@bp.route("/storage-units/<unit_id>/temperature-readings", methods=["POST"])
def record_temperature_reading(unit_id):
    get_auth([ROLE_VACCINE_MANAGER])
    unit = get_or_404(db.storage_units, unit_id, "storage unit")
    body = require_body(request.get_json(silent=True))
    recorded_at_raw, recorded_at_dt = require_datetime(body, "recorded_at")
    temperature_c = require_number(body, "temperature_c")

    is_out_of_range = temperature_c < unit["min_temp_c"] or temperature_c > unit["max_temp_c"]

    reading = {
        "id": db.new_id(),
        "created_at": db.now_ts(),
        "storage_unit_id": unit["id"],
        "recorded_at": recorded_at_raw,
        "temperature_c": temperature_c,
        "is_out_of_range": is_out_of_range,
    }
    db.temperature_readings[reading["id"]] = reading

    active_id = unit["active_excursion_id"]
    if is_out_of_range and active_id is None:
        excursion_svc.open_excursion(unit, reading)
    elif is_out_of_range and active_id is not None:
        excursion = db.temperature_excursions[active_id]
        excursion_svc.update_peak(unit, excursion, temperature_c)
    elif not is_out_of_range and active_id is not None:
        excursion = db.temperature_excursions[active_id]
        excursion_svc.close_excursion_on_in_range(excursion, reading)

    return success_object(serialize_reading(reading), 201)


@bp.route("/storage-units/<unit_id>/temperature-readings", methods=["GET"])
def list_temperature_readings(unit_id):
    get_auth(ALL_ROLES)
    unit = get_or_404(db.storage_units, unit_id, "storage unit")
    items = [r for r in db.temperature_readings.values() if r["storage_unit_id"] == unit["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return paginate([serialize_reading(r) for r in items], request.args)


@bp.route("/temperature-readings", methods=["GET"])
def list_temperature_readings_global():
    get_auth(ALL_ROLES)
    items = list(db.temperature_readings.values())
    unit_filter = request.args.get("storage_unit_id")
    if unit_filter is not None:
        items = [r for r in items if r["storage_unit_id"] == unit_filter]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return paginate([serialize_reading(r) for r in items], request.args)


# --------------------------- Temperature Excursions ------------------------

@bp.route("/storage-units/<unit_id>/excursions", methods=["GET"])
def list_excursions(unit_id):
    get_auth(ALL_ROLES)
    unit = get_or_404(db.storage_units, unit_id, "storage unit")
    items = [e for e in db.temperature_excursions.values() if e["storage_unit_id"] == unit["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    return paginate([serialize_excursion(e) for e in items], request.args)


@bp.route("/storage-units/<unit_id>/excursions/<excursion_id>", methods=["GET"])
def get_excursion(unit_id, excursion_id):
    get_auth(ALL_ROLES)
    unit = get_or_404(db.storage_units, unit_id, "storage unit")
    excursion = get_or_404(db.temperature_excursions, excursion_id, "excursion")
    if excursion["storage_unit_id"] != unit["id"]:
        from errors import not_found
        raise not_found("excursion")
    return success_object(serialize_excursion(excursion))


@bp.route("/temperature-excursions", methods=["GET"])
def list_excursions_global():
    get_auth(ALL_ROLES)
    items = list(db.temperature_excursions.values())
    unit_filter = request.args.get("storage_unit_id")
    status_filter = request.args.get("status")
    if unit_filter is not None:
        items = [e for e in items if e["storage_unit_id"] == unit_filter]
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    return paginate([serialize_excursion(e) for e in items], request.args)


def _get_unit_excursion(unit_id, excursion_id):
    unit = get_or_404(db.storage_units, unit_id, "storage unit")
    excursion = get_or_404(db.temperature_excursions, excursion_id, "excursion")
    if excursion["storage_unit_id"] != unit["id"]:
        from errors import not_found
        raise not_found("excursion")
    return unit, excursion


@bp.route("/storage-units/<unit_id>/excursions/<excursion_id>/begin-review", methods=["POST"])
def begin_review(unit_id, excursion_id):
    get_auth([ROLE_VACCINE_MANAGER])
    unit, excursion = _get_unit_excursion(unit_id, excursion_id)
    if excursion["status"] != "OPEN":
        raise invalid_state("Excursion must be OPEN to begin review")
    if excursion["closed_at"] is None:
        raise ApiError(ERR_EXCURSION_STILL_OPEN,
                       "begin-review requires an in-range reading to have closed the excursion first",
                       409)
    excursion["status"] = "UNDER_REVIEW"
    excursion["updated_at"] = db.now_ts()
    excursion["version"] += 1
    return success_object(serialize_excursion(excursion))


@bp.route("/storage-units/<unit_id>/excursions/<excursion_id>/resolve-viable", methods=["POST"])
def resolve_viable(unit_id, excursion_id):
    get_auth([ROLE_VACCINE_MANAGER])
    unit, excursion = _get_unit_excursion(unit_id, excursion_id)
    if excursion["status"] != "UNDER_REVIEW":
        raise invalid_state("Excursion must be UNDER_REVIEW to resolve viable")
    body = request.get_json(silent=True)
    notes = body.get("resolution_notes") if isinstance(body, dict) else None
    excursion_svc.resolve_viable(unit, excursion, notes)
    return success_object(serialize_excursion(excursion))


@bp.route("/storage-units/<unit_id>/excursions/<excursion_id>/resolve-wasted", methods=["POST"])
def resolve_wasted(unit_id, excursion_id):
    get_auth([ROLE_VACCINE_MANAGER])
    unit, excursion = _get_unit_excursion(unit_id, excursion_id)
    if excursion["status"] != "UNDER_REVIEW":
        raise invalid_state("Excursion must be UNDER_REVIEW to resolve wasted")
    body = request.get_json(silent=True)
    notes = body.get("resolution_notes") if isinstance(body, dict) else None
    excursion_svc.resolve_wasted(unit, excursion, notes)
    return success_object(serialize_excursion(excursion))

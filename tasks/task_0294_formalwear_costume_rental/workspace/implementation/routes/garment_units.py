"""GarmentUnit endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from clock import current_dt, parse_iso
from errors import err, ERR_INVALID_STATE, ERR_STALE_VERSION
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers
from services.calculations import MAX_STRIKES

bp = Blueprint("garment_units", __name__)


@bp.route("/garment-units", methods=["POST"])
def create_garment_unit():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = helpers.get_json_body()

    # Existence (priority 3) before well-formedness checks on referenced FK.
    catalog_id = helpers.as_str(body, "catalog_id")
    helpers.find("Catalog", catalog_id)
    size_code = helpers.as_enum(body, "size_code", helpers.SIZE_VALUES)

    unit = {
        "catalog_id": catalog_id,
        "size_code": size_code,
        "condition_grade": "GRADE_A",
        "status": "AVAILABLE",
        "damage_strike_count": 0,
        "available_from_iso": None,
    }
    db.stamp_create(unit)
    db.garment_units[unit["id"]] = unit
    return success(views.garment_unit_view(unit), status=201)


@bp.route("/garment-units/<uid>", methods=["GET"])
def get_garment_unit(uid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk"})
    unit = helpers.find("GarmentUnit", uid)
    return success(views.garment_unit_view(unit))


@bp.route("/garment-units", methods=["GET"])
def list_garment_units():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk"})
    limit, offset = helpers.parse_pagination()
    records = list(db.garment_units.values())
    catalog_id = request.args.get("catalog_id")
    status = request.args.get("status")
    size_code = request.args.get("size_code")
    if catalog_id is not None:
        records = [u for u in records if u["catalog_id"] == catalog_id]
    if status is not None:
        records = [u for u in records if u["status"] == status]
    if size_code is not None:
        records = [u for u in records if u["size_code"] == size_code]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.garment_unit_view(u) for u in page], limit, offset, total)


@bp.route("/garment-units/<uid>/clear-cleaning", methods=["POST"])
def clear_cleaning(uid):
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    unit = helpers.find("GarmentUnit", uid)

    # State gate: only IN_CLEANING units may be cleared (priority 6).
    if unit["status"] != "IN_CLEANING":
        raise err(ERR_INVALID_STATE, "Unit is not IN_CLEANING")
    # Buffer gate: current clock must have reached available_from_iso.
    afi = unit["available_from_iso"]
    if afi is not None and current_dt() < parse_iso(afi):
        raise err(ERR_INVALID_STATE, "Cleaning buffer has not elapsed")

    if unit["damage_strike_count"] >= MAX_STRIKES:
        # Two strikes exhaust serviceable life -> RETIRED instead of AVAILABLE.
        unit["status"] = "RETIRED"
    else:
        unit["status"] = "AVAILABLE"
    db.touch(unit)
    return success(views.garment_unit_view(unit))


@bp.route("/garment-units/<uid>/retire", methods=["POST"])
def retire(uid):
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    unit = helpers.find("GarmentUnit", uid)
    body = helpers.get_json_body()

    # Retire allowed only from AVAILABLE or IN_CLEANING (PRD §3.1).
    if unit["status"] not in ("AVAILABLE", "IN_CLEANING"):
        raise err(ERR_INVALID_STATE, "Unit cannot be retired from its current state")

    # OCC: expected_garment_unit_version must match current version (PRD §2.10).
    expected = body.get("expected_garment_unit_version")
    if expected is not None and expected != unit["version"]:
        raise err(ERR_STALE_VERSION, "expected_garment_unit_version mismatch")

    unit["status"] = "RETIRED"
    db.touch(unit)
    return success(views.garment_unit_view(unit))

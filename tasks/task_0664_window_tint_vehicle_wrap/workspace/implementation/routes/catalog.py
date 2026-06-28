"""Config / catalog routes: shop locations, state regulations, film materials,
service packages."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body
from models import stamp_create, serialize
from response import success
from services import common

bp = Blueprint("catalog", __name__)


# ---- ShopLocation -----------------------------------------------------------
@bp.route("/shop-locations", methods=["POST"])
def create_shop_location():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    name = common.require_string(body, "name")
    state_code = common.require_string(body, "state_code")
    rec = {
        "name": name,
        "state_code": state_code,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.shop_locations[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/shop-locations/<rid>", methods=["GET"])
def get_shop_location(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer", "Customer", "FleetManager", "ComplianceOfficer"})
    rec = common.get_or_404(db.shop_locations, rid)
    return success(serialize(rec), 200)


# ---- StateTintRegulation ----------------------------------------------------
# Reference record: carries only id and created_at (no updated_at, no version).
@bp.route("/state-tint-regulations", methods=["POST"])
def create_state_regulation():
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    body = get_json_body()
    state_code = common.require_string(body, "state_code")
    front_side_min_vlt_pct = common.require_int(body, "front_side_min_vlt_pct")
    windshield_strip_max_inches = common.require_field(body, "windshield_strip_max_inches")
    if isinstance(windshield_strip_max_inches, bool) or not isinstance(windshield_strip_max_inches, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "windshield_strip_max_inches must be a number.")
    medical_exemption_allowed = common.require_field(body, "medical_exemption_allowed")
    if not isinstance(medical_exemption_allowed, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "medical_exemption_allowed must be a boolean.")

    # Unique state_code across regulations.
    for reg in db.state_tint_regulations.values():
        if reg["state_code"] == state_code:
            raise ApiError(errors.ERR_DUPLICATE_STATE_REGULATION, 409, "State regulation already exists.")

    rec = {
        "state_code": state_code,
        "front_side_min_vlt_pct": front_side_min_vlt_pct,
        "windshield_strip_max_inches": windshield_strip_max_inches,
        "medical_exemption_allowed": medical_exemption_allowed,
    }
    stamp_create(rec, common=False)  # only id + created_at
    db.state_tint_regulations[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/state-tint-regulations/<rid>", methods=["GET"])
def get_state_regulation(rid):
    user_id, role = get_identity()
    require_role(role, {"ComplianceOfficer", "ShopManager", "Customer"})
    rec = common.get_or_404(db.state_tint_regulations, rid)
    return success(serialize(rec), 200)


# ---- FilmMaterial -----------------------------------------------------------
MATERIAL_CATEGORIES = {"TINT_FILM", "PPF_FILM", "WRAP_VINYL", "CERAMIC_COATING"}


@bp.route("/film-materials", methods=["POST"])
def create_film_material():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    sku = common.require_string(body, "sku")
    category = common.require_enum(body, "category", MATERIAL_CATEGORIES)
    cure_hours = common.require_int(body, "cure_hours")
    if cure_hours < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "cure_hours must be >= 0.")
    price_multiplier_bps = common.require_int(body, "price_multiplier_bps")
    if price_multiplier_bps < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "price_multiplier_bps must be >= 0.")

    for mat in db.film_materials.values():
        if mat["sku"] == sku:
            raise ApiError(errors.ERR_DUPLICATE_SKU, 409, "FilmMaterial sku already exists.")

    rec = {
        "sku": sku,
        "category": category,
        "cure_hours": cure_hours,
        "price_multiplier_bps": price_multiplier_bps,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.film_materials[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/film-materials/<rid>", methods=["GET"])
def get_film_material(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer", "Customer"})
    rec = common.get_or_404(db.film_materials, rid)
    return success(serialize(rec), 200)


# ---- ServicePackage ---------------------------------------------------------
SERVICE_TYPES = {"TINT", "PPF", "WRAP", "CERAMIC"}


@bp.route("/service-packages", methods=["POST"])
def create_service_package():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    name = common.require_string(body, "name")
    service_type = common.require_enum(body, "service_type", SERVICE_TYPES)
    base_rate_cents = common.require_int(body, "base_rate_cents")
    if base_rate_cents < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "base_rate_cents must be >= 0.")
    duration_minutes = common.require_int(body, "duration_minutes")
    if duration_minutes <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "duration_minutes must be > 0.")
    cure_buffer_minutes = common.require_int(body, "cure_buffer_minutes")
    if cure_buffer_minutes < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "cure_buffer_minutes must be >= 0.")
    warranty_days = common.require_int(body, "warranty_days")
    if warranty_days < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "warranty_days must be >= 0.")
    requires_proof = common.require_field(body, "requires_proof")
    if not isinstance(requires_proof, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "requires_proof must be a boolean.")

    rec = {
        "name": name,
        "service_type": service_type,
        "base_rate_cents": base_rate_cents,
        "duration_minutes": duration_minutes,
        "cure_buffer_minutes": cure_buffer_minutes,
        "warranty_days": warranty_days,
        "requires_proof": requires_proof,
    }
    stamp_create(rec)
    db.service_packages[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/service-packages/<rid>", methods=["GET"])
def get_service_package(rid):
    user_id, role = get_identity()
    require_role(role, {"ShopManager", "Installer", "Customer"})
    rec = common.get_or_404(db.service_packages, rid)
    return success(serialize(rec), 200)

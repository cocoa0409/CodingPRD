"""Vehicle profiles and fleet accounts."""
from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_identity, require_role, get_json_body
from models import stamp_create, serialize
from response import success
from services import common
from services import fleet as fleet_svc
from services.calculations import SIZE_SURCHARGE

bp = Blueprint("vehicles_fleet", __name__)

SIZE_CLASSES = {"SEDAN", "SUV", "TRUCK"}


# ---- VehicleProfile ---------------------------------------------------------
@bp.route("/vehicle-profiles", methods=["POST"])
def create_vehicle_profile():
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager"})
    body = get_json_body()
    customer_user_id = common.require_string(body, "customer_user_id")
    vin = common.require_string(body, "vin")
    size_class = common.require_enum(body, "size_class", SIZE_CLASSES)

    # Customer creating a vehicle owns it: X-User-ID must equal customer_user_id.
    if role == "Customer" and customer_user_id != user_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "Customer may only register vehicles they own.")

    for v in db.vehicle_profiles.values():
        if v["vin"] == vin:
            raise ApiError(errors.ERR_DUPLICATE_VIN, 409, "VehicleProfile vin already exists.")

    rec = {
        "customer_user_id": customer_user_id,
        "vin": vin,
        "size_class": size_class,
        "size_surcharge_cents": SIZE_SURCHARGE[size_class],
    }
    stamp_create(rec)
    db.vehicle_profiles[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/vehicle-profiles/<rid>", methods=["GET"])
def get_vehicle_profile(rid):
    user_id, role = get_identity()
    require_role(role, {"Customer", "ShopManager", "Installer"})
    rec = common.get_or_404(db.vehicle_profiles, rid)
    common.check_customer_owns_vehicle(role, user_id, rec)
    return success(serialize(rec), 200)


# ---- FleetAccount -----------------------------------------------------------
@bp.route("/fleet-accounts", methods=["POST"])
def create_fleet_account():
    user_id, role = get_identity()
    require_role(role, {"ShopManager"})
    body = get_json_body()
    company_name = common.require_string(body, "company_name")
    fleet_manager_user_id = common.require_string(body, "fleet_manager_user_id")
    discount_bps = common.require_int(body, "discount_bps")
    if discount_bps < 0 or discount_bps > 10000:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "discount_bps must be between 0 and 10000.")
    credit_limit_cents = common.require_int(body, "credit_limit_cents")
    if credit_limit_cents < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "credit_limit_cents must be >= 0.")

    rec = {
        "company_name": company_name,
        "fleet_manager_user_id": fleet_manager_user_id,
        "discount_bps": discount_bps,
        "credit_limit_cents": credit_limit_cents,
        "held_credit_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.fleet_accounts[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/fleet-accounts/<rid>", methods=["GET"])
def get_fleet_account(rid):
    user_id, role = get_identity()
    require_role(role, {"FleetManager", "ShopManager"})
    rec = common.get_or_404(db.fleet_accounts, rid)
    common.check_fleet_manager_owns(role, user_id, rec)
    # Recompute held credit on read (calc fleet_available_credit, PROVISIONAL).
    fleet_svc.recompute_held_credit(rec)
    return success(serialize(rec), 200)

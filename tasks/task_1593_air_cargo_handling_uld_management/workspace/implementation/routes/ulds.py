"""ULD type / unit / charge endpoints (PRD 3.4 fleet registration, 3.8
return-damage-repair cycle and the per-unit charge ledger)."""

from flask import Blueprint

import db
import serializers
import services
from envelope import success_list, success_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_DUPLICATE_ULD_CODE,
    ERR_ULD_INVALID_STATE,
)
from middleware import require_roles, ALL_ROLES
from util import (
    apply_eq_filter,
    get_json_body,
    paginate,
    parse_pagination,
    require_number,
    require_string,
    sort_created_asc,
)

bp = Blueprint("ulds", __name__)


def get_uld_or_404(uld_id: str) -> dict:
    uld = db.ulds.get(uld_id)
    if uld is None:
        raise_err(ERR_NOT_FOUND, f"ULD {uld_id} not found")
    return uld


# ---------------------------------------------------------------------------
# ULD types
# ---------------------------------------------------------------------------

@bp.route("/uld-types", methods=["POST"])
@require_roles("RampOperator")
def create_uld_type(_user_id: str, _role: str):
    body = get_json_body()
    type_code = require_string(body, "type_code")
    tare_weight = require_number(body, "tare_weight_kg")
    max_gross = require_number(body, "max_gross_weight_kg")
    internal_volume = require_number(body, "internal_volume_m3")
    # rung 11: type codes are unique
    for existing in db.uld_types.values():
        if existing["type_code"] == type_code:
            raise_err(ERR_DUPLICATE_ULD_CODE, f"type_code {type_code} already exists")
    uld_type = {
        "type_code": type_code,
        "tare_weight_kg": tare_weight,
        "max_gross_weight_kg": max_gross,
        "internal_volume_m3": internal_volume,
    }
    db.stamp_new_light(uld_type)  # ULDType carries only id + created_at
    db.uld_types[uld_type["id"]] = uld_type
    return success_object(serializers.uld_type(uld_type), 201)


# ---------------------------------------------------------------------------
# ULD units
# ---------------------------------------------------------------------------

@bp.route("/ulds", methods=["POST"])
@require_roles("RampOperator")
def create_uld(_user_id: str, _role: str):
    body = get_json_body()
    # rung 3: uld_type_id referenced in the body must exist
    type_ref = body.get("uld_type_id")
    if type_ref is not None and type_ref not in db.uld_types:
        raise_err(ERR_NOT_FOUND, f"ULDType {type_ref} not found")
    uld_code = require_string(body, "uld_code")
    uld_type_id = require_string(body, "uld_type_id")
    # rung 11: serial codes unique across all ULDs
    for existing in db.ulds.values():
        if existing["uld_code"] == uld_code:
            raise_err(ERR_DUPLICATE_ULD_CODE, f"uld_code {uld_code} already exists")
    uld = {
        "uld_code": uld_code,
        "uld_type_id": uld_type_id,
        "status": "SERVICEABLE",
        "dispatched_at": None,
        "returned_at": None,
    }
    db.stamp_new(uld)
    db.ulds[uld["id"]] = uld
    return success_object(serializers.uld(uld), 201)


@bp.route("/ulds", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_ulds(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_eq_filter(list(db.ulds.values()), "status")
    items = apply_eq_filter(items, "uld_type_id")
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.uld(u) for u in page], limit, offset, total)


@bp.route("/ulds/<uld_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_uld(uld_id: str, _user_id: str, _role: str):
    return success_object(serializers.uld(get_uld_or_404(uld_id)))


@bp.route("/ulds/<uld_id>/return", methods=["POST"])
@require_roles("RampOperator")
def return_uld(uld_id: str, _user_id: str, _role: str):
    uld = get_uld_or_404(uld_id)
    if uld["status"] != "DISPATCHED":
        raise_err(ERR_ULD_INVALID_STATE, "Return requires ULD DISPATCHED")
    uld["status"] = "RETURNED"
    uld["returned_at"] = db.now_iso()
    db.touch(uld)
    services.finalize_demurrage(uld)
    return success_object(serializers.uld(uld))


@bp.route("/ulds/<uld_id>/report-damage", methods=["POST"])
@require_roles("RampOperator")
def report_damage(uld_id: str, _user_id: str, _role: str):
    uld = get_uld_or_404(uld_id)
    body = get_json_body()
    damage_description = require_string(body, "damage_description")
    repair_cost_estimate = require_number(body, "repair_cost_estimate")
    if uld["status"] != "RETURNED":
        raise_err(ERR_ULD_INVALID_STATE, "Report-damage requires ULD RETURNED")
    uld["status"] = "DAMAGE_REPORTED"
    db.touch(uld)
    charge = {
        "uld_id": uld["id"],
        "charge_type": "REPAIR",
        "amount": services.money2(services.dec(repair_cost_estimate)),
        "tier1_days": None,
        "tier2_days": None,
        "description": damage_description,
        "status": "PROVISIONAL",
    }
    db.stamp_new(charge)
    db.uld_charges[charge["id"]] = charge
    return success_object(serializers.uld(uld))


@bp.route("/ulds/<uld_id>/complete-repair", methods=["POST"])
@require_roles("RampOperator")
def complete_repair(uld_id: str, _user_id: str, _role: str):
    uld = get_uld_or_404(uld_id)
    body = get_json_body()
    final_repair_cost = require_number(body, "final_repair_cost")
    if uld["status"] != "DAMAGE_REPORTED":
        raise_err(ERR_ULD_INVALID_STATE, "Complete-repair requires ULD DAMAGE_REPORTED")
    uld["status"] = "SERVICEABLE"
    db.touch(uld)
    charge = services.provisional_charge(uld["id"], "REPAIR")
    if charge is not None:
        charge["amount"] = services.money2(services.dec(final_repair_cost))
        charge["status"] = "FINALIZED"
        db.touch(charge)
    return success_object(serializers.uld(uld))


@bp.route("/ulds/<uld_id>/release", methods=["POST"])
@require_roles("RampOperator")
def release_uld(uld_id: str, _user_id: str, _role: str):
    uld = get_uld_or_404(uld_id)
    if uld["status"] != "RETURNED":
        raise_err(ERR_ULD_INVALID_STATE, "Release requires ULD RETURNED")
    uld["status"] = "SERVICEABLE"
    db.touch(uld)
    return success_object(serializers.uld(uld))


@bp.route("/ulds/<uld_id>/build-up-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_uld_plans(uld_id: str, _user_id: str, _role: str):
    uld = get_uld_or_404(uld_id)
    limit, offset = parse_pagination()
    items = [p for p in db.build_up_plans.values() if p["uld_id"] == uld["id"]]
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.build_up_plan(p) for p in page], limit, offset, total)


@bp.route("/ulds/<uld_id>/charges", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_uld_charges(uld_id: str, _user_id: str, _role: str):
    uld = get_uld_or_404(uld_id)
    limit, offset = parse_pagination()
    items = [c for c in db.uld_charges.values() if c["uld_id"] == uld["id"]]
    items = apply_eq_filter(items, "charge_type")
    items = apply_eq_filter(items, "status")
    items = sort_created_asc(items)
    page, total = paginate(items, limit, offset)
    return success_list([serializers.uld_charge(c) for c in page], limit, offset, total)


@bp.route("/uld-charges/<charge_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_uld_charge(charge_id: str, _user_id: str, _role: str):
    charge = db.uld_charges.get(charge_id)
    if charge is None:
        raise_err(ERR_NOT_FOUND, f"ULDCharge {charge_id} not found")
    return success_object(serializers.uld_charge(charge))

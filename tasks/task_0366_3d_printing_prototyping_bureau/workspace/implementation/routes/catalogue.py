"""Catalogue & tenant routes: Bureau, Customer, Material, Machine, Spool."""

from datetime import datetime, timezone

from flask import Blueprint

import errors
import validation as V
from db import DB, LOCK, stamp_create, touch
from middleware import require_auth, require_role
from pagination import paginate
from response import object_response, array_response
from services import domain

bp = Blueprint("catalogue", __name__)

EPOCH_CLOCK = "1970-01-01T00:00:00.000Z"
PROCESSES = ("SLA", "FDM", "SLS")

ALL_ROLES = ("BureauAdmin", "Operator", "QAReviewer", "Customer")
STAFF_ROLES = ("BureauAdmin", "Operator", "QAReviewer")


def _parse_iso8601(value):
    """Validate an ISO 8601 instant; return it normalized to 3 fractional
    digits with trailing Z."""
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 string")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --------------------------------------------------------------------------- #
# Bureau
# --------------------------------------------------------------------------- #
@bp.route("/bureaus", methods=["POST"])
def create_bureau():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        body = V.get_body()
        name = V.require_string(body, "name")

        cooldown = 15
        if "cooldown_buffer_min" in body and body["cooldown_buffer_min"] is not None:
            cooldown = V.require_nonneg_int(body, "cooldown_buffer_min")
        shift = 480
        if "shift_capacity_minutes" in body and body["shift_capacity_minutes"] is not None:
            shift = V.require_positive_int(body, "shift_capacity_minutes")

        bureau = stamp_create({
            "name": name,
            "cooldown_buffer_min": cooldown,
            "shift_capacity_minutes": shift,
            "clock_utc": EPOCH_CLOCK,
        })
        DB.bureaus[bureau["id"]] = bureau
        return object_response(bureau, 201)


@bp.route("/bureaus/<bureau_id>", methods=["GET"])
def get_bureau(bureau_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ALL_ROLES)
        bureau = domain.get_or_404(DB.bureaus, bureau_id)
        return object_response(bureau, 200)


@bp.route("/bureaus/<bureau_id>/clock", methods=["POST"])
def set_clock(bureau_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        bureau = domain.get_or_404(DB.bureaus, bureau_id)
        body = V.get_body()
        if "to_iso8601" not in body:
            raise errors.invalid_request("Missing field: to_iso8601")
        bureau["clock_utc"] = _parse_iso8601(body["to_iso8601"])
        touch(bureau)
        return object_response(bureau, 200)


# --------------------------------------------------------------------------- #
# Customer
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/customers", methods=["POST"])
def create_customer():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        body = V.get_body()
        bureau_id = V.require_id(body, "bureau_id")
        email = V.require_string(body, "email")
        display_name = V.require_string(body, "display_name")
        if bureau_id not in DB.bureaus:
            raise errors.reference_not_found()

        customer = stamp_create({
            "bureau_id": bureau_id,
            "email": email,
            "display_name": display_name,
            "lifetime_deposits_cents": 0,
            "wallet_balance_cents": 0,
            "escrow_held_cents": 0,
            "captured_revenue_cents": 0,
        })
        DB.customers[customer["id"]] = customer
        return object_response(customer, 201)


@bp.route("/bureaus/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ALL_ROLES)
        customer = domain.get_or_404(DB.customers, customer_id)
        if principal.role == "Customer" and principal.user_id != customer["id"]:
            raise errors.forbidden()
        return object_response(customer, 200)


@bp.route("/bureaus/customers", methods=["GET"])
def list_customers():
    with LOCK:
        principal = require_auth()
        require_role(principal, STAFF_ROLES)
        items = list(DB.customers.values())
        bureau_id = _arg("bureau_id")
        email = _arg("email")
        if bureau_id is not None:
            items = [c for c in items if c["bureau_id"] == bureau_id]
        if email is not None:
            items = [c for c in items if c["email"] == email]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bureaus/customers/<customer_id>/deposit", methods=["POST"])
def deposit(customer_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        customer = domain.get_or_404(DB.customers, customer_id)
        body = V.get_body()
        amount = V.require_positive_int(body, "amount_cents")
        customer["wallet_balance_cents"] += amount
        customer["lifetime_deposits_cents"] += amount
        touch(customer)
        return object_response(customer, 200)


# --------------------------------------------------------------------------- #
# Material
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/materials", methods=["POST"])
def create_material():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        body = V.get_body()
        bureau_id = V.require_id(body, "bureau_id")
        process = V.require_enum(body, "process", PROCESSES)
        name = V.require_string(body, "name")
        density = V.require_positive_number(body, "density_g_per_cm3")
        material_rate = V.require_positive_number(body, "material_rate_cents_per_cm3")
        machine_rate = V.require_positive_number(body, "machine_rate_cents_per_min")
        setup_fee = V.require_nonneg_int(body, "setup_fee_cents")
        min_wall = V.require_positive_number(body, "min_wall_thickness_mm")
        max_overhang = V.require_positive_number(body, "max_overhang_deg")
        if bureau_id not in DB.bureaus:
            raise errors.reference_not_found()

        material = stamp_create({
            "bureau_id": bureau_id,
            "process": process,
            "name": name,
            "density_g_per_cm3": density,
            "material_rate_cents_per_cm3": material_rate,
            "machine_rate_cents_per_min": machine_rate,
            "setup_fee_cents": setup_fee,
            "min_wall_thickness_mm": min_wall,
            "max_overhang_deg": max_overhang,
            "status": "ACTIVE",
        })
        DB.materials[material["id"]] = material
        return object_response(material, 201)


@bp.route("/bureaus/materials/<material_id>", methods=["GET"])
def get_material(material_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ALL_ROLES)
        material = domain.get_or_404(DB.materials, material_id)
        return object_response(material, 200)


@bp.route("/bureaus/materials", methods=["GET"])
def list_materials():
    with LOCK:
        principal = require_auth()
        require_role(principal, ALL_ROLES)
        items = list(DB.materials.values())
        for key in ("bureau_id", "process", "status"):
            val = _arg(key)
            if val is not None:
                items = [m for m in items if m[key] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bureaus/materials/<material_id>/retire", methods=["POST"])
def retire_material(material_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        material = domain.get_or_404(DB.materials, material_id)
        material["status"] = "RETIRED"
        touch(material)
        return object_response(material, 200)


# --------------------------------------------------------------------------- #
# Machine
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/machines", methods=["POST"])
def create_machine():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin",))
        body = V.get_body()
        bureau_id = V.require_id(body, "bureau_id")
        process = V.require_enum(body, "process", PROCESSES)
        label = V.require_string(body, "label")
        bx = V.require_positive_number(body, "build_x_mm")
        by = V.require_positive_number(body, "build_y_mm")
        bz = V.require_positive_number(body, "build_z_mm")
        if bureau_id not in DB.bureaus:
            raise errors.reference_not_found()

        machine = stamp_create({
            "bureau_id": bureau_id,
            "process": process,
            "label": label,
            "build_x_mm": bx,
            "build_y_mm": by,
            "build_z_mm": bz,
            "scheduled_minutes": 0,
            "active_minutes": 0,
            "utilization_pct": 0,
            "active_utilization_pct": 0,
            "status": "ONLINE",
        })
        DB.machines[machine["id"]] = machine
        return object_response(machine, 201)


@bp.route("/bureaus/machines/<machine_id>", methods=["GET"])
def get_machine(machine_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, STAFF_ROLES)
        machine = domain.get_or_404(DB.machines, machine_id)
        return object_response(machine, 200)


@bp.route("/bureaus/machines", methods=["GET"])
def list_machines():
    with LOCK:
        principal = require_auth()
        require_role(principal, STAFF_ROLES)
        items = list(DB.machines.values())
        for key in ("bureau_id", "process", "status"):
            val = _arg(key)
            if val is not None:
                items = [m for m in items if m[key] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bureaus/machines/<machine_id>/maintenance", methods=["POST"])
def toggle_maintenance(machine_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin", "Operator"))
        machine = domain.get_or_404(DB.machines, machine_id)
        body = V.get_body()
        status = V.require_enum(body, "status", ("ONLINE", "MAINTENANCE"))
        machine["status"] = status
        touch(machine)
        return object_response(machine, 200)


# --------------------------------------------------------------------------- #
# Spool
# --------------------------------------------------------------------------- #
@bp.route("/bureaus/spools", methods=["POST"])
def create_spool():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("BureauAdmin", "Operator"))
        body = V.get_body()
        bureau_id = V.require_id(body, "bureau_id")
        material_id = V.require_id(body, "material_id")
        grams_total = V.require_positive_int(body, "grams_total")
        if bureau_id not in DB.bureaus:
            raise errors.reference_not_found()
        domain.ref_or_404(DB.materials, material_id, bureau_id)

        spool = stamp_create({
            "bureau_id": bureau_id,
            "material_id": material_id,
            "grams_total": grams_total,
            "grams_committed": 0,
            "grams_consumed": 0,
            "grams_remaining": grams_total,
            "status": "LOADED" if grams_total > 0 else "DEPLETED",
        })
        DB.spools[spool["id"]] = spool
        return object_response(spool, 201)


@bp.route("/bureaus/spools/<spool_id>", methods=["GET"])
def get_spool(spool_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, STAFF_ROLES)
        spool = domain.get_or_404(DB.spools, spool_id)
        return object_response(spool, 200)


@bp.route("/bureaus/spools", methods=["GET"])
def list_spools():
    with LOCK:
        principal = require_auth()
        require_role(principal, STAFF_ROLES)
        items = list(DB.spools.values())
        for key in ("bureau_id", "material_id", "status"):
            val = _arg(key)
            if val is not None:
                items = [s for s in items if s[key] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


# --------------------------------------------------------------------------- #
def _arg(name):
    from flask import request
    return request.args.get(name)

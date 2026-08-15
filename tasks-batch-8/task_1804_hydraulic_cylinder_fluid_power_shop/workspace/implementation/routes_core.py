"""Routes: logical clock, shops, customers, technicians, seal kits, cylinders."""

from flask import Blueprint

from db import DB, CLOCK, make_entity, touch, serialize, sorted_entities
from middleware import (
    validate_body, require_auth, require_role, parse_pagination, get_filter, ALL_ROLES,
)
from errors import err_invalid_state, err_invalid_request
from helpers import get_or_404, check_customer_owns, check_seal_kit_compatible
from calc import SHOP_DEFAULTS
from response import success_object, success_list

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/_clock/set_current_utc")
def set_clock():
    body = validate_body([
        ("to_iso8601", ("datetime", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    from db import parse_iso8601
    CLOCK.set(parse_iso8601(body["to_iso8601"]))
    return success_object({"current_utc": body["to_iso8601"]})


# ---------------------------------------------------------------------------
# Shops (PRD 2.10)
# ---------------------------------------------------------------------------

# Fields overridable at creation time (everything else fixed at defaults).
SHOP_CREATE_OVERRIDES = [
    ("labor_rate_cents_per_hour", ("integer", False, False)),
    ("expedite_multiplier", ("number", False, False)),
    ("emergency_multiplier", ("number", False, False)),
    ("expedite_cutoff_hours", ("integer", False, False)),
    ("emergency_cutoff_hours", ("integer", False, False)),
    ("honing_pass_fee_cents", ("integer", False, False)),
    ("cut_fee_cents", ("integer", False, False)),
    ("kerf_mm", ("integer", False, False)),
    ("min_remnant_mm", ("integer", False, False)),
    ("cleanliness_target_code4", ("integer", False, False)),
    ("cleanliness_target_code6", ("integer", False, False)),
    ("cleanliness_target_code14", ("integer", False, False)),
    ("quote_ttl_hours", ("integer", False, False)),
    ("bay_buffer_minutes", ("integer", False, False)),
]

# Fields patchable later (PRD 2.10: kerf, cleanliness targets, and the rest are
# not patchable).
SHOP_PATCH_FIELDS = [
    ("labor_rate_cents_per_hour", ("integer", False, False)),
    ("expedite_multiplier", ("number", False, False)),
    ("emergency_multiplier", ("number", False, False)),
    ("expedite_cutoff_hours", ("integer", False, False)),
    ("emergency_cutoff_hours", ("integer", False, False)),
    ("honing_pass_fee_cents", ("integer", False, False)),
    ("cut_fee_cents", ("integer", False, False)),
    ("min_remnant_mm", ("integer", False, False)),
    ("quote_ttl_hours", ("integer", False, False)),
    ("bay_buffer_minutes", ("integer", False, False)),
]


@bp.post("/fluid-power/shops")
def create_shop():
    body = validate_body([("name", ("string", True, False))] + SHOP_CREATE_OVERRIDES)
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    fields = {"name": body["name"]}
    fields.update(SHOP_DEFAULTS)
    for key, _spec in SHOP_CREATE_OVERRIDES:
        if body.get(key) is not None:
            fields[key] = body[key]
    shop = make_entity(fields)
    DB.shops[shop["id"]] = shop
    return success_object(serialize(shop), status=201)


@bp.get("/fluid-power/shops/<shop_id>")
def get_shop(shop_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    shop = get_or_404(DB.shops, shop_id)
    return success_object(serialize(shop))


@bp.patch("/fluid-power/shops/<shop_id>")
def patch_shop(shop_id):
    body = validate_body(
        [("expected_shop_version", ("integer", True, False))] + SHOP_PATCH_FIELDS)
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    shop = get_or_404(DB.shops, shop_id)
    if body["expected_shop_version"] != shop["version"]:
        from errors import err_stale_version
        raise err_stale_version()
    for key, _spec in SHOP_PATCH_FIELDS:
        if key in body and body[key] is not None:
            shop[key] = body[key]
    touch(shop)
    return success_object(serialize(shop))


# ---------------------------------------------------------------------------
# Customers (PRD 3.1)
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/customers")
def create_customer():
    body = validate_body([
        ("full_name", ("string", True, False)),
        ("email", ("string", True, False)),
        ("credit_limit_cents", ("integer", True, False)),
        ("opening_ytd_spend_cents", ("integer", False, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    opening = body.get("opening_ytd_spend_cents") or 0
    customer = make_entity({
        "full_name": body["full_name"],
        "email": body["email"],
        "credit_limit_cents": body["credit_limit_cents"],
        "opening_ytd_spend_cents": opening,
        "ytd_spend_cents": opening,
        "status": "ACTIVE",
    })
    DB.customers[customer["id"]] = customer
    return success_object(serialize(customer), status=201)


@bp.get("/fluid-power/customers/<customer_id>")
def get_customer(customer_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.customers, customer_id)))


@bp.post("/fluid-power/customers/<customer_id>/suspend")
def suspend_customer(customer_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    customer = get_or_404(DB.customers, customer_id)
    if customer["status"] != "ACTIVE":
        raise err_invalid_state("Customer is not ACTIVE")
    customer["status"] = "SUSPENDED"
    touch(customer)
    return success_object(serialize(customer))


@bp.post("/fluid-power/customers/<customer_id>/reactivate")
def reactivate_customer(customer_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    customer = get_or_404(DB.customers, customer_id)
    if customer["status"] != "SUSPENDED":
        raise err_invalid_state("Customer is not SUSPENDED")
    customer["status"] = "ACTIVE"
    touch(customer)
    return success_object(serialize(customer))


# ---------------------------------------------------------------------------
# Technicians (PRD 3.1)
# ---------------------------------------------------------------------------

TECH_SKILLS = ["CYLINDER_REPAIR", "FIELD_SERVICE"]


@bp.post("/fluid-power/technicians")
def create_technician():
    body = validate_body([
        ("full_name", ("string", True, False)),
        ("skills", ("enum_array", True, False, TECH_SKILLS, True)),
        ("active", ("boolean", False, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    tech = make_entity({
        "full_name": body["full_name"],
        "skills": list(body["skills"]),
        "active": body["active"] if body.get("active") is not None else True,
    })
    DB.technicians[tech["id"]] = tech
    return success_object(serialize(tech), status=201)


@bp.get("/fluid-power/technicians/<technician_id>")
def get_technician(technician_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.technicians, technician_id)))


# ---------------------------------------------------------------------------
# Seal kits (PRD 3.1)
# ---------------------------------------------------------------------------

PRESSURE_CLASSES = ["CLASS_3000", "CLASS_5000"]
FLUID_TYPES = ["MINERAL_OIL", "PHOSPHATE_ESTER", "WATER_GLYCOL"]
SEAL_MATERIALS = ["NBR", "VITON", "PU"]


@bp.post("/fluid-power/seal-kits")
def create_seal_kit():
    body = validate_body([
        ("kit_code", ("string", True, False)),
        ("bore_min_mm", ("integer", True, False)),
        ("bore_max_mm", ("integer", True, False)),
        ("pressure_class_max", ("enum", True, False, PRESSURE_CLASSES)),
        ("fluid_compat", ("enum_array", True, False, FLUID_TYPES, False)),
        ("price_cents", ("integer", True, False)),
        ("material", ("enum", True, False, SEAL_MATERIALS)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin"])
    for existing in DB.seal_kits.values():
        if existing["kit_code"] == body["kit_code"]:
            raise err_invalid_request("kit_code must be unique across all seal kits")
    kit = make_entity({
        "kit_code": body["kit_code"],
        "bore_min_mm": body["bore_min_mm"],
        "bore_max_mm": body["bore_max_mm"],
        "pressure_class_max": body["pressure_class_max"],
        "fluid_compat": list(body["fluid_compat"]),
        "price_cents": body["price_cents"],
        "material": body["material"],
    })
    DB.seal_kits[kit["id"]] = kit
    return success_object(serialize(kit), status=201)


@bp.get("/fluid-power/seal-kits/<kit_id>")
def get_seal_kit(kit_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.seal_kits, kit_id)))


# ---------------------------------------------------------------------------
# Cylinders (PRD 3.1)
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/cylinders")
def create_cylinder():
    body = validate_body([
        ("customer_id", ("string", True, False)),
        ("serial_number", ("string", True, False)),
        ("bore_mm", ("integer", True, False)),
        ("stroke_mm", ("integer", True, False)),
        ("rod_diameter_mm", ("integer", True, False)),
        ("pressure_class", ("enum", True, False, PRESSURE_CLASSES)),
        ("fluid_type", ("enum", True, False, FLUID_TYPES)),
        ("seal_kit_id", ("string", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor", "Customer"])
    # ownership (priority 4): a Customer actor registers only its own assets
    check_customer_owns(actor, body["customer_id"])
    # existence (priority 5): body FKs left-to-right per declared input order
    get_or_404(DB.customers, body["customer_id"])
    kit = get_or_404(DB.seal_kits, body["seal_kit_id"])
    # safety (priority 9): seal-kit compatibility
    check_seal_kit_compatible(kit, body["bore_mm"], body["pressure_class"], body["fluid_type"])
    cylinder = make_entity({
        "customer_id": body["customer_id"],
        "serial_number": body["serial_number"],
        "bore_mm": body["bore_mm"],
        "stroke_mm": body["stroke_mm"],
        "rod_diameter_mm": body["rod_diameter_mm"],
        "pressure_class": body["pressure_class"],
        "fluid_type": body["fluid_type"],
        "seal_kit_id": body["seal_kit_id"],
        "status": "ACTIVE",
    })
    DB.cylinders[cylinder["id"]] = cylinder
    return success_object(serialize(cylinder), status=201)


@bp.get("/fluid-power/cylinders/<cylinder_id>")
def get_cylinder(cylinder_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.cylinders, cylinder_id)))


@bp.get("/fluid-power/cylinders")
def list_cylinders():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    customer_id = get_filter("customer_id")
    seal_kit_id = get_filter("seal_kit_id")
    status = get_filter("status")
    items = sorted_entities(DB.cylinders)
    if customer_id is not None:
        items = [c for c in items if c["customer_id"] == customer_id]
    if seal_kit_id is not None:
        items = [c for c in items if c["seal_kit_id"] == seal_kit_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(c) for c in page], limit, offset, total)

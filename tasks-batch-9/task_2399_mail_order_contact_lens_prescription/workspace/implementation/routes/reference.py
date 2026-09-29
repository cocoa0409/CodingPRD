"""Logical clock, vision plans, products, lens equivalences, prescribers, patients."""

from flask import Blueprint

from db import db, make_row, set_clock, sort_rows, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_CUSTOMER,
    ROLE_FULFILLMENT,
    ROLE_PRESCRIBER,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_role,
)
from response import list_response, object_response
from services.ledger import allowance_remaining, compute_ledger

bp = Blueprint("reference", __name__)

NETWORK_STATUSES = ("IN_NETWORK", "OUT_OF_NETWORK")
PLAN_STATUSES = ("ACTIVE", "RETIRED")
WEAR_SCHEDULES = ("DAILY_DISPOSABLE", "BIWEEKLY", "MONTHLY")
PRODUCT_STATUSES = ("ACTIVE", "INACTIVE")
EQUIVALENCE_CLASSES = ("EXACT", "CLINICAL", "MATERIAL_ONLY")
EQUIVALENCE_STATUSES = ("ACTIVE", "RETIRED")
CONTACT_CHANNELS = ("FAX", "PORTAL", "EMAIL")
PRESCRIBER_STATUSES = ("ACTIVE", "SUSPENDED")


# ----------------------------------------------------------------- logical clock


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = identity()
    body = parse_body({"current_utc": {"type": "timestamp", "required": True}})
    require_role(role, [ROLE_ADMIN])
    set_clock(body["current_utc"])
    return object_response({"current_utc": db.clock})


@bp.get("/_clock")
def read_clock():
    _, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT])
    return object_response({"current_utc": db.clock})


# ------------------------------------------------------------------ vision plans


@bp.post("/insurance-plans")
def create_insurance_plan():
    _, role = identity()
    body = parse_body(
        {
            "name": {"type": "string", "required": True},
            "network_status": {"type": "enum", "values": NETWORK_STATUSES, "required": True},
            "annual_allowance_cents": {"type": "int", "required": True, "min": 0},
            "coinsurance_rate": {"type": "decimal", "required": True, "min": 0, "max": 1, "places": 2},
            "requires_itemized_receipt": {"type": "bool", "default": True},
            "covers_shipping": {"type": "bool", "default": False},
            "claim_window_days": {"type": "int", "min": 0, "default": 90},
            "plan_year_start_month_day": {"type": "mmdd", "default": "01-01"},
            "status": {"type": "enum", "values": PLAN_STATUSES, "default": "ACTIVE"},
        }
    )
    require_role(role, [ROLE_ADMIN])
    row = make_row(
        {
            "name": body["name"],
            "network_status": body["network_status"],
            "annual_allowance_cents": body["annual_allowance_cents"],
            "coinsurance_rate": body["coinsurance_rate"],
            "requires_itemized_receipt": body["requires_itemized_receipt"],
            "covers_shipping": body["covers_shipping"],
            "claim_window_days": body["claim_window_days"],
            "plan_year_start_month_day": body["plan_year_start_month_day"],
            "status": body["status"],
        }
    )
    db.insurance_plans[row["id"]] = row
    return object_response(row, 201)


@bp.get("/insurance-plans/<plan_id>")
def get_insurance_plan(plan_id):
    _, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    return object_response(lookup("insurance_plan", plan_id))


@bp.get("/insurance-plans")
def list_insurance_plans():
    _, role = identity()
    filters = parse_query(
        {
            "network_status": {"type": "enum", "values": NETWORK_STATUSES},
            "status": {"type": "enum", "values": PLAN_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE])
    rows = list(db.insurance_plans.values())
    if filters["network_status"]:
        rows = [r for r in rows if r["network_status"] == filters["network_status"]]
    if filters["status"]:
        rows = [r for r in rows if r["status"] == filters["status"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/insurance-plans/<plan_id>/retire")
def retire_insurance_plan(plan_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_ADMIN])
    plan = lookup("insurance_plan", plan_id)
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    plan["status"] = "RETIRED"
    touch(plan)
    return object_response(plan)


# ---------------------------------------------------------------------- products


@bp.post("/products")
def create_product():
    _, role = identity()
    body = parse_body(
        {
            "brand": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "wear_schedule": {"type": "enum", "values": WEAR_SCHEDULES, "required": True},
            "lenses_per_box": {"type": "int", "required": True, "min": 1},
            "unit_price_cents": {"type": "int", "required": True, "min": 1},
            "base_curve": {"type": "decimal", "required": True, "places": 2},
            "diameter": {"type": "decimal", "required": True, "places": 2},
            "sphere_min": {"type": "decimal", "required": True, "places": 2},
            "sphere_max": {"type": "decimal", "required": True, "places": 2},
            "sphere_step": {"type": "decimal", "places": 2, "default": None},
            "material_family": {"type": "string", "required": True},
            "status": {"type": "enum", "values": PRODUCT_STATUSES, "default": "ACTIVE"},
        }
    )
    require_role(role, [ROLE_ADMIN])
    if body["sphere_max"] < body["sphere_min"]:
        raise ApiError("ERR_INVALID_REQUEST", "sphere_max must be at least sphere_min.")
    step = body["sphere_step"]
    if step is None:
        from decimal import Decimal

        step = Decimal("0.25")
    row = make_row(
        {
            "brand": body["brand"],
            "name": body["name"],
            "wear_schedule": body["wear_schedule"],
            "lenses_per_box": body["lenses_per_box"],
            "unit_price_cents": body["unit_price_cents"],
            "base_curve": body["base_curve"],
            "diameter": body["diameter"],
            "sphere_min": body["sphere_min"],
            "sphere_max": body["sphere_max"],
            "sphere_step": step,
            "material_family": body["material_family"],
            "status": body["status"],
        }
    )
    db.products[row["id"]] = row
    return object_response(row, 201)


@bp.get("/products/<product_id>")
def get_product(product_id):
    _, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT, ROLE_CUSTOMER])
    return object_response(lookup("product", product_id))


@bp.get("/products")
def list_products():
    _, role = identity()
    filters = parse_query(
        {
            "wear_schedule": {"type": "enum", "values": WEAR_SCHEDULES},
            "status": {"type": "enum", "values": PRODUCT_STATUSES},
            "material_family": {"type": "string"},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT, ROLE_CUSTOMER])
    rows = list(db.products.values())
    if filters["wear_schedule"]:
        rows = [r for r in rows if r["wear_schedule"] == filters["wear_schedule"]]
    if filters["status"]:
        rows = [r for r in rows if r["status"] == filters["status"]]
    if filters["material_family"]:
        rows = [r for r in rows if r["material_family"] == filters["material_family"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/products/<product_id>/deactivate")
def deactivate_product(product_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_ADMIN])
    product = lookup("product", product_id)
    if product["status"] == "INACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    product["status"] = "INACTIVE"
    touch(product)
    return object_response(product)


# ------------------------------------------------------------- lens equivalences


@bp.post("/products/<product_id>/lens-equivalences")
def create_lens_equivalence(product_id):
    _, role = identity()
    body = parse_body(
        {
            "to_product_id": {"type": "uuid", "required": True},
            "equivalence_class": {"type": "enum", "values": EQUIVALENCE_CLASSES, "required": True},
            "requires_patient_consent": {"type": "bool", "default": False},
            "status": {"type": "enum", "values": EQUIVALENCE_STATUSES, "default": "ACTIVE"},
        }
    )
    require_role(role, [ROLE_ADMIN])
    lookup("product", product_id)
    lookup("product", body["to_product_id"])
    row = make_row(
        {
            "from_product_id": product_id,
            "to_product_id": body["to_product_id"],
            "equivalence_class": body["equivalence_class"],
            "requires_patient_consent": body["requires_patient_consent"],
            "status": body["status"],
        }
    )
    db.lens_equivalences[row["id"]] = row
    return object_response(row, 201)


@bp.get("/products/<product_id>/lens-equivalences")
def list_lens_equivalences(product_id):
    _, role = identity()
    filters = parse_query(
        {
            "direction": {"type": "enum", "values": ("FROM", "TO")},
            "status": {"type": "enum", "values": EQUIVALENCE_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_FULFILLMENT])
    lookup("product", product_id)
    rows = []
    for row in db.lens_equivalences.values():
        if filters["direction"] == "FROM":
            match = row["from_product_id"] == product_id
        elif filters["direction"] == "TO":
            match = row["to_product_id"] == product_id
        else:
            match = product_id in (row["from_product_id"], row["to_product_id"])
        if match:
            rows.append(row)
    if filters["status"]:
        rows = [r for r in rows if r["status"] == filters["status"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


# ------------------------------------------------------------------- prescribers


@bp.post("/prescribers")
def create_prescriber():
    _, role = identity()
    body = parse_body(
        {
            "full_name": {"type": "string", "required": True},
            "license_number": {"type": "string", "required": True},
            "license_state": {"type": "string", "required": True},
            "contact_channel": {"type": "enum", "values": CONTACT_CHANNELS, "required": True},
            "directory_verified": {"type": "bool", "default": False},
            "status": {"type": "enum", "values": PRESCRIBER_STATUSES, "default": "ACTIVE"},
        }
    )
    require_role(role, [ROLE_ADMIN])
    for existing in db.prescribers.values():
        if (
            existing["license_number"] == body["license_number"]
            and existing["license_state"] == body["license_state"]
        ):
            raise ApiError("ERR_DUPLICATE_LICENSE")
    row = make_row(
        {
            "full_name": body["full_name"],
            "license_number": body["license_number"],
            "license_state": body["license_state"],
            "contact_channel": body["contact_channel"],
            "directory_verified": body["directory_verified"],
            "status": body["status"],
        }
    )
    db.prescribers[row["id"]] = row
    return object_response(row, 201)


@bp.get("/prescribers/<prescriber_id>")
def get_prescriber(prescriber_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_PRESCRIBER])
    prescriber = lookup("prescriber", prescriber_id)
    require_owner(role, user_id, prescriber["id"], ROLE_PRESCRIBER)
    return object_response(prescriber)


@bp.get("/prescribers")
def list_prescribers():
    _, role = identity()
    filters = parse_query(
        {
            "license_state": {"type": "string"},
            "directory_verified": {"type": "bool"},
            "status": {"type": "enum", "values": PRESCRIBER_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE])
    rows = list(db.prescribers.values())
    if filters["license_state"]:
        rows = [r for r in rows if r["license_state"] == filters["license_state"]]
    if filters["directory_verified"] is not None:
        rows = [r for r in rows if r["directory_verified"] == filters["directory_verified"]]
    if filters["status"]:
        rows = [r for r in rows if r["status"] == filters["status"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/prescribers/<prescriber_id>/suspend")
def suspend_prescriber(prescriber_id):
    _, role = identity()
    parse_body({})
    require_role(role, [ROLE_ADMIN])
    prescriber = lookup("prescriber", prescriber_id)
    if prescriber["status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    prescriber["status"] = "SUSPENDED"
    touch(prescriber)
    return object_response(prescriber)


# --------------------------------------------------------------------- customers


@bp.post("/customers")
def create_customer():
    _, role = identity()
    body = parse_body(
        {
            "full_name": {"type": "string", "required": True},
            "email": {"type": "string", "required": True},
            "state_code": {"type": "string", "required": True},
            "insurance_plan_id": {"type": "uuid"},
        }
    )
    require_role(role, [ROLE_ADMIN])
    if body["insurance_plan_id"] is not None:
        lookup("insurance_plan", body["insurance_plan_id"])
    for existing in db.customers.values():
        if existing["email"] == body["email"]:
            raise ApiError("ERR_DUPLICATE_EMAIL")
    row = make_row(
        {
            "full_name": body["full_name"],
            "email": body["email"],
            "state_code": body["state_code"],
            "insurance_plan_id": body["insurance_plan_id"],
            "store_credit_cents": 0,
            "lifetime_charged_cents": 0,
            "lifetime_refunded_cents": 0,
            "net_cash_position_cents": 0,
            "allowance_used_cents": 0,
            "open_hold_count": 0,
            "active_schedule_count": 0,
            "auto_reorder_enabled": False,
        }
    )
    db.customers[row["id"]] = row
    return object_response(row, 201)


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    customer = lookup("customer", customer_id)
    require_owner(role, user_id, customer["id"])
    return object_response(customer)


@bp.get("/customers")
def list_customers():
    _, role = identity()
    filters = parse_query(
        {
            "insurance_plan_id": {"type": "string"},
            "state_code": {"type": "string"},
            "auto_reorder_enabled": {"type": "bool"},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE])
    rows = list(db.customers.values())
    if filters["insurance_plan_id"]:
        rows = [r for r in rows if r["insurance_plan_id"] == filters["insurance_plan_id"]]
    if filters["state_code"]:
        rows = [r for r in rows if r["state_code"] == filters["state_code"]]
    if filters["auto_reorder_enabled"] is not None:
        rows = [r for r in rows if r["auto_reorder_enabled"] == filters["auto_reorder_enabled"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/customers/<customer_id>/ledger")
def get_customer_ledger(customer_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER])
    customer = lookup("customer", customer_id)
    require_owner(role, user_id, customer["id"])
    ledger = compute_ledger(customer)
    payload = {
        "customer_id": customer["id"],
        "lifetime_charged_cents": ledger["lifetime_charged_cents"],
        "lifetime_refunded_cents": ledger["lifetime_refunded_cents"],
        "net_cash_position_cents": ledger["net_cash_position_cents"],
        "store_credit_cents": ledger["store_credit_cents"],
        "allowance_used_cents": ledger["allowance_used_cents"],
        "allowance_remaining_cents": allowance_remaining(customer, ledger["allowance_used_cents"]),
        "open_hold_count": ledger["open_hold_count"],
        "active_schedule_count": ledger["active_schedule_count"],
        "auto_reorder_enabled": ledger["auto_reorder_enabled"],
    }
    return object_response(payload)

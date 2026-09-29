"""Accounts, catalog models, warehouses, carriers and the logical clock."""
from flask import Blueprint

import calc
from common import (
    ALL_ROLES, ApiError, DB, D, STATE_CODE_RE, authenticate, f_bool, f_enum,
    f_enum_list, f_int, f_num, f_str, f_datetime, get_body, must, new_row, num,
    ok, page, parse_dt, public, qp, rhu, scope, touch,
)

bp = Blueprint("ref", __name__, url_prefix="/distribution")

READ_ALL = ALL_ROLES
OPERATORS = ["PlatformAdmin", "SalesRep", "WarehouseOperator", "HazmatCertifier", "ComplianceOfficer"]


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@bp.post("/accounts")
def create_account():
    authenticate(["PlatformAdmin"])
    body = get_body()
    name = f_str(body, "name")
    tier = f_enum(body, "account_tier", ("PLATINUM", "GOLD", "STANDARD"))
    state_code = f_str(body, "state_code", pattern=STATE_CODE_RE)
    credit_limit = f_int(body, "credit_limit_cents", required=False, default=0, minimum=0)
    rank = f_int(body, "storm_priority_rank", required=False, default=9, minimum=1, maximum=9)
    row = new_row({
        "name": name,
        "account_tier": tier,
        "state_code": state_code,
        "storm_priority_rank": rank,
        "credit_limit_cents": credit_limit,
        "open_receivable_cents": 0,
        "core_deposit_balance_cents": 0,
        "warranty_credit_cents": 0,
        "lifetime_lead_recovered_kg": 0.0,
        "status": "ACTIVE",
    })
    DB.accounts[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/accounts/<account_id>")
def read_account(account_id):
    user_id, role = authenticate(READ_ALL)
    row = must("accounts", account_id)
    scope(role, user_id, row["id"])
    return ok(public(row))


# ---------------------------------------------------------------------------
# Battery models
# ---------------------------------------------------------------------------
@bp.post("/battery-models")
def create_battery_model():
    authenticate(["PlatformAdmin"])
    body = get_body()
    sku = f_str(body, "sku")
    chemistry = f_enum(body, "chemistry", calc.CHEMISTRIES)
    nominal_voltage = f_num(body, "nominal_voltage", exclusive_min=0)
    amp_hour_capacity = f_num(body, "amp_hour_capacity", exclusive_min=0)
    peukert = f_num(body, "peukert_exponent", minimum=1.0, maximum=1.5)
    unit_weight = f_num(body, "unit_weight_kg", exclusive_min=0)
    lead_content = f_num(body, "lead_content_kg", minimum=0)
    core_deposit = f_int(body, "core_deposit_cents", minimum=0)
    list_price = f_int(body, "list_price_cents", minimum=1)
    free_months = f_int(body, "warranty_free_replacement_months", minimum=0)
    prorata_months = f_int(body, "warranty_prorata_months", minimum=1)
    shelf_life = f_int(body, "shelf_life_days", minimum=1)
    self_discharge = f_num(body, "self_discharge_pct_per_month", exclusive_min=0)

    for existing in DB.battery_models.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", "sku already taken")

    watt_hours = rhu(D(nominal_voltage) * D(amp_hour_capacity), 2)
    class_code = calc.classify_model(chemistry, unit_weight, watt_hours)
    row = new_row({
        "sku": sku,
        "chemistry": chemistry,
        "nominal_voltage": nominal_voltage,
        "amp_hour_capacity": amp_hour_capacity,
        "peukert_exponent": peukert,
        "unit_weight_kg": unit_weight,
        "lead_content_kg": lead_content,
        "core_deposit_cents": core_deposit,
        "list_price_cents": list_price,
        "warranty_free_replacement_months": free_months,
        "warranty_prorata_months": prorata_months,
        "shelf_life_days": shelf_life,
        "self_discharge_pct_per_month": self_discharge,
        "watt_hour_rating": float(watt_hours),
        "hazmat_class_code": class_code,
        "hazmat_severity_rank": calc.HAZMAT_SEVERITY_RANK[class_code],
        "replacement_model_id": None,
        "status": "ACTIVE",
    })
    DB.battery_models[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/battery-models/<model_id>")
def read_battery_model(model_id):
    authenticate(READ_ALL)
    return ok(public(must("battery_models", model_id)))


@bp.get("/battery-models")
def list_battery_models():
    authenticate(READ_ALL)
    rows = list(DB.battery_models.values())
    chemistry = qp("chemistry")
    status = qp("status")
    replacement = qp("replacement_model_id")
    if chemistry is not None:
        rows = [r for r in rows if r["chemistry"] == chemistry]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if replacement is not None:
        rows = [r for r in rows if r["replacement_model_id"] == replacement]
    return page(rows, public)


@bp.post("/battery-models/<model_id>/discontinue")
def discontinue_battery_model(model_id):
    authenticate(["PlatformAdmin"])
    row = must("battery_models", model_id)
    body = get_body()
    replacement_id = f_str(body, "replacement_model_id")
    must("battery_models", replacement_id)
    row["status"] = "DISCONTINUED"
    row["replacement_model_id"] = replacement_id
    touch(row)
    return ok(public(row))


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------
@bp.post("/warehouses")
def create_warehouse():
    authenticate(["PlatformAdmin"])
    body = get_body()
    code = f_str(body, "code")
    state_code = f_str(body, "state_code", pattern=STATE_CODE_RE)
    endorsement = f_bool(body, "hazmat_endorsement", required=False, default=False)
    reserve_pct = f_num(body, "storm_reserve_pct", required=False, default=0.0, minimum=0.0, maximum=0.5)
    dock_capacity = f_num(body, "dock_capacity_kg_per_window", exclusive_min=0)
    for existing in DB.warehouses.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_SKU", "warehouse code already taken")
    row = new_row({
        "code": code,
        "state_code": state_code,
        "hazmat_endorsement": endorsement,
        "storm_reserve_pct": reserve_pct,
        "dock_capacity_kg_per_window": dock_capacity,
    })
    DB.warehouses[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/warehouses/<warehouse_id>")
def read_warehouse(warehouse_id):
    authenticate(OPERATORS)
    return ok(public(must("warehouses", warehouse_id)))


# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
@bp.post("/carriers")
def create_carrier():
    authenticate(["PlatformAdmin"])
    body = get_body()
    code = f_str(body, "code")
    name = f_str(body, "name")
    classes = f_enum_list(body, "accepts_hazmat_classes", calc.HAZMAT_CLASSES, nonempty=False)
    max_wh = f_num(body, "max_lithium_watt_hours_per_package", minimum=0)
    ground_only = f_bool(body, "ground_only", required=False, default=True)
    for existing in DB.carriers.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_SKU", "carrier code already taken")
    row = new_row({
        "code": code,
        "name": name,
        "accepts_hazmat_classes": list(classes),
        "max_lithium_watt_hours_per_package": max_wh,
        "ground_only": ground_only,
    })
    DB.carriers[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/carriers/<carrier_id>")
def read_carrier(carrier_id):
    authenticate(OPERATORS)
    return ok(public(must("carriers", carrier_id)))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["PlatformAdmin"])
    body = get_body()
    raw = f_datetime(body, "to_iso8601")
    DB.clock = parse_dt(raw)
    from common import fmt_ts
    return ok({"current_utc": fmt_ts(DB.clock)})

from flask import Blueprint

import auth
import common
import response
import shape
import store

bp = Blueprint("parties", __name__)

WRAP_SPECS = ["KRAFT_ONLY", "POLY_COATED", "STRETCH_HOOD"]
TIERS = ["P1", "P2", "P3"]


# ------------------------------------------------------------ customers ---
@bp.post("/customers")
def create_customer():
    auth.require_roles("MillPlanner")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row = {
        "name": shape.get_str(data, "name", min_len=1, max_len=120),
        "allocation_priority_tier": shape.get_enum(data, "allocation_priority_tier", TIERS,
                                                   required=False, default="P3"),
        "max_roll_diameter_mm": shape.get_int(data, "max_roll_diameter_mm", minimum=800, maximum=1800),
        "max_roll_width_mm": shape.get_int(data, "max_roll_width_mm", minimum=400, maximum=2800),
        "wrap_spec": shape.get_enum(data, "wrap_spec", WRAP_SPECS, required=False, default="KRAFT_ONLY"),
        "status": "ACTIVE",
    }
    store.insert("customers", row)
    return response.ok(common.view(row), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    auth.require_roles("MillPlanner", "Customer")
    row = common.need("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    auth.own_customer_or_403(row["id"])
    return response.ok(common.view(row))


@bp.patch("/customers/<cid>/status")
def patch_customer_status(cid):
    auth.require_roles("MillPlanner")
    row = common.need("customers", cid, "ERR_CUSTOMER_NOT_FOUND")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row["status"] = shape.get_enum(data, "status", ["ACTIVE", "SUSPENDED"])
    store.touch("customers", row)
    return response.ok(common.view(row))


# ------------------------------------------------------------ suppliers ---
@bp.post("/suppliers")
def create_supplier():
    auth.require_roles("FiberBuyer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row = {
        "name": shape.get_str(data, "name", min_len=1, max_len=120),
        "freight_per_ton": shape.get_num(data, "freight_per_ton", minimum=0, places=2),
        "contamination_strike_count": 0,
        "qualification_status": "QUALIFIED",
        "probation_entered_at": None,
    }
    store.insert("suppliers", row)
    return response.ok(common.view(row), 201)


@bp.get("/suppliers/<sid>")
def get_supplier(sid):
    auth.require_roles("FiberBuyer", "MillPlanner", "Supplier")
    row = common.need("suppliers", sid, "ERR_SUPPLIER_NOT_FOUND")
    auth.own_supplier_or_403(row["id"])
    return response.ok(common.view(row))


# --------------------------------------------------------- fiber grades ---
INDEX_SYMBOLS = ["PPI_OCC", "PPI_DLK", "PPI_SOP", "PPI_ONP"]


@bp.post("/fiber-grades")
def create_fiber_grade():
    auth.require_roles("FiberBuyer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row = {
        "grade_code": shape.get_str(data, "grade_code", pattern=r"[A-Z]{2,4}_[0-9]{2}"),
        "index_symbol": shape.get_enum(data, "index_symbol", INDEX_SYMBOLS),
        "max_contamination_pct": shape.get_num(data, "max_contamination_pct", minimum=0, maximum=25, places=2),
        "max_moisture_pct": shape.get_num(data, "max_moisture_pct", minimum=0, maximum=20, places=2),
        "nominal_yield_pct": shape.get_num(data, "nominal_yield_pct", minimum=40, maximum=95, places=2),
        "deink_required": shape.get_bool(data, "deink_required"),
        "downgrade_target_grade_code": shape.get_str(data, "downgrade_target_grade_code",
                                                     required=False, default=None),
        "rank_order": shape.get_int(data, "rank_order", minimum=1, maximum=99),
    }
    common.unique_or_conflict("fiber_grades", "grade_code", row["grade_code"])
    common.unique_or_conflict("fiber_grades", "rank_order", row["rank_order"])
    store.insert("fiber_grades", row)
    return response.ok(common.view(row), 201)


@bp.get("/fiber-grades")
def list_fiber_grades():
    auth.require_roles("FiberBuyer", "MillPlanner", "QualityLab", "MachineOperator")
    limit, offset = shape.pagination()
    rows = common.filtered("fiber_grades", {"grade_code": "grade_code", "index_symbol": "index_symbol"})
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


# --------------------------------------------------- market index quotes ---
@bp.post("/market-index-quotes")
def create_quote():
    auth.require_roles("FiberBuyer")
    data = shape.body()
    shape.reject_unexpected_version(data)
    symbol = shape.get_enum(data, "index_symbol", INDEX_SYMBOLS)
    month = shape.get_str(data, "effective_month", pattern=r"[0-9]{4}-(0[1-9]|1[0-2])")
    price = shape.get_num(data, "published_price_per_ton", exclusive_min=0, places=2)
    prev = common.current_quote(symbol, month)
    row = {
        "index_symbol": symbol,
        "effective_month": month,
        "published_price_per_ton": price,
        "superseded": False,
    }
    store.insert("market_index_quotes", row)
    if prev is not None:
        prev["superseded"] = True
    return response.ok(common.view(row), 201)


@bp.get("/market-index-quotes")
def list_quotes():
    auth.require_roles("FiberBuyer", "MillPlanner")
    limit, offset = shape.pagination()
    rows = common.filtered("market_index_quotes", {
        "index_symbol": "index_symbol",
        "effective_month": "effective_month",
        "superseded": "superseded",
    })
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))


# ---------------------------------------------------- paper grade specs ---
FAMILIES = ["CONTAINERBOARD", "TISSUE"]


@bp.post("/paper-grade-specs")
def create_spec():
    auth.require_roles("MillPlanner")
    data = shape.body()
    shape.reject_unexpected_version(data)
    row = {
        "product_code": shape.get_str(data, "product_code", pattern=r"[A-Z]{2,4}_[0-9]{2,3}"),
        "family": shape.get_enum(data, "family", FAMILIES),
        "basis_weight_gsm": shape.get_num(data, "basis_weight_gsm", minimum=12, maximum=400, places=1),
        "target_moisture_pct": shape.get_num(data, "target_moisture_pct", minimum=2, maximum=12, places=2),
        "moisture_tolerance_pct": shape.get_num(data, "moisture_tolerance_pct", minimum=0.1, maximum=3, places=2),
        "min_sct_kn_m": shape.get_num(data, "min_sct_kn_m", minimum=0, places=2),
        "min_brightness_iso": shape.get_num(data, "min_brightness_iso", required=False,
                                            minimum=0, maximum=100, places=1, default=None),
        "requires_deink_pulp": shape.get_bool(data, "requires_deink_pulp"),
        "rank_order": shape.get_int(data, "rank_order", minimum=1, maximum=99),
    }
    common.unique_or_conflict("paper_grade_specs", "product_code", row["product_code"])
    common.unique_or_conflict("paper_grade_specs", "rank_order", row["rank_order"])
    store.insert("paper_grade_specs", row)
    return response.ok(common.view(row), 201)


@bp.get("/paper-grade-specs")
def list_specs():
    auth.require_roles("MillPlanner", "MachineOperator", "QualityLab", "Customer")
    limit, offset = shape.pagination()
    rows = common.filtered("paper_grade_specs", {"product_code": "product_code", "family": "family"})
    return response.ok_list(common.views(shape.paginate(rows, limit, offset)), limit, offset, len(rows))

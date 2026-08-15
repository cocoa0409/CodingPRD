"""Shared validation and serialization helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import DB, now_iso
from errors import ApiError


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def round_half_up_int(value):
    """Round a Decimal to 0 decimal places, half-up, returning int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_int_field(body, name, required=True):
    """Extract an integer from a JSON body. Booleans are rejected."""
    if name not in body:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer")
    return v


def parse_str_field(body, name, required=True):
    if name not in body:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a string")
    return v


def parse_enum_field(body, name, allowed, required=True):
    v = parse_str_field(body, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {name} must be one of {sorted(allowed)}",
        )
    return v


def parse_bool_field(body, name, required=False, default=None):
    if name not in body:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a boolean")
    return v


def json_body():
    """Return the request JSON body, raising ERR_INVALID_REQUEST if not an object."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Parse limit/offset per scaffold pagination_defaults: limit=10, min=1, max=100, offset=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items are pre-sorted by created_at ascending. Returns (page, total)."""
    total = len(items)
    page = items[offset : offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_or_404(collection, rid, what="Resource"):
    obj = DB[collection].get(rid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{what} does not exist")
    return obj


def get_deal(deal_id):
    return get_or_404("deals", deal_id, "Deal")


def get_property(prop_id):
    return get_or_404("properties", prop_id, "Property")


def get_scenario(scenario_id):
    return get_or_404("scenarios", scenario_id, "Scenario")


def get_assumption(assumption_id):
    return get_or_404("market_assumptions", assumption_id, "MarketAssumption")


def get_memo(memo_id):
    return get_or_404("ic_memos", memo_id, "ICMemo")


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def init_common_fields(record):
    """Assign created_at / updated_at / version=1 to a newly created record."""
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Bump version by 1 and refresh updated_at on a mutable record."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
    return record


# ---------------------------------------------------------------------------
# Serializers (shape is flat dicts; matches scaffold entity field names)
# ---------------------------------------------------------------------------

def deal_view(d):
    return {
        "id": d["id"],
        "deal_code": d["deal_code"],
        "deal_name": d["deal_name"],
        "strategy": d["strategy"],
        "status": d["status"],
        "target_purchase_price_cents": d["target_purchase_price_cents"],
        "analyst_id": d["analyst_id"],
        "asset_manager_id": d["asset_manager_id"],
        "current_scenario_id": d["current_scenario_id"],
        "approved_at": d["approved_at"],
        "rejected_reason": d["rejected_reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def property_view(p):
    return {
        "id": p["id"],
        "deal_id": p["deal_id"],
        "address_line": p["address_line"],
        "market": p["market"],
        "property_type": p["property_type"],
        "units": p["units"],
        "rentable_sqft": p["rentable_sqft"],
        "year_built": p["year_built"],
        "occupancy_pct": p["occupancy_pct"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def rent_roll_view(r):
    return {
        "id": r["id"],
        "property_id": r["property_id"],
        "period_month": r["period_month"],
        "occupied_units": r["occupied_units"],
        "total_units": r["total_units"],
        "gross_potential_rent_cents": r["gross_potential_rent_cents"],
        "collected_rent_cents": r["collected_rent_cents"],
        "concessions_cents": r["concessions_cents"],
        "source_doc_ref": r["source_doc_ref"],
        "created_at": r["created_at"],
    }


def opex_view(o):
    return {
        "id": o["id"],
        "property_id": o["property_id"],
        "period_year": o["period_year"],
        "category": o["category"],
        "amount_cents": o["amount_cents"],
        "is_recoverable": o["is_recoverable"],
        "created_at": o["created_at"],
    }


def assumption_view(m):
    return {
        "id": m["id"],
        "deal_id": m["deal_id"],
        "label": m["label"],
        "market_rent_growth_yr1_bps": m["market_rent_growth_yr1_bps"],
        "market_rent_growth_steady_bps": m["market_rent_growth_steady_bps"],
        "expense_growth_bps": m["expense_growth_bps"],
        "exit_cap_rate_bps": m["exit_cap_rate_bps"],
        "hold_period_years": m["hold_period_years"],
        "capex_per_unit_cents": m["capex_per_unit_cents"],
        "lease_up_months": m["lease_up_months"],
        "is_active": m["is_active"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def scenario_view(s):
    return {
        "id": s["id"],
        "deal_id": s["deal_id"],
        "scenario_kind": s["scenario_kind"],
        "assumption_id": s["assumption_id"],
        "occupancy_stress_pct": s["occupancy_stress_pct"],
        "status": s["status"],
        "computed_noi_yr1_cents": s["computed_noi_yr1_cents"],
        "computed_irr_bps": s["computed_irr_bps"],
        "computed_equity_multiple_bp": s["computed_equity_multiple_bp"],
        "superseded_by_id": s["superseded_by_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def debt_sizing_view(ds):
    return {
        "id": ds["id"],
        "scenario_id": ds["scenario_id"],
        "loan_amount_cents": ds["loan_amount_cents"],
        "interest_rate_bps": ds["interest_rate_bps"],
        "amortization_years": ds["amortization_years"],
        "io_months": ds["io_months"],
        "min_dscr_pct": ds["min_dscr_pct"],
        "max_ltv_pct": ds["max_ltv_pct"],
        "dscr_at_size_pct": ds["dscr_at_size_pct"],
        "ltv_at_size_pct": ds["ltv_at_size_pct"],
        "sizing_constraint": ds["sizing_constraint"],
        "created_at": ds["created_at"],
        "updated_at": ds["updated_at"],
        "version": ds["version"],
    }


def waterfall_view(w):
    return {
        "id": w["id"],
        "scenario_id": w["scenario_id"],
        "pref_return_bps": w["pref_return_bps"],
        "promote_tier1_bps": w["promote_tier1_bps"],
        "tier1_hurdle_bps": w["tier1_hurdle_bps"],
        "promote_tier2_bps": w["promote_tier2_bps"],
        "lp_split_cents": w["lp_split_cents"],
        "gp_split_cents": w["gp_split_cents"],
        "gp_promote_cents": w["gp_promote_cents"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ic_memo_view(m):
    return {
        "id": m["id"],
        "deal_id": m["deal_id"],
        "scenario_id": m["scenario_id"],
        "recommendation": m["recommendation"],
        "thesis": m["thesis"],
        "risks": m["risks"],
        "status": m["status"],
        "submitted_at": m["submitted_at"],
        "decided_at": m["decided_at"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ic_vote_view(v):
    return {
        "id": v["id"],
        "memo_id": v["memo_id"],
        "voter_user_id": v["voter_user_id"],
        "vote": v["vote"],
        "comment": v["comment"],
        "cast_at": v["cast_at"],
        "created_at": v["created_at"],
    }

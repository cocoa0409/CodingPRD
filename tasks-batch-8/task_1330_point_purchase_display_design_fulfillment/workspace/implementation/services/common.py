"""Shared helpers: common fields, pagination, validation, compliance, recap."""

import math
from datetime import datetime, timezone

import db
import errors


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------

def new_common_fields():
    ts = db.now_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = db.now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate(items, request_args):
    """Parse limit/offset with defaults 10/0, min 1, max 100. Returns (page, limit, offset, total)."""
    try:
        limit = int(request_args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    try:
        offset = int(request_args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    if offset < 0:
        offset = 0
    total = len(items)
    return items[offset : offset + limit], limit, offset, total


def sort_by_created(items):
    return sorted(items, key=lambda x: x.get("created_at", ""))


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

def require_field(body, name):
    val = body.get(name)
    if val is None:
        raise errors.err_invalid_request(f"Missing required field: {name}")
    return val


def require_int(body, name, minimum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err_invalid_request(f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.err_invalid_request(f"Field {name} must be >= {minimum}")
    return val


def require_number(body, name, exclusive_min=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err_invalid_request(f"Field {name} must be a number")
    if exclusive_min is not None and val <= exclusive_min:
        raise errors.err_invalid_request(f"Field {name} must be > {exclusive_min}")
    return val


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or not val:
        raise errors.err_invalid_request(f"Field {name} must be a non-empty string")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if val not in allowed:
        raise errors.err_invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return val


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601)
# ---------------------------------------------------------------------------

def parse_iso(val):
    if not isinstance(val, str):
        raise errors.err_invalid_request("Expected ISO 8601 datetime string")
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err_invalid_request(f"Invalid ISO 8601 datetime: {val}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Compliance recomputation
# ---------------------------------------------------------------------------

def recompute_compliance(design):
    """Recompute a design's compliance_result against its program's active rules."""
    program_id = design["program_id"]
    active_rules = [
        r for r in db.compliance_rules.values()
        if r["program_id"] == program_id and r.get("active", True)
    ]
    result = "PASS"
    for rule in active_rules:
        dim = rule["dimension"]
        lv = rule["limit_value"]
        if dim == "MAX_WIDTH_IN":
            if design["width_in"] > float(lv):
                result = "FAIL"
                break
        elif dim == "MAX_HEIGHT_IN":
            if design["height_in"] > float(lv):
                result = "FAIL"
                break
        elif dim == "MAX_DEPTH_IN":
            if design["depth_in"] > float(lv):
                result = "FAIL"
                break
        elif dim == "MAX_WEIGHT_LB":
            if design["weight_lb"] > float(lv):
                result = "FAIL"
                break
        elif dim == "ALLOWED_MATERIAL":
            if design["material"] != lv:
                result = "FAIL"
                break
    design["compliance_result"] = result


def recompute_program_designs(program_id):
    """Recompute compliance_result for all non-terminal designs of a program."""
    for d in db.designs.values():
        if d["program_id"] == program_id and d["status"] not in ("LOCKED", "REJECTED"):
            recompute_compliance(d)


# ---------------------------------------------------------------------------
# Production calculations
# ---------------------------------------------------------------------------

def compute_production_quantity(store_count, overage_pct):
    return math.ceil(store_count * (1 + overage_pct / 100))


def compute_unit_cost_cents(production_quantity):
    if production_quantity < 100:
        return 2500
    elif production_quantity < 500:
        return 2200
    else:
        return 1950


# ---------------------------------------------------------------------------
# Recap minting
# ---------------------------------------------------------------------------

def round_half_up_2dp(value):
    """Round to 2 decimal places, half-up. Works on float input."""
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_roi_pct(revenue_cents, cost_cents):
    if cost_cents == 0:
        return 0.0
    return round_half_up_2dp((revenue_cents - cost_cents) / cost_cents * 100)


def mint_recap(program):
    program_id = program["id"]
    produced_runs = [r for r in db.production_runs.values()
                     if r["program_id"] == program_id and r["status"] == "PRODUCED"]
    total_produced = sum(r.get("production_quantity") or 0 for r in produced_runs)

    total_delivered = sum(
        1 for s in db.shipments.values()
        if _shipment_program_id(s) == program_id and s["status"] == "DELIVERED"
    )

    fulfilled_claims = [
        c for c in db.damage_claims.values()
        if _claim_program_id(c) == program_id and c["status"] == "FULFILLED"
    ]
    total_damaged = len(fulfilled_claims)

    runs_cost = sum(r.get("total_cost_cents") or 0 for r in produced_runs)
    claims_cost = sum(c.get("replacement_cost_cents") or 0 for c in fulfilled_claims)
    total_cost = runs_cost + claims_cost

    roi_final = compute_roi_pct(program["program_revenue_cents"], total_cost)

    # roi_pct_provisional: captured when first run hit PRODUCED; persist on program
    roi_provisional = program.get("_roi_pct_provisional")
    if roi_provisional is None:
        roi_provisional = compute_roi_pct(program["program_revenue_cents"], runs_cost)

    ts = db.now_iso()
    recap = {
        "id": db.new_id(),
        "created_at": ts,
        "program_id": program_id,
        "total_produced": total_produced,
        "total_delivered": total_delivered,
        "total_damaged": total_damaged,
        "total_cost_cents": total_cost,
        "roi_pct_provisional": roi_provisional,
        "roi_pct_final": roi_final,
        "generated_at": ts,
    }
    db.recaps[recap["id"]] = recap
    return recap


def capture_provisional_roi(program):
    """Called when a run transitions to PRODUCED; captures ROI on the first such run."""
    if program.get("_roi_pct_provisional") is not None:
        return
    program_id = program["id"]
    produced_runs = [r for r in db.production_runs.values()
                     if r["program_id"] == program_id and r["status"] == "PRODUCED"]
    cost = sum(r.get("total_cost_cents") or 0 for r in produced_runs)
    program["_roi_pct_provisional"] = compute_roi_pct(program["program_revenue_cents"], cost)


def _shipment_program_id(shipment):
    kit = db.kits.get(shipment["kit_id"])
    if not kit:
        return None
    run = db.production_runs.get(kit["production_run_id"])
    if not run:
        return None
    return run["program_id"]


def _claim_program_id(claim):
    kit = db.kits.get(claim["kit_id"])
    if not kit:
        return None
    run = db.production_runs.get(kit["production_run_id"])
    if not run:
        return None
    return run["program_id"]


# ---------------------------------------------------------------------------
# Public serializers (strip internal fields like _roi_pct_provisional)
# ---------------------------------------------------------------------------

def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}

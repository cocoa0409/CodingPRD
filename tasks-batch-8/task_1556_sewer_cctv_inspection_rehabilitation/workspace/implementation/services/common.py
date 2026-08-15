"""Shared helpers: pagination parsing, validation primitives, lookup helpers."""
import math
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from db import _parse_iso
from errors import err_invalid_request, err_not_found, err_conflict


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Parse limit/offset query params per scaffold defaults (limit 10, min 1, max 100, offset 0)."""
    try:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range")
    if offset < 0:
        raise err_invalid_request("offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable on insertion order), slice, return (page, total)."""
    ordered = sorted(items, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def body():
    return request.get_json(silent=True) or {}


def require_field(payload, name):
    if name not in payload or payload[name] is None:
        raise err_invalid_request(f"missing required field: {name}")
    return payload[name]


def require_int(payload, name):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{name} must be an integer")
    return v


def require_number(payload, name):
    v = require_field(payload, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{name} must be a number")
    return v


def require_string(payload, name):
    v = require_field(payload, name)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{name} must be a non-empty string")
    return v


def require_enum(payload, name, allowed):
    v = require_string(payload, name)
    if v not in allowed:
        raise err_invalid_request(f"{name} must be one of {sorted(allowed)}")
    return v


def parse_datetime_field(payload, name, required=True):
    v = payload.get(name)
    if v is None:
        if required:
            raise err_invalid_request(f"missing required field: {name}")
        return None
    if not isinstance(v, str):
        raise err_invalid_request(f"{name} must be ISO8601 string")
    try:
        return db._parse_iso(v)
    except Exception:
        raise err_invalid_request(f"{name} must be ISO8601 string")


# ---------------------------------------------------------------------------
# Entity lookups (existence / hierarchy)
# ---------------------------------------------------------------------------

def get_or_404(store, entity_id, msg="not found"):
    ent = store.get(entity_id)
    if ent is None:
        raise err_not_found(msg)
    return ent


def get_district(district_id):
    return get_or_404(db.districts, district_id, "district not found")


def get_segment(segment_id):
    return get_or_404(db.segments, segment_id, "segment not found")


def get_segment_in_district(district_id, segment_id):
    district = get_district(district_id)
    segment = db.segments.get(segment_id)
    if segment is None or segment["district_id"] != district["id"]:
        raise err_not_found("segment not found in district")
    return segment


def get_cycle(cycle_id):
    return get_or_404(db.cycles, cycle_id, "cycle not found")


def get_inspection(inspection_id):
    return get_or_404(db.inspections, inspection_id, "inspection not found")


def get_plan(plan_id):
    return get_or_404(db.plans, plan_id, "rehab plan not found")


def get_work_order(wo_id):
    return get_or_404(db.work_orders, wo_id, "work order not found")


def get_bypass(bypass_id):
    return get_or_404(db.bypass_plans, bypass_id, "bypass plan not found")


def get_notice(notice_id):
    return get_or_404(db.notices, notice_id, "notice not found")


def get_warranty_case(case_id):
    return get_or_404(db.warranty_cases, case_id, "warranty case not found")


def get_flow_period(period_id):
    return get_or_404(db.flow_periods, period_id, "flow period not found")


def get_lateral_in_segment(segment_id, lateral_id):
    segment = get_segment(segment_id)
    lat = db.laterals.get(lateral_id)
    if lat is None or lat["segment_id"] != segment["id"]:
        raise err_not_found("lateral not found in segment")
    return lat


# ---------------------------------------------------------------------------
# Notice expiry sweep (§2.4): evaluated on every state-changing request
# ---------------------------------------------------------------------------

def sweep_notice_expiry():
    """QUEUED -> EXPIRED for any notice whose event_start <= current logical time."""
    now = db.now_dt()
    for notice in db.notices.values():
        if notice["status"] == "QUEUED":
            ev = _parse_iso(notice["event_start"])
            if ev <= now:
                notice["status"] = "EXPIRED"
                db.touch(notice)


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal numeric value half-up to integer cents."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_line_cents(qty, unit_price_cents):
    """round_half_up(qty * unit_price_cents) per-line."""
    q = Decimal(str(qty))
    p = Decimal(int(unit_price_cents))
    return round_half_up_cents(q * p)


# ---------------------------------------------------------------------------
# PACP scoring (§3.3, calculations.pacp_scoring)
# ---------------------------------------------------------------------------

def compute_pacp_scores(observations):
    """Compute (structural_grade, om_grade, structural_index, quick_rating) from observations.

    structural_index: extent-weighted mean over STRUCTURAL observations, weight = max(extent, 1.0),
      rounded half-up to 2 decimals; None when no STRUCTURAL observations.
    quick_rating: 4-char code from two highest structural grades, counts capped at 9; "0000" when none.
    """
    structural = [o for o in observations if o["family"] == "STRUCTURAL"]
    om = [o for o in observations if o["family"] == "OM"]

    structural_grade = max((o["grade"] for o in structural), default=0)
    om_grade = max((o["grade"] for o in om), default=0)

    structural_index = None
    if structural:
        num = Decimal(0)
        den = Decimal(0)
        for o in structural:
            w = max(Decimal(str(o.get("extent_m") or 0)), Decimal("1.0"))
            num += Decimal(int(o["grade"])) * w
            den += w
        idx = num / den
        structural_index = float(idx.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    # quick_rating
    if structural:
        grade_counts = {}
        for o in structural:
            grade_counts[o["grade"]] = grade_counts.get(o["grade"], 0) + 1
        # order by grade desc, then count desc
        ordered = sorted(grade_counts.items(), key=lambda kv: (-kv[0], -kv[1]))
        g1, c1 = ordered[0]
        first = str(g1)
        second = str(min(c1, 9))
        if len(ordered) > 1:
            g2, c2 = ordered[1]
            third = str(g2)
            fourth = str(min(c2, 9))
        else:
            third = "0"
            fourth = "0"
        quick_rating = first + second + third + fourth
    else:
        quick_rating = "0000"

    return structural_grade, om_grade, structural_index, quick_rating


# ---------------------------------------------------------------------------
# Mobilization tier + fees
# ---------------------------------------------------------------------------

MOB_FEES = {
    "MOB_SMALL": 150000,
    "MOB_STANDARD": 400000,
    "MOB_LARGE": 900000,
}


def compute_mobilization_tier(segment):
    """MOB_LARGE first, then MOB_STANDARD, else MOB_SMALL."""
    diameter = segment["diameter_mm"]
    length = segment["length_m"]
    if diameter >= 600 or length > 300:
        return "MOB_LARGE"
    if diameter >= 300:
        return "MOB_STANDARD"
    return "MOB_SMALL"


def recompute_plan_provisional(plan_id):
    """Recompute plan.provisional_total_cents from all non-CANCELLED child WOs.

    Sum of per-line round_half_up(scheduled_qty * unit_price_cents) plus per-WO mobilization fee.

    PRD §3.1: the district's `budget_committed_cents` is maintained as the running
    sum of provisional totals over the district's plans in `APPROVED` or
    `EXECUTING` status. Any recompute that moves such a plan's provisional total
    therefore propagates the delta to the district ledger.
    """
    plan = db.plans[plan_id]
    old_total = plan["provisional_total_cents"]
    total = 0
    for wo in db.work_orders.values():
        if wo["plan_id"] != plan_id:
            continue
        if wo["execution_status"] == "CANCELLED":
            continue
        for li in db.line_items.values():
            if li["work_order_id"] != wo["id"]:
                continue
            total += li["provisional_line_cents"]
        fee = MOB_FEES.get(wo.get("mobilization_tier") or "MOB_SMALL", 0)
        total += fee
    plan["provisional_total_cents"] = total
    db.touch(plan)
    if plan["status"] in ("APPROVED", "EXECUTING"):
        delta = total - old_total
        if delta:
            segment = db.segments[plan["segment_id"]]
            district = db.districts[segment["district_id"]]
            district["budget_committed_cents"] += delta
            db.touch(district)


def recompute_plan_final(plan_id):
    """Compute plan.final_total_cents using final lines (fallback to provisional per line)."""
    plan = db.plans[plan_id]
    total = 0
    for wo in db.work_orders.values():
        if wo["plan_id"] != plan_id:
            continue
        if wo["execution_status"] == "CANCELLED":
            continue
        for li in db.line_items.values():
            if li["work_order_id"] != wo["id"]:
                continue
            val = li["final_line_cents"] if li["final_line_cents"] is not None else li["provisional_line_cents"]
            total += val
        fee = MOB_FEES.get(wo.get("mobilization_tier") or "MOB_SMALL", 0)
        total += fee
    plan["final_total_cents"] = total
    db.touch(plan)


# ---------------------------------------------------------------------------
# Pump sizing
# ---------------------------------------------------------------------------

def required_pump_gpm(diameter_mm):
    """25 gpm per inch of diameter, inches = ceil(diameter_mm / 25.4)."""
    inches = math.ceil(diameter_mm / 25.4)
    return 25 * inches


def buffered_window_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals expanded by +/- 30 minutes; check overlap."""
    from datetime import timedelta
    buf = timedelta(minutes=30)
    a_s = _parse_iso(a_start) - buf
    a_e = _parse_iso(a_end) + buf
    b_s = _parse_iso(b_start) - buf
    b_e = _parse_iso(b_end) + buf
    return a_s < b_e and b_s < a_e

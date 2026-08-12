"""Business services: calculations (SCAFFOLD section 1.3), scheduling checks,
and the derived-field recomputes used by cascades."""

from datetime import timedelta
from decimal import Decimal

from db import store
from util import rhu, num_out, refresh


# ---------------------------------------------------------------------------
# build_cost_balance (exact integer cents; conservation invariant)
# ---------------------------------------------------------------------------

COMMITTED_STATUSES = ("ORDERED", "BUILT", "DELIVERED", "IN_USE")
ACTUAL_STATUSES = ("BUILT", "DELIVERED", "IN_USE")


def effective_cost(item):
    if item["status"] in ACTUAL_STATUSES and item.get("actual_cost_cents") is not None:
        return item["actual_cost_cents"]
    return item["quoted_cost_cents"]


def recompute_build_balance(prod):
    committed = sum(
        effective_cost(it)
        for it in store.build_items.values()
        if it["production_id"] == prod["id"] and it["status"] in COMMITTED_STATUSES
    )
    new_balance = prod["build_budget_cents"] - committed
    if new_balance != prod["build_cost_balance_cents"]:
        prod["build_cost_balance_cents"] = new_balance
        refresh(prod)


# ---------------------------------------------------------------------------
# season revenue + co-production accrual cascade
# ---------------------------------------------------------------------------

def recompute_season_revenue(prod):
    total = sum(
        p["realized_revenue_cents"]
        for p in store.performances.values()
        if p["production_id"] == prod["id"] and p["lifecycle_status"] != "CANCELLED"
    )
    if total != prod["season_revenue_cents"]:
        prod["season_revenue_cents"] = total
        refresh(prod)
    for sh in store.co_production_shares.values():
        if (sh["production_id"] == prod["id"] and sh["status"] == "RATIFIED"
                and sh["cost_split_method"] == "NET_REVENUE_SHARE"):
            acc = rhu(sh["share_percentage"] / Decimal(100)
                      * Decimal(prod["season_revenue_cents"]))
            if acc != sh["accrued_revenue_share_cents"]:
                sh["accrued_revenue_share_cents"] = acc
                refresh(sh)


# ---------------------------------------------------------------------------
# coproduction settlement (RATIFIED -> SETTLED), two pinned variants
# ---------------------------------------------------------------------------

def compute_settlement(share, prod):
    total_build = sum(
        effective_cost(it)
        for it in store.build_items.values()
        if it["production_id"] == prod["id"] and it["status"] in ("DELIVERED", "IN_USE")
    )
    cost_share = rhu(share["share_percentage"] / Decimal(100) * Decimal(total_build))
    if share["cost_split_method"] == "GROSS_COST":
        return cost_share
    accrued = rhu(share["share_percentage"] / Decimal(100)
                  * Decimal(prod["season_revenue_cents"]))
    return cost_share - accrued


# ---------------------------------------------------------------------------
# casting_completeness
# ---------------------------------------------------------------------------

def recompute_casting_status(role):
    confirmed = [a for a in store.cast_assignments.values()
                 if a["role_id"] == role["id"] and a["status"] == "CONFIRMED"]
    has_principal = any(a["slot"] == "PRINCIPAL" for a in confirmed)
    has_cover = any(a["slot"] in ("COVER_1", "COVER_2") for a in confirmed)
    if has_principal and has_cover:
        new = "FULLY_CAST"
    elif has_principal:
        new = "PRINCIPAL_SET"
    else:
        new = "UNFILLED"
    if new != role["casting_status"]:
        role["casting_status"] = new
        refresh(role)


# ---------------------------------------------------------------------------
# RehearsalCall.confirmed_headcount
# ---------------------------------------------------------------------------

def recompute_headcount(call):
    n = sum(1 for p in store.call_participants.values()
            if p["call_id"] == call["id"] and p["status"] in ("CONFIRMED", "CHECKED_IN"))
    if n != call["confirmed_headcount"]:
        call["confirmed_headcount"] = n
        refresh(call)


# ---------------------------------------------------------------------------
# seat_price_cents — pinned two-stage rounding (must not be collapsed)
# ---------------------------------------------------------------------------

SECTION_MULT = {
    "STALLS": Decimal("1.0"),
    "BALCONY": Decimal("1.25"),
    "BOX": Decimal("1.6"),
    "GALLERY": Decimal("0.8"),
}
GROUP_MIN = 10
GROUP_DISCOUNT = Decimal("0.9")


def seat_unit_base(inv):
    return rhu(Decimal(inv["base_price_cents"]) * SECTION_MULT[inv["section"]])


def demand_multiplier(sold_ratio):
    if sold_ratio < Decimal("0.5"):
        return Decimal("1.0")
    if sold_ratio < Decimal("0.8"):
        return Decimal("1.2")
    return Decimal("1.5")


def current_demand_multiplier(inv):
    ratio = Decimal(inv["seats_sold"]) / Decimal(inv["total_seats"])
    return demand_multiplier(ratio)


def compute_current_price(inv):
    unit1 = seat_unit_base(inv)
    return rhu(Decimal(unit1) * current_demand_multiplier(inv))


def purchase_total(inv, quantity):
    mult = GROUP_DISCOUNT if quantity >= GROUP_MIN else Decimal("1.0")
    return rhu(Decimal(inv["current_price_cents"]) * Decimal(quantity) * mult)


# ---------------------------------------------------------------------------
# rental_fee_cents — pinned evaluation order, tier keys on fee_base only
# ---------------------------------------------------------------------------

LARGE_RENTAL_THRESHOLD_CENTS = 5_000_000
LARGE_RENTAL_SURCHARGE_PCT = 8
MAX_NEGOTIATION_ROUNDS = 5


def compute_fee_schedule(offer):
    base = offer["performances_count"] * offer["per_performance_fee_cents"]
    pct = 0 if base < LARGE_RENTAL_THRESHOLD_CENTS else LARGE_RENTAL_SURCHARGE_PCT
    total = base + rhu(Decimal(base) * Decimal(pct) / Decimal(100))
    offer["fee_base_cents"] = base
    offer["surcharge_pct"] = pct
    offer["total_fee_cents"] = total


# ---------------------------------------------------------------------------
# room_overlap_check — strict half-open, zero buffer, per-room resource
# ---------------------------------------------------------------------------

def room_conflict(room_id, starts_at, ends_at, exclude_id=None):
    for c in store.rehearsal_calls.values():
        if c["room_id"] != room_id or c["id"] == exclude_id:
            continue
        if c["status"] not in ("DRAFT", "PUBLISHED"):
            continue
        if starts_at < c["ends_at"] and c["starts_at"] < ends_at:
            return True
    return False


# ---------------------------------------------------------------------------
# stage_changeover_check — buffered adjacency on the single shared stage
# ---------------------------------------------------------------------------

RESET_BUFFER = timedelta(hours=2)
CHANGEOVER_BUFFER = timedelta(hours=6)


def stage_conflict(production_id, starts_at, ends_at, exclude_id=None):
    for s in store.stage_slots.values():
        if s["id"] == exclude_id:
            continue
        if s["status"] not in ("PLANNED", "LOCKED", "DONE"):
            continue
        gap = RESET_BUFFER if s["production_id"] == production_id else CHANGEOVER_BUFFER
        if s["starts_at"] < ends_at + gap and starts_at < s["ends_at"] + gap:
            return True
    return False


# ---------------------------------------------------------------------------
# rest_floor_check — union rest floor; a gap of exactly F seconds passes
# ---------------------------------------------------------------------------

def rest_floor_violation(contract, new_call):
    floor = timedelta(hours=contract["rest_floor_hours"])
    for p in store.call_participants.values():
        if p["contract_id"] != contract["id"]:
            continue
        if p["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        d = store.rehearsal_calls.get(p["call_id"])
        if d is None or d["id"] == new_call["id"]:
            continue
        if d["status"] not in ("PUBLISHED", "COMPLETED"):
            continue
        ok = ((new_call["starts_at"] - d["ends_at"]) >= floor
              or (d["starts_at"] - new_call["ends_at"]) >= floor)
        if not ok:
            return True
    return False


# ---------------------------------------------------------------------------
# artist_weekly_pay_cents / overtime_tier_pay — no intermediate rounding
# ---------------------------------------------------------------------------

OT_TIER1_SPAN = Decimal("10")
OT1_MULT = Decimal("1.5")
OT2_MULT = Decimal("2.0")
NIGHT_PREMIUM_CENTS = 1500


def _included_calls(contract, week_start, mode):
    week_end = week_start + timedelta(days=7)
    allowed = ("PUBLISHED", "COMPLETED") if mode == "PROJECTED" else ("COMPLETED",)
    calls = []
    seen = set()
    for p in store.call_participants.values():
        if p["contract_id"] != contract["id"]:
            continue
        if p["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        c = store.rehearsal_calls.get(p["call_id"])
        if c is None or c["id"] in seen:
            continue
        if c["status"] not in allowed:
            continue
        if not (week_start <= c["starts_at"] < week_end):
            continue
        seen.add(c["id"])
        calls.append(c)
    return calls


def _pay_for(calls, contract):
    hours = Decimal(0)
    nights = 0
    for c in calls:
        secs = Decimal(str((c["ends_at"] - c["starts_at"]).total_seconds()))
        hours += secs / Decimal(3600)
        # night call: ends_at UTC time-of-day in [23:00, 24:00)
        if c["ends_at"].hour == 23:
            nights += 1
    cap = Decimal(contract["weekly_hours_cap"])
    rate = Decimal(contract["hourly_rate_cents"])
    regular = min(hours, cap)
    ot1 = min(max(hours - cap, Decimal(0)), OT_TIER1_SPAN)
    ot2 = max(hours - cap - OT_TIER1_SPAN, Decimal(0))
    pay = (regular * rate + ot1 * rate * OT1_MULT + ot2 * rate * OT2_MULT
           + Decimal(nights * NIGHT_PREMIUM_CENTS))
    return hours, rhu(pay)


def weekly_pay_quote(contract, week_start):
    proj_hours, proj_pay = _pay_for(_included_calls(contract, week_start, "PROJECTED"), contract)
    fin_hours, fin_pay = _pay_for(_included_calls(contract, week_start, "FINAL"), contract)
    return {
        "projected_hours": num_out(proj_hours),
        "final_hours": num_out(fin_hours),
        "projected_pay_cents": proj_pay,
        "final_pay_cents": fin_pay,
    }

"""Business calculations and cascades (SCAFFOLD table 1.3, PRD §3)."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, stamp_new_ledger, touch, clock_date, now_dt
from errors import ApiError


# ---------- rounding (PRD §2.6: round half-up to integer cents) ----------

def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x):
    """round_half_up to integer cents."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------- constants ----------

CHASSIS_BASE = {"CASCADIA_126": 14500000, "M2_106": 9800000, "SD_114": 12300000}
ENGINE_SURCHARGE = {"DD13": 0, "DD15": 1200000, "CUMMINS_X15": 1450000}
AXLE_SURCHARGE = {"A4X2": 0, "A6X4": 850000}
DESTINATION_FEE = 285000

UPFIT_CODES = {"DUMP_BODY", "REEFER_BOX", "CRANE_PTO", "LIFTGATE", "VAN_BODY"}

TIER_PCT = {"STANDARD": Decimal("0"), "GOLD": Decimal("0.10"), "PLATINUM": Decimal("0.20")}
QTY_BREAK_THRESHOLD = 10
QTY_BREAK_EXTRA = Decimal("0.05")
MAX_DISCOUNT = Decimal("0.40")

SHOP_SUPPLIES_RATE = Decimal("0.05")
SHOP_SUPPLIES_CAP = 3500

GRACE_MINUTES = 120
PENALTY_RATE = Decimal("0.25")
PENALTY_CAP_LABOR_FRACTION = Decimal("0.50")

DENOMINATOR_DAYS = 360

ANNUAL_DEPRECIATION = Decimal("0.12")
FREE_MILES = 150000
MILEAGE_PENALTY_CENTS = 5
CONDITION_MULT = {"A": Decimal("1.10"), "B": Decimal("1.00"), "C": Decimal("0.85")}

WRITEOFF_SMALL_BALANCE = 2500
WRITEOFF_AGE_DAYS = 45
NO_SHOW_GRACE_MINUTES = 60

COVERED_CLAIM_STATUSES = ("APPROVED", "SHORT_PAID", "PAID")


# ---------- month helpers ----------

def slot_month_bounds(slot):
    y, m = map(int, slot["build_month"].split("-"))
    first = date(y, m, 1)
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return first, nxt


def month_is_closed(slot):
    """Clock date is past the end of the build month."""
    _, nxt = slot_month_bounds(slot)
    return clock_date() >= nxt


# ---------- credit posture (PRD §2.9) ----------

def reeval_credit_posture(account):
    """CREDIT_HOLD auto-set / auto-clear on receivable movement (FLEET only)."""
    if account["account_type"] != "FLEET":
        return
    if account["open_ar_cents"] > account["credit_limit_cents"]:
        if account["status"] == "ACTIVE":
            account["status"] = "CREDIT_HOLD"
    else:
        if account["status"] == "CREDIT_HOLD":
            account["status"] = "ACTIVE"


def adjust_open_ar(account, delta):
    if delta == 0:
        return
    account["open_ar_cents"] += delta
    reeval_credit_posture(account)
    touch(account)


# ---------- slot pool posture (PRD §3.2) ----------

def slots_available(slot):
    return slot["capacity"] - slot["held_count"] - slot["committed_count"]


def reeval_slot_posture(slot):
    """LOCKED when availability hits 0; reopen on release while month is open."""
    avail = slots_available(slot)
    if slot["status"] == "OPEN" and avail <= 0:
        slot["status"] = "LOCKED"
        touch(slot)
    elif slot["status"] == "LOCKED" and avail > 0 and not month_is_closed(slot):
        slot["status"] = "OPEN"
        touch(slot)


# ---------- upfit compatibility (priority 8) ----------

def validate_upfit(vocation_group, codes):
    """codes: full component_code set including any newly appended line."""
    if "CRANE_PTO" in codes and vocation_group != "SEVERE":
        raise ApiError("ERR_UPFIT_INCOMPATIBLE", 422,
                       "CRANE_PTO requires vocation_group SEVERE")
    if "REEFER_BOX" in codes and "DUMP_BODY" in codes:
        raise ApiError("ERR_UPFIT_INCOMPATIBLE", 422,
                       "REEFER_BOX and DUMP_BODY are mutually exclusive")
    if "LIFTGATE" in codes and "VAN_BODY" not in codes and "REEFER_BOX" not in codes:
        raise ApiError("ERR_UPFIT_DEPENDENCY_MISSING", 422,
                       "LIFTGATE requires VAN_BODY or REEFER_BOX on the same order")


# ---------- factory order pricing (pinned sequence, PRD §3.2) ----------

COMMITTED_LIKE = ("COMMITTED", "IN_PRODUCTION", "SHIPPED", "DELIVERED")


def factory_order_price(customer_account_id, chassis, engine, axle, vocation, upfit_lines):
    sub = CHASSIS_BASE[chassis] + ENGINE_SURCHARGE[engine] + AXLE_SURCHARGE[axle]
    if customer_account_id is None:
        prior = 0
    else:
        prior = sum(
            1 for o in store.factory_orders.values()
            if o["customer_account_id"] == customer_account_id
            and o["status"] in COMMITTED_LIKE
        )
    if prior <= 2:
        tier = Decimal("0")
    elif prior <= 5:
        tier = Decimal("0.02")
    else:
        tier = Decimal("0.04")
    rebate = rhu(D(sub) * tier)
    upfit_sum = sum(l["price_cents"] for l in upfit_lines)
    mult = Decimal("1.08") if vocation == "SEVERE" else Decimal("1.00")
    upfit_total = rhu(D(upfit_sum) * mult)
    return sub - rebate + upfit_total + DESTINATION_FEE


# ---------- unit aging / curtailment (recomputed on read and by sweep) ----------

def days_in_stock(unit):
    return (clock_date() - date.fromisoformat(unit["stocking_date"])).days


def aging_bucket(days):
    if days <= 90:
        return "B0_90"
    if days <= 180:
        return "B91_180"
    if days <= 270:
        return "B181_270"
    if days <= 365:
        return "B271_365"
    return "OVER_365"


def curtailment_due(unit, days):
    cost = unit["invoice_cost_cents"]
    if days >= 366:
        return cost
    if days >= 271:
        return rhu(D(cost) * Decimal("0.25"))
    if days >= 181:
        return rhu(D(cost) * Decimal("0.10"))
    return 0


# ---------- floor-plan ledger (PRD §2.8) ----------

def post_fp_entry(unit, entry_type, amount_cents, note=None):
    unit["floorplan_balance_cents"] += amount_cents
    entry = {
        "unit_id": unit["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "entry_date": clock_date().isoformat(),
        "note": note,
        "resulting_balance_cents": unit["floorplan_balance_cents"],
    }
    stamp_new_ledger(entry)
    store.floor_plan_entries[entry["id"]] = entry
    return entry


def interest_amount(balance_cents, apr_bp, days):
    return rhu(D(balance_cents) * D(apr_bp) * D(days) / D(10000 * DENOMINATOR_DAYS))


def accrue_interest_to_clock(unit):
    """Post one INTEREST_ACCRUAL from last_accrual_date through the clock date."""
    if not unit["floorplan_active"]:
        return
    if unit["floorplan_balance_cents"] <= 0 or not unit["last_accrual_date"]:
        return
    days = (clock_date() - date.fromisoformat(unit["last_accrual_date"])).days
    if days <= 0:
        return
    interest = interest_amount(unit["floorplan_balance_cents"], unit["apr_bp"], days)
    post_fp_entry(unit, "INTEREST_ACCRUAL", interest)
    unit["last_accrual_date"] = clock_date().isoformat()


def settle_floor_plan(unit):
    """Interest current, then PAYOFF to zero (floor-plan units only)."""
    if not unit["floorplan_active"]:
        return
    accrue_interest_to_clock(unit)
    if unit["floorplan_balance_cents"] != 0:
        post_fp_entry(unit, "PAYOFF", -unit["floorplan_balance_cents"])


# ---------- repair order totals (pinned dependency order, PRD §3.7) ----------

def ro_lines(ro_id):
    return [l for l in store.repair_order_lines.values()
            if l["repair_order_id"] == ro_id]


def recompute_ro_totals(ro):
    lines = ro_lines(ro["id"])
    labor = sum(l["line_total_cents"] for l in lines if l["line_type"] == "LABOR")
    parts = sum(l["line_total_cents"] for l in lines if l["line_type"] == "PART")
    account = store.customer_accounts.get(ro["customer_account_id"])
    tier = TIER_PCT[account["fleet_tier"]] if account else Decimal("0")
    discount = rhu(D(labor) * tier)
    fee = min(rhu(SHOP_SUPPLIES_RATE * D(labor - discount)), SHOP_SUPPLIES_CAP)
    covered = sum(
        (c["approved_labor_cents"] or 0) + (c["approved_parts_cents"] or 0)
        for c in store.warranty_claims.values()
        if c["repair_order_id"] == ro["id"] and c["status"] in COVERED_CLAIM_STATUSES
    )
    due = labor - discount + parts + fee - ro["downtime_penalty_cents"] - covered
    ro["labor_sum_cents"] = labor
    ro["parts_sum_cents"] = parts
    ro["discount_cents"] = discount
    ro["shop_supplies_fee_cents"] = fee
    ro["warranty_covered_cents"] = covered
    ro["customer_due_cents"] = max(0, due)


def recompute_ro_sums(ro):
    """Line-add path: only the raw sums (discount/fee/due freeze at invoice)."""
    lines = ro_lines(ro["id"])
    ro["labor_sum_cents"] = sum(l["line_total_cents"] for l in lines
                                if l["line_type"] == "LABOR")
    ro["parts_sum_cents"] = sum(l["line_total_cents"] for l in lines
                                if l["line_type"] == "PART")


def downtime_penalty(ro, completed_dt, promised_dt):
    late_seconds = (completed_dt - promised_dt).total_seconds()
    late_minutes = max(0, int(late_seconds // 60))
    penalty_minutes = max(0, late_minutes - GRACE_MINUTES)
    raw = rhu(D(penalty_minutes) * D(ro["labor_rate_cents"]) * PENALTY_RATE / D(60))
    cap = rhu(D(ro["labor_sum_cents"]) * PENALTY_CAP_LABOR_FRACTION)
    return min(raw, cap)


# ---------- warranty cascade (four levels, PRD §3.8) ----------

def claim_cascade(ro):
    """Recompute covered/due; if INVOICED push the delta to the account's AR."""
    old_due = ro["customer_due_cents"]
    recompute_ro_totals(ro)
    if ro["work_status"] == "INVOICED":
        delta = ro["customer_due_cents"] - old_due
        if delta != 0:
            account = store.customer_accounts.get(ro["customer_account_id"])
            if account is not None:
                adjust_open_ar(account, delta)
    touch(ro)


# ---------- booking RO demotion (PRD §3.6) ----------

def booking_demotion_check(ro):
    if ro["work_status"] != "SCHEDULED":
        return
    open_bookings = [
        b for b in store.service_bookings.values()
        if b["repair_order_id"] == ro["id"] and b["status"] in ("BOOKED", "CHECKED_IN")
    ]
    if not open_bookings:
        ro["work_status"] = "OPEN"
        touch(ro)


# ---------- trade allowance (BOOK + MARKET variants, PRD §3.4) ----------

def book_estimate(model_year, mileage, base_book_value_cents):
    age_years = max(0, now_dt().year - model_year)
    factor = Decimal("1") - ANNUAL_DEPRECIATION * D(age_years)
    if factor < 0:
        factor = Decimal("0")
    book = D(base_book_value_cents) * factor
    excess_miles = max(0, mileage - FREE_MILES)
    estimate = rhu(book) - excess_miles * MILEAGE_PENALTY_CENTS
    return max(0, estimate)


def market_acv(book_estimate_cents, condition_grade, market_index_bp):
    mult = CONDITION_MULT[condition_grade]
    return rhu(D(book_estimate_cents) * mult * D(market_index_bp) / D(10000))


# ---------- parts pricing (per-line rounding pinned, PRD §3.9) ----------

def parts_line_net_price(list_price_cents, fleet_tier, quantity):
    tier_discount = TIER_PCT[fleet_tier]
    qty_break = QTY_BREAK_EXTRA if quantity >= QTY_BREAK_THRESHOLD else Decimal("0")
    effective = tier_discount + qty_break
    if effective > MAX_DISCOUNT:
        effective = MAX_DISCOUNT
    return rhu(D(list_price_cents) * (Decimal("1") - effective))

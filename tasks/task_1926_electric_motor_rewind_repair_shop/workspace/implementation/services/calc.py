"""Calculation modules — precision-critical. Uses Decimal everywhere."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta


# ---------- constants ----------
TIER_SMALL_MAX = 200
TIER_MEDIUM_MAX = 355
TIER_LARGE_MAX = 560

SUPPLIES_TIER_BREAK_CENTS = 100000

EMERGENCY_MULT = Decimal("1.5")

RISK_CORE_FAIL = Decimal("0.35")
RISK_AGE_15 = Decimal("0.25")
RISK_AGE_8 = Decimal("0.15")
RISK_BASE = Decimal("0.08")

CORE_LOSS_MAX_PCT = Decimal("0.05")

VIB_LIMIT_SMALL = Decimal("2.8")
VIB_LIMIT_MEDIUM = Decimal("3.5")
VIB_LIMIT_LARGE = Decimal("4.5")
FRAME_SMALL_MAX = 315
FRAME_MEDIUM_MAX = 630

INCOMING_TEST_FEE_CENTS = 7500
CORE_LOSS_TEST_FEE_CENTS = 12000
BALANCING_FEE_CENTS = 9500
FINAL_TEST_FEE_CENTS = 8500

QUOTE_VALID_DAYS = 30

EASA_FORM_VERSION = "EASA-AR100-2024"


def dec(value):
    """Coerce a numeric input to Decimal via string (avoid float artifacts)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_int(d):
    """Round a Decimal to nearest integer, ROUND_HALF_UP."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------- labor tier ----------
def labor_rate_for_frame(shop, frame_mm):
    if frame_mm <= TIER_SMALL_MAX:
        return shop["labor_rate_small_cents"]
    elif frame_mm <= TIER_MEDIUM_MAX:
        return shop["labor_rate_medium_cents"]
    elif frame_mm <= TIER_LARGE_MAX:
        return shop["labor_rate_large_cents"]
    else:
        return shop["labor_rate_xlarge_cents"]


def compute_rewind_labor_cents(shop, motor, rewind_hours):
    rate = labor_rate_for_frame(shop, motor["frame_mm"])
    return rewind_hours * rate


# ---------- shop supplies (marginal tiering, round once after tier split) ----------
def compute_shop_supplies_cents(shop, rewind_labor_cents, rewind_materials_cents):
    base = rewind_labor_cents + rewind_materials_cents
    low = dec(shop["supplies_low_pct"])
    high = dec(shop["supplies_high_pct"])
    if base <= SUPPLIES_TIER_BREAK_CENTS:
        raw = dec(base) * low
    else:
        raw = dec(SUPPLIES_TIER_BREAK_CENTS) * low + dec(base - SUPPLIES_TIER_BREAK_CENTS) * high
    return round_half_up_int(raw)


# ---------- rush premium ----------
def compute_rush_premium_cents(shop, priority, rewind_labor_cents, rewind_materials_cents, shop_supplies_cents):
    if priority == "STANDARD":
        return 0
    subtotal = rewind_labor_cents + rewind_materials_cents + shop_supplies_cents
    pct = dec(shop["rush_premium_pct"])
    if priority == "RUSH":
        return round_half_up_int(dec(subtotal) * pct)
    # EMERGENCY
    return round_half_up_int(dec(subtotal) * pct * EMERGENCY_MULT)


# ---------- failure risk ----------
def compute_risk_pct(motor, test_records, now):
    """test_records: list of TestRecord dicts for this work order."""
    for tr in test_records:
        if tr["kind"] == "CORE_LOSS" and tr["verdict"] == "FAIL":
            return RISK_CORE_FAIL
    age_years = now.year - motor["manufacture_year"]
    if age_years >= 15:
        return RISK_AGE_15
    if age_years >= 8:
        return RISK_AGE_8
    return RISK_BASE


# ---------- verdicts ----------
def core_loss_verdict(measured_watts, rated_kw):
    rated_watts = dec(rated_kw) * Decimal("1000")
    if rated_watts <= 0:
        return "FAIL"
    loss_pct = dec(measured_watts) / rated_watts
    return "PASS" if loss_pct <= CORE_LOSS_MAX_PCT else "FAIL"


def vibration_verdict(vibration_mm_s, frame_mm):
    if frame_mm <= FRAME_SMALL_MAX:
        limit = VIB_LIMIT_SMALL
    elif frame_mm <= FRAME_MEDIUM_MAX:
        limit = VIB_LIMIT_MEDIUM
    else:
        limit = VIB_LIMIT_LARGE
    # PRD §3.4: "A reading at or below the applicable limit is a PASS;
    # anything strictly above is a FAIL." Compare the reading exactly
    # (decimal arithmetic, no rounding of the reading).
    v = dec(vibration_mm_s)
    return "PASS" if v <= limit else "FAIL"


# ---------- quote assembly ----------
def compute_quote(shop, motor, work_order, test_records, now):
    rewind_labor = compute_rewind_labor_cents(shop, motor, work_order["rewind_hours"])
    rewind_materials = work_order["materials_cents"]
    supplies = compute_shop_supplies_cents(shop, rewind_labor, rewind_materials)
    rush = compute_rush_premium_cents(
        shop, work_order["priority"], rewind_labor, rewind_materials, supplies
    )
    rewind_total = rewind_labor + rewind_materials + supplies + rush
    risk_pct = compute_risk_pct(motor, test_records, now)
    risk_cost = round_half_up_int(dec(rewind_total) * risk_pct)
    tco_total = rewind_total + risk_cost
    threshold = round_half_up_int(dec(shop["replace_threshold_pct"]) * dec(work_order["replacement_cost_cents"]))
    recommendation = "REWIND" if tco_total <= threshold else "REPLACE"
    return {
        "variant": "TCO_ADJUSTED",
        "rewind_labor_cents": rewind_labor,
        "rewind_materials_cents": rewind_materials,
        "shop_supplies_cents": supplies,
        "rush_premium_cents": rush,
        "rewind_total_cents": rewind_total,
        "risk_pct": float(risk_pct),
        "risk_cost_cents": risk_cost,
        "tco_total_cents": tco_total,
        "recommendation": recommendation,
    }


# ---------- invoice total ----------
def compute_invoice_total(shop, work_order, accepted_quote, test_records, reached_balancing):
    if work_order.get("no_charge"):
        return 0
    lines = [INCOMING_TEST_FEE_CENTS]
    has_core_loss = any(tr["kind"] == "CORE_LOSS" for tr in test_records)
    if has_core_loss:
        lines.append(CORE_LOSS_TEST_FEE_CENTS)
    if reached_balancing:
        lines.append(BALANCING_FEE_CENTS)
    if accepted_quote is not None:
        lines.append(accepted_quote["rewind_labor_cents"])
        lines.append(accepted_quote["rewind_materials_cents"])
        lines.append(accepted_quote["shop_supplies_cents"])
        lines.append(accepted_quote["rush_premium_cents"])
    lines.append(FINAL_TEST_FEE_CENTS)
    return sum(lines)


# ---------- pool first month fee ----------
def compute_first_month_fee_cents(shop, slot_count, activated_on):
    full = slot_count * shop["pool_slot_monthly_cents"]
    # days in month of activated_on
    year = activated_on.year
    month = activated_on.month
    if month == 12:
        next_month = activated_on.replace(year=year + 1, month=1, day=1)
    else:
        next_month = activated_on.replace(month=month + 1, day=1)
    this_month = activated_on.replace(day=1)
    days_in_month = (next_month - this_month).days
    day_of_month = activated_on.day
    remaining_days = days_in_month - day_of_month + 1
    raw = dec(full) * dec(remaining_days) / dec(days_in_month)
    return round_half_up_int(raw)


# ---------- pool overdue ----------
def compute_overdue(due_at, returned_at, now, pool_loan_daily_cents):
    if due_at is None:
        return 0, 0
    end = returned_at if returned_at is not None else now
    delta = end - due_at
    days = int(delta.total_seconds() // 86400)
    overdue_days = max(0, days)
    return overdue_days, overdue_days * pool_loan_daily_cents


# ---------- warranty prorated credit ----------
def compute_months_elapsed(delivered_at, filed_at):
    """Whole months between two datetimes, floored."""
    if delivered_at is None or filed_at is None:
        return 0
    # compute whole months: iterate year/month
    months = (filed_at.year - delivered_at.year) * 12 + (filed_at.month - delivered_at.month)
    # adjust if day-of-month not reached
    if filed_at.day < delivered_at.day:
        months -= 1
    # adjust for time-of-day on same day boundary
    elif filed_at.day == delivered_at.day:
        if (filed_at.hour, filed_at.minute, filed_at.second, filed_at.microsecond) < (
            delivered_at.hour,
            delivered_at.minute,
            delivered_at.second,
            delivered_at.microsecond,
        ):
            months -= 1
    return max(0, months)


def compute_prorated_credit(invoice_total_cents, months_elapsed, warranty_months):
    if warranty_months <= 0:
        return 0
    remaining = max(0, warranty_months - months_elapsed)
    raw = dec(invoice_total_cents) * dec(remaining) / dec(warranty_months)
    return round_half_up_int(raw)


# ---------- customer standing ----------
def compute_standing(customer_id, invoices, pool_loans, pool_contracts, now):
    """invoices: all Invoice dicts. pool_loans: all PoolLoan dicts. pool_contracts: all SparePoolContract dicts.

    PRD §3.5 defines standing over the ledger itself: HOLD when any invoice is
    more than thirty days past its due_at, WATCH when any invoice is past due
    or any pool loan is OVERDUE. Because standing is recomputed lazily on
    customer read (PRD §2.4), past-due-ness is evaluated temporally here —
    an OPEN invoice past due_at with a positive balance (or one already
    flipped to OVERDUE) counts, and an OUT loan whose due_at has passed
    counts, whether or not the resource itself has been read since the
    clock advanced.
    """
    def invoice_past_due(inv):
        if inv["customer_id"] != customer_id:
            return False
        if inv["status"] not in ("OPEN", "OVERDUE"):
            return False
        if inv["due_at"] is None or inv["balance_due_cents"] <= 0:
            return False
        return now > inv["due_at"]

    past_due_invoices = [inv for inv in invoices if invoice_past_due(inv)]
    # map contract_id -> contract
    cust_contract_ids = {
        c["id"] for c in pool_contracts if c["customer_id"] == customer_id
    }
    overdue_loans = [
        ln for ln in pool_loans
        if ln["contract_id"] in cust_contract_ids
        and (
            ln["status"] == "OVERDUE"
            or (ln["status"] == "OUT" and ln["due_at"] is not None and now > ln["due_at"])
        )
    ]
    for inv in past_due_invoices:
        delta = now - inv["due_at"]
        if delta.total_seconds() > 30 * 86400:
            return "HOLD"
    if past_due_invoices:
        return "WATCH"
    if overdue_loans:
        return "WATCH"
    return "GOOD"


# ---------- estimated rewind hours (advisory) ----------
def estimated_rewind_hours(rated_kw):
    raw = Decimal("6") + Decimal("0.08") * dec(rated_kw)
    return round_half_up_int(raw)

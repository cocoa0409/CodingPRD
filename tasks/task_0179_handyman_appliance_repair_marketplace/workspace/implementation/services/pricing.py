"""Calculation rules (SCAFFOLD §1.3, PRD §3.6 / §3.7 / §3.8).

All amounts are integer cents. Multiplications that produce fractional cents are
rounded half-up (money.round_half_up). The professional callback rate is the one
non-cent ratio, retained to four decimal places (round-half-up).
"""
from money import round_half_up, mul_round, ratio_round_4dp

# part_line_pricing constants (SCAFFOLD §1.3)
TRUCK_MARKUP_CAP_CENTS = 5000
TRUCK_MARKUP_FLOOR_CENTS = 300
SPECIAL_ORDER_HANDLING_CENTS = 1500

# invoice_total trip-fee constants (SCAFFOLD §1.3)
LOCAL_TRIP_FEE_CENTS = 2500
REMOTE_TRIP_FEE_CENTS = 6000
FREE_TRIP_THRESHOLD_CENTS = 40000


# ---------------------------------------------------------------------------
# quote_pricing (SCAFFOLD §1.3, PRD §3.3)
# ---------------------------------------------------------------------------
def instant_quote_amount(category):
    """INSTANT variant: all-in sight-unseen flat price, ignoring hours, parts,
    and trip fee."""
    return category["instant_quote_flat_cents"]


def in_home_quote_amount(category, job, pro, estimated_labor_hours):
    """IN_HOME variant: itemized projection = labor (flat or hours*rate) + trip
    fee; parts are deferred to the invoice and excluded here."""
    if category["pricing_model"] == "FLAT":
        labor = category["flat_task_fee_cents"]
    else:  # HOURLY
        labor = mul_round(category["hourly_rate_cents"], estimated_labor_hours)
    trip = base_trip_fee(job, pro)
    return labor + trip


# ---------------------------------------------------------------------------
# part_line_pricing (SCAFFOLD §1.3, PRD §3.6)
# ---------------------------------------------------------------------------
def part_line_total(unit_cost_cents, quantity, from_truck_stock, markup_pct):
    base = unit_cost_cents * quantity
    if from_truck_stock:
        markup = mul_round(base, markup_pct)
        # cap first, then floor raises any too-small markup up to the minimum.
        markup = min(markup, TRUCK_MARKUP_CAP_CENTS)
        markup = max(markup, TRUCK_MARKUP_FLOOR_CENTS)
        return base + markup
    # special-order: flat handling fee, no percentage markup.
    return base + SPECIAL_ORDER_HANDLING_CENTS


# ---------------------------------------------------------------------------
# labor line per-line total (SCAFFOLD §1.3 invoice_total per-line rounding)
# ---------------------------------------------------------------------------
def labor_line_total(hours_worked, rate_cents_per_hour):
    return mul_round(rate_cents_per_hour, hours_worked)


# ---------------------------------------------------------------------------
# invoice_total (SCAFFOLD §1.3, PRD §3.7) — evaluation order is PINNED:
#   (1) labor_subtotal, (2) parts_subtotal, (3) trip_fee, (4) total.
# ---------------------------------------------------------------------------
def base_trip_fee(job, pro):
    if pro is not None and job["address_zip_code"] == pro["home_zip_code"]:
        return LOCAL_TRIP_FEE_CENTS
    return REMOTE_TRIP_FEE_CENTS


def compute_invoice_totals(job, category, pro, labor_lines, part_lines):
    if category["pricing_model"] == "FLAT":
        labor_subtotal = category["flat_task_fee_cents"]
    else:  # HOURLY — round EACH labor line to cents, THEN sum.
        labor_subtotal = sum(
            round_half_up(ll["line_total_cents"]) for ll in labor_lines)

    parts_subtotal = sum(pl["line_total_cents"] for pl in part_lines)

    trip_fee = base_trip_fee(job, pro)
    # WAIVER: warranty-callback jobs and jobs whose labor+parts >= threshold pay
    # no trip fee.
    if job["is_warranty_callback"] or (labor_subtotal + parts_subtotal) >= FREE_TRIP_THRESHOLD_CENTS:
        trip_fee = 0

    total = labor_subtotal + parts_subtotal + trip_fee
    return {
        "labor_subtotal_cents": labor_subtotal,
        "parts_subtotal_cents": parts_subtotal,
        "trip_fee_cents": trip_fee,
        "total_cents": total,
    }


# ---------------------------------------------------------------------------
# invoice_reconciliation (SCAFFOLD §1.3, PRD §3.7) — refunds ADD to balance_due.
# ---------------------------------------------------------------------------
def reconcile_balance(invoice):
    invoice["balance_due_cents"] = (
        invoice["total_cents"] - invoice["amount_paid_cents"]
        + invoice["refunded_cents"])
    return invoice["balance_due_cents"]


# ---------------------------------------------------------------------------
# pro_callback_rate (SCAFFOLD §1.3, PRD §3.8)
# ---------------------------------------------------------------------------
def callback_rate(pro):
    if pro["completed_job_count"] == 0:
        return 0
    return ratio_round_4dp(pro["callback_job_count"], pro["completed_job_count"])

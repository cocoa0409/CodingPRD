"""Business calculations, tier/credit governance, and cascading side effects."""
from datetime import timedelta
from decimal import Decimal

from store import db, touch
from timeutil import round_half_up, floor_days

# ---- Constants (SCAFFOLD §1.3) ----
DISCOUNT_CAP_CENTS = 200000
GOLD_THRESHOLD_CENTS = 5000000
SILVER_THRESHOLD_CENTS = 2000000
TIER_PCT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.08"),
    "GOLD": Decimal("0.15"),
}
RESTOCK_FEE_PCT = Decimal("0.20")
RESTOCK_GRACE_DAYS = 14
BUFFER_MINUTES = 30


# ---------------------------------------------------------------------------
# TradeAccount governance (§2.9)
# ---------------------------------------------------------------------------
def account_orders(acct_id):
    return [o for o in db.orders.values() if o.get("trade_account_id") == acct_id]


def account_available_credit(acct):
    committed = sum(
        o["committed_credit_cents"]
        for o in account_orders(acct["id"])
        if o["fulfillment_status"] == "CONFIRMED"
    )
    return acct["credit_limit_cents"] - committed


def account_annual_spend(acct):
    window_start = db.clock - timedelta(days=365)
    total = 0
    for o in account_orders(acct["id"]):
        if o["payment_status"] == "SETTLED" and o.get("settled_at") is not None:
            if o["settled_at"] >= window_start and o.get("total_final_cents") is not None:
                total += o["total_final_cents"]
    return total


def account_tier(annual_spend):
    if annual_spend >= GOLD_THRESHOLD_CENTS:
        return "GOLD"
    if annual_spend >= SILVER_THRESHOLD_CENTS:
        return "SILVER"
    return "STANDARD"


def account_tier_and_pct(acct):
    """(tier, Decimal pct) resolved from the account's current annual spend."""
    tier = account_tier(account_annual_spend(acct))
    return tier, TIER_PCT[tier]


# ---------------------------------------------------------------------------
# Order pricing (§3.3 / §3.4)
# ---------------------------------------------------------------------------
def order_active_lines(order_id):
    lines = [
        l
        for l in db.order_lines.values()
        if l["order_id"] == order_id and l["line_status"] == "ACTIVE"
    ]
    lines.sort(key=lambda l: l["_seq"])
    return lines


def _order_pct(order):
    if order.get("trade_account_id"):
        acct = db.trade_accounts.get(order["trade_account_id"])
        if acct is not None:
            _, pct = account_tier_and_pct(acct)
            return pct
    return Decimal("0.00")


def compute_order_pricing(order, variant):
    """variant in {'ESTIMATE','FINAL'}. Writes the corresponding pricing fields.

    Does NOT touch/version-bump the order; the caller owns the single mutation.
    """
    subtotal = sum(l["unit_price_cents"] * l["quantity"] for l in order_active_lines(order["id"]))
    pct = _order_pct(order)
    raw_discount = round_half_up(Decimal(subtotal) * pct)
    discount = min(raw_discount, DISCOUNT_CAP_CENTS)
    total = subtotal - discount
    if variant == "ESTIMATE":
        order["subtotal_estimate_cents"] = subtotal
        order["discount_estimate_cents"] = discount
        order["total_estimate_cents"] = total
    else:  # FINAL
        order["subtotal_final_cents"] = subtotal
        order["discount_final_cents"] = discount
        order["total_final_cents"] = total


# ---------------------------------------------------------------------------
# Rebate (§3.9)
# ---------------------------------------------------------------------------
def effective_wattage(line, fixture):
    watt = fixture["base_wattage"]
    for opt in fixture.get("options", []):
        if opt["option_id"] in line["selected_option_ids"]:
            watt += opt.get("wattage_delta", 0)
    return watt


def compute_rebate_claimed(order_id, program):
    """Round-per-line-then-sum over eligible ACTIVE lines. Returns (claimed, count)."""
    rate = Decimal(str(program["rebate_rate"]))
    claimed = 0
    count = 0
    for line in order_active_lines(order_id):
        fixture = db.fixture_models.get(line["fixture_model_id"])
        if fixture is None:
            continue
        if not fixture.get("energy_star"):
            continue
        if effective_wattage(line, fixture) > program["wattage_ceiling"]:
            continue
        per_line = round_half_up(Decimal(line["unit_price_cents"] * line["quantity"]) * rate)
        claimed += per_line
        count += 1
    return claimed, count


def rebate_budget_remaining(program):
    used = sum(
        c["claimed_cents"]
        for c in db.rebate_claims.values()
        if c["rebate_program_id"] == program["id"] and c["status"] == "APPROVED"
    )
    return program["budget_total_cents"] - used


# ---------------------------------------------------------------------------
# Returns / restocking (§3.8)
# ---------------------------------------------------------------------------
def line_value(line):
    return line["unit_price_cents"] * line["quantity"]


def order_delivery_window_end(order_id):
    """Latest non-voided delivery-window end for the order, or None."""
    ends = [
        j["window_end"]
        for j in db.delivery_jobs.values()
        if j["order_id"] == order_id and j["status"] != "VOIDED"
    ]
    return max(ends) if ends else None


def compute_restocking_fee(line, order, reason):
    lv = line_value(line)
    if reason in ("DAMAGE", "DEFECTIVE", "WARRANTY"):
        pct = Decimal("0.00")
    else:  # CHANGED_MIND
        win_end = order_delivery_window_end(order["id"])
        if win_end is None:
            days_since = 0
        else:
            days_since = floor_days(db.clock, win_end)
        pct = Decimal("0.00") if days_since <= RESTOCK_GRACE_DAYS else RESTOCK_FEE_PCT
    return round_half_up(Decimal(lv) * pct)


# ---------------------------------------------------------------------------
# Cascades (§2.7)
# ---------------------------------------------------------------------------
def void_delivery_job(job):
    job["status"] = "VOIDED"
    touch(job)
    for ref in db.install_referrals.values():
        if ref["delivery_job_id"] == job["id"] and ref["status"] in ("REFERRED", "SCHEDULED"):
            ref["status"] = "WITHDRAWN"
            touch(ref)
            inst = db.installers.get(ref["installer_id"])
            if inst is not None:
                inst["active_referral_count"] -= 1
                touch(inst)


def cancel_order(order):
    was_confirmed = order["fulfillment_status"] == "CONFIRMED"
    order["fulfillment_status"] = "CANCELLED"
    # every non-terminal line -> CANCELLED
    for line in db.order_lines.values():
        if line["order_id"] == order["id"] and line["line_status"] == "ACTIVE":
            line["line_status"] = "CANCELLED"
            touch(line)
    if was_confirmed:
        # release committed credit (compensates the confirm debit)
        order["committed_credit_cents"] = 0
        acct = db.trade_accounts.get(order.get("trade_account_id"))
        if acct is not None:
            touch(acct)
        # cascade special orders
        for so in db.special_orders.values():
            if so["order_id"] == order["id"] and so["status"] in ("REQUESTED", "CONFIRMED"):
                so["status"] = "CANCELLED"
                touch(so)
        # void SCHEDULED delivery jobs (which withdraws their referrals)
        for job in list(db.delivery_jobs.values()):
            if job["order_id"] == order["id"] and job["status"] == "SCHEDULED":
                void_delivery_job(job)
    touch(order)


def deliver_job(job):
    job["status"] = "DELIVERED"
    touch(job)
    order = db.orders.get(job["order_id"])
    if order is not None and order["fulfillment_status"] == "CONFIRMED":
        order["fulfillment_status"] = "COMPLETED"
        order["committed_credit_cents"] = 0
        acct = db.trade_accounts.get(order.get("trade_account_id"))
        if acct is not None:
            touch(acct)
        touch(order)


def maybe_bubble_order_refunded(order):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    if (
        lines
        and all(l["line_status"] in ("RETURNED", "CANCELLED") for l in lines)
        and order["payment_status"] == "SETTLED"
    ):
        order["payment_status"] = "REFUNDED"
        touch(order)


# ---------------------------------------------------------------------------
# Installer overlap (§2.10)
# ---------------------------------------------------------------------------
def installer_has_overlap(installer_id, start, end, exclude_ref_id):
    """Half-open [start,end) overlap against SCHEDULED referrals for the installer."""
    for ref in db.install_referrals.values():
        if ref["id"] == exclude_ref_id:
            continue
        if ref["installer_id"] != installer_id or ref["status"] != "SCHEDULED":
            continue
        a_start = ref.get("appointment_start")
        a_end = ref.get("appointment_end")
        if a_start is None or a_end is None:
            continue
        if start < a_end and a_start < end:
            return True
    return False


def truck_window_conflict(truck_id, start, end, exclude_job_id=None):
    """Closed intervals; any two non-VOIDED windows must be >= BUFFER_MINUTES apart."""
    buf = timedelta(minutes=BUFFER_MINUTES)
    for job in db.delivery_jobs.values():
        if job["id"] == exclude_job_id:
            continue
        if job["delivery_truck_id"] != truck_id or job["status"] == "VOIDED":
            continue
        e_start = job["window_start"]
        e_end = job["window_end"]
        if start < e_end + buf and e_start < end + buf:
            return True
    return False

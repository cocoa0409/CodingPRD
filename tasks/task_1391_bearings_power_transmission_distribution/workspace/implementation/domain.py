"""Business logic: contract-lag pricing, expedite fees, order totals,
stock availability, receivables reconciliation, referral selector."""

from datetime import timedelta
from decimal import Decimal

from db import store
from helpers import dec, rhu, touch, local_time, now

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
RESERVATION_TTL_HOURS = 72
RMA_WINDOW_DAYS = 30
RUSH_PCT = Decimal("0.08")
EMERGENCY_PCT = Decimal("0.15")
AFTER_CUTOFF_MULT = Decimal("1.25")
STANDARD_FLAT_CENTS = 1500
RUSH_MIN_CENTS = 2500
EMERGENCY_MIN_CENTS = 5000
RESTOCK_FEE_PCT = Decimal("0.15")
OBSOLETE_WRITE_DOWN_PCT = Decimal("0.50")
WEEKEND_FEE_MULTIPLIER = Decimal("1.5")
PER_UNIT_HANDLING_CENTS = 250
REFERRAL_FEE_PCT = Decimal("0.10")
REFERRAL_FEE_CAP_CENTS = 2500 * 10  # 25000


# ---------------------------------------------------------------------------
# Stock availability (available_stock)
# ---------------------------------------------------------------------------

def reserved_qty(stock):
    return sum(
        r["qty"]
        for r in store.reservations.values()
        if r["branch_stock_id"] == stock["id"] and r["status"] == "ACTIVE"
    )


def available_qty(stock):
    return stock["on_hand_qty"] - reserved_qty(stock)


def find_stock(branch_id, product_id):
    """The stock record for a (branch, product) pair; earliest created wins."""
    matches = [
        s for s in store.stocks.values()
        if s["branch_id"] == branch_id and s["product_id"] == product_id
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda s: s["_seq"])[0]


# ---------------------------------------------------------------------------
# Price-file history and the contract-lag unit price (contract_lag_unit_price)
# ---------------------------------------------------------------------------

def _effective_history(product_id):
    """Price files that actually took effect (EFFECTIVE now or SUPERSEDED after
    having taken effect), sorted by effective_at then insertion order."""
    files = [
        f for f in store.price_files.values()
        if f["product_id"] == product_id and f.get("_took_effect")
    ]
    return sorted(files, key=lambda f: (f["effective_at"], f["_seq"]))


def list_price_at(product, T):
    """List price at instant T: newest took-effect file with effective_at <= T,
    else the product's creation list price."""
    hist = _effective_history(product["id"])
    chosen = None
    for f in hist:
        if f["effective_at"] <= T:
            chosen = f
        else:
            break
    if chosen is not None:
        return chosen["new_list_price_cents"]
    return product["_original_list_price_cents"]


def find_active_contract(customer_id, family, T):
    """The ACTIVE contract for (customer, family) whose half-open window
    [effective_from, effective_to) contains T. At most one can exist."""
    for c in store.contracts.values():
        if (
            c["customer_id"] == customer_id
            and c["family"] == family
            and c["status"] == "ACTIVE"
            and c["effective_from"] <= T < c["effective_to"]
        ):
            return c
    return None


def contract_lag_unit_price(customer_id, product, T):
    """Returns (unit_price_cents, price_protection_applied)."""
    list_at_T = list_price_at(product, T)
    contract = find_active_contract(customer_id, product["family"], T)

    if contract is None:
        candidate = list_at_T
    elif contract["price_basis"] == "CONTRACT_FIXED":
        candidate = contract["fixed_unit_price_cents"]
    else:  # LIST_LESS
        candidate = rhu(dec(list_at_T) * (Decimal(1) - dec(contract["discount_pct"])))

    applied = False
    if contract is not None and contract["lag_protection_days"] > 0:
        E = product["last_price_change_at"]
        if E is not None and T < E + timedelta(days=contract["lag_protection_days"]):
            new_price = list_price_at(product, E)
            # price in effect just before E
            hist = _effective_history(product["id"])
            prev = product["_original_list_price_cents"]
            for f in hist:
                if f["effective_at"] < E:
                    prev = f["new_list_price_cents"]
                else:
                    break
            if new_price > prev:
                # recompute candidate with the pre-increase price
                if contract["price_basis"] == "CONTRACT_FIXED":
                    protected = contract["fixed_unit_price_cents"]
                else:
                    protected = rhu(dec(prev) * (Decimal(1) - dec(contract["discount_pct"])))
                if protected < candidate:
                    candidate = protected
                    applied = True
    return candidate, applied


# ---------------------------------------------------------------------------
# Expedite fee stacking (expedite_fee_stacking)
# ---------------------------------------------------------------------------

def expedite_fee(tier, unit_price_cents, qty, branch, at):
    """Per-line fee; `at` is the pricing-pass instant whose branch-local hour
    is compared to the branch expedite cutoff."""
    protected = dec(unit_price_cents) * qty
    if tier == "RUSH":
        pct = rhu(RUSH_PCT * protected)
    elif tier == "EMERGENCY":
        pct = rhu(EMERGENCY_PCT * protected)
    else:
        pct = 0
    if tier in ("RUSH", "EMERGENCY"):
        local_hour = local_time(branch, at).hour
        if local_hour >= branch["expedite_cutoff_hour"]:
            pct = rhu(dec(pct) * AFTER_CUTOFF_MULT)
    flat = STANDARD_FLAT_CENTS if tier == "STANDARD" else 0
    fee = flat + pct
    if tier == "RUSH":
        fee = max(fee, RUSH_MIN_CENTS)
    elif tier == "EMERGENCY":
        fee = max(fee, EMERGENCY_MIN_CENTS)
    return fee


# ---------------------------------------------------------------------------
# Order totals (order_total_aggregation): per-line first, then sum.
# ---------------------------------------------------------------------------

def compute_line_pricing(order, line, anchor, branch):
    """Pure computation for one line. Returns dict of new field values."""
    product = store.products[line["product_id"]]
    unit, applied = contract_lag_unit_price(order["customer_id"], product, anchor)
    fee = expedite_fee(line["expedite_tier"], unit, line["qty"], branch, anchor)
    goods = rhu(dec(unit) * line["qty"])
    return {
        "unit_price_cents": unit,
        "price_protection_applied": applied,
        "expedite_fee_cents": fee,
        "line_total_cents": goods + fee,
        "_goods": goods,
    }


def order_lines(order_id):
    return sorted(
        (l for l in store.order_lines.values() if l["order_id"] == order_id),
        key=lambda l: l["_seq"],
    )


def recompute_order_totals(order):
    """Sum goods/fees over non-CANCELLED lines (sum-then-round forbidden)."""
    lines = [l for l in order_lines(order["id"]) if l["sourcing_status"] != "CANCELLED"]
    subtotal = 0
    fees = 0
    for l in lines:
        unit = l["unit_price_cents"] or 0
        goods = rhu(dec(unit) * l["qty"])
        l["line_total_cents"] = goods + l["expedite_fee_cents"]
        subtotal += goods
        fees += l["expedite_fee_cents"]
    order["subtotal_cents"] = subtotal
    order["expedite_fees_cents"] = fees
    order["total_cents"] = subtotal + fees


# ---------------------------------------------------------------------------
# Order fulfillment re-evaluation (pure function of line states)
# ---------------------------------------------------------------------------

def reevaluate_order_fulfillment(order):
    if order["fulfillment_status"] in ("DRAFT", "CANCELLED", "CLOSED"):
        return
    lines = order_lines(order["id"])
    if not lines:
        return
    statuses = [l["sourcing_status"] for l in lines]
    if all(s == "SHIPPED" for s in statuses):
        new = "SHIPPED"
    elif any(s == "SHIPPED" for s in statuses):
        new = "PARTIALLY_SHIPPED"
    elif all(s != "PENDING_SOURCING" for s in statuses):
        new = "FULLY_SOURCED"
    else:
        new = "CONFIRMED"
    if new != order["fulfillment_status"]:
        order["fulfillment_status"] = new
        touch(order)


# ---------------------------------------------------------------------------
# Consignment derived quantities
# ---------------------------------------------------------------------------

def consumed_qty(agreement):
    return sum(
        c["qty"]
        for c in store.consumptions.values()
        if c["agreement_id"] == agreement["id"]
        and c["status"] in ("REPORTED", "INVOICED", "DISPUTED")
    )


def remaining_qty(agreement):
    return agreement["consigned_qty"] - consumed_qty(agreement)


# ---------------------------------------------------------------------------
# Receivables reconciliation (open_receivables_reconciliation) — derived,
# recomputed eagerly from source records on every read / contributing change.
# ---------------------------------------------------------------------------

def claim_customer_id(claim):
    if claim["order_line_id"]:
        line = store.order_lines.get(claim["order_line_id"])
        if line:
            order = store.orders.get(line["order_id"])
            return order["customer_id"] if order else None
    if claim["consumption_id"]:
        cons = store.consumptions.get(claim["consumption_id"])
        if cons:
            ag = store.agreements.get(cons["agreement_id"])
            return ag["customer_id"] if ag else None
    return None


def open_receivables(customer_id):
    total = 0
    for o in store.orders.values():
        if o["customer_id"] == customer_id and o["billing_status"] in ("INVOICED", "PARTIALLY_PAID"):
            total += o["total_cents"] - o["paid_cents"]
    for c in store.consumptions.values():
        if c["status"] != "INVOICED":
            continue
        ag = store.agreements.get(c["agreement_id"])
        if ag and ag["customer_id"] == customer_id:
            total += c["billed_amount_cents"] - c["offset_applied_cents"]
    for co in store.call_outs.values():
        if co["customer_id"] == customer_id and co["status"] == "FULFILLED":
            total += co["total_charge_cents"]
    for w in store.claims.values():
        if w["status"] == "CREDIT_ISSUED" and claim_customer_id(w) == customer_id:
            total -= w["credit_amount_cents"]
    for r in store.returns.values():
        if r["customer_id"] == customer_id and r["status"] == "CREDIT_ISSUED":
            total -= r["offset_applied_cents"] + r["credit_memo_cents"]
    return total


# ---------------------------------------------------------------------------
# Call-out fee (call_out_fee)
# ---------------------------------------------------------------------------

def call_out_fee(branch, qty, at):
    lt = local_time(branch, at)
    fee = branch["after_hours_fee_cents"]
    if lt.weekday() >= 5:  # Saturday / Sunday
        fee = rhu(dec(fee) * WEEKEND_FEE_MULTIPLIER)
    return fee + qty * PER_UNIT_HANDLING_CENTS


# ---------------------------------------------------------------------------
# Referral shop selector (referral_shop_selector)
# ---------------------------------------------------------------------------

def chain_declined_shop_ids(claim_id):
    ids = []
    for r in sorted(
        (r for r in store.referrals.values() if r["warranty_claim_id"] == claim_id),
        key=lambda r: r["_seq"],
    ):
        if r["status"] == "DECLINED" and r["service_shop_id"] not in ids:
            ids.append(r["service_shop_id"])
    return ids


def select_shop(claim, region, declined_ids):
    product = store.products[claim["product_id"]]
    candidates = [
        s for s in store.shops.values()
        if s["status"] == "ACTIVE"
        and product["family"] in s["capabilities"]
        and s["region"] == region
        and s["id"] not in declined_ids
    ]
    if not candidates:
        return None
    # labor_rate ASC, tie-break created_at ASC (never shop.id)
    return sorted(candidates, key=lambda s: (s["labor_rate_cents"], s["created_at"], s["_seq"]))[0]


def month_end_instant(dt):
    """Last instant of the UTC calendar month containing dt."""
    if dt.month == 12:
        first_next = dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        first_next = dt.replace(month=dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return first_next - timedelta(microseconds=1)

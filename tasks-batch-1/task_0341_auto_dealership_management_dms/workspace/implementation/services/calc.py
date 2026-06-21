"""Calculation rules (PRD §3.4, §3.1; scaffold §1.3). All money is integer cents.

Rounding is always round-half-up via Decimal. float is never used for money.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import db

# Calculation constants (scaffold §1.3).
DESK_ESTIMATE_RATE_BPS = 699
DESK_ESTIMATE_TERM_MONTHS = 72
MARKUP_TIER_BPS = 150
RESERVE_RATE_LOW = Decimal("0.01")
RESERVE_RATE_HIGH = Decimal("0.02")
DAY_COUNT_BASIS = 360
CURTAILMENT_AGE_DAYS = 90
CURTAILMENT_PCT = Decimal("0.10")


def rhu(value):
    """Round half up to a whole integer cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Deal helpers (operate on raw dicts to avoid import cycles).
# --------------------------------------------------------------------------- #
def _attached_trade(deal):
    """The deal's attached non-RELEASED TradeIn (or None)."""
    candidates = [
        t for t in db.trade_ins.values()
        if t["deal_id"] == deal["id"] and t["status"] != "RELEASED"
    ]
    if not candidates:
        return None
    # at most one non-released trade is attached at a time
    candidates.sort(key=lambda t: (t["created_at"], t["id"]))
    return candidates[-1]


def _active_products(deal):
    return [
        p for p in db.deal_products.values()
        if p["deal_id"] == deal["id"] and p["status"] == "ACTIVE"
    ]


def _non_void_products(deal):
    return [
        p for p in db.deal_products.values()
        if p["deal_id"] == deal["id"] and p["status"] != "VOID"
    ]


def _active_finance_contract(deal):
    for c in db.finance_contracts.values():
        if c["deal_id"] == deal["id"] and c["status"] == "ACTIVE":
            return c
    return None


def active_floor_plan_line(vehicle_id):
    """Latest ACTIVE FloorPlanLine for a vehicle by created_at, or None."""
    lines = [
        l for l in db.floor_plan_lines.values()
        if l["vehicle_id"] == vehicle_id and l["status"] == "ACTIVE"
    ]
    if not lines:
        return None
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines[-1]


# --------------------------------------------------------------------------- #
# Calculation: deal_tax (PRD §3.4 — round-per-line-then-sum, authoritative).
# --------------------------------------------------------------------------- #
def deal_tax(deal):
    rate = Decimal(deal["tax_rate_bps"]) / Decimal(10000)
    trade_allowance = deal.get("trade_allowance_cents", 0)
    taxable_sale = max(0, deal["sale_price_cents"] - trade_allowance)
    line_tax_sale = rhu(Decimal(taxable_sale) * rate)
    line_tax_acc = rhu(Decimal(deal.get("accessories_cents", 0)) * rate)
    line_tax_doc = rhu(Decimal(deal.get("doc_fee_cents", 0)) * rate)
    return line_tax_sale + line_tax_acc + line_tax_doc


# --------------------------------------------------------------------------- #
# Calculation: amount_financed (PRD §3.4).
# --------------------------------------------------------------------------- #
def fi_products_total(deal):
    """Sum of sold_price_cents over the deal's non-VOID product lines."""
    return sum(p["sold_price_cents"] for p in _non_void_products(deal))


def amount_financed(deal):
    total_tax = deal_tax(deal)
    fi_total = sum(p["sold_price_cents"] for p in _active_products(deal))
    gross_due = (
        deal["sale_price_cents"]
        + deal.get("accessories_cents", 0)
        + deal.get("doc_fee_cents", 0)
        + deal.get("title_fee_cents", 0)
        + deal.get("registration_fee_cents", 0)
        + total_tax
        + fi_total
    )
    reductions = (
        deal.get("rebate_cents", 0)
        + deal.get("trade_equity_cents", 0)
        + deal.get("cash_down_cents", 0)
    )
    return gross_due - reductions


# --------------------------------------------------------------------------- #
# Calculation: deal_gross FRONT/BACK (PRD §3.4).
# --------------------------------------------------------------------------- #
def vehicle_cost_basis(deal):
    line = active_floor_plan_line(deal["vehicle_id"])
    if line is not None:
        return line["principal_cents"]
    vehicle = db.vehicles.get(deal["vehicle_id"])
    return vehicle["list_price_cents"] if vehicle else 0


def front_gross(deal):
    return deal["sale_price_cents"] + deal.get("accessories_cents", 0) - vehicle_cost_basis(deal)


def back_gross(deal):
    product_markup = sum(
        p["sold_price_cents"] - p["product_cost_cents"] for p in _active_products(deal)
    )
    contract = _active_finance_contract(deal)
    reserve = contract["finance_reserve_cents"] if contract else 0
    return product_markup + reserve


# --------------------------------------------------------------------------- #
# Calculation: monthly_payment (PRD §3.4) — fixed-rate amortization.
# --------------------------------------------------------------------------- #
def monthly_payment(amount_financed_cents, rate_bps, term_months):
    apr = Decimal(rate_bps) / Decimal(10000)
    n = term_months
    P = Decimal(amount_financed_cents) / Decimal(100)
    r = apr / Decimal(12)
    if r == 0:
        pmt = P / Decimal(n)
    else:
        pmt = P * r / (Decimal(1) - (Decimal(1) + r) ** (-n))
    return rhu(pmt * Decimal(100))


def estimate_payment(deal):
    af = amount_financed(deal)
    return monthly_payment(af, DESK_ESTIMATE_RATE_BPS, DESK_ESTIMATE_TERM_MONTHS)


# --------------------------------------------------------------------------- #
# Calculation: finance_reserve (PRD §3.4) — pinned 3-step order.
# --------------------------------------------------------------------------- #
def finance_reserve(amount_financed_snapshot_cents, markup_bps, max_markup_bps):
    effective_markup = min(markup_bps, max_markup_bps)
    reserve_rate = RESERVE_RATE_LOW if effective_markup <= MARKUP_TIER_BPS else RESERVE_RATE_HIGH
    return rhu(Decimal(amount_financed_snapshot_cents) * reserve_rate)


# --------------------------------------------------------------------------- #
# Calculation: floor_plan_payoff (PRD §3.1).
# --------------------------------------------------------------------------- #
def payoff_days(floored_on_dt, as_of_dt):
    """Whole days from floored_on to as_of (rounded up so a partial day counts)."""
    delta = as_of_dt - floored_on_dt
    return max(0, math.ceil(delta.total_seconds() / 86400.0))


def floor_plan_interest(principal_outstanding_cents, annual_rate_bps, days):
    return rhu(
        Decimal(principal_outstanding_cents)
        * (Decimal(annual_rate_bps) / Decimal(10000))
        / Decimal(DAY_COUNT_BASIS)
        * Decimal(days)
    )


# --------------------------------------------------------------------------- #
# Calculation: curtailment (PRD §3.1).
# --------------------------------------------------------------------------- #
def curtailment_age_days(floored_on_dt, as_of_dt):
    delta = as_of_dt - floored_on_dt
    return int(delta.total_seconds() // 86400)


def curtailment_reduction(principal_cents):
    return rhu(Decimal(principal_cents) * CURTAILMENT_PCT)


# --------------------------------------------------------------------------- #
# Calculation: incentive_eligibility (PRD §3.4).
# --------------------------------------------------------------------------- #
def incentive_eligible(incentive, vehicle, deal):
    if not incentive["active"]:
        return False
    cond = incentive["eligible_condition"]
    if not (cond == "ANY" or cond == vehicle["condition"]):
        return False
    if incentive.get("eligible_make") is not None and incentive["eligible_make"] != vehicle["make"]:
        return False
    if incentive.get("min_model_year") is not None and vehicle["model_year"] < incentive["min_model_year"]:
        return False
    if deal["deal_type"] == "FINANCE" and not incentive["stackable_with_finance"]:
        return False
    return True

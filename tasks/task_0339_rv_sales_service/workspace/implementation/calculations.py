"""Money math (PRD section 3 / scaffold §1.3). All amounts integer cents.

Rounding is round-half-up, applied only at the step each formula pins.
"""

from decimal import Decimal, ROUND_HALF_UP

from common import APR_BAND, MAX_LTV_BPS, WINTERIZE_FEE_CENTS

_DAY_US = 86400 * 1_000_000


def round_half_up(value):
    """Round a Decimal (or numeric) to the nearest integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- net trade equity (dual variant) -----------------------------------------
def trade_equities(deal):
    """Return (applied buyer credit, dealer-book equity).

    Applied: allowance - payoff (recon NOT subtracted) -> buyer credit (may be < 0).
    Dealer-book: allowance - payoff - recon (margin view).
    Both 0 when no trade unit is linked.
    """
    if not deal.get("trade_unit_id"):
        return 0, 0
    allowance = deal["trade_allowance_cents"]
    payoff = deal["trade_payoff_cents"]
    recon = deal["trade_recon_cost_cents"]
    applied = allowance - payoff
    book = allowance - payoff - recon
    return applied, book


# --- deal amount due (pinned evaluation order) -------------------------------
def quote_amounts(deal, dealership):
    """Compute doc_fee snapshot, tax, gross due, amount financed.

    Returns a dict of the computed money fields.
    """
    applied, book = trade_equities(deal)
    doc_fee = dealership["doc_fee_cents"]                                   # step 1
    taxable_base = max(deal["sale_price_cents"] - applied, 0)               # step 2
    tax = round_half_up(                                                    # step 3
        Decimal(taxable_base) * Decimal(dealership["sales_tax_rate_bps"]) / Decimal(10000)
    )
    gross_due = deal["sale_price_cents"] + doc_fee + tax                    # step 4
    financed = max(gross_due - applied - deal["down_payment_cents"], 0)     # step 5
    return {
        "net_trade_equity_cents": applied,
        "dealer_book_equity_cents": book,
        "doc_fee_cents": doc_fee,
        "tax_cents": tax,
        "amount_financed_cents": financed,
    }


# --- monthly payment (tiered APR + amortization) -----------------------------
def ltv_bps(amount_financed, list_price_cents):
    if list_price_cents <= 0:
        # Avoid division by zero; treat as infinite LTV.
        return None
    return (amount_financed * 10000) // list_price_cents


def monthly_payment(amount_financed, term_months, credit_tier):
    apr = APR_BAND[credit_tier]
    P = Decimal(amount_financed)
    n = term_months
    r = Decimal(apr) / Decimal(10000) / Decimal(12)
    if r == 0:
        payment = P / Decimal(n)
    else:
        factor = (Decimal(1) + r) ** n
        payment = P * r * factor / (factor - Decimal(1))
    return round_half_up(payment)


# --- service order total (round-then-sum; warranty split) --------------------
def labor_cents(labor_hours, labor_rate_cents):
    return round_half_up(Decimal(str(labor_hours)) * Decimal(labor_rate_cents))


def service_totals(gross_cents, is_warranty, plan):
    """Return (covered_cents, total_cents). plan may be None for non-warranty."""
    if is_warranty:
        remaining_cap = plan["coverage_cap_cents"] - plan["consumed_cents"]
        coverable = max(gross_cents - plan["deductible_cents"], 0)
        covered = min(coverable, remaining_cap)
        total = gross_cents - covered
        return covered, total
    return 0, gross_cents


def warranty_coverable(gross_cents, plan):
    return max(gross_cents - plan["deductible_cents"], 0)


# --- storage charge (ceil-day, min 1, winterize fee) -------------------------
def storage_charge(start_dt, released_dt, daily_rate_cents, winterized):
    # Half-open day count: each started calendar day bills a full day; minimum 1.
    # Use microsecond precision so a one-microsecond-over-boundary release rolls a day.
    delta = released_dt - start_dt
    elapsed_us = delta.days * _DAY_US + delta.seconds * 1_000_000 + delta.microseconds
    if elapsed_us <= 0:
        days = 1
    else:
        days = max(1, -(-elapsed_us // _DAY_US))  # ceil division
    base = days * daily_rate_cents
    return base + (WINTERIZE_FEE_CENTS if winterized else 0)


# --- consignor proceeds (waterfall, floor honored) ---------------------------
def consignor_proceeds(sale_price_cents, consignment_fee_bps, consignment_floor_cents):
    commission = round_half_up(
        Decimal(sale_price_cents) * Decimal(consignment_fee_bps) / Decimal(10000)
    )
    consignor_net = sale_price_cents - commission
    if consignor_net < consignment_floor_cents:
        consignor_net = consignment_floor_cents
        commission = sale_price_cents - consignment_floor_cents
    dealer_margin = sale_price_cents - consignor_net
    return {
        "commission_cents": commission,
        "consignor_net_cents": consignor_net,
        "dealer_margin_cents": dealer_margin,
    }

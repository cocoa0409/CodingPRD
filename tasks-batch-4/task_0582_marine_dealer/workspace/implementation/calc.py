"""Calculation rules (SCAFFOLD 1.3 / PRD 2.7, 3.x). All money in integer cents.

Rounding is round-half-up (away from zero at exactly .5) via Decimal.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from store import DAYS_PER_YEAR, PAYOFF_NOTICE_DAYS, MIN_DOWN_BPS


def _dec(x):
    return Decimal(str(x))


def rhu(value):
    """Round a Decimal to a whole integer, half up (away from zero)."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def rhu_ratio(numer, denom):
    """round_half_up(numer / denom) where numer, denom are exact numbers."""
    return rhu(_dec(numer) / _dec(denom))


# ---- deal_financials --------------------------------------------------------

def deal_financials(sale_price_cents, tax_rate_bps, doc_fee_cents,
                    down_payment_cents, trade_allowance_cents, trade_lien_payoff_cents):
    trade_equity_cents = trade_allowance_cents - trade_lien_payoff_cents
    tax_base_cents = max(0, sale_price_cents - max(0, trade_allowance_cents))
    tax_cents = rhu_ratio(tax_base_cents * tax_rate_bps, 10000)
    amount_due_cents = (sale_price_cents + tax_cents + doc_fee_cents
                        - down_payment_cents - trade_equity_cents)
    return trade_equity_cents, tax_cents, amount_due_cents


def min_down_required(sale_price_cents):
    """ceil(sale_price_cents * MIN_DOWN_BPS / 10000)."""
    num = sale_price_cents * MIN_DOWN_BPS
    return -((-num) // 10000)


# ---- floor_plan_accrual -----------------------------------------------------

def days_out(clock_now, advanced_at):
    delta = (clock_now - advanced_at).total_seconds() / 86400.0
    return math.floor(delta)


def accrued_interest(outstanding_principal_cents, apr_bps, d_out):
    return rhu_ratio(outstanding_principal_cents * apr_bps * d_out, 10000 * DAYS_PER_YEAR)


def payoff(outstanding_principal_cents, apr_bps, d_out):
    proj_days = d_out + PAYOFF_NOTICE_DAYS
    interest = rhu_ratio(outstanding_principal_cents * apr_bps * proj_days, 10000 * DAYS_PER_YEAR)
    return outstanding_principal_cents + interest


# ---- repair_order_totals ----------------------------------------------------

def estimate_total(ro_type, labor_rate_cents_per_hour, tax_rate_bps,
                   flat_rate_hours, flat_rate_parts_cents, estimated_hours):
    if ro_type == "FLAT_RATE":
        labor = rhu(_dec(flat_rate_hours) * _dec(labor_rate_cents_per_hour))
        base = labor + int(flat_rate_parts_cents)
    else:  # DIAGNOSTIC | CUSTOM
        base = rhu(_dec(estimated_hours) * _dec(labor_rate_cents_per_hour))
    tax = rhu_ratio(base * tax_rate_bps, 10000)
    return base + tax


def line_extended(line_type, hours, quantity, effective_price):
    if line_type == "LABOR":
        return rhu(_dec(hours) * _dec(effective_price))
    return rhu(_dec(quantity) * _dec(effective_price))


def final_total(subtotal_cents, tax_rate_bps):
    tax = rhu_ratio(subtotal_cents * tax_rate_bps, 10000)
    return subtotal_cents + tax


# ---- consignment_payout -----------------------------------------------------

def consignment_payout(sale_price_cents, commission_bps):
    commission = rhu_ratio(sale_price_cents * commission_bps, 10000)
    return sale_price_cents - commission


# ---- slip nights ------------------------------------------------------------

def nights_between(start_date, end_date):
    delta = (end_date - start_date).total_seconds() / 86400.0
    return math.floor(delta)

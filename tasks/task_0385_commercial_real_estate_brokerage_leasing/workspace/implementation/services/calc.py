"""Calculation rules (PRD §3.7, §3.8; SCAFFOLD §1.3).

All monetary figures use Decimal with ROUND_HALF_UP, single final rounding.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

LONG_TERM_MONTHS = 120
LONG_TERM_DISCOUNT = Decimal("0.01")
MIN_COMMISSION_PCT = Decimal("0.03")
TWO_DP = Decimal("0.01")


def _D(v):
    return Decimal(str(v))


def _round2(d):
    return d.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def _to_number(d):
    """Decimal -> plain JSON number (int when whole, else float)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def gross_total_psf(base_rent_psf_yr, term_months, annual_escalation_pct):
    """Escalated gross-rent stream per square foot (unrounded Decimal sum).

    PINNED order: escalate per whole lease-year, prorate the final partial
    year by its in-term month fraction, sum (no intermediate rounding).
    """
    base = _D(base_rent_psf_yr)
    esc = _D(annual_escalation_pct)
    n_years = math.ceil(term_months / 12)
    total = Decimal("0")
    for y in range(n_years):
        year_rate = base * ((Decimal("1") + esc) ** y)
        months_in_year = min(12, term_months - 12 * y)
        total += year_rate * (_D(months_in_year) / _D(12))
    return total


def net_effective_rent(base_rent_psf_yr, term_months, free_rent_months,
                       ti_allowance_psf, annual_escalation_pct):
    """Net effective rent PSF/yr (PRD §3.7). Single final round_half_up to 2dp."""
    gross = gross_total_psf(base_rent_psf_yr, term_months, annual_escalation_pct)
    # Free rent credited at YEAR-1 base rate (PINNED — never escalated).
    free_credit = _D(base_rent_psf_yr) * (_D(free_rent_months) / _D(12))
    net_total = gross - free_credit - _D(ti_allowance_psf)
    term_years = _D(term_months) / _D(12)
    result = _round2(net_total / term_years)
    return _to_number(result)


def gross_effective_rent(base_rent_psf_yr, term_months, annual_escalation_pct):
    """Gross effective rent PSF/yr (PRD §3.7 — reported, not stored)."""
    gross = gross_total_psf(base_rent_psf_yr, term_months, annual_escalation_pct)
    term_years = _D(term_months) / _D(12)
    return _to_number(_round2(gross / term_years))


def lease_consideration(base_rent_psf_yr, term_months, annual_escalation_pct,
                        rentable_sf):
    """Total gross base-rent dollars over the term (PRD §3.7). Sum-then-round."""
    base = _D(base_rent_psf_yr)
    esc = _D(annual_escalation_pct)
    rsf = _D(rentable_sf)
    n_years = math.ceil(term_months / 12)
    total = Decimal("0")
    for y in range(n_years):
        year_rate = base * ((Decimal("1") + esc) ** y)
        months_in_year = min(12, term_months - 12 * y)
        total += year_rate * rsf * (_D(months_in_year) / _D(12))
    return _to_number(_round2(total))


def effective_commission_pct(default_commission_pct, accepted_term_months):
    """Effective commission RATE at full precision (PRD §3.8)."""
    base_pct = _D(default_commission_pct)
    if accepted_term_months >= LONG_TERM_MONTHS:
        eff = base_pct - LONG_TERM_DISCOUNT
    else:
        eff = base_pct
    if eff < MIN_COMMISSION_PCT:
        eff = MIN_COMMISSION_PCT
    return eff  # Decimal, full precision


def total_commission(total_consideration, eff_pct):
    """Commission dollars = consideration * eff_pct, rounded 2dp (PRD §3.8)."""
    result = _round2(_D(total_consideration) * eff_pct)
    return _to_number(result)


def commission_split(total_commission_amt, is_co_broke, co_broke_offered_pct):
    """Allocate commission into (listing_amount, procuring_amount) (PRD §3.8).

    Conserved-quantity invariant: listing + procuring == total_commission.
    Procuring rounded to 2dp; listing is the residual (NOT independently rounded).
    """
    total = _D(total_commission_amt)
    if is_co_broke:
        procuring = _round2(total * _D(co_broke_offered_pct))
        listing = total - procuring  # residual — conserves total exactly
    else:
        procuring = Decimal("0.00")
        listing = _round2(total)
    return _to_number(listing), _to_number(procuring)

"""Calculation rules from scaffold §1.3.

Every function returns Decimal values rounded to 2dp at the points the
scaffold pins, never silently in the middle of an aggregation.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from config import (
    GST_EXEMPTION_LIMIT,
    GST_GENERATION_GAP_YEARS,
    GST_TAX_RATE,
    TRUST_TAX_BRACKETS,
)
from utils import money, to_decimal


# ── GST skip-person determination (scaffold §1.3 gst_skip_person_determination) ──


def years_between(later: datetime, earlier: datetime) -> Decimal:
    """Day-count years using /365.25, expressed to two decimal places.

    The PRD pins this precision for the skip-person threshold so that
    exactly 37.5 years (at the day-count precision) qualifies as skip.
    """
    if later is None or earlier is None:
        return Decimal("0")
    days = (later - earlier).total_seconds() / 86400.0
    # Quantize the year value to two decimal places to match the scaffold.
    years = Decimal(repr(days)) / Decimal("365.25")
    return years.quantize(Decimal("0.01"))


def determine_is_skip_person(beneficiary: dict, trust: dict) -> bool:
    relation = beneficiary["relation_class"]
    if relation == "GRANDCHILD":
        return True
    if relation in ("OTHER_LINEAL", "NON_LINEAL"):
        diff = years_between(beneficiary["birth_date"], trust["inception_date"])
        return diff >= GST_GENERATION_GAP_YEARS
    # SPOUSE, CHILD never skip-person.
    return False


# ── GST taxable / tax computation (scaffold §1.3) ────────────────────────────


def compute_gst_classification(trust: dict, distribution: dict, beneficiary: dict):
    """Return (gst_taxable: bool, exemption_applied: Decimal, taxable_portion: Decimal).

    The exemption is applied FIRST against the running gst_exemption_used,
    then the residual is the taxable_portion. Boundary: total_amount equal
    to remaining_exemption ⇒ taxable_portion 0 ⇒ gst_taxable False.
    """
    total = money(to_decimal(distribution["amount_principal"])
                  + to_decimal(distribution["amount_income"]))
    remaining_exemption = GST_EXEMPTION_LIMIT - to_decimal(trust["gst_exemption_used"])
    if remaining_exemption < 0:
        remaining_exemption = Decimal("0")

    if not beneficiary["is_skip_person"]:
        return False, Decimal("0"), Decimal("0")

    exemption_applied = min(total, remaining_exemption)
    taxable_portion = total - exemption_applied
    if taxable_portion < 0:
        taxable_portion = Decimal("0")
    gst_taxable = taxable_portion > 0
    return gst_taxable, exemption_applied, taxable_portion


def compute_gst_tax_amount(taxable_portion: Decimal) -> Decimal:
    """40% on the residual, rounded half-up to 2dp."""
    return money(taxable_portion * GST_TAX_RATE)


# ── DNI computation (scaffold §1.3 dni_computation) ──────────────────────────


def compute_dni(transactions_in_year):
    """Aggregate income & expense buckets and return (dni, buckets dict).

    `transactions_in_year` is any iterable of transaction dicts whose
    transaction_date falls inside the TaxYear's inclusive interval.

    Returns:
        dni: Decimal (already quantized to 2dp)
        buckets: dict with keys ordinary_income, interest_income,
                 dividend_income, capital_gain (each Decimal, NOT rounded;
                 used for character-share pro-rata).
    """
    ordinary = Decimal("0")
    interest = Decimal("0")
    dividend = Decimal("0")
    capital_gain = Decimal("0")
    admin_expense = Decimal("0")
    invest_expense = Decimal("0")

    for tx in transactions_in_year:
        amt = to_decimal(tx["amount"])
        t = tx["txn_type"]
        if t == "INCOME_ORDINARY":
            ordinary += amt
        elif t == "INCOME_INTEREST":
            interest += amt
        elif t == "INCOME_DIVIDEND":
            dividend += amt
        elif t == "INCOME_CAPITAL_GAIN":
            if tx["principal_or_income"] == "INCOME":
                capital_gain += amt
        elif t == "EXPENSE_ADMINISTRATIVE":
            admin_expense += amt
        elif t == "EXPENSE_INVESTMENT":
            invest_expense += amt

    gross_income = ordinary + interest + dividend + capital_gain
    deductible_expense = admin_expense + invest_expense
    raw_dni = gross_income - deductible_expense
    if raw_dni < 0:
        raw_dni = Decimal("0")
    dni = money(raw_dni)

    return dni, {
        "ordinary_income": ordinary,
        "interest_income": interest,
        "dividend_income": dividend,
        "capital_gain": capital_gain,
    }


# ── Trust taxable income (scaffold §1.3 trust_taxable_income_computation) ────


def compute_trust_taxable_income(trust: dict, dni: Decimal, executed_income_distributions_sum: Decimal) -> Decimal:
    if trust["grantor_tax_status"] == "GRANTOR":
        return Decimal("0.00")
    raw = to_decimal(dni) - to_decimal(executed_income_distributions_sum)
    if raw < 0:
        raw = Decimal("0")
    return money(raw)


# ── Trust income tax (scaffold §1.3 trust_income_tax_computation) ────────────


def compute_trust_income_tax(trust_taxable_income: Decimal) -> Decimal:
    """Marginal tiers, single rounding pass at the end (scaffold-pinned)."""
    taxable = to_decimal(trust_taxable_income)
    if taxable <= 0:
        return Decimal("0.00")
    tax = Decimal("0")
    remaining = taxable
    prev_top = Decimal("0")
    for (lo, hi, rate) in TRUST_TAX_BRACKETS:
        if remaining <= 0:
            break
        if hi is None:
            band_taxable = remaining
        else:
            band_width = hi - lo
            band_taxable = min(remaining, band_width)
        if band_taxable <= 0:
            break
        tax += band_taxable * rate
        remaining -= band_taxable
        prev_top = hi if hi is not None else prev_top
    # Pinned: rounding applied ONCE at the end of accumulation.
    return money(tax)


# ── K-1 DNI allocation waterfall (scaffold §1.3 k1_dni_allocation) ───────────


def compute_k1_shares(
    dni: Decimal,
    buckets: dict,
    beneficiaries_with_tier: list,
    executed_income_per_beneficiary: dict,
    largest_distribution_type_per_beneficiary: dict,
):
    """Waterfall + character split per scaffold-pinned order.

    Args:
        dni: TaxYear.dni (Decimal, 2dp).
        buckets: character composition from compute_dni (Decimals).
        beneficiaries_with_tier: list of (beneficiary_id, distribution_tier).
        executed_income_per_beneficiary: {beneficiary_id: Decimal(amount_income sum)}.
        largest_distribution_type_per_beneficiary: {beneficiary_id: distribution_type
            of that beneficiary's largest EXECUTED distribution in the year}.

    Returns:
        {beneficiary_id: {
            "b_share": Decimal (rounded to 2dp),
            "ordinary_income_share": Decimal,
            "interest_income_share": Decimal,
            "dividend_income_share": Decimal,
            "capital_gain_share": Decimal,
        }}
    """
    dni = to_decimal(dni)
    result = {}
    if dni <= 0:
        # Zero DNI ⇒ every share is 0.00 (boundary §3.7).
        for bid, _tier in beneficiaries_with_tier:
            result[bid] = {
                "b_share": Decimal("0.00"),
                "ordinary_income_share": Decimal("0.00"),
                "interest_income_share": Decimal("0.00"),
                "dividend_income_share": Decimal("0.00"),
                "capital_gain_share": Decimal("0.00"),
            }
        return result

    # Step 1-2: tier totals.
    tier1_ids = [bid for bid, t in beneficiaries_with_tier if t == "TIER_1"]
    tier2_ids = [bid for bid, t in beneficiaries_with_tier if t == "TIER_2"]
    tier1_total = sum((executed_income_per_beneficiary.get(bid, Decimal("0")) for bid in tier1_ids), Decimal("0"))
    tier2_total = sum((executed_income_per_beneficiary.get(bid, Decimal("0")) for bid in tier2_ids), Decimal("0"))

    # Step 3-5: DNI tier allocations.
    dni_to_tier1 = min(dni, tier1_total)
    dni_remaining = dni - dni_to_tier1
    dni_to_tier2 = min(dni_remaining, tier2_total)

    # Step 6-7: pre-character share per beneficiary.
    pre_share = {}
    for bid in tier1_ids:
        amt = executed_income_per_beneficiary.get(bid, Decimal("0"))
        if tier1_total > 0:
            pre_share[bid] = (amt / tier1_total) * dni_to_tier1
        else:
            pre_share[bid] = Decimal("0")
    for bid in tier2_ids:
        amt = executed_income_per_beneficiary.get(bid, Decimal("0"))
        if tier2_total > 0:
            pre_share[bid] = (amt / tier2_total) * dni_to_tier2
        else:
            pre_share[bid] = Decimal("0")

    # Character split. Per-beneficiary B_share is rounded FIRST, then the four
    # character shares pro-rated; the largest bucket absorbs any 0.01 remainder.
    for bid, _tier in beneficiaries_with_tier:
        raw_b = pre_share.get(bid, Decimal("0"))
        b_share = money(raw_b)

        # Character ratios from the gross DNI character composition.
        # Note: divide by DNI (a 2dp quantity); use the raw character buckets.
        # The four shares must sum exactly to b_share — absorb remainder into
        # the largest character bucket.
        char_buckets = {
            "ordinary_income_share": buckets["ordinary_income"],
            "interest_income_share": buckets["interest_income"],
            "dividend_income_share": buckets["dividend_income"],
            "capital_gain_share": buckets["capital_gain"],
        }
        # capital_gain_share is only populated when this beneficiary's largest
        # distribution in the year was TERMINATING (PRD §3.7).
        ldt = largest_distribution_type_per_beneficiary.get(bid)
        if ldt != "TERMINATING":
            char_buckets["capital_gain_share"] = Decimal("0")

        # Compute each character share = b_share * (bucket / dni), rounded 2dp.
        char_shares = {}
        for cname, cval in char_buckets.items():
            raw = b_share * (cval / dni)
            char_shares[cname] = money(raw)

        # Adjust so they sum to b_share — push the 0.01 delta into the bucket
        # with the largest raw character value. If they all are zero (DNI==0
        # case is already handled) we still output zeros.
        total = sum(char_shares.values(), Decimal("0"))
        delta = b_share - total
        if delta != 0:
            # Find the character with the largest raw character value.
            largest = max(
                char_buckets.items(),
                key=lambda kv: (kv[1], kv[0]),  # ties broken by name for determinism
            )[0]
            char_shares[largest] = money(char_shares[largest] + delta)

        result[bid] = {
            "b_share": b_share,
            "ordinary_income_share": char_shares["ordinary_income_share"],
            "interest_income_share": char_shares["interest_income_share"],
            "dividend_income_share": char_shares["dividend_income_share"],
            "capital_gain_share": char_shares["capital_gain_share"],
        }
    return result

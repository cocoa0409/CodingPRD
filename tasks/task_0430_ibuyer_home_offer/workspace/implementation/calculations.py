"""The 6 calculation rules (SCAFFOLD.yaml §1.3 / PRD §3).

All amounts use Decimal-backed round-half-up at 2 dp (money.round2). Rounding
order relative to summation/multiplication is pinned exactly as specified — see
each function's docstring.
"""

from constants import EST_CONCESSION_PCT, LEASEBACK_DAILY_PCT
from db import store
from money import D, round2


# ---------------------------------------------------------------------------
# 1. avm_valuation
# ---------------------------------------------------------------------------
def compute_avm(comp_median_value, market_trend_pct):
    """avm_value = round(comp_median_value * (1 + market_trend_pct), 2)."""
    return round2(D(comp_median_value) * (D(1) + D(market_trend_pct)))


def compute_revised_avm(avm_value_snapshot, retrade_amount):
    """revised_avm_value = round(avm_value_snapshot - retrade_amount, 2)."""
    return round2(D(avm_value_snapshot) - D(retrade_amount))


def effective_avm(property_record, offer_record):
    """revised_avm_value if a re-trade applied (non-null), else avm_value_snapshot."""
    revised = property_record.get("revised_avm_value")
    if revised is not None:
        return revised
    return offer_record["avm_value_snapshot"]


# ---------------------------------------------------------------------------
# 2. preliminary_net_proceeds  (provisional variant, at offer issuance)
# ---------------------------------------------------------------------------
def compute_service_fee(avm_basis, service_fee_pct):
    """service_fee = round(avm_basis * service_fee_pct, 2)."""
    return round2(D(avm_basis) * D(service_fee_pct))


def compute_estimated_concession(avm_value_snapshot):
    """estimated_concession = round(avm_value_snapshot * EST_CONCESSION_PCT, 2)."""
    return round2(D(avm_value_snapshot) * D(EST_CONCESSION_PCT))


def compute_preliminary_net_proceeds(avm_value_snapshot, service_fee, estimated_concession):
    """preliminary = round(snapshot - service_fee - estimated_concession, 2).

    Repair credit assumed 0, no leaseback at issuance.
    """
    return round2(D(avm_value_snapshot) - D(service_fee) - D(estimated_concession))


# ---------------------------------------------------------------------------
# 3. repair_credit_aggregation  (round-per-line THEN sum)
# ---------------------------------------------------------------------------
def compute_repair_credit(assessment_id):
    """Sum rounded_amount over FINALIZED assessment's repair line items.

    Each line's rounded_amount is already round(estimate_amount, 2) (pinned at
    line creation). We sum those pinned cents, then round the total to 2 dp.
    """
    total = D(0)
    for line in store.repair_line_items.values():
        if line["assessment_id"] == assessment_id:
            total += D(line["rounded_amount"])
    return round2(total)


# ---------------------------------------------------------------------------
# 4. leaseback_charge  (round daily FIRST, THEN multiply)
# ---------------------------------------------------------------------------
def compute_leaseback_daily_rate(eff_avm):
    """leaseback_daily_rate = round(effective_avm * LEASEBACK_DAILY_PCT, 2)."""
    return round2(D(eff_avm) * D(LEASEBACK_DAILY_PCT))


def compute_leaseback_total(daily_rate, leaseback_days):
    """leaseback_total = round(daily_rate * leaseback_days, 2)."""
    return round2(D(daily_rate) * D(leaseback_days))


# ---------------------------------------------------------------------------
# 5. final_net_proceeds  (chronological / final variant)
# ---------------------------------------------------------------------------
def compute_final_net_proceeds(eff_avm, service_fee_eff, final_concession,
                               repair_credit, leaseback_total):
    """final = round(eff_avm - service_fee_eff - final_concession
                     - repair_credit - leaseback_total, 2)."""
    return round2(
        D(eff_avm)
        - D(service_fee_eff)
        - D(final_concession)
        - D(repair_credit)
        - D(leaseback_total)
    )


# ---------------------------------------------------------------------------
# 6. resale_spread  (projected at listing, net at sale)
# ---------------------------------------------------------------------------
def compute_resale_commission(price, commission_pct):
    """commission = round(price * resale_commission_pct, 2)."""
    return round2(D(price) * D(commission_pct))


def compute_resale_spread(price, acquisition_cost, repair_credit, commission):
    """spread = round(price - acquisition_cost - repair_credit - commission, 2)."""
    return round2(D(price) - D(acquisition_cost) - D(repair_credit) - D(commission))

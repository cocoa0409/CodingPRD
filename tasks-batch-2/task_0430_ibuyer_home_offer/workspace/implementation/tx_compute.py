"""Transaction derived-field reconciliation (PRD §2.6, §3.5-§3.7).

Centralizes the final-variant cascade: effective AVM -> effective service fee
-> leaseback daily rate / total -> final_net_proceeds. Called from schedule-close,
retrade, and close so all derived fields stay consistent within the request.
"""

from calculations import (
    compute_final_net_proceeds,
    compute_leaseback_daily_rate,
    compute_leaseback_total,
    compute_service_fee,
    effective_avm,
)
from db import store


def recompute_transaction_financials(tx):
    """Recompute leaseback_daily_rate, leaseback_total, final_net_proceeds in place.

    Uses the current effective AVM of the property/offer (revised if a re-trade
    applied, else the offer snapshot). service_fee uses the offer's
    service_fee_pct on the effective AVM. final_concession and repair_credit are
    read from the transaction's current state.
    """
    offer = store.offers[tx["offer_id"]]
    prop = store.properties[tx["property_id"]]

    eff_avm = effective_avm(prop, offer)

    service_fee_eff = compute_service_fee(eff_avm, offer["service_fee_pct"])

    daily_rate = compute_leaseback_daily_rate(eff_avm)
    leaseback_total = compute_leaseback_total(daily_rate, tx["leaseback_days"])

    final = compute_final_net_proceeds(
        eff_avm,
        service_fee_eff,
        tx["final_concession"],
        tx["repair_credit"],
        leaseback_total,
    )

    tx["leaseback_daily_rate"] = daily_rate
    tx["leaseback_total"] = leaseback_total
    tx["final_net_proceeds"] = final
    return tx

"""LP statement / K-1 figures (PRD §3.8, compute_lp_irr_summary).

paid_in       = commitment.drawn_cents
distributions = commitment.distributed_cents
nav           = round_half_up(fund_nav * committed_cents / fund.total_committed_cents)
dpi_bps       = distributions * 10000 / paid_in       (0 when paid_in == 0)
tvpi_bps      = (distributions + nav) * 10000 / paid_in (0 when paid_in == 0)
K-1 lines     = sum of LP's distribution-allocation amounts on PAID events by type
ubti_flag     = lp.is_tax_exempt AND k1_income > 0
"""
from decimal import Decimal

import db
from services import derive


def build_statement(commitment):
    fund = db.funds[commitment["fund_id"]]
    paid_in = derive.commitment_drawn(commitment)
    distributions = derive.commitment_distributed(commitment)

    fund_nav = derive.fund_nav(fund["id"])
    total_committed = derive.fund_total_committed(fund["id"])
    if total_committed > 0:
        nav = derive.round_half_up(
            Decimal(fund_nav) * Decimal(commitment["committed_cents"]) / Decimal(total_committed)
        )
    else:
        nav = 0

    # Ratios are integer basis points; both zero when paid_in == 0.
    # Integer (truncating) division on the basis-point figure.
    if paid_in > 0:
        dpi_bps = (distributions * 10000) // paid_in
        tvpi_bps = ((distributions + nav) * 10000) // paid_in
    else:
        dpi_bps = 0
        tvpi_bps = 0

    # K-1 line items: sum amount_cents on PAID events by distribution_type for
    # this commitment.
    cid = commitment["id"]
    k1_roc = 0
    k1_gain = 0
    k1_income = 0
    for a in db.distribution_allocations.values():
        if a["commitment_id"] != cid:
            continue
        event = db.distribution_events.get(a["distribution_event_id"])
        if not event or event["status"] != "PAID":
            continue
        dtype = event["distribution_type"]
        if dtype == "RETURN_OF_CAPITAL":
            k1_roc += a["amount_cents"]
        elif dtype == "CAPITAL_GAIN":
            k1_gain += a["amount_cents"]
        elif dtype == "INCOME":
            k1_income += a["amount_cents"]

    lp = db.limited_partners[commitment["lp_id"]]
    ubti_flag = bool(lp["is_tax_exempt"]) and k1_income > 0

    return {
        "paid_in_cents": paid_in,
        "distributed_cents": distributions,
        "nav_cents": nav,
        "dpi_bps": dpi_bps,
        "tvpi_bps": tvpi_bps,
        "k1_return_of_capital_cents": k1_roc,
        "k1_capital_gain_cents": k1_gain,
        "k1_income_cents": k1_income,
        "ubti_flag": ubti_flag,
    }

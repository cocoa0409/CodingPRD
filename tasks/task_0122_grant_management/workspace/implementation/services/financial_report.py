"""FinancialReport computations (PRD §2.5, §3.6)."""
from decimal import Decimal

import db
from routes.indirect_cost_rates import active_rate_for_award
from services import common as c

SUBAWARD_EXCLUSION_CAP_CENTS = 2500000   # $25,000 per-subaward MTDC exclusion
DE_MINIMIS_RATE = Decimal("0.10")

# Direct-cost line categories: any RestrictedFund category except INDIRECT.
DIRECT_COST_CATEGORIES = {
    "PERSONNEL", "EQUIPMENT", "TRAVEL", "SUPPLIES", "SUBAWARD_PASS_THROUGH",
}


def approved_direct_total(report):
    """report_approval_totals: exact sum of direct_cost_lines amounts (PRD §3.6)."""
    return sum(line["amount_cents"] for line in report["direct_cost_lines"])


def compute_indirect_cost(report, award):
    """indirect_cost_recovery (PRD §3.6).

    Base over the award's single ACTIVE IndirectCostRate. MTDC excludes EQUIPMENT
    entirely and the portion of each SUBAWARD_PASS_THROUGH line over the cap; TDC
    uses the raw direct total. The rate is applied ONCE to the summed base and
    rounded half-up. With no ACTIVE rate, indirect recovery is 0.
    """
    rate = active_rate_for_award(award["id"])
    if rate is None:
        return 0

    lines = report["direct_cost_lines"]
    direct_total = sum(line["amount_cents"] for line in lines)

    if rate["base_type"] == "MTDC":
        equipment_excl = sum(
            line["amount_cents"] for line in lines if line["category"] == "EQUIPMENT"
        )
        subaward_excess = sum(
            max(0, line["amount_cents"] - SUBAWARD_EXCLUSION_CAP_CENTS)
            for line in lines if line["category"] == "SUBAWARD_PASS_THROUGH"
        )
        base = direct_total - equipment_excl - subaward_excess
    else:  # TDC
        base = direct_total

    if rate["rate_type"] == "NEGOTIATED":
        rate_value = Decimal(str(rate["negotiated_rate"]))
    else:  # DE_MINIMIS
        rate_value = DE_MINIMIS_RATE

    # SUM-THEN-ROUND: apply once to the whole base.
    return c.round_half_up(Decimal(int(base)) * rate_value)


def compute_reimbursable(report, award, approved_direct_cents):
    """reimbursement_reconciliation (PRD §3.6). INTERIM = provisional;
    FINAL = cumulative, capped, netted."""
    pct = award["federal_share_pct"]
    if report["report_basis"] == "INTERIM":
        # Provisional: federal share of this period's approved direct only.
        return c.apply_rate(approved_direct_cents, pct)

    # FINAL (closeout): cumulative across ACCEPTED reports including this one.
    cum_direct = approved_direct_cents
    for r in db.financial_reports.values():
        if (r["award_id"] == award["id"] and r["status"] == "ACCEPTED"
                and r["id"] != report["id"]):
            cum_direct += r.get("approved_direct_cents", 0)

    cum_federal = c.apply_rate(cum_direct, pct) - report.get("disallowed_cents", 0)
    capped = min(award["federal_ceiling_cents"], cum_federal)
    return capped - award["federal_drawn_cents"]

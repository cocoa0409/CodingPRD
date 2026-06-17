"""Deal computed-field reconciliation and trade aggregation helpers.

These functions write the deal's `source: computed` fields onto the record.
They do NOT bump version themselves — the caller decides when a write counts as
a mutation (PRD §2.5). `recompute_quote` is the desk re-quote (taxes, amount
financed, gross FRONT/BACK, estimated payment).
"""
import db
from services import calc


def attached_trade(deal):
    return calc._attached_trade(deal)


def sync_trade_fields(deal):
    """Refresh trade_allowance_cents / trade_equity_cents from the attached trade."""
    trade = attached_trade(deal)
    if trade is None:
        deal["trade_allowance_cents"] = 0
        deal["trade_equity_cents"] = 0
    else:
        deal["trade_allowance_cents"] = trade["allowance_cents"]
        deal["trade_equity_cents"] = trade["gross_equity_cents"]


def recompute_quote(deal):
    """Recompute every derived monetary field on a deal (the full desk re-quote)."""
    sync_trade_fields(deal)
    deal["total_tax_cents"] = calc.deal_tax(deal)
    deal["fi_products_total_cents"] = calc.fi_products_total(deal)
    deal["amount_financed_cents"] = calc.amount_financed(deal)
    deal["front_gross_cents"] = calc.front_gross(deal)
    deal["back_gross_cents"] = calc.back_gross(deal)
    deal["estimated_payment_cents"] = calc.estimate_payment(deal)


def recompute_money_only(deal):
    """Recompute totals WITHOUT touching estimated_payment (used after product/
    trade/incentive changes — but estimated payment also depends on amount
    financed, so we keep it in sync too)."""
    sync_trade_fields(deal)
    deal["total_tax_cents"] = calc.deal_tax(deal)
    deal["fi_products_total_cents"] = calc.fi_products_total(deal)
    deal["amount_financed_cents"] = calc.amount_financed(deal)
    deal["front_gross_cents"] = calc.front_gross(deal)
    deal["back_gross_cents"] = calc.back_gross(deal)
    deal["estimated_payment_cents"] = calc.estimate_payment(deal)

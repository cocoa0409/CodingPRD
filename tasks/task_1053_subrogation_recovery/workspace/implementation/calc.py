"""Calculation rules (§1.3 / PRD §2.5, §3.2, §3.6, §3.8).

All money is integer cents; every division rounds half-up to whole cents.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """value is a Decimal; return the nearest integer, halves rounding up."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def liability_share_cents(total_damages_cents, liability_pct):
    val = Decimal(total_damages_cents) * Decimal(str(liability_pct)) / Decimal(100)
    return round_half_up(val)


def provisional_recoverable_cents(claim, adverse):
    """Smallest of the liability share, the adverse policy limit, and base exposure."""
    base_exposure = claim["paid_loss_cents"] + claim["deductible_cents"]
    share = liability_share_cents(claim["total_damages_cents"], claim["liability_pct"])
    return min(share, adverse["policy_limit_cents"], base_exposure)


def commission_on(amount_cents, commission_rate_bps):
    val = Decimal(commission_rate_bps) * Decimal(amount_cents) / Decimal(10000)
    return round_half_up(val)


def commission_due_cents(claim, carrier):
    """Commission owed on a recovered claim under the carrier's basis (§3.8)."""
    gross = claim["final_recovered_cents"]
    if carrier["commission_basis"] == "GROSS":
        return commission_on(gross, carrier["commission_rate_bps"])
    net = gross - claim["deductible_reimbursed_cents"]
    return commission_on(net, carrier["commission_rate_bps"])

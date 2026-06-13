"""Order pricing + net-earnings (provisional/final), maturation.

PRD §3.4 (pricing), §3.5 (maturation). Calculation: order_net_earnings.
Round each fee component to whole cents BEFORE summation (PRD §2.5, §3.4).
"""
from decimal import Decimal

from common import round_half_up


def compute_components(gross_amount_cents, schedule):
    """Return (commission, platform_fee, processing_fee) — each whole cents,
    rounded per-component (PRD §3.4)."""
    commission = round_half_up(
        Decimal(gross_amount_cents) * Decimal(schedule["commission_bps"]) / Decimal(10000)
    )
    platform_fee = schedule["fixed_fee_cents"]
    processing = round_half_up(
        Decimal(gross_amount_cents) * Decimal(schedule["payment_processing_bps"]) / Decimal(10000)
    ) + schedule["payment_processing_fixed_cents"]
    return commission, platform_fee, processing


def provisional_net(gross_amount_cents, commission, platform_fee, processing):
    """Provisional net = gross - commission - platform - processing (no refund)."""
    return gross_amount_cents - commission - platform_fee - processing


def final_net(order, schedule):
    """Final net at maturation (PRD §3.5):

    final = provisional_net - net_share_of_refund
    net_share_of_refund = refunded_amount_cents
        - round_half_up(refunded_amount_cents * commission_bps / 10000)
    Processing & platform fees are NOT returned."""
    gross = order["gross_amount_cents"]
    provisional = provisional_net(
        gross, order["commission_cents"], order["platform_fee_cents"],
        order["processing_fee_cents"],
    )
    refunded = order["refunded_amount_cents"]
    if refunded <= 0:
        return provisional
    returned_commission = round_half_up(
        Decimal(refunded) * Decimal(schedule["commission_bps"]) / Decimal(10000)
    )
    net_share_of_refund = refunded - returned_commission
    return provisional - net_share_of_refund

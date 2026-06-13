"""Withdrawal fee computation (scaffold withdrawal_fee).

INSTANT: pct = ceil(gross * 175 / 10000); fee = min(max(pct, 25), 1500); floor then cap.
STANDARD: fee = 0.
"""
import math

INSTANT_FEE_RATE_BPS = 175
INSTANT_FEE_FLOOR_CENTS = 25
INSTANT_FEE_CAP_CENTS = 1500


def compute_fee(gross_amount_cents, speed):
    """Return (fee_cents, net_amount_cents)."""
    if speed == "STANDARD":
        fee = 0
    else:  # INSTANT
        pct_fee = math.ceil(gross_amount_cents * INSTANT_FEE_RATE_BPS / 10000)
        fee = max(pct_fee, INSTANT_FEE_FLOOR_CENTS)   # floor first
        fee = min(fee, INSTANT_FEE_CAP_CENTS)         # cap after
    net = gross_amount_cents - fee
    return fee, net

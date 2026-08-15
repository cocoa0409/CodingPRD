"""Reconnection fee computation (calc: reconnection_fee_computation).

PINNED rounding order: each component is rounded to cents BEFORE summation.
Summing raw components and rounding once is explicitly rejected (PRD §3.7).
"""

from fractions import Fraction

from services.common import round_half_up, active_enrollment, active_life_threatening_cert

BASE_FEE_CENTS = 3325
AFTER_HOURS_RATE = Fraction(1, 2)
FEE_WAIVER_PCT = {"TIER_1": 100, "TIER_2": 30, "TIER_3": 25, "NONE": 0}
DEPOSIT_REQUIRED_CENTS = 7500


def snapshot_fee_schedule(account):
    """At shutoff execution: compute and store base, surcharge, deposit top-up."""
    enrollment = active_enrollment(account["id"])
    tier = enrollment["tier"] if enrollment else "NONE"
    w = FEE_WAIVER_PCT[tier]
    lt_cert = active_life_threatening_cert(account["id"]) is not None
    if lt_cert:
        w = 100
    # component 1: discounted base fee
    base_disc = round_half_up(Fraction(BASE_FEE_CENTS) * Fraction(100 - w, 100))
    # component 2: after-hours surcharge, two pinned rounding steps
    sur_gross = round_half_up(Fraction(BASE_FEE_CENTS) * AFTER_HOURS_RATE)
    sur_disc = round_half_up(Fraction(sur_gross) * Fraction(100 - w, 100))
    # component 3: deposit top-up
    if w == 100 or lt_cert:
        deposit_topup = 0
    else:
        deposit_topup = max(0, DEPOSIT_REQUIRED_CENTS - account["deposit_held_cents"])
    account["reconnection_fee_base_cents"] = base_disc
    account["reconnection_fee_surcharge_cents"] = sur_disc
    account["reconnection_deposit_topup_cents"] = deposit_topup
    account["reconnection_fee_due_cents"] = base_disc + deposit_topup
    account["reconnection_surcharge_applied"] = False

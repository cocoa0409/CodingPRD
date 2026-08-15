"""Shared gift-vehicle validation + economics (PRD 3.2/3.3)."""
from calc import (
    annual_annuity,
    exhaustion_limit_cents,
    lives_factor,
    pv_of_annuity,
)
from errors import ApiError


def check_vehicle_fields(vehicle_type, payload, partial=False):
    """Vehicle/field consistency (validation 12) + payout bounds (13).

    partial=True is used by amend: only fields actually supplied are checked,
    against the agreement's stored vehicle_type.
    """
    payout = payload.get("payout_rate_bps")
    lives = payload.get("lives", 1)
    age1 = payload.get("annuitant_1_age")
    age2 = payload.get("annuitant_2_age")

    if vehicle_type == "BEQUEST":
        if payout is not None:
            raise ApiError(
                "ERR_BEQUEST_VEHICLE_MISMATCH",
                422,
                "BEQUEST must not carry payout_rate_bps",
            )
    else:
        if not partial or payout is not None or age1 is None:
            if payout is None or age1 is None:
                raise ApiError(
                    "ERR_BEQUEST_VEHICLE_MISMATCH",
                    422,
                    "Annuity vehicles require payout_rate_bps and annuitant_1_age",
                )
        if lives == 2 and age2 is None:
            raise ApiError(
                "ERR_BEQUEST_VEHICLE_MISMATCH",
                422,
                "lives=2 requires annuitant_2_age",
            )
        if payout is not None and not (500 <= payout <= 5000):
            raise ApiError(
                "ERR_PAYOUT_RATE_OUT_OF_RANGE",
                422,
                "payout_rate_bps must be within [500, 5000]",
            )


def economics(vehicle_type, gift_amount_cents, payout_rate_bps, lives, age1, age2, rate_bps):
    """Return (annual_annuity_cents, pv_cents, deduction_cents).

    BEQUEST: annual is None, pv is 0, deduction is the full gift amount.
    """
    if vehicle_type == "BEQUEST":
        return None, 0, gift_amount_cents
    annual = annual_annuity(gift_amount_cents, payout_rate_bps)
    factor = lives_factor(age1, age2, lives, rate_bps)
    pv = pv_of_annuity(annual, factor)
    deduction = max(0, gift_amount_cents - pv)
    return annual, pv, deduction


def check_remainder_test(vehicle_type, gift_amount_cents, deduction_cents):
    """10% remainder test (validation 8), inclusive boundary; annuity vehicles only."""
    if vehicle_type == "BEQUEST":
        return
    if deduction_cents * 10 < gift_amount_cents:
        raise ApiError(
            "ERR_REMAINDER_TEST_FAILED",
            422,
            "Charitable deduction below the 10% remainder floor",
        )


def check_exhaustion_test(vehicle_type, gift_amount_cents, pv_cents):
    """CRT_ANNUITY only (validation 9): pv <= round_half_up(gift * 8500/10000)."""
    if vehicle_type != "CRT_ANNUITY":
        return
    if pv_cents > exhaustion_limit_cents(gift_amount_cents):
        raise ApiError(
            "ERR_EXHAUSTION_TEST_FAILED",
            422,
            "PV of annuity exceeds 85% of the gift amount",
        )

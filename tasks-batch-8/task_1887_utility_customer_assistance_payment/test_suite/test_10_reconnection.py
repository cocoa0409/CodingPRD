"""Reconnection fee schedule: pinned per-component rounding and the one-time
after-hours surcharge fold-in."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_disconnected_account, get_account,
    TEST_USERS, INCOME_TIER_2,
)

FIELDCREW = TEST_USERS["fieldcrew_headers"]


def _tier2_disconnected(api):
    """TIER_2-enrolled account (deposit fully held at 7500), aged 120000
    arrearage, driven to DISCONNECTED by an executed order at 2026-09-30.
    Waiver 30% -> base round(3325*0.7)=2328; surcharge round(round(3325*0.5)
    *0.7)=round(1663*0.7)=1164; top-up 0."""
    account, _order = setup_disconnected_account(
        arrearage_cents=120_000, with_enrollment_income=INCOME_TIER_2,
        deposit_held_cents=7_500, service_address="55 Pine Rd")
    return account


def test_execution_snapshots_fee_components_each_rounded(api):
    """PRD §3.7: "Three components are then computed, each rounded half-up to cents
    *before* any summation: the discounted base fee is the standard $33.25 base
    multiplied by the non-waived percentage, stored as `reconnection_fee_base_cents`;
    the after-hours surcharge is precomputed in two steps — first the gross
    surcharge, the $33.25 base multiplied by the 50-percent after-hours rate and
    rounded, then that gross multiplied by the non-waived percentage and rounded —
    stored as `reconnection_fee_surcharge_cents`; and the deposit top-up, stored as
    `reconnection_deposit_topup_cents`, is zero when the waiver is 100 percent or a
    `LIFE_THREATENING` certificate is active, and otherwise the shortfall between
    the $75.00 deposit requirement and the account's `deposit_held_cents`, never
    below zero."
    PRD §3.7: "The amount blocking reconnection, `reconnection_fee_due_cents`, is
    initially the discounted base plus the deposit top-up."

    Design: Difficulty/combinatorial_formula/reconnection_fee_nested_rounding
    """
    account = _tier2_disconnected(api)
    read = get_account(account["id"])
    assert read["service_status"] == "DISCONNECTED"
    assert read["reconnection_fee_base_cents"] == 2_328      # round_half_up(3325*0.7)
    assert read["reconnection_fee_surcharge_cents"] == 1_164  # round(round(3325*.5)*.7)
    assert read["reconnection_deposit_topup_cents"] == 0     # 7500 held covers 7500
    assert read["reconnection_fee_due_cents"] == 2_328       # base + top-up
    assert read["reconnection_surcharge_applied"] is False


def test_after_hours_fold_in_happens_once_before_fee_check(api):
    """PRD §3.7: "An optional `after_hours` flag on the request folds the
    precomputed surcharge into `reconnection_fee_due_cents` — exactly once, and
    only while `reconnection_surcharge_applied` is still false, at which point that
    flag flips to true. With any surcharge folded in, the fee due must stand at
    exactly zero, ordinarily by having been paid down through the payment waterfall
    of §3.5; a positive remainder refuses the reconnect with
    `ERR_RECONNECTION_FEE_UNPAID` (HTTP 422)."
    PRD §3.7: "Summing the raw components and rounding once at the end is
    explicitly rejected — it produces different cents."

    Design: Difficulty/combinatorial_formula/reconnection_fee_nested_rounding
    """
    account = _tier2_disconnected(api)
    resp = api.reconnect_account(account["id"], {"after_hours": True}, FIELDCREW)
    validate_error(resp, ApiErrorId.ERR_RECONNECTION_FEE_UNPAID)
    read = get_account(account["id"])
    # Pinned per-component order: 2328 + 1164 = 3492 (NOT the sum-then-round 3491).
    assert read["reconnection_fee_due_cents"] == 3_492
    assert read["reconnection_surcharge_applied"] is True
    assert read["service_status"] == "DISCONNECTED"

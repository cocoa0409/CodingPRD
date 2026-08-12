"""Hardship gross-up economics: NET vs GROSS variants, fee-tier boundary,
pinned evaluation order (PRD §3.9)."""
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    TEST_USERS,
    create_hardship_request_payload,
    create_plan_payload,
    enroll_participant,
    make_participant_headers,
    setup_plan_and_participant,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: hardship_gross_up_net_vs_gross_variants
# ---------------------------------------------------------------------------


def test_hardship_gross_up_net_variant_arithmetic(api):
    """PRD §3.9: "Under the `NET` semantics — the participant must receive
    exactly `amount_cents` after withholding and fee — the provisional gross is
    `amount_cents` divided by the difference between one and w; `fee_cents` is
    then 5,000 cents when that provisional gross is at most 1,000,000 cents
    (ten thousand dollars) and 7,500 cents above it; `gross_withdrawal_cents`
    is the sum of `amount_cents` and `fee_cents`, divided by the difference
    between one and w, rounded half up to a whole cent; `withholding_cents` is
    the gross multiplied by w, rounded half up; and `net_disbursed_cents` is
    the gross minus the withholding minus the fee."

    Design: Difficulty/dual_variant_calc/hardship_gross_up_net_vs_gross_variants
    """
    _, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="MEDICAL", amount_cents=800_000, amount_semantics="NET"
        ),
        make_participant_headers(participant["id"]),
    )
    h = validate_success(res, 201)
    assert h["gross_withdrawal_cents"] == 1_006_250
    assert h["withholding_cents"] == 201_250
    assert h["fee_cents"] == 5_000
    assert h["net_disbursed_cents"] == 800_000


def test_hardship_gross_up_gross_variant_arithmetic(api):
    """PRD §3.9: "Under the default `GROSS` semantics — `amount_cents` is the
    total distribution — `gross_withdrawal_cents` equals `amount_cents`; the
    same tier rule sets `fee_cents` at 5,000 cents when the gross is at most
    1,000,000 cents and 7,500 cents above it; `withholding_cents` is the gross
    multiplied by w, rounded half up; and `net_disbursed_cents` is again the
    gross minus the withholding minus the fee. The same `amount_cents`
    therefore yields a larger `gross_withdrawal_cents` under `NET` than under
    `GROSS`."

    Design: Difficulty/dual_variant_calc/hardship_gross_up_net_vs_gross_variants
    """
    _, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="MEDICAL", amount_cents=800_000, amount_semantics="GROSS"
        ),
        make_participant_headers(participant["id"]),
    )
    h = validate_success(res, 201)
    assert h["gross_withdrawal_cents"] == 800_000
    assert h["withholding_cents"] == 160_000
    assert h["fee_cents"] == 5_000
    assert h["net_disbursed_cents"] == 635_000


# ---------------------------------------------------------------------------
# Difficulty: hardship_gross_up_pinned_evaluation_order
# ---------------------------------------------------------------------------


def test_hardship_gross_up_pinned_evaluation_order_high_tier(api):
    """PRD §3.9: "Creation also computes and stores the distribution's
    economics, in an evaluation order that is pinned because the fee tier
    depends on the gross and the gross depends on the fee". NET 800,001c pushes
    the provisional gross above 1,000,000c, so the 7,500c fee tier is selected
    before the final gross is computed.

    Design: Difficulty/combinatorial_formula/hardship_gross_up_pinned_evaluation_order
    """
    _, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="TUITION", amount_cents=800_001, amount_semantics="NET"
        ),
        make_participant_headers(participant["id"]),
    )
    h = validate_success(res, 201)
    assert h["fee_cents"] == 7_500
    assert h["gross_withdrawal_cents"] == 1_009_376
    assert h["withholding_cents"] == 201_875
    assert h["net_disbursed_cents"] == 800_001


def test_hardship_gross_up_pinned_evaluation_order_reconciles(api):
    """PRD §3.9: "`net_disbursed_cents` is the gross minus the withholding minus
    the fee." The pinned evaluation order reproduces the requested net exactly.

    Design: Difficulty/combinatorial_formula/hardship_gross_up_pinned_evaluation_order
    """
    _, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="TUITION", amount_cents=800_001, amount_semantics="NET"
        ),
        make_participant_headers(participant["id"]),
    )
    h = validate_success(res, 201)
    # Evaluation order reproduces the requested net exactly
    assert (
        h["gross_withdrawal_cents"] - h["withholding_cents"] - h["fee_cents"]
        == 800_001
    )


# ---------------------------------------------------------------------------
# Corner: hardship_fee_tier_boundary_at_provisional_gross
# ---------------------------------------------------------------------------


def test_hardship_fee_tier_boundary_at_provisional_gross_low(api):
    """PRD §3.9: "`fee_cents` is then 5,000 cents when that provisional gross is
    at most 1,000,000 cents (ten thousand dollars) and 7,500 cents above it" —
    the `at most` boundary is inclusive. NET 800,000c has provisional gross
    800,000 / 0.8 = 1,000,000c, exactly at the threshold, so fee = 5,000c.

    Design: Corner/calculations/hardship_fee_tier_boundary_at_provisional_gross
    """
    _, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="MEDICAL", amount_cents=800_000, amount_semantics="NET"
        ),
        make_participant_headers(participant["id"]),
    )
    h = validate_success(res, 201)
    assert h["fee_cents"] == 5_000
    assert h["gross_withdrawal_cents"] == 1_006_250


def test_hardship_fee_tier_boundary_at_provisional_gross_high(api):
    """PRD §3.9: "`fee_cents` is then 5,000 cents when that provisional gross is
    at most 1,000,000 cents (ten thousand dollars) and 7,500 cents above it."
    NET 800,001c has provisional gross 800,001 / 0.8 = 1,000,001.25c, crossing
    the threshold, so fee = 7,500c.

    Design: Corner/calculations/hardship_fee_tier_boundary_at_provisional_gross
    """
    _, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="MEDICAL", amount_cents=800_001, amount_semantics="NET"
        ),
        make_participant_headers(participant["id"]),
    )
    h = validate_success(res, 201)
    assert h["fee_cents"] == 7_500
    assert h["gross_withdrawal_cents"] == 1_009_376

"""Two multi-entity invariants that must hold exactly, with no rounding slack.

A draw reversal is an exact compensation: every figure the settlement moved
across the merchant, the loan account, the project and the milestone returns to
its pre-settlement value, even though the settlement wrote two independently
rounded amounts.  A consumer-favour chargeback is an exact partition: the claim
is split into three buckets that re-sum to the claim, and the same three figures
reappear as the ledger movements on the merchant.  Reversal restores; a
chargeback redistributes without restoring.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import (
    assert_chargeback_conserved,
    assert_fields,
    assert_unchanged,
    bps_of,
    ratio_bps,
)
from test_helpers.test_users import AGENT_HEADERS, SECOND_AGENT_HEADERS

#: 3500000 contract * 3000 bps verified release on milestone 1.
DRAW_ONE_CENTS = 1050000

#: The negotiated rate on the scenario's ACTIVE enrollment.
EFFECTIVE_DISCOUNT_BPS = C.NEGOTIATED_DISCOUNT_BPS  # 449

#: 1050000 * 449 bps, rounded half up, with no speed surcharge and no volume credit.
DRAW_ONE_DISCOUNT_CENTS = 47145

#: STANDARD risk tier reserve target of 400 bps on a trailing volume of 1050000,
#: which is below the 500 bps base withholding and far below the per-draw ceiling.
DRAW_ONE_HOLDBACK_CENTS = 42000

#: 1050000 - 47145 - 42000.
DRAW_ONE_NET_CENTS = 960855


def _settled_single_draw(api):
    """One verified milestone carrying a single settled 1050000 draw, plus the pre-draw reads."""
    scenario = S.project_with_milestones(api, releases=(3000,), verify=(0,))
    before = {
        "merchant": S.read_merchant(api, scenario.merchant_id),
        "loan": S.read_loan(api, scenario.loan_id),
        "project": S.read_project(api, scenario.project_id),
    }
    S.request_draw(api, scenario, DRAW_ONE_CENTS, 0, "STANDARD_3DAY")
    settled = S.settle_draw(api, scenario)
    return scenario, before, settled


def _reverse(api, draw_id, reason_code="MERCHANT_BILLING_ERROR"):
    """Reverse a settled draw as the servicing agent and return the reversed row."""
    return validate_success(
        api.reverse_funding_draw(
            draw_id, F.reversal_payload(reason_code), AGENT_HEADERS
        )
    )


def test_settlement_writes_two_independently_rounded_amounts(api):
    """The settlement being compensated is not trivial: it rounds a discount and a holdback separately.

    PRD: "Sixth, `holdback_withheld_cents` is the smallest of the base withholding, the gap and the per-draw ceiling, taken exactly with no further rounding."

    Design: Difficulty/compensating_invariant/draw_reversal_restores_the_funding_ledger_with_no_drift
    """
    _scenario, _before, settled = _settled_single_draw(api)

    assert_fields(
        settled,
        status="SETTLED",
        effective_discount_bps=EFFECTIVE_DISCOUNT_BPS,
        volume_tier_credit_bps=0,
        merchant_discount_cents=DRAW_ONE_DISCOUNT_CENTS,
        holdback_withheld_cents=DRAW_ONE_HOLDBACK_CENTS,
        net_settlement_cents=DRAW_ONE_NET_CENTS,
        settled_on=C.DEFAULT_CLOCK_DATE,
        released_by_user_id="sa-1",
    )
    # 1050000 * 449 / 10000 = 47145.0 and the 400 bps target caps the 500 bps base.
    assert settled["merchant_discount_cents"] == bps_of(DRAW_ONE_CENTS, EFFECTIVE_DISCOUNT_BPS)
    assert settled["holdback_withheld_cents"] == bps_of(
        DRAW_ONE_CENTS, C.RESERVE_TARGET_RATE_BPS["STANDARD"]
    )
    assert (
        settled["net_settlement_cents"]
        == DRAW_ONE_CENTS
        - settled["merchant_discount_cents"]
        - settled["holdback_withheld_cents"]
    )


def test_draw_reversal_restores_the_merchant_reserve_ledger_with_no_drift(api):
    """Every merchant figure the settlement moved returns to its exact pre-draw value.

    PRD: "It then compensates every effect of settlement exactly, with no drift: the loan account's `principal_balance_cents` and `total_funded_cents` each fall by `funded_amount_cents`; the merchant's `funded_volume_cents` falls by `funded_amount_cents` and its `holdback_reserve_cents` falls by `holdback_withheld_cents`, returning that reserve to the merchant, with `holdback_target_cents` and `reserve_coverage_bps` recomputed; the project's `settled_funded_cents`, `funded_pct_bps` and `max_fundable_now_cents` are recomputed and the milestone's `is_funded` returns to false so that the milestone may be re-drawn; and the account's `accrued_deferred_interest_cents` is recomputed on the reduced balance from the reversal date forward."

    Design: Difficulty/compensating_invariant/draw_reversal_restores_the_funding_ledger_with_no_drift
    """
    scenario, before, settled = _settled_single_draw(api)
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        funded_volume_cents=DRAW_ONE_CENTS,
        holdback_reserve_cents=DRAW_ONE_HOLDBACK_CENTS,
        holdback_target_cents=DRAW_ONE_HOLDBACK_CENTS,
        reserve_coverage_bps=10000,
    )

    _reverse(api, settled["id"])

    after = S.read_merchant(api, scenario.merchant_id)
    # The REVERSED draw leaves the trailing-180-day settled volume, so the target
    # falls back to zero and the zero-target guard reports full coverage.
    assert_fields(
        after,
        funded_volume_cents=0,
        holdback_reserve_cents=0,
        holdback_target_cents=0,
        reserve_coverage_bps=10000,
    )
    assert_unchanged(
        before["merchant"],
        after,
        "funded_volume_cents",
        "holdback_reserve_cents",
        "holdback_target_cents",
        "reserve_coverage_bps",
        "settlement_offset_receivable_cents",
        "program_write_off_cents",
        "enrollment_status",
        "risk_tier",
        "portfolio_grade",
    )


def test_draw_reversal_restores_the_loan_and_project_ledger_with_no_drift(api):
    """The loan account and the project return to their exact pre-draw figures.

    PRD: "It then compensates every effect of settlement exactly, with no drift: the loan account's `principal_balance_cents` and `total_funded_cents` each fall by `funded_amount_cents`; the merchant's `funded_volume_cents` falls by `funded_amount_cents` and its `holdback_reserve_cents` falls by `holdback_withheld_cents`, returning that reserve to the merchant, with `holdback_target_cents` and `reserve_coverage_bps` recomputed; the project's `settled_funded_cents`, `funded_pct_bps` and `max_fundable_now_cents` are recomputed and the milestone's `is_funded` returns to false so that the milestone may be re-drawn; and the account's `accrued_deferred_interest_cents` is recomputed on the reduced balance from the reversal date forward."

    Design: Difficulty/compensating_invariant/draw_reversal_restores_the_funding_ledger_with_no_drift
    """
    scenario, before, settled = _settled_single_draw(api)
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=DRAW_ONE_CENTS,
        total_funded_cents=DRAW_ONE_CENTS,
        first_funding_on=C.DEFAULT_CLOCK_DATE,
    )
    assert_fields(
        S.read_project(api, scenario.project_id),
        settled_funded_cents=DRAW_ONE_CENTS,
        funded_pct_bps=ratio_bps(DRAW_ONE_CENTS, C.CANONICAL_PROJECT["contract_amount_cents"]),
        max_fundable_now_cents=0,
    )

    _reverse(api, settled["id"])

    loan_after = S.read_loan(api, scenario.loan_id)
    assert_fields(
        loan_after,
        principal_balance_cents=0,
        total_funded_cents=0,
        accrued_deferred_interest_cents=0,
        promo_payoff_cents=0,
        standard_payoff_cents=0,
    )
    assert_unchanged(
        before["loan"],
        loan_after,
        "principal_balance_cents",
        "total_funded_cents",
        "accrued_deferred_interest_cents",
        "capitalized_interest_cents",
        "promo_payoff_cents",
        "standard_payoff_cents",
        "balance_status",
        "promo_status",
    )
    project_after = S.read_project(api, scenario.project_id)
    assert_fields(
        project_after,
        settled_funded_cents=0,
        funded_pct_bps=0,
        completion_status="IN_PROGRESS",
    )
    assert_unchanged(
        before["project"],
        project_after,
        "settled_funded_cents",
        "funded_pct_bps",
        "completion_status",
        "verified_release_bps",
        "disputed_amount_cents",
    )


def test_draw_reversal_restores_the_milestone_headroom_exactly(api):
    """The milestone stops being funded without losing its VERIFIED status, so the headroom comes back whole.

    PRD: "It then compensates every effect of settlement exactly, with no drift: the loan account's `principal_balance_cents` and `total_funded_cents` each fall by `funded_amount_cents`; the merchant's `funded_volume_cents` falls by `funded_amount_cents` and its `holdback_reserve_cents` falls by `holdback_withheld_cents`, returning that reserve to the merchant, with `holdback_target_cents` and `reserve_coverage_bps` recomputed; the project's `settled_funded_cents`, `funded_pct_bps` and `max_fundable_now_cents` are recomputed and the milestone's `is_funded` returns to false so that the milestone may be re-drawn; and the account's `accrued_deferred_interest_cents` is recomputed on the reduced balance from the reversal date forward."

    Design: Difficulty/compensating_invariant/draw_reversal_restores_the_funding_ledger_with_no_drift
    """
    scenario, before, settled = _settled_single_draw(api)
    assert before["project"]["max_fundable_now_cents"] == DRAW_ONE_CENTS
    assert S.read_milestones(api, scenario.project_id)[0]["is_funded"] is True

    _reverse(api, settled["id"])

    milestone = S.read_milestones(api, scenario.project_id)[0]
    assert_fields(milestone, status="VERIFIED", is_funded=False)
    project_after = S.read_project(api, scenario.project_id)
    assert_fields(
        project_after, verified_release_bps=3000, max_fundable_now_cents=DRAW_ONE_CENTS
    )
    assert_unchanged(before["project"], project_after, "max_fundable_now_cents")


def test_the_reversed_milestone_can_be_drawn_again_for_the_full_amount(api):
    """The restored headroom is real: the identical 1050000 draw is accepted a second time.

    PRD: "Pending draws therefore reserve headroom: a merchant cannot queue two draws that together exceed what the verified work supports."

    Design: Difficulty/compensating_invariant/draw_reversal_restores_the_funding_ledger_with_no_drift
    """
    scenario, _before, settled = _settled_single_draw(api)
    _reverse(api, settled["id"])

    redraw = validate_success(
        api.create_funding_draw(
            F.funding_draw_payload(
                scenario.loan_id,
                scenario.milestone_id(0),
                DRAW_ONE_CENTS,
                S.loan_version(api, scenario.loan_id),
                "STANDARD_3DAY",
            ),
            scenario.as_merchant,
        ),
        201,
    )

    assert_fields(redraw, status="REQUESTED", funded_amount_cents=DRAW_ONE_CENTS)
    assert redraw["id"] != settled["id"]
    assert S.read_project(api, scenario.project_id)["max_fundable_now_cents"] == 0


def test_draw_reversal_advances_the_versions_it_cannot_restore(api):
    """Money is compensated but history is not: the versions climb and the draw keeps its settlement stamp.

    PRD: "The draw's `settled_on` remains populated on a reversed draw, since the reversal is a fact about a settlement that did happen."

    Design: Difficulty/compensating_invariant/draw_reversal_restores_the_funding_ledger_with_no_drift
    """
    scenario, before, settled = _settled_single_draw(api)
    # Origination wrote loan version 1; approval wrote merchant version 3.
    assert before["loan"]["version"] == 1
    assert before["merchant"]["version"] == 3

    reversed_draw = _reverse(api, settled["id"])

    assert_fields(
        reversed_draw,
        status="REVERSED",
        reversal_reason_code="MERCHANT_BILLING_ERROR",
        settled_on=C.DEFAULT_CLOCK_DATE,
        funded_amount_cents=DRAW_ONE_CENTS,
        merchant_discount_cents=DRAW_ONE_DISCOUNT_CENTS,
        holdback_withheld_cents=DRAW_ONE_HOLDBACK_CENTS,
    )
    # Settlement then reversal each incremented both counterparties.
    assert S.read_loan(api, scenario.loan_id)["version"] == 3
    assert S.read_merchant(api, scenario.merchant_id)["version"] == 5


#: Draw 1 at NEXT_DAY on the 3000 bps milestone; draw 2 at STANDARD_3DAY on the 4000 bps one.
DRAW_A_CENTS = 1000050
DRAW_B_CENTS = 1400000

#: 400 bps of the trailing settled volume at each settlement: 1000050 then 2400050,
#: taken as the gap to the running target.
DRAW_A_HOLDBACK_CENTS = 40002
DRAW_B_HOLDBACK_CENTS = 56000
RESERVE_AT_RESOLUTION_CENTS = DRAW_A_HOLDBACK_CENTS + DRAW_B_HOLDBACK_CENTS  # 96002

#: The homeowner claims the whole settled advance, which is the inclusive boundary.
CLAIM_CENTS = DRAW_A_CENTS + DRAW_B_CENTS  # 2400050

#: min(2400050, 96002); then min(2400050 - 96002, 5000 bps of 2400050); then the rest.
ABSORBED_CENTS = 96002
RECEIVABLE_CENTS = 1200025
WRITE_OFF_CENTS = 1104023


def _disputed_project_with_two_settled_draws(api):
    """Two settled draws totalling 2400050 and an open dispute claiming all of it."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000), verify=(0,))
    S.request_draw(api, scenario, DRAW_A_CENTS, 0, "NEXT_DAY")
    S.settle_draw(api, scenario)
    S.claim_milestone(api, scenario, 1)
    S.verify_milestone(api, scenario, 1)
    S.request_draw(api, scenario, DRAW_B_CENTS, 1, "STANDARD_3DAY")
    S.settle_draw(api, scenario)
    case = S.file_dispute(api, scenario, CLAIM_CENTS)
    return scenario, case


def _resolve_in_consumer_favor(api, scenario, case):
    """Resolve as the second servicing agent, who released neither draw."""
    return validate_success(
        api.resolve_dispute(
            case["id"],
            F.resolution_payload(
                "CONSUMER_FAVOR",
                expected_merchant_version=S.merchant_version(api, scenario.merchant_id),
            ),
            SECOND_AGENT_HEADERS,
        )
    )


def test_the_chargeback_waterfall_splits_the_claim_into_three_exact_buckets(api):
    """The three buckets carry their exact derived integers and re-sum to the claim with no slack.

    PRD: "Because every subtraction here is exact and only the receivable ceiling is rounded, the three buckets always re-sum to `chargeback_amount_cents` precisely; that conservation is an invariant with no rounding slack."

    Design: Difficulty/compensating_invariant/chargeback_waterfall_conserves_the_claim_across_three_buckets
    """
    scenario, case = _disputed_project_with_two_settled_draws(api)
    assert_fields(
        case,
        status="MERCHANT_RESPONSE_PENDING",
        opened_on=C.DEFAULT_CLOCK_DATE,
        chargeback_amount_cents=0,
        chargeback_absorbed_from_reserve_cents=0,
        chargeback_receivable_cents=0,
        chargeback_write_off_cents=0,
    )
    assert case["response_due_at"].startswith("2026-08-11T00:00:00")
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=RESERVE_AT_RESOLUTION_CENTS,
    )

    resolved = _resolve_in_consumer_favor(api, scenario, case)

    assert_fields(
        resolved,
        status="RESOLVED_CONSUMER_FAVOR",
        resolved_by_user_id="sa-2",
        resolved_on=C.DEFAULT_CLOCK_DATE,
        chargeback_amount_cents=CLAIM_CENTS,
        chargeback_absorbed_from_reserve_cents=ABSORBED_CENTS,
        chargeback_receivable_cents=RECEIVABLE_CENTS,
        chargeback_write_off_cents=WRITE_OFF_CENTS,
    )
    # 5000 bps of the trailing settled volume is the only rounded figure in the split.
    assert resolved["chargeback_receivable_cents"] == bps_of(
        CLAIM_CENTS, C.CHARGEBACK_RECEIVABLE_CEILING_BPS
    )
    assert (
        resolved["chargeback_write_off_cents"]
        == CLAIM_CENTS - ABSORBED_CENTS - RECEIVABLE_CENTS
    )
    assert_chargeback_conserved(resolved)


def test_the_merchant_ledger_movements_mirror_the_three_buckets(api):
    """The reserve falls by the absorbed amount while the receivable and write-off rise by the other two.

    PRD: "The second hop is caused by the first: the merchant's `holdback_reserve_cents` falls by the absorbed amount, its `settlement_offset_receivable_cents` rises by the receivable amount, its `program_write_off_cents` rises by the written-off amount, and `reserve_coverage_bps` is recomputed against an **unchanged** `holdback_target_cents` — a consumer-favour resolution consumes reserve without lowering the target, which is exactly what makes coverage collapse."

    Design: Difficulty/compensating_invariant/chargeback_waterfall_conserves_the_claim_across_three_buckets
    """
    scenario, case = _disputed_project_with_two_settled_draws(api)
    before = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        before,
        holdback_reserve_cents=RESERVE_AT_RESOLUTION_CENTS,
        holdback_target_cents=RESERVE_AT_RESOLUTION_CENTS,
        settlement_offset_receivable_cents=0,
        program_write_off_cents=0,
        reserve_coverage_bps=10000,
    )

    _resolve_in_consumer_favor(api, scenario, case)

    after = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        after,
        holdback_reserve_cents=0,
        settlement_offset_receivable_cents=RECEIVABLE_CENTS,
        program_write_off_cents=WRITE_OFF_CENTS,
    )
    assert (
        before["holdback_reserve_cents"] - after["holdback_reserve_cents"]
    ) == ABSORBED_CENTS
    # 96002 + 1200025 + 1104023 == 2400050: the movements re-sum to the claim.
    assert (
        (before["holdback_reserve_cents"] - after["holdback_reserve_cents"])
        + after["settlement_offset_receivable_cents"]
        + after["program_write_off_cents"]
    ) == CLAIM_CENTS
    # Coverage is recomputed against the untouched target, so it collapses to zero.
    assert_unchanged(before, after, "holdback_target_cents", "funded_volume_cents")
    assert_fields(after, reserve_coverage_bps=0)
    assert after["version"] == before["version"] + 1


def test_a_consumer_favor_resolution_never_reverses_the_settled_draws(api):
    """Unlike a reversal, the chargeback leaves funded volume and both settled draws alone.

    PRD: "It reduces the loan account's principal by the chargeback amount and leaves the merchant's `funded_volume_cents`, its `holdback_target_cents` and every settled draw untouched, because reversing the draws as well would debit the same advance twice."

    Design: Difficulty/compensating_invariant/chargeback_waterfall_conserves_the_claim_across_three_buckets
    """
    scenario, case = _disputed_project_with_two_settled_draws(api)

    _resolve_in_consumer_favor(api, scenario, case)

    draws, meta = validate_paginated(
        api.list_funding_draws(
            SECOND_AGENT_HEADERS, {"merchant_id": scenario.merchant_id}
        )
    )
    assert meta["total_count"] == 2
    withheld = {draw["funded_amount_cents"]: draw for draw in draws}
    assert_fields(
        withheld[DRAW_A_CENTS],
        status="SETTLED",
        holdback_withheld_cents=DRAW_A_HOLDBACK_CENTS,
    )
    assert_fields(
        withheld[DRAW_B_CENTS],
        status="SETTLED",
        holdback_withheld_cents=DRAW_B_HOLDBACK_CENTS,
    )
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        funded_volume_cents=CLAIM_CENTS,
        holdback_target_cents=RESERVE_AT_RESOLUTION_CENTS,
    )
    # The principal falls by exactly the chargeback amount; only a payment can pay off.
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=0,
        balance_status="CURRENT",
        promo_status="PROMO_ACTIVE",
        version=4,
    )


def test_the_collapsed_coverage_suspends_the_merchant_and_its_enrollment(api):
    """Consuming the reserve against an unchanged target drives coverage to zero and cascades.

    PRD: "The third hop is caused by the second: if the recomputed `reserve_coverage_bps` has fallen below five thousand — below half the target reserve — the merchant moves `APPROVED → SUSPENDED` with `suspension_reason_code` recorded as `RESERVE_COVERAGE`."

    Design: Difficulty/compensating_invariant/chargeback_waterfall_conserves_the_claim_across_three_buckets
    """
    scenario, case = _disputed_project_with_two_settled_draws(api)

    _resolve_in_consumer_favor(api, scenario, case)

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        reserve_coverage_bps=0,
        enrollment_status="SUSPENDED",
        suspension_reason_code="RESERVE_COVERAGE",
        dispute_rate_bps=10000,
        portfolio_grade="D",
        termination_recommended=True,
        risk_tier="STANDARD",
    )
    enrollments, _meta = validate_paginated(
        api.list_merchant_promotion_enrollments(
            scenario.merchant_id, SECOND_AGENT_HEADERS
        )
    )
    assert_fields(enrollments[0], id=scenario.enrollment["id"], status="SUSPENDED")
    # The project is abandoned but keeps the settled figures the chargeback did not undo.
    assert_fields(
        S.read_project(api, scenario.project_id),
        completion_status="ABANDONED",
        disputed_amount_cents=0,
        settled_funded_cents=CLAIM_CENTS,
        funded_pct_bps=ratio_bps(CLAIM_CENTS, C.CANONICAL_PROJECT["contract_amount_cents"]),
        max_fundable_now_cents=0,
    )

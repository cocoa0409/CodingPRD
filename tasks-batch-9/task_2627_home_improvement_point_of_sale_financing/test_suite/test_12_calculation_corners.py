"""Exact-integer corners of the program's money and rate arithmetic.

Every figure asserted here is the single integer the PRD's formula yields:
round-half-up on each pinned component, cross-multiplied comparisons with no
rounding at all, and ratio defaults where a denominator is zero.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import (
    assert_empty,
    assert_fields,
    assert_reason_codes,
    bps_of,
    ratio_bps,
)
from test_helpers.test_users import ADMIN_HEADERS, AGENT_HEADERS, SERVICING_AGENT_ID


# ─── Module-private builders and helpers ──────────────

def _instant_equals(actual, expected):
    """Compare two UTC instants, tolerating an optional three-digit fraction."""
    if not isinstance(actual, str):
        return False
    return actual.replace(".000Z", "Z") == expected


def _mixed_state_project(api):
    """3500000 project: milestone 1 PENDING, milestone 2 CLAIMED, milestone 3 VERIFIED."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000, 3000), verify=())
    S.claim_milestone(api, scenario, 1)
    S.claim_milestone(api, scenario, 2)
    S.verify_milestone(api, scenario, 2)
    scenario.project = S.read_project(api, scenario.project_id)
    return scenario


def _odd_cent_project(api):
    """One VERIFIED 3000 bps milestone on an odd 1000005-cent contract."""
    return S.project_with_milestones(
        api,
        releases=(3000,),
        verify=(0,),
        contract_amount_cents=1000005,
        ticket_cents=1000005,
    )


def _velocity_capped_project(api):
    """3500000 project, milestones of 3000 and 4000 bps both VERIFIED, velocity cap 1050000."""
    return S.project_with_milestones(
        api,
        releases=(3000, 4000),
        verify=(0, 1),
        trade_rule={"velocity_cap_cents": 1050000},
    )


def _consumer_application(api, scenario, fico_score, ssn_last4, ticket_cents):
    """Register one homeowner at the given score and file a point-of-sale application."""
    consumer = S.register_consumer(
        api, scenario.merchant_id, fico_score=fico_score, ssn_last4=ssn_last4
    )
    return api.create_credit_application(
        F.credit_application_payload(
            scenario.merchant_id,
            consumer["id"],
            scenario.plan_id,
            project_amount_cents=ticket_cents,
        ),
        scenario.as_merchant,
    )


# ─── Staged release counts VERIFIED milestones only ──────────────

def test_verified_release_bps_sums_only_the_verified_milestones(api):
    """A PENDING and a CLAIMED milestone contribute nothing to the verified release share.

    PRD: "First, the project's `verified_release_bps` is the sum of `release_pct_bps` over its milestones standing at `VERIFIED` only — a milestone at `PENDING`, `CLAIMED` or `REJECTED` releases nothing at all, no matter how convincing its evidence."

    Design: Corner/calculations/staged_release_counts_verified_milestones_only
    """
    scenario = _mixed_state_project(api)

    assert_fields(scenario.project, verified_release_bps=3000)

    response = api.list_milestones(scenario.project_id, ADMIN_HEADERS, {"status": "VERIFIED"})
    validate_success(response)
    assert response.json()["meta"]["total_count"] == 1


def test_max_fundable_now_follows_the_verified_share_alone(api):
    """Only the one VERIFIED milestone's 3000 bps opens funding headroom on the contract.

    PRD: "Third, the release cap is the **lower** of the verified share and the completion cap, and the releasable amount is the project's `contract_amount_cents` multiplied by that release cap in basis points, divided by ten thousand and rounded half up."

    Design: Corner/calculations/staged_release_counts_verified_milestones_only
    """
    scenario = _mixed_state_project(api)

    # min(verified 3000, precompletion cap 7000) = 3000; 3500000 * 3000 / 10000 = 1050000
    assert_fields(scenario.project, max_fundable_now_cents=bps_of(C.CANONICAL_PROJECT["contract_amount_cents"], 3000))
    assert scenario.project["max_fundable_now_cents"] == 1050000


def test_a_pending_milestone_cannot_back_a_funding_draw(api):
    """A draw naming the still-PENDING first milestone is refused for milestone state.

    PRD: "Violations are `ERR_INVALID_MILESTONE_STATE`, which is also the code raised when a draw names a milestone that is not `VERIFIED`."

    Design: Corner/calculations/staged_release_counts_verified_milestones_only
    """
    scenario = _mixed_state_project(api)

    response = api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id,
            scenario.milestone_id(0),
            100000,
            S.loan_version(api, scenario.loan_id),
        ),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_INVALID_MILESTONE_STATE)

    assert_fields(S.read_project(api, scenario.project_id), max_fundable_now_cents=1050000)


def test_a_claimed_milestone_cannot_back_a_funding_draw(api):
    """A draw naming the CLAIMED but unverified second milestone is refused the same way.

    PRD: "Violations are `ERR_INVALID_MILESTONE_STATE`, which is also the code raised when a draw names a milestone that is not `VERIFIED`."

    Design: Corner/calculations/staged_release_counts_verified_milestones_only
    """
    scenario = _mixed_state_project(api)

    response = api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id,
            scenario.milestone_id(1),
            100000,
            S.loan_version(api, scenario.loan_id),
        ),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_INVALID_MILESTONE_STATE)

    assert_fields(S.read_project(api, scenario.project_id), max_fundable_now_cents=1050000)


def test_a_requested_draw_consumes_the_whole_verified_headroom(api):
    """A draw for the full 1050000 headroom leaves nothing fundable while it stands at REQUESTED.

    PRD: "Fourth, `max_fundable_now_cents` is that releasable amount reduced by the project's `settled_funded_cents` and reduced again by the total `requested_amount_cents` of every draw on the project still standing at `REQUESTED`, with the result floored at zero so it never goes negative."

    Design: Corner/calculations/staged_release_counts_verified_milestones_only
    """
    scenario = _mixed_state_project(api)

    response = api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id,
            scenario.milestone_id(2),
            1050000,
            S.loan_version(api, scenario.loan_id),
        ),
        scenario.as_merchant,
    )
    validate_success(response, 201)

    # 1050000 releasable - 0 settled - 1050000 requested = 0
    assert_fields(S.read_project(api, scenario.project_id), max_fundable_now_cents=0)


# ─── FICO floor and offer validity constants ──────────────

def test_a_score_one_below_the_floor_declines_without_computing_the_ratio(api):
    """A 619 score declines outright and leaves the debt-to-income figure at zero.

    PRD: "If `fico_score` is below 620, the application is declined outright: `decision` becomes `DECLINED`, `approved_limit_cents` stays at zero, `decision_reason_codes` is written as the single code `FICO_BELOW_FLOOR`, and `decision_dti_bps` is left at zero because the debt-to-income ratio is never computed when the score floor fails."

    Design: Corner/calculations/fico_floor_and_offer_validity_constants_are_applied_as_declared
    """
    scenario = S.enrolled_merchant(api)

    response = _consumer_application(api, scenario, C.FICO_FLOOR - 1, "8801", 1000000)
    data = validate_success(response, 201)

    assert_fields(
        data,
        decision="DECLINED",
        approved_limit_cents=0,
        decision_dti_bps=0,
    )
    assert_reason_codes(data, "FICO_BELOW_FLOOR")


def test_a_score_exactly_at_the_floor_is_underwritten_in_the_bottom_tier(api):
    """A 620 score clears the floor and takes the bottom tier's 1500000-cent cap.

    PRD: "The consumer's `annual_income_cents` is multiplied by the tier's income factor in basis points, divided by ten thousand and rounded half up; the lower of that figure and the tier's cap is the credit ceiling."

    Design: Corner/calculations/fico_floor_and_offer_validity_constants_are_applied_as_declared
    """
    scenario = S.enrolled_merchant(api)

    response = _consumer_application(api, scenario, C.FICO_FLOOR, "8802", 1000000)
    data = validate_success(response, 201)

    # min(round_half_up(9600000 * 2000 / 10000) = 1920000, tier cap 1500000) = 1500000
    assert_fields(
        data,
        decision="APPROVED",
        approved_limit_cents=min(bps_of(C.CANONICAL_CONSUMER["annual_income_cents"], 2000), 1500000),
        decision_dti_bps=ratio_bps(1000000, C.CANONICAL_CONSUMER["annual_income_cents"]),
    )
    assert data["approved_limit_cents"] == 1500000
    assert data["decision_dti_bps"] == 1042  # 1000000 * 10000 / 9600000 = 1041.66... -> 1042
    assert_reason_codes(data, "WITHIN_LIMIT")


def test_offer_expiry_is_stamped_fourteen_days_out_on_a_declined_application(api):
    """The fourteen-day offer clock is stamped even when the score floor declines the file.

    PRD: "Whatever the outcome, the sixth step stamps `offer_expires_at` at fourteen days after the decision instant."

    Design: Corner/calculations/fico_floor_and_offer_validity_constants_are_applied_as_declared
    """
    scenario = S.enrolled_merchant(api)

    response = _consumer_application(api, scenario, C.FICO_FLOOR - 1, "8803", 1000000)
    data = validate_success(response, 201)

    # 2026-08-01T00:00:00Z + 14 days
    assert data["decision"] == "DECLINED"
    assert _instant_equals(data["offer_expires_at"], C.CANONICAL_OFFER_EXPIRES_AT)


def test_offer_expiry_is_stamped_fourteen_days_out_on_an_approved_application(api):
    """The same fourteen-day offer clock is stamped on an approval.

    PRD: "Whatever the outcome, the sixth step stamps `offer_expires_at` at fourteen days after the decision instant."

    Design: Corner/calculations/fico_floor_and_offer_validity_constants_are_applied_as_declared
    """
    scenario = S.enrolled_merchant(api)

    response = _consumer_application(api, scenario, C.FICO_FLOOR, "8804", 1000000)
    data = validate_success(response, 201)

    assert data["decision"] == "APPROVED"
    assert _instant_equals(data["offer_expires_at"], C.CANONICAL_OFFER_EXPIRES_AT)


# ─── Every FICO tier boundary picks its own ceiling and cap ──────────────

@pytest.mark.parametrize(
    "fico_score, expected_limit_cents",
    [
        (760, 5760000),  # 9600000 * 6000 / 10000 = 5760000, below the 7500000 cap
        (759, 4320000),  # 9600000 * 4500 / 10000 = 4320000, below the 5000000 cap
        (700, 4320000),  # same band, lower edge
        (699, 2880000),  # 9600000 * 3000 / 10000 = 2880000, below the 3000000 cap
        (660, 2880000),  # same band, lower edge
        (659, 1500000),  # 9600000 * 2000 / 10000 = 1920000, so the 1500000 cap binds
    ],
)
def test_every_fico_band_edge_takes_the_lower_of_income_ceiling_and_tier_cap(
    api, fico_score, expected_limit_cents
):
    """Each closed band edge selects its own income factor and cap, and the lower figure wins.

    PRD: "The bands are closed at both ends and do not overlap: a score of 760 or above is the top tier, carrying an income factor of six thousand basis points and a tier cap of 7500000 cents; a score from 700 through 759 carries four thousand five hundred basis points and a cap of 5000000 cents; a score from 660 through 699 carries three thousand basis points and a cap of 3000000 cents; and a score from 620 through 659 carries two thousand basis points and a cap of 1500000 cents."

    Design: Corner/calculations/every_fico_tier_boundary_selects_the_right_ceiling_and_cap
    """
    scenario = S.enrolled_merchant(api)

    response = _consumer_application(api, scenario, fico_score, "77" + str(fico_score % 100).zfill(2), 1000000)
    data = validate_success(response, 201)

    assert_fields(
        data,
        decision="APPROVED",
        approved_limit_cents=expected_limit_cents,
        # the tier never touches the ratio: 1000000 * 10000 / 9600000 = 1041.66... -> 1042
        decision_dti_bps=1042,
    )
    assert_reason_codes(data, "WITHIN_LIMIT")


def test_the_approved_limit_is_the_credit_line_and_not_the_requested_ticket(api):
    """An approval writes the whole ceiling as the limit rather than the 1000000-cent ticket.

    PRD: "When `project_amount_cents` is less than or equal to the ceiling, `decision` becomes `APPROVED`, `approved_limit_cents` is written as the **ceiling** rather than the ticket — the program extends a line of credit, not a single-purpose advance — and `decision_reason_codes` is written as the single code `WITHIN_LIMIT`."

    Design: Corner/calculations/every_fico_tier_boundary_selects_the_right_ceiling_and_cap
    """
    scenario = S.enrolled_merchant(api)

    response = _consumer_application(api, scenario, 760, "7601", 1000000)
    data = validate_success(response, 201)

    assert_fields(data, project_amount_cents=1000000, approved_limit_cents=5760000)


# ─── Half-cent releases and discounts round half up per component ──────────────

def test_a_half_cent_release_share_rounds_the_headroom_up(api):
    """3000 bps of a 1000005-cent contract is 300001.5 cents, which rounds up to 300002.

    PRD: "Wherever a rule divides one integer by another, the result is rounded half up to a whole number — that is, the exact rational value is rounded to the nearest integer, and a value exactly halfway between two integers rounds away from zero to the larger magnitude."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)

    # 1000005 * 3000 / 10000 = 300001.5 -> 300002
    assert_fields(scenario.project, max_fundable_now_cents=bps_of(1000005, 3000))
    assert scenario.project["max_fundable_now_cents"] == 300002


def test_provisional_components_each_round_half_up_at_draw_creation(api):
    """The provisional discount and holdback each round their own quotient half up.

    PRD: "The provisional view deliberately uses only plan-level and trade-level rates: `provisional_discount_cents` is `funded_amount_cents` multiplied by the promotion plan's `merchant_discount_bps`, divided by ten thousand and rounded half up; `provisional_holdback_cents` is `funded_amount_cents` multiplied by the trade rule's `holdback_pct_bps`, divided by ten thousand and rounded half up; and `provisional_net_settlement_cents` is `funded_amount_cents` reduced by `provisional_discount_cents` and reduced again by `provisional_holdback_cents`."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)

    draw = S.request_draw(api, scenario, 300002)

    # 300002 * 525 / 10000 = 15750.105 -> 15750; 300002 * 500 / 10000 = 15000.1 -> 15000
    assert_fields(
        draw,
        funded_amount_cents=300002,
        provisional_discount_cents=bps_of(300002, C.DEFERRED_INTEREST_PLAN["merchant_discount_bps"]),
        provisional_holdback_cents=bps_of(300002, C.ROOFING_TRADE_RULE["holdback_pct_bps"]),
        provisional_net_settlement_cents=300002 - 15750 - 15000,
    )
    assert draw["provisional_discount_cents"] == 15750
    assert draw["provisional_holdback_cents"] == 15000
    assert draw["provisional_net_settlement_cents"] == 269252


def test_the_billed_discount_rounds_the_negotiated_rate_half_up_at_settlement(api):
    """The base discount component on 300002 cents at 449 bps rounds 13470.0898 down to 13470.

    PRD: "The base component is `funded_amount_cents` multiplied by `effective_discount_bps`, divided by ten thousand and rounded half up."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)
    S.request_draw(api, scenario, 300002)

    draw = S.settle_draw(api, scenario)

    # 300002 * 449 / 10000 = 13470.0898 -> 13470, with no speed surcharge and no volume credit
    assert_fields(
        draw,
        effective_discount_bps=C.NEGOTIATED_DISCOUNT_BPS,
        volume_tier_credit_bps=0,
        merchant_discount_cents=bps_of(300002, C.NEGOTIATED_DISCOUNT_BPS),
    )
    assert draw["merchant_discount_cents"] == 13470


def test_the_reserve_target_gap_caps_the_holdback_on_a_half_cent_draw(api):
    """The smallest of the 15000 base, the 12000 gap and the 45000 per-draw ceiling is withheld.

    PRD: "Sixth, `holdback_withheld_cents` is the smallest of the base withholding, the gap and the per-draw ceiling, taken exactly with no further rounding."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)
    S.request_draw(api, scenario, 300002)

    draw = S.settle_draw(api, scenario)

    base = bps_of(300002, C.ROOFING_TRADE_RULE["holdback_pct_bps"])     # 15000
    target = bps_of(300002, C.RESERVE_TARGET_RATE_BPS["STANDARD"])      # 12000.08 -> 12000
    ceiling = bps_of(300002, C.PER_DRAW_HOLDBACK_CEILING_BPS)           # 45000.3  -> 45000
    gap = target - 0                                                   # reserve stands at zero
    assert (base, target, ceiling) == (15000, 12000, 45000)
    assert_fields(draw, holdback_withheld_cents=min(base, gap, ceiling))
    assert draw["holdback_withheld_cents"] == 12000


def test_the_net_settlement_is_the_funded_amount_less_both_deductions(api):
    """300002 less a 13470 discount and a 12000 holdback reaches the contractor as 274532.

    PRD: "`net_settlement_cents`, the money that actually reaches the contractor, is `funded_amount_cents` reduced by `merchant_discount_cents` and reduced again by `holdback_withheld_cents`."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)
    S.request_draw(api, scenario, 300002)

    draw = S.settle_draw(api, scenario)

    assert_fields(draw, net_settlement_cents=300002 - 13470 - 12000)
    assert draw["net_settlement_cents"] == 274532


def test_reserve_coverage_reaches_ten_thousand_when_the_gap_is_closed_exactly(api):
    """Withholding exactly the gap leaves the reserve equal to the target and coverage at 10000 bps.

    PRD: "On the merchant, `funded_volume_cents` rises by `funded_amount_cents`, `holdback_reserve_cents` rises by `holdback_withheld_cents`, `holdback_target_cents` is written as the target computed at step two, and `reserve_coverage_bps` is recomputed as `holdback_reserve_cents` multiplied by ten thousand, divided by `holdback_target_cents` and rounded half up — or as exactly ten thousand when `holdback_target_cents` is zero, since a merchant with no target is trivially fully covered."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)
    S.request_draw(api, scenario, 300002)
    S.settle_draw(api, scenario)

    merchant = S.read_merchant(api, scenario.merchant_id)

    assert_fields(
        merchant,
        funded_volume_cents=300002,
        holdback_reserve_cents=12000,
        holdback_target_cents=12000,
        reserve_coverage_bps=ratio_bps(12000, 12000),
    )
    assert merchant["reserve_coverage_bps"] == 10000


def test_funded_pct_bps_rounds_the_settled_share_half_up(api):
    """300002 of a 1000005-cent contract reports as 3000 bps funded.

    PRD: "The project's `funded_pct_bps` is at all times the project's `settled_funded_cents` multiplied by ten thousand, divided by its `contract_amount_cents` and rounded half up."

    Design: Corner/calculations/half_cent_release_and_discount_rounding_is_half_up_on_every_component
    """
    scenario = _odd_cent_project(api)
    S.request_draw(api, scenario, 300002)
    S.settle_draw(api, scenario)

    project = S.read_project(api, scenario.project_id)

    # 300002 * 10000 / 1000005 = 3000.005... -> 3000
    assert_fields(
        project,
        settled_funded_cents=300002,
        funded_pct_bps=ratio_bps(300002, 1000005),
    )
    assert project["funded_pct_bps"] == 3000


# ─── The funding-velocity window is a closed seven-day interval ──────────────

def test_a_window_volume_exactly_at_the_cap_still_settles(api):
    """A draw taking window volume to exactly 1050000 against a 1050000 cap is allowed through.

    PRD: "The comparison is strict: a window volume exactly equal to `velocity_cap_cents` settles, and only a volume strictly greater than the cap is refused with `ERR_FUNDING_VELOCITY_EXCEEDED`."

    Design: Corner/calculations/velocity_window_is_a_closed_seven_day_rolling_interval
    """
    scenario = _velocity_capped_project(api)
    S.request_draw(api, scenario, 1050000, milestone_index=0)

    draw = S.settle_draw(api, scenario)

    assert_fields(draw, status="SETTLED", funded_amount_cents=1050000, settled_on=C.DEFAULT_CLOCK_DATE)


def test_a_draw_settled_six_days_ago_is_still_inside_the_window(api):
    """On the seventh calendar day the earlier settlement still counts, so one extra cent breaches the cap.

    PRD: "That budget is measured over a closed rolling window spanning the clock date and the six calendar days before it: the `funded_amount_cents` of every draw of that merchant standing at `SETTLED` whose `settled_on` falls inside the window is summed, the `funded_amount_cents` of the draw now being settled is added, and the total is compared to the governing trade rule's `velocity_cap_cents`."

    Design: Corner/calculations/velocity_window_is_a_closed_seven_day_rolling_interval
    """
    scenario = _velocity_capped_project(api)
    S.request_draw(api, scenario, 1050000, milestone_index=0)
    S.settle_draw(api, scenario)
    second = S.request_draw(api, scenario, 1, milestone_index=1)

    S.set_clock(api, "2026-08-07T00:00:00Z")
    response = api.settle_funding_draw(second["id"], F.settlement_payload("SETTLE"), AGENT_HEADERS)
    validate_error(response, E.ERR_FUNDING_VELOCITY_EXCEEDED)

    # 1050000 (settled 2026-08-01, still in [2026-08-01, 2026-08-07]) + 1 > 1050000
    unchanged = S.read_draw(api, second["id"])
    assert_fields(unchanged, status="REQUESTED")
    assert_empty(unchanged, "settled_on", "net_settlement_cents")


def test_a_draw_settled_seven_days_ago_has_dropped_out_of_the_window(api):
    """On the eighth calendar day the earlier settlement no longer counts, so the cent settles.

    PRD: "Draws that have been reversed are excluded from the window even if they settled inside it, and a draw whose `settled_on` is exactly seven days behind the clock date has already dropped out."

    Design: Corner/calculations/velocity_window_is_a_closed_seven_day_rolling_interval
    """
    scenario = _velocity_capped_project(api)
    S.request_draw(api, scenario, 1050000, milestone_index=0)
    S.settle_draw(api, scenario)
    second = S.request_draw(api, scenario, 1, milestone_index=1)

    S.set_clock(api, "2026-08-08T00:00:00Z")
    settled = S.settle_draw(api, scenario, second["id"])

    # window is [2026-08-02, 2026-08-08]: 0 + 1 <= 1050000
    assert_fields(
        settled,
        status="SETTLED",
        settled_on="2026-08-08",
        # 1 * 449 / 10000 = 0.0449 -> 0 and 1 * 500 / 10000 = 0.05 -> 0
        merchant_discount_cents=0,
        holdback_withheld_cents=0,
        net_settlement_cents=1,
    )


def test_a_zero_holdback_settlement_leaves_the_reserve_fully_covered(api):
    """A cent that closes no gap adds nothing to the reserve and leaves coverage at 10000 bps.

    PRD: "On the merchant, `funded_volume_cents` rises by `funded_amount_cents`, `holdback_reserve_cents` rises by `holdback_withheld_cents`, `holdback_target_cents` is written as the target computed at step two, and `reserve_coverage_bps` is recomputed as `holdback_reserve_cents` multiplied by ten thousand, divided by `holdback_target_cents` and rounded half up — or as exactly ten thousand when `holdback_target_cents` is zero, since a merchant with no target is trivially fully covered."

    Design: Corner/calculations/velocity_window_is_a_closed_seven_day_rolling_interval
    """
    scenario = _velocity_capped_project(api)
    S.request_draw(api, scenario, 1050000, milestone_index=0)
    S.settle_draw(api, scenario)
    second = S.request_draw(api, scenario, 1, milestone_index=1)

    S.set_clock(api, "2026-08-08T00:00:00Z")
    S.settle_draw(api, scenario, second["id"])

    merchant = S.read_merchant(api, scenario.merchant_id)

    # 1050000 * 400 / 10000 = 42000 was withheld on the first draw; 1 * 1500 / 10000 = 0.15 -> 0
    assert_fields(
        merchant,
        funded_volume_cents=1050001,
        holdback_reserve_cents=bps_of(1050000, C.RESERVE_TARGET_RATE_BPS["STANDARD"]),
        reserve_coverage_bps=10000,
    )
    assert merchant["holdback_reserve_cents"] == 42000


# ─── Payments fill capitalized interest first and lock a closed loan ──────────────

def _funded_loan(api):
    """A loan carrying exactly 1050000 cents of principal from one settled draw."""
    return S.settled_draw(api, amount_cents=1050000)


def _paid_off_loan(api):
    """The same loan, taken to a zero principal balance by two payments."""
    scenario = _funded_loan(api)
    get_success_data(api.create_payment(F.payment_payload(scenario.loan_id, 400000), scenario.as_consumer))
    get_success_data(api.create_payment(F.payment_payload(scenario.loan_id, 650000), scenario.as_consumer))
    return scenario


def test_a_payment_one_cent_over_the_payoff_is_refused_and_records_nothing(api):
    """1050001 cents against a 1050000-cent payoff is rejected with no row and no ledger change.

    PRD: "Before either allocation bucket is written, an overpayment gate applies: if `amount_cents` exceeds the sum of the account's `capitalized_interest_cents` and `principal_balance_cents`, the payment is refused with `ERR_PAYMENT_EXCEEDS_PAYOFF` and nothing is recorded."

    Design: Corner/calculations/payment_fills_capitalized_interest_before_principal_and_locks_a_closed_loan
    """
    scenario = _funded_loan(api)

    response = api.create_payment(
        F.payment_payload(scenario.loan_id, 1050001), scenario.as_consumer
    )
    validate_error(response, E.ERR_PAYMENT_EXCEEDS_PAYOFF)

    assert_fields(S.read_loan(api, scenario.loan_id), principal_balance_cents=1050000)
    listing = api.list_payments(scenario.loan_id, scenario.as_consumer)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


def test_a_partial_payment_lands_entirely_on_principal_while_the_promo_runs(api):
    """With deferred interest unpayable, 400000 cents all reduces principal to 650000.

    PRD: "The first bucket, `applied_to_capitalized_interest_cents`, takes the lesser of `amount_cents` and the account's `capitalized_interest_cents`; while `promo_status` is `PROMO_ACTIVE` this bucket is necessarily zero, since accrued promotional interest is not payable — that is the entire point of a deferred-interest product."

    Design: Corner/calculations/payment_fills_capitalized_interest_before_principal_and_locks_a_closed_loan
    """
    scenario = _funded_loan(api)

    data = validate_success(
        api.create_payment(F.payment_payload(scenario.loan_id, 400000), scenario.as_consumer), 201
    )

    assert_fields(
        data,
        applied_to_capitalized_interest_cents=0,
        applied_to_principal_cents=400000,
        resulting_principal_balance_cents=1050000 - 400000,
    )
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=650000,
        promo_status="PROMO_ACTIVE",
        balance_status="CURRENT",
        waived_interest_cents=0,
    )


def test_clearing_principal_inside_the_promo_window_satisfies_and_closes_the_loan(api):
    """The payment that zeroes principal moves the loan to PROMO_SATISFIED and PAID_OFF.

    PRD: "If the payment brings `principal_balance_cents` to zero on or before `promo_expires_on` — the boundary being inclusive, so a payment posted on the expiration date itself still wins the wager — the promotional dimension moves `PROMO_ACTIVE → PROMO_SATISFIED`: `waived_interest_cents` is written with the accrual standing at that instant, `accrued_deferred_interest_cents` and `deferred_interest_at_risk_cents` both drop to zero, `capitalized_interest_cents` stays at zero, and the repayment dimension moves `CURRENT → PAID_OFF`, with the consumer's `existing_program_debt_cents` and `active_loan_count` recomputed."

    Design: Corner/calculations/payment_fills_capitalized_interest_before_principal_and_locks_a_closed_loan
    """
    scenario = _funded_loan(api)
    get_success_data(api.create_payment(F.payment_payload(scenario.loan_id, 400000), scenario.as_consumer))

    data = validate_success(
        api.create_payment(F.payment_payload(scenario.loan_id, 650000), scenario.as_consumer), 201
    )

    assert_fields(
        data,
        applied_to_capitalized_interest_cents=0,
        applied_to_principal_cents=650000,
        resulting_principal_balance_cents=0,
    )
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=0,
        promo_status="PROMO_SATISFIED",
        balance_status="PAID_OFF",
        # funding and payoff both fall on 2026-08-01, so no day of accrual ever elapsed
        waived_interest_cents=0,
        accrued_deferred_interest_cents=0,
        deferred_interest_at_risk_cents=0,
        capitalized_interest_cents=0,
    )


def test_a_paid_off_loan_refuses_further_money_movement(api):
    """One more cent on a PAID_OFF account is stopped by the loan-openness check.

    PRD: "Loan-account openness: the account's `balance_status` must be neither `PAID_OFF` nor `CHARGED_OFF` for money to move, otherwise `ERR_LOAN_CLOSED`."

    Design: Corner/calculations/payment_fills_capitalized_interest_before_principal_and_locks_a_closed_loan
    """
    scenario = _paid_off_loan(api)

    response = api.create_payment(F.payment_payload(scenario.loan_id, 1), scenario.as_consumer)
    validate_error(response, E.ERR_LOAN_CLOSED)

    listing = api.list_payments(scenario.loan_id, scenario.as_consumer)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 2


# ─── The provisional variant is written at creation and frozen at settlement ──────────────

def test_draw_creation_writes_the_provisional_view_and_moves_no_money(api):
    """Creation stamps the plan-and-trade estimate only, leaving both ledgers untouched.

    PRD: "The provisional view deliberately uses only plan-level and trade-level rates: `provisional_discount_cents` is `funded_amount_cents` multiplied by the promotion plan's `merchant_discount_bps`, divided by ten thousand and rounded half up; `provisional_holdback_cents` is `funded_amount_cents` multiplied by the trade rule's `holdback_pct_bps`, divided by ten thousand and rounded half up; and `provisional_net_settlement_cents` is `funded_amount_cents` reduced by `provisional_discount_cents` and reduced again by `provisional_holdback_cents`."

    Design: Corner/calculations/provisional_variant_is_written_at_creation_and_frozen_at_settlement
    """
    scenario = S.project_with_milestones(api, verify=(0,))

    draw = S.request_draw(api, scenario, 1050000)

    # 1050000 * 525 / 10000 = 55125 and 1050000 * 500 / 10000 = 52500, both exact
    assert_fields(
        draw,
        status="REQUESTED",
        funded_amount_cents=1050000,
        provisional_discount_cents=55125,
        provisional_holdback_cents=52500,
        provisional_net_settlement_cents=1050000 - 55125 - 52500,
    )
    assert draw["provisional_net_settlement_cents"] == 942375
    assert_fields(S.read_loan(api, scenario.loan_id), principal_balance_cents=0, total_funded_cents=0)
    assert_fields(S.read_merchant(api, scenario.merchant_id), holdback_reserve_cents=0, funded_volume_cents=0)


def test_a_requested_draw_carries_no_final_variant_figures_yet(api):
    """None of the settlement-time figures exist while the draw still stands at REQUESTED.

    PRD: "A created draw stands at `status` `REQUESTED`, and its `funded_amount_cents` is frozen at that moment as a copy of `requested_amount_cents`; nothing later changes it."

    Design: Corner/calculations/provisional_variant_is_written_at_creation_and_frozen_at_settlement
    """
    scenario = S.project_with_milestones(api, verify=(0,))

    draw = S.request_draw(api, scenario, 1050000)

    assert_fields(draw, requested_amount_cents=1050000, funded_amount_cents=1050000)
    assert_empty(
        draw,
        "effective_discount_bps",
        "merchant_discount_cents",
        "holdback_withheld_cents",
        "net_settlement_cents",
        "settled_on",
        "released_by_user_id",
    )


def test_settlement_bills_the_negotiated_rate_and_the_reserve_gap(api):
    """The final variant swaps the plan rate for the negotiated 449 bps and caps holdback at the gap.

    PRD: "The discount rate actually billed, recorded as `effective_discount_bps`, is the merchant's `negotiated_discount_bps` from the governing enrollment when one was agreed, and the plan's `merchant_discount_bps` when it was left unset."

    Design: Corner/calculations/provisional_variant_is_written_at_creation_and_frozen_at_settlement
    """
    scenario = S.project_with_milestones(api, verify=(0,))
    S.request_draw(api, scenario, 1050000)

    draw = S.settle_draw(api, scenario)

    # discount 1050000 * 449 / 10000 = 47145; holdback min(52500 base, 42000 gap, 157500 cap)
    assert_fields(
        draw,
        status="SETTLED",
        effective_discount_bps=449,
        volume_tier_credit_bps=0,
        merchant_discount_cents=bps_of(1050000, C.NEGOTIATED_DISCOUNT_BPS),
        holdback_withheld_cents=min(52500, bps_of(1050000, 400), bps_of(1050000, 1500)),
        net_settlement_cents=1050000 - 47145 - 42000,
    )
    assert (draw["merchant_discount_cents"], draw["holdback_withheld_cents"]) == (47145, 42000)
    assert draw["net_settlement_cents"] == 960855


def test_settlement_leaves_the_provisional_estimate_frozen_for_reconciliation(api):
    """The provisional trio still reads 55125 / 52500 / 942375 after the real figures land.

    PRD: "The provisional view ignores the merchant's `negotiated_discount_bps`, ignores `settlement_speed`, ignores volume tiers entirely, and computes holdback from the trade rate alone with no reserve-target gap and no per-draw cap."

    Design: Corner/calculations/provisional_variant_is_written_at_creation_and_frozen_at_settlement
    """
    scenario = S.project_with_milestones(api, verify=(0,))
    S.request_draw(api, scenario, 1050000)
    S.settle_draw(api, scenario)

    draw = S.read_draw(api, scenario.draw["id"])

    assert_fields(
        draw,
        provisional_discount_cents=55125,
        provisional_holdback_cents=52500,
        provisional_net_settlement_cents=942375,
        settled_on=C.DEFAULT_CLOCK_DATE,
        released_by_user_id=SERVICING_AGENT_ID,
    )

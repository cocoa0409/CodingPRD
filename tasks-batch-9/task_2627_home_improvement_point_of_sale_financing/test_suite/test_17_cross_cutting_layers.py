"""Several mechanisms layered inside one request.

Each test here stacks an optimistic-concurrency guard, an ordered check sequence
and a derived cascade on top of the same write, and asserts both the winning
outcome and the absence of the side effects a losing check would have written.
The harness restarts the server and empties the store before each test, with the
logical clock at 2026-08-01T00:00:00Z.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import types as T
from test_helpers.assertions import (
    assert_chargeback_conserved,
    assert_fields,
    bps_of,
    round_half_up,
)
from test_helpers.test_users import AGENT_HEADERS, ADMIN_HEADERS, SECOND_AGENT_HEADERS


# ─── Shared builders ──────────────────────────────────

def _one_settled_draw(api):
    """A merchant with a single settled draw of 1050000: reserve 42000 == target, coverage 10000."""
    return S.settled_draw(api, amount_cents=1050000, releases=(3000,), verify=(0,))


def _two_verified_milestones(api):
    """A project whose first two milestones (3000 + 4000 bps) are VERIFIED, nothing drawn yet."""
    return S.project_with_milestones(api, releases=(3000, 4000), verify=(0, 1))


# ─── A replayed merchant version cannot move the reserve twice ───────

def test_the_replayed_holdback_deposit_is_rejected_as_stale(api):
    """The second post of the same deposit carries a spent version and writes nothing.

    PRD: "If it does not equal the merchant's current `version` — because a draw settled and withheld holdback, or a chargeback absorbed reserve, since the client read the record — the request is rejected with `ERR_STALE_MERCHANT_VERSION` and HTTP 412, and no reserve movement is written."

    Design: Corner/cross_cutting_complexity_layers/holdback_adjustment_rejects_the_replayed_merchant_version
    """
    scenario = _one_settled_draw(api)
    version_1 = S.merchant_version(api, scenario.merchant_id)
    payload = F.holdback_adjustment_payload("DEPOSIT", 500, version_1)

    first = validate_success(
        api.post_holdback_adjustment(scenario.merchant_id, payload, AGENT_HEADERS)
    )
    # 42000 + 500 against an unchanged 42000 target: 425000000 / 42000 = 10119.0476 -> 10119.
    assert_fields(
        first,
        holdback_reserve_cents=42500,
        holdback_target_cents=42000,
        reserve_coverage_bps=round_half_up(42500 * 10000, 42000),
        version=version_1 + 1,
    )

    replay = api.post_holdback_adjustment(scenario.merchant_id, payload, AGENT_HEADERS)
    validate_error(replay, E.ERR_STALE_MERCHANT_VERSION)

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=42500,
        holdback_target_cents=42000,
        reserve_coverage_bps=10119,
        version=version_1 + 1,
        enrollment_status="APPROVED",
    )


def test_the_same_deposit_lands_once_the_version_is_read_again(api):
    """Re-reading the merchant supplies the fresh version, and the intended second deposit lands.

    PRD: "Either way `reserve_coverage_bps` is recomputed against the unchanged `holdback_target_cents` and the merchant's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/holdback_adjustment_rejects_the_replayed_merchant_version
    """
    scenario = _one_settled_draw(api)
    version_1 = S.merchant_version(api, scenario.merchant_id)
    validate_success(
        api.post_holdback_adjustment(
            scenario.merchant_id,
            F.holdback_adjustment_payload("DEPOSIT", 500, version_1),
            AGENT_HEADERS,
        )
    )

    version_2 = S.merchant_version(api, scenario.merchant_id)
    assert version_2 == version_1 + 1, "One deposit is exactly one version bump"

    second = validate_success(
        api.post_holdback_adjustment(
            scenario.merchant_id,
            F.holdback_adjustment_payload("DEPOSIT", 500, version_2),
            AGENT_HEADERS,
        )
    )
    # 42000 + 1000 against an unchanged 42000 target: 430000000 / 42000 = 10238.0952 -> 10238.
    assert_fields(
        second,
        holdback_reserve_cents=43000,
        holdback_target_cents=42000,
        reserve_coverage_bps=round_half_up(43000 * 10000, 42000),
        version=version_1 + 2,
        enrollment_status="APPROVED",
    )


# ─── A settlement invalidates the loan version a draw was sized against ──

def test_a_draw_requested_on_the_pre_settlement_loan_version_is_rejected(api):
    """The version read before a settlement is stale afterwards, and no second draw is recorded.

    PRD: "A mismatch with the account's current `version` is rejected with `ERR_STALE_LOAN_ACCOUNT_VERSION` and HTTP 412, because the staged-funding headroom the client used to size `requested_amount_cents` may already have been consumed by a settlement the client has not seen."

    Design: Corner/cross_cutting_complexity_layers/funding_draw_creation_rejects_a_stale_loan_account_version
    """
    scenario = _two_verified_milestones(api)
    version_1 = S.loan_version(api, scenario.loan_id)
    S.request_draw(api, scenario, 1000000, milestone_index=0, expected_version=version_1)
    S.settle_draw(api, scenario)
    # 3500000 * min(7000, 7000) / 10000 = 2450000, less the 1000000 already settled.
    assert_fields(
        S.read_project(api, scenario.project_id), max_fundable_now_cents=1450000
    )
    assert_fields(S.read_loan(api, scenario.loan_id), principal_balance_cents=1000000)

    stale = api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id, scenario.milestone_id(1), 1400000, version_1
        ),
        scenario.as_merchant,
    )
    validate_error(stale, E.ERR_STALE_LOAN_ACCOUNT_VERSION)

    _draws, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert meta["total_count"] == 1, "The rejected draw must not have been recorded"
    assert S.loan_version(api, scenario.loan_id) == version_1 + 1, (
        "Only the settlement bumped the account"
    )


def test_the_reissued_draw_carries_the_plan_level_provisional_economics(api):
    """Re-issued against the fresh version the draw is created, and creation does not bump the account.

    PRD: "The provisional view deliberately uses only plan-level and trade-level rates: `provisional_discount_cents` is `funded_amount_cents` multiplied by the promotion plan's `merchant_discount_bps`, divided by ten thousand and rounded half up; `provisional_holdback_cents` is `funded_amount_cents` multiplied by the trade rule's `holdback_pct_bps`, divided by ten thousand and rounded half up; and `provisional_net_settlement_cents` is `funded_amount_cents` reduced by `provisional_discount_cents` and reduced again by `provisional_holdback_cents`."

    Design: Corner/cross_cutting_complexity_layers/funding_draw_creation_rejects_a_stale_loan_account_version
    """
    scenario = _two_verified_milestones(api)
    version_1 = S.loan_version(api, scenario.loan_id)
    S.request_draw(api, scenario, 1000000, milestone_index=0, expected_version=version_1)
    S.settle_draw(api, scenario)
    version_2 = S.loan_version(api, scenario.loan_id)

    draw = validate_success(
        api.create_funding_draw(
            F.funding_draw_payload(
                scenario.loan_id, scenario.milestone_id(1), 1400000, version_2
            ),
            scenario.as_merchant,
        ),
        201,
    )
    discount = bps_of(1400000, C.DEFERRED_INTEREST_PLAN["merchant_discount_bps"])
    holdback = bps_of(1400000, C.ROOFING_TRADE_RULE["holdback_pct_bps"])
    assert (discount, holdback) == (73500, 70000), "Plan 525 bps and trade 500 bps"
    assert_fields(
        draw,
        status="REQUESTED",
        funded_amount_cents=1400000,
        provisional_discount_cents=discount,
        provisional_holdback_cents=holdback,
        provisional_net_settlement_cents=1400000 - discount - holdback,
    )
    assert S.loan_version(api, scenario.loan_id) == version_2, (
        "Creating a REQUESTED draw leaves the parent account version alone"
    )


# ─── A settlement invalidates the merchant version a resolver read ───

def _answered_dispute_then_second_settlement(api):
    """A dispute answered with evidence, after which a second draw settles and bumps the merchant."""
    scenario = S.settled_draw(
        api, amount_cents=1050000, releases=(3000, 4000), verify=(0, 1)
    )
    case = S.file_dispute(api, scenario, 50000)
    validate_success(
        api.respond_to_dispute(
            case["id"],
            F.merchant_response_payload("WORK_COMPLETE_EVIDENCE"),
            scenario.as_merchant,
        )
    )
    version_1 = S.merchant_version(api, scenario.merchant_id)
    S.request_draw(api, scenario, 400000, milestone_index=1)
    settlement = S.settle_draw(api, scenario)
    return scenario, case["id"], version_1, settlement


def test_a_resolution_carrying_the_pre_settlement_merchant_version_is_rejected(api):
    """The second settlement spends the version the resolver read, and the refused resolution writes nothing.

    PRD: "A mismatch with the merchant's current `version` is rejected with `ERR_STALE_MERCHANT_VERSION` and HTTP 412 before any chargeback bucket is computed or written, since a resolver working from a stale merchant record would allocate against reserve and receivable figures that no longer exist."

    Design: Corner/cross_cutting_complexity_layers/dispute_resolution_rejects_a_merchant_version_bumped_by_a_settlement
    """
    scenario, case_id, version_1, settlement = _answered_dispute_then_second_settlement(api)
    # min(base 20000, gap round_half_up(1450000 * 400 / 10000) - 42000 = 16000, cap 60000).
    assert_fields(
        settlement,
        holdback_withheld_cents=16000,
        merchant_discount_cents=bps_of(400000, C.NEGOTIATED_DISCOUNT_BPS),
        net_settlement_cents=400000 - 17960 - 16000,
    )
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=58000,
        holdback_target_cents=58000,
        reserve_coverage_bps=10000,
    )

    stale = api.resolve_dispute(
        case_id, F.resolution_payload("MERCHANT_FAVOR", version_1), SECOND_AGENT_HEADERS
    )
    validate_error(stale, E.ERR_STALE_MERCHANT_VERSION)

    assert_fields(
        S.read_dispute(api, case_id),
        status="MERCHANT_RESPONSE_PENDING",
        chargeback_amount_cents=0,
    )
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        settlement_offset_receivable_cents=0,
        holdback_reserve_cents=58000,
        version=version_1 + 1,
    )


def test_the_resolution_lands_on_the_version_the_settlement_left_behind(api):
    """Reading the merchant again yields the version that resolves the case in the merchant's favour.

    PRD: "The merchant keeps the funds: `chargeback_amount_cents` stays at zero and there is no reserve, receivable or write-off movement of any kind."

    Design: Corner/cross_cutting_complexity_layers/dispute_resolution_rejects_a_merchant_version_bumped_by_a_settlement
    """
    scenario, case_id, version_1, _settlement = _answered_dispute_then_second_settlement(api)
    version_2 = S.merchant_version(api, scenario.merchant_id)
    assert version_2 == version_1 + 1, "The second settlement is the only bump"

    resolved = validate_success(
        api.resolve_dispute(
            case_id,
            F.resolution_payload("MERCHANT_FAVOR", version_2),
            SECOND_AGENT_HEADERS,
        )
    )
    assert_fields(
        resolved,
        status="RESOLVED_MERCHANT_FAVOR",
        chargeback_amount_cents=0,
        chargeback_absorbed_from_reserve_cents=0,
        chargeback_receivable_cents=0,
        chargeback_write_off_cents=0,
    )
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=58000,
        holdback_target_cents=58000,
        settlement_offset_receivable_cents=0,
        program_write_off_cents=0,
        version=version_2 + 1,
    )


# ─── One cent decides whether reserve coverage suspends the merchant ──

def _two_settled_projects(api):
    """One merchant, two homeowners, two settled draws: reserve 96002 == target, coverage 10000."""
    first = S.settled_draw(
        api,
        amount_cents=1000050,
        settlement_speed="NEXT_DAY",
        releases=(3000,),
        verify=(0,),
    )
    second = S.Scenario()
    second.trade_rule = first.trade_rule
    second.plan = first.plan
    second.merchant = first.merchant
    second.enrollment = first.enrollment
    S.application(api, second, consumer={"full_name": "Owen Trask", "ssn_last4": "5150"})
    S.disclosed_application(api, second)
    S.activated_loan(api, second)
    S.project(api, second)
    S.add_milestones(api, second, (4000,))
    S.claim_milestone(api, second, 0)
    S.verify_milestone(api, second, 0)
    S.request_draw(api, second, 1400000)
    S.settle_draw(api, second)
    return first, second


def _resolve_in_consumer_favour(api, scenario, claimed_cents):
    """File a claim on the scenario's project and resolve it for the homeowner as a second agent."""
    case = S.file_dispute(api, scenario, claimed_cents)
    return validate_success(
        api.resolve_dispute(
            case["id"],
            F.resolution_payload(
                "CONSUMER_FAVOR", S.merchant_version(api, scenario.merchant_id)
            ),
            SECOND_AGENT_HEADERS,
        )
    )


def test_a_chargeback_that_lands_exactly_on_the_coverage_floor_leaves_the_merchant_approved(api):
    """Coverage of exactly 5000 bps is not below the floor, so the merchant stays APPROVED.

    PRD: "The third hop is caused by the second: if the recomputed `reserve_coverage_bps` has fallen below five thousand — below half the target reserve — the merchant moves `APPROVED → SUSPENDED` with `suspension_reason_code` recorded as `RESERVE_COVERAGE`."

    Design: Corner/cross_cutting_complexity_layers/reserve_coverage_suspension_fires_one_cent_below_the_5000_bps_floor
    """
    first, _second = _two_settled_projects(api)
    # min(base 50003, gap 40002, cap 150008) then min(base 70000, gap 56000, cap 210000).
    assert_fields(
        S.read_merchant(api, first.merchant_id),
        holdback_reserve_cents=96002,
        holdback_target_cents=96002,
        reserve_coverage_bps=C.FULL_COVERAGE_BPS,
        risk_tier="STANDARD",
    )

    resolved = _resolve_in_consumer_favour(api, first, 48005)
    assert_fields(
        resolved,
        status="RESOLVED_CONSUMER_FAVOR",
        chargeback_amount_cents=48005,
        chargeback_absorbed_from_reserve_cents=48005,
        chargeback_receivable_cents=0,
        chargeback_write_off_cents=0,
    )
    assert_chargeback_conserved(resolved)
    # 479970000 / 96002 = 4999.5834, which rounds half up to exactly the 5000 floor.
    assert_fields(
        S.read_merchant(api, first.merchant_id),
        holdback_reserve_cents=47997,
        holdback_target_cents=96002,
        reserve_coverage_bps=round_half_up(47997 * 10000, 96002),
        enrollment_status="APPROVED",
    )
    assert_fields(
        validate_success(
            api.get_promotion_enrollment(first.enrollment["id"], ADMIN_HEADERS)
        ),
        status="ACTIVE",
    )
    assert_fields(S.read_project(api, first.project_id), completion_status="ABANDONED")
    assert_fields(S.read_loan(api, first.loan_id), principal_balance_cents=952045)


def test_one_further_cent_of_chargeback_suspends_the_merchant_and_its_enrollment(api):
    """A single extra cent drops coverage to 4999 bps, firing the suspension and its cascade.

    PRD: "The fourth hop is caused by the third: every promotion enrollment of that merchant standing at `ACTIVE` moves to `SUSPENDED`, and every funding draw of that merchant standing at `REQUESTED` moves to `DENIED` with `denial_reason_code` recorded as `MERCHANT_SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/reserve_coverage_suspension_fires_one_cent_below_the_5000_bps_floor
    """
    first, second = _two_settled_projects(api)
    _resolve_in_consumer_favour(api, first, 48005)

    resolved = _resolve_in_consumer_favour(api, second, 1)
    assert_fields(
        resolved,
        status="RESOLVED_CONSUMER_FAVOR",
        chargeback_amount_cents=1,
        chargeback_absorbed_from_reserve_cents=1,
        chargeback_receivable_cents=0,
        chargeback_write_off_cents=0,
    )
    # 479960000 / 96002 = 4999.4791, which rounds half up to 4999 — strictly below the floor.
    assert_fields(
        S.read_merchant(api, first.merchant_id),
        holdback_reserve_cents=47996,
        holdback_target_cents=96002,
        reserve_coverage_bps=round_half_up(47996 * 10000, 96002),
        enrollment_status="SUSPENDED",
        suspension_reason_code="RESERVE_COVERAGE",
    )
    assert_fields(
        validate_success(
            api.get_promotion_enrollment(first.enrollment["id"], ADMIN_HEADERS)
        ),
        status="SUSPENDED",
    )
    assert_fields(S.read_project(api, second.project_id), completion_status="ABANDONED")
    assert_fields(S.read_loan(api, second.loan_id), principal_balance_cents=1399999)


def test_both_homeowner_favour_resolutions_grade_the_merchant_for_termination(api):
    """Two counted disputes over two accounts give a 10000 bps dispute rate, grade D and termination.

    PRD: "Finally, `termination_recommended` is true whenever any one of three conditions holds: `portfolio_grade` is `D`, or `phantom_risk_score` has reached 60, or `dispute_rate_bps` has reached 2500."

    Design: Corner/cross_cutting_complexity_layers/reserve_coverage_suspension_fires_one_cent_below_the_5000_bps_floor
    """
    first, second = _two_settled_projects(api)
    _resolve_in_consumer_favour(api, first, 48005)
    _resolve_in_consumer_favour(api, second, 1)

    assert_fields(
        S.read_merchant(api, first.merchant_id),
        dispute_rate_bps=round_half_up(2 * 10000, 2),
        risk_tier="STANDARD",
        portfolio_grade="D",
        termination_recommended=True,
        phantom_risk_score=0,
    )


# ─── Escalation fires exactly at the response deadline ───────────────

def _unanswered_dispute(api):
    """A 50000 claim on a project funded by one 1050000 draw, with no merchant response on file."""
    scenario = _one_settled_draw(api)
    case = S.file_dispute(api, scenario, 50000)
    # Ten days after the 2026-08-01 filing, at midnight UTC.
    assert case["response_due_at"][:19] == "2026-08-11T00:00:00", case["response_due_at"]
    assert_fields(case, status="MERCHANT_RESPONSE_PENDING")
    return scenario, case


def test_the_checkpoint_one_second_before_the_deadline_escalates_nothing(api):
    """At 2026-08-10T23:59:59Z the deadline has not been reached, so every counter is zero.

    PRD: "And a dispute case standing at `MERCHANT_RESPONSE_PENDING` whose `response_due_at` the clock has reached or passed with `merchant_responded_at` still empty moves `MERCHANT_RESPONSE_PENDING → ESCALATED_NO_RESPONSE`."

    Design: Corner/cross_cutting_complexity_layers/dispute_escalation_fires_exactly_at_response_due_at
    """
    scenario, case = _unanswered_dispute(api)

    S.set_clock(api, "2026-08-10T23:59:59Z")
    counts = S.run_sweep(api)

    for key in T.SWEEP_COUNT_KEYS:
        assert counts[key] == 0, f"One second early nothing is due, but {key} was {counts[key]}"
    assert_fields(S.read_dispute(api, case["id"]), status="MERCHANT_RESPONSE_PENDING")
    assert_fields(S.read_merchant(api, scenario.merchant_id), holdback_reserve_cents=42000)


def test_the_checkpoint_at_the_deadline_escalates_the_silent_contractor(api):
    """At exactly 2026-08-11T00:00:00Z the case escalates and only that counter moves.

    PRD: "And a dispute case standing at `MERCHANT_RESPONSE_PENDING` whose `response_due_at` the clock has reached or passed with `merchant_responded_at` still empty moves `MERCHANT_RESPONSE_PENDING → ESCALATED_NO_RESPONSE`."

    Design: Corner/cross_cutting_complexity_layers/dispute_escalation_fires_exactly_at_response_due_at
    """
    _scenario, case = _unanswered_dispute(api)

    S.set_clock(api, "2026-08-11T00:00:00Z")
    counts = S.run_sweep(api)

    assert counts["escalated_disputes"] == 1, counts
    for key in T.SWEEP_COUNT_KEYS:
        if key != "escalated_disputes":
            assert counts[key] == 0, f"Only the dispute is due, but {key} was {counts[key]}"
    assert_fields(S.read_dispute(api, case["id"]), status="ESCALATED_NO_RESPONSE")


def test_a_second_checkpoint_at_the_same_clock_reports_all_zeros(api):
    """The escalation is not repeated when the checkpoint runs again without moving the clock.

    PRD: "It is idempotent for a fixed clock — run it twice without moving the clock and the second run reports all zeros."

    Design: Corner/cross_cutting_complexity_layers/dispute_escalation_fires_exactly_at_response_due_at
    """
    _scenario, case = _unanswered_dispute(api)
    S.set_clock(api, "2026-08-11T00:00:00Z")
    S.run_sweep(api)

    again = S.run_sweep(api)

    for key in T.SWEEP_COUNT_KEYS:
        assert again[key] == 0, f"The re-run must report zero, but {key} was {again[key]}"
    assert_fields(S.read_dispute(api, case["id"]), status="ESCALATED_NO_RESPONSE")


def test_an_escalated_case_cannot_be_resolved_in_the_merchants_favour(api):
    """Escalation closes the merchant's window, so a merchant-favour resolution is refused.

    PRD: "That escalation closes the merchant's window permanently: from `ESCALATED_NO_RESPONSE` only a homeowner-favour resolution remains reachable, and an attempt to resolve such a case in the merchant's favour is refused with `ERR_INVALID_DISPUTE_STATE`."

    Design: Corner/cross_cutting_complexity_layers/dispute_escalation_fires_exactly_at_response_due_at
    """
    scenario, case = _unanswered_dispute(api)
    S.set_clock(api, "2026-08-11T00:00:00Z")
    S.run_sweep(api)

    response = api.resolve_dispute(
        case["id"],
        F.resolution_payload(
            "MERCHANT_FAVOR", S.merchant_version(api, scenario.merchant_id)
        ),
        SECOND_AGENT_HEADERS,
    )
    validate_error(response, E.ERR_INVALID_DISPUTE_STATE)

    assert_fields(S.read_dispute(api, case["id"]), status="ESCALATED_NO_RESPONSE")
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=42000,
        enrollment_status="APPROVED",
    )


def test_an_escalated_case_resolved_for_the_homeowner_runs_the_whole_waterfall(api):
    """The homeowner-favour branch drains the reserve, opens a receivable and suspends the merchant.

    PRD: "The first bucket, `chargeback_absorbed_from_reserve_cents`, takes the lesser of the chargeback amount and the merchant's `holdback_reserve_cents` at resolution time — the reserve fills the claim first, and exactly."

    Design: Corner/cross_cutting_complexity_layers/dispute_escalation_fires_exactly_at_response_due_at
    """
    scenario, case = _unanswered_dispute(api)
    S.set_clock(api, "2026-08-11T00:00:00Z")
    S.run_sweep(api)

    resolved = validate_success(
        api.resolve_dispute(
            case["id"],
            F.resolution_payload(
                "CONSUMER_FAVOR", S.merchant_version(api, scenario.merchant_id)
            ),
            SECOND_AGENT_HEADERS,
        )
    )
    # Remainder 8000 against a ceiling of round_half_up(1050000 * 5000 / 10000) = 525000.
    assert_fields(
        resolved,
        status="RESOLVED_CONSUMER_FAVOR",
        chargeback_amount_cents=50000,
        chargeback_absorbed_from_reserve_cents=42000,
        chargeback_receivable_cents=8000,
        chargeback_write_off_cents=0,
        resolved_on="2026-08-11",
    )
    assert_chargeback_conserved(resolved)
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=0,
        holdback_target_cents=42000,
        reserve_coverage_bps=0,
        settlement_offset_receivable_cents=8000,
        program_write_off_cents=0,
        enrollment_status="SUSPENDED",
        suspension_reason_code="RESERVE_COVERAGE",
    )
    assert_fields(S.read_project(api, scenario.project_id), completion_status="ABANDONED")
    assert_fields(S.read_loan(api, scenario.loan_id), principal_balance_cents=1000000)

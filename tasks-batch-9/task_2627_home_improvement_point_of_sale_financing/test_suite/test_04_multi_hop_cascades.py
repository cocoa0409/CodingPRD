"""Multi-hop cascades that run entirely inside one request.

Two chains are pinned here.  A consumer-favour dispute resolution splits the
claim three ways, consumes the whole reserve, collapses coverage, suspends the
merchant and — through that suspension — suspends its enrollment and denies its
pending draw.  A confirmed fraud alert re-scores the merchant from half weight
to full weight, crosses the suspension threshold and drives the same downstream
suspension without moving a cent.

Every figure asserted below is the exact integer the contract's formulas yield
for the canonical ROOFING programme, and each test also pins the records the
contract says the cascade must leave alone.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import (
    assert_chargeback_conserved,
    assert_fields,
    assert_reserve_coverage,
    bps_of,
    ratio_bps,
    round_half_up,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    SECOND_AGENT_HEADERS,
)

# ─── Figures the contract's formulas yield for these scenarios ────────
#
# Draw 1 funds 1000050 cents against milestone 1 (3000 bps of a 3500000
# contract releases 1050000).  Its holdback is the smallest of the base
# withholding (500 bps -> 50003), the reserve-target gap (a STANDARD merchant's
# 400 bps of the 1000050 trailing volume, so 40002 - 0) and the per-draw
# ceiling (1500 bps -> 150008): 40002.
DRAW_ONE_CENTS = 1000050
DRAW_ONE_HOLDBACK_CENTS = 40002

# Draw 2 funds 1400000 more.  Trailing volume including it is 2400050, so the
# target becomes 96002 and the gap 96002 - 40002 = 56000, which is below the
# base withholding of 70000 and the ceiling of 210000.
DRAW_TWO_CENTS = 1400000
DRAW_TWO_HOLDBACK_CENTS = 56000

RESERVE_AFTER_TWO_DRAWS_CENTS = DRAW_ONE_HOLDBACK_CENTS + DRAW_TWO_HOLDBACK_CENTS  # 96002
SETTLED_FUNDED_CENTS = DRAW_ONE_CENTS + DRAW_TWO_CENTS  # 2400050

# Draw 3 exactly exhausts the remaining pre-completion headroom
# (7000 bps of 3500000 = 2450000, less 2400050 already settled).
DRAW_THREE_CENTS = 49950

# The homeowner disputes 1800000 of the 2400050 advanced.
CLAIM_CENTS = 1800000
ABSORBED_CENTS = RESERVE_AFTER_TWO_DRAWS_CENTS                     # 96002
RECEIVABLE_CENTS = 1200025                                          # 5000 bps of 2400050
WRITE_OFF_CENTS = CLAIM_CENTS - ABSORBED_CENTS - RECEIVABLE_CENTS   # 503973

OPEN_ALERT_WEIGHT = 35
CONFIRMED_ALERT_WEIGHT = 75


# ─── Scenario builders ────────────────────────────────────────────────

def _build_dispute_ready_book(api) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    """Two settled draws, one draw left `REQUESTED`, and an open dispute case."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000, 3000), verify=(0,))
    S.request_draw(api, scenario, DRAW_ONE_CENTS, 0, "NEXT_DAY")
    S.settle_draw(api, scenario)
    S.claim_milestone(api, scenario, 1)
    S.verify_milestone(api, scenario, 1)
    S.request_draw(api, scenario, DRAW_TWO_CENTS, 1, "STANDARD_3DAY")
    S.settle_draw(api, scenario)
    S.claim_milestone(api, scenario, 2)
    S.verify_milestone(api, scenario, 2)
    pending_draw = S.request_draw(api, scenario, DRAW_THREE_CENTS, 2, "STANDARD_3DAY")
    case = S.file_dispute(api, scenario, CLAIM_CENTS)
    return scenario, pending_draw, case


def _resolve_for_consumer(api, scenario, case_id):
    """Resolve in the homeowner's favour as an agent who released no draw here."""
    version = S.merchant_version(api, scenario.merchant_id)
    return api.resolve_dispute(
        case_id,
        F.resolution_payload("CONSUMER_FAVOR", version),
        SECOND_AGENT_HEADERS,
    )


def _build_open_alert_book(api) -> Tuple[Any, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """One settled draw, one `REQUESTED` draw, and two `OPEN` analyst alerts."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000), verify=(0, 1))
    S.request_draw(api, scenario, DRAW_ONE_CENTS, 0, "NEXT_DAY")
    S.settle_draw(api, scenario)
    pending_draw = S.request_draw(api, scenario, DRAW_TWO_CENTS, 1, "STANDARD_3DAY")
    low_alert = S.raise_fraud_alert(
        api, scenario.merchant_id, "PHANTOM_PROJECT", OPEN_ALERT_WEIGHT
    )
    high_alert = S.raise_fraud_alert(
        api, scenario.merchant_id, "DUPLICATE_CONSUMER", CONFIRMED_ALERT_WEIGHT
    )
    return scenario, pending_draw, low_alert, high_alert


def _confirm_alert(api, merchant_id, alert_id):
    return api.investigate_fraud_alert(
        merchant_id,
        alert_id,
        F.investigation_payload("CONFIRMED", investigation_note="Fabricated address"),
        ANALYST_HEADERS,
    )


# ─── Hop 1: the chargeback waterfall ──────────────────────────────────

def test_consumer_favour_resolution_splits_claim_across_three_buckets(api):
    """A consumer-favour resolution fills reserve first, then the capped receivable, then write-off.

    PRD: "The first bucket, `chargeback_absorbed_from_reserve_cents`, takes the lesser of the chargeback amount and the merchant's `holdback_reserve_cents` at resolution time — the reserve fills the claim first, and exactly."

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, _pending, case = _build_dispute_ready_book(api)

    response = _resolve_for_consumer(api, scenario, case["id"])
    resolved = validate_success(response, 200)

    # 5000 bps of the 2400050 trailing-180-day settled volume caps the receivable.
    assert RECEIVABLE_CENTS == bps_of(SETTLED_FUNDED_CENTS, 5000)
    assert_fields(
        resolved,
        status="RESOLVED_CONSUMER_FAVOR",
        chargeback_amount_cents=CLAIM_CENTS,
        chargeback_absorbed_from_reserve_cents=ABSORBED_CENTS,
        chargeback_receivable_cents=RECEIVABLE_CENTS,
        chargeback_write_off_cents=WRITE_OFF_CENTS,
    )
    assert_chargeback_conserved(resolved)


# ─── Hop 2: caused by hop 1 ───────────────────────────────────────────

def test_absorbed_reserve_collapses_coverage_against_an_unchanged_target(api):
    """The absorbed bucket empties reserve while the holdback target stands still, so coverage hits zero.

    PRD: "The second hop is caused by the first: the merchant's `holdback_reserve_cents` falls by the absorbed amount, its `settlement_offset_receivable_cents` rises by the receivable amount, its `program_write_off_cents` rises by the written-off amount, and `reserve_coverage_bps` is recomputed against an **unchanged** `holdback_target_cents` — a consumer-favour resolution consumes reserve without lowering the target, which is exactly what makes coverage collapse."

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, _pending, case = _build_dispute_ready_book(api)
    before = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        before,
        holdback_reserve_cents=RESERVE_AFTER_TWO_DRAWS_CENTS,
        holdback_target_cents=RESERVE_AFTER_TWO_DRAWS_CENTS,
        reserve_coverage_bps=C.FULL_COVERAGE_BPS,
    )

    validate_success(_resolve_for_consumer(api, scenario, case["id"]), 200)

    after = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        after,
        holdback_reserve_cents=0,
        settlement_offset_receivable_cents=RECEIVABLE_CENTS,
        program_write_off_cents=WRITE_OFF_CENTS,
        holdback_target_cents=RESERVE_AFTER_TWO_DRAWS_CENTS,
        reserve_coverage_bps=0,
    )
    assert_reserve_coverage(after)


def test_chargeback_debits_principal_and_leaves_funded_volume_and_settled_draws_alone(api):
    """Principal falls by the chargeback while funded volume, the holdback target and both settled draws stand.

    PRD: "It reduces the loan account's principal by the chargeback amount and leaves the merchant's `funded_volume_cents`, its `holdback_target_cents` and every settled draw untouched, because reversing the draws as well would debit the same advance twice."

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, _pending, case = _build_dispute_ready_book(api)
    settled_ids = [scenario.draws[0]["id"], scenario.draws[1]["id"]]

    validate_success(_resolve_for_consumer(api, scenario, case["id"]), 200)

    loan = S.read_loan(api, scenario.loan_id)
    assert_fields(
        loan,
        principal_balance_cents=SETTLED_FUNDED_CENTS - CLAIM_CENTS,  # 2400050 - 1800000
        total_funded_cents=SETTLED_FUNDED_CENTS,
    )
    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        funded_volume_cents=SETTLED_FUNDED_CENTS,
        holdback_target_cents=RESERVE_AFTER_TWO_DRAWS_CENTS,
    )
    for draw_id in settled_ids:
        assert_fields(S.read_draw(api, draw_id), status="SETTLED")


# ─── Hop 3: caused by hop 2 ───────────────────────────────────────────

def test_collapsed_coverage_suspends_the_merchant_for_reserve_coverage(api):
    """Coverage falling below five thousand basis points is what suspends the merchant.

    PRD: "The third hop is caused by the second: if the recomputed `reserve_coverage_bps` has fallen below five thousand — below half the target reserve — the merchant moves `APPROVED → SUSPENDED` with `suspension_reason_code` recorded as `RESERVE_COVERAGE`."

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, _pending, case = _build_dispute_ready_book(api)
    assert_fields(S.read_merchant(api, scenario.merchant_id), enrollment_status="APPROVED")

    validate_success(_resolve_for_consumer(api, scenario, case["id"]), 200)

    merchant = S.read_merchant(api, scenario.merchant_id)
    assert merchant["reserve_coverage_bps"] < C.RESERVE_COVERAGE_FLOOR_BPS
    assert_fields(
        merchant,
        enrollment_status="SUSPENDED",
        suspension_reason_code="RESERVE_COVERAGE",
    )


# ─── Hop 4: caused by hop 3 ───────────────────────────────────────────

def test_suspension_suspends_the_enrollment_and_denies_the_pending_draw(api):
    """The suspension itself suspends the active enrollment and denies the requested draw.

    PRD: "The fourth hop is caused by the third: every promotion enrollment of that merchant standing at `ACTIVE` moves to `SUSPENDED`, and every funding draw of that merchant standing at `REQUESTED` moves to `DENIED` with `denial_reason_code` recorded as `MERCHANT_SUSPENDED`."

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, pending_draw, case = _build_dispute_ready_book(api)
    enrollment_id = scenario.enrollment["id"]
    assert_fields(
        get_success_data(api.get_promotion_enrollment(enrollment_id, ADMIN_HEADERS)),
        status="ACTIVE",
    )
    assert_fields(S.read_draw(api, pending_draw["id"]), status="REQUESTED")

    validate_success(_resolve_for_consumer(api, scenario, case["id"]), 200)

    assert_fields(
        get_success_data(api.get_promotion_enrollment(enrollment_id, ADMIN_HEADERS)),
        status="SUSPENDED",
    )
    assert_fields(
        S.read_draw(api, pending_draw["id"]),
        status="DENIED",
        denial_reason_code="MERCHANT_SUSPENDED",
    )


def test_consumer_favour_resolution_abandons_the_project_and_zeroes_its_headroom(api):
    """The disputed project is abandoned and can fund nothing further.

    PRD: "Abandonment clears `completion_certificate_ref` and `certified_on`, recomputes `settled_funded_cents` and `funded_pct_bps`, and drives `max_fundable_now_cents` to zero; no further draw may be requested against the project, and an attempt is refused with `ERR_INVALID_PROJECT_STATE`."

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, _pending, case = _build_dispute_ready_book(api)

    validate_success(_resolve_for_consumer(api, scenario, case["id"]), 200)

    project = S.read_project(api, scenario.project_id)
    assert_fields(
        project,
        completion_status="ABANDONED",
        settled_funded_cents=SETTLED_FUNDED_CENTS,
        max_fundable_now_cents=0,
        disputed_amount_cents=0,
        funded_pct_bps=ratio_bps(SETTLED_FUNDED_CENTS, 3500000),  # 2400050/3500000 -> 6857
    )
    assert project["funded_pct_bps"] == 6857


def test_consumer_favour_resolution_reprices_the_merchant_portfolio(api):
    """The resolved-consumer-favour case counts toward the dispute rate, grading the merchant D.

    PRD: "Otherwise, `dispute_rate_bps` is the count of that merchant's dispute cases standing at `SUBMITTED`, `MERCHANT_RESPONSE_PENDING`, `ESCALATED_NO_RESPONSE` or `RESOLVED_CONSUMER_FAVOR`"

    Design: Difficulty/transitive_cascade/consumer_favor_resolution_four_hop_reserve_suspension_cascade
    """
    scenario, _pending, case = _build_dispute_ready_book(api)

    validate_success(_resolve_for_consumer(api, scenario, case["id"]), 200)

    merchant = S.read_merchant(api, scenario.merchant_id)
    # One counted case over one loan account: 1 * 10000 / 1.
    assert_fields(
        merchant,
        dispute_rate_bps=ratio_bps(1, 1),
        delinquency_rate_bps=0,
        phantom_risk_score=0,
        portfolio_grade="D",
        termination_recommended=True,
    )
    assert merchant["dispute_rate_bps"] == 10000


# ─── The fraud-confirmation chain ─────────────────────────────────────

def test_confirming_one_alert_moves_it_from_half_weight_to_full_weight(api):
    """Confirming the heavier alert re-scores the merchant from 55 to 93 in one request.

    PRD: "Then halve the **aggregate** open total once — dividing it by two and rounding half up — and add the confirmed total, clamping the result at 100."

    Design: Difficulty/transitive_cascade/confirmed_fraud_alert_three_hop_suspension_cascade
    """
    scenario, _pending, low_alert, high_alert = _build_open_alert_book(api)
    # Both alerts open: 0 confirmed + round_half_up((35 + 75) / 2) = 55.
    before_score = 0 + round_half_up(OPEN_ALERT_WEIGHT + CONFIRMED_ALERT_WEIGHT, 2)
    assert before_score == 55
    assert_fields(S.read_merchant(api, scenario.merchant_id), phantom_risk_score=55)

    validate_success(_confirm_alert(api, scenario.merchant_id, high_alert["id"]), 200)

    alerts = get_success_data(
        api.list_fraud_alerts(scenario.merchant_id, ANALYST_HEADERS)
    )
    by_id = {alert["id"]: alert for alert in alerts}
    assert_fields(
        by_id[high_alert["id"]],
        status="CONFIRMED",
        investigated_by_user_id=ANALYST_HEADERS["X-User-ID"],
    )
    assert_fields(by_id[low_alert["id"]], status="OPEN")
    # 75 confirmed + round_half_up(35 / 2) = 75 + 18 = 93.
    expected_score = CONFIRMED_ALERT_WEIGHT + round_half_up(OPEN_ALERT_WEIGHT, 2)
    assert expected_score == 93
    assert_fields(S.read_merchant(api, scenario.merchant_id), phantom_risk_score=93)


def test_score_reaching_sixty_suspends_the_merchant_for_confirmed_fraud(api):
    """The re-scored phantom risk crossing sixty is what suspends an approved merchant.

    PRD: "`OPEN → CONFIRMED` sets off three hops: first the merchant's `phantom_risk_score` is recomputed with this alert now counting at its full `severity_weight` rather than half; caused by that, `risk_tier`, `portfolio_grade` and `termination_recommended` are recomputed, and if the recomputed `phantom_risk_score` has reached 60 while the merchant is `APPROVED`, the merchant moves `APPROVED → SUSPENDED` with `suspension_reason_code` recorded as `FRAUD_CONFIRMED`; and caused by that suspension, every promotion enrollment of that merchant standing at `ACTIVE` moves to `SUSPENDED` and every funding draw standing at `REQUESTED` moves to `DENIED`."

    Design: Difficulty/transitive_cascade/confirmed_fraud_alert_three_hop_suspension_cascade
    """
    scenario, _pending, _low_alert, high_alert = _build_open_alert_book(api)
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        enrollment_status="APPROVED",
        portfolio_grade="C",
        termination_recommended=False,
    )

    validate_success(_confirm_alert(api, scenario.merchant_id, high_alert["id"]), 200)

    merchant = S.read_merchant(api, scenario.merchant_id)
    assert merchant["phantom_risk_score"] >= C.PHANTOM_SUSPENSION_THRESHOLD
    assert_fields(
        merchant,
        enrollment_status="SUSPENDED",
        suspension_reason_code="FRAUD_CONFIRMED",
        portfolio_grade="D",
        termination_recommended=True,
        risk_tier="STANDARD",
    )


def test_fraud_suspension_suspends_the_enrollment_and_denies_the_requested_draw(api):
    """The fraud suspension cascades onward into the enrollment and the pending draw.

    PRD: "Suspension cascades twice: every promotion enrollment of that merchant standing at `ACTIVE` moves to `SUSPENDED`, and every funding draw of that merchant standing at `REQUESTED` moves to `DENIED` with `denial_reason_code` recorded as `MERCHANT_SUSPENDED`."

    Design: Difficulty/transitive_cascade/confirmed_fraud_alert_three_hop_suspension_cascade
    """
    scenario, pending_draw, _low_alert, high_alert = _build_open_alert_book(api)
    enrollment_id = scenario.enrollment["id"]

    validate_success(_confirm_alert(api, scenario.merchant_id, high_alert["id"]), 200)

    assert_fields(
        get_success_data(api.get_promotion_enrollment(enrollment_id, ADMIN_HEADERS)),
        status="SUSPENDED",
    )
    assert_fields(
        S.read_draw(api, pending_draw["id"]),
        status="DENIED",
        denial_reason_code="MERCHANT_SUSPENDED",
    )
    assert_fields(S.read_draw(api, scenario.draws[0]["id"]), status="SETTLED")


def test_fraud_cascade_denial_moves_no_money_at_all(api):
    """Denying the pending draw through the fraud cascade leaves every ledger figure where it was.

    PRD: "The `REQUESTED → DENIED` branch is the mirror image and its restraint is the point: it records `denial_reason_code` and touches no money whatsoever."

    Design: Difficulty/transitive_cascade/confirmed_fraud_alert_three_hop_suspension_cascade
    """
    scenario, _pending, _low_alert, high_alert = _build_open_alert_book(api)

    validate_success(_confirm_alert(api, scenario.merchant_id, high_alert["id"]), 200)

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        holdback_reserve_cents=DRAW_ONE_HOLDBACK_CENTS,
        holdback_target_cents=DRAW_ONE_HOLDBACK_CENTS,
        funded_volume_cents=DRAW_ONE_CENTS,
        settlement_offset_receivable_cents=0,
        program_write_off_cents=0,
    )
    assert_fields(
        S.read_loan(api, scenario.loan_id),
        principal_balance_cents=DRAW_ONE_CENTS,
        total_funded_cents=DRAW_ONE_CENTS,
    )
    settled, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id,
                                              "status": "SETTLED"})
    )
    assert meta["total_count"] == 1, "Only the first draw ever settled"
    assert settled[0]["funded_amount_cents"] == DRAW_ONE_CENTS

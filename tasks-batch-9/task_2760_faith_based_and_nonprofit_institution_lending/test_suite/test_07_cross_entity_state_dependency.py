"""
Queue A — §1.8 rule ``cross_entity_state_dependency``.

In both instances the answer to an unchanged request is decided by the state of a
third entity: a covenant decides whether a workout may be proposed, and a
covenant — not the loan's posture — decides whether cash may leave.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.assertions import (
    assert_fields,
    assert_loan_ledger,
    assert_nulls,
    assert_ratio,
    assert_score,
)
from test_helpers.factories import (
    REFERENCE_AUDITED_QUARTERS,
    REFERENCE_INTERNAL_2026Q1,
    covenant_test_payload,
    draw_disbursement_payload,
    forbearance_payload,
    term_extension_payload,
    workout_approval_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_covenant,
    chain_through_loan,
)
from test_helpers.test_users import (
    COMMITTEE_1,
    COMMITTEE_MEMBER,
    CREDIT_ANALYST,
    LOAN_SERVICER,
)

FIVE_PERIODS = list(REFERENCE_AUDITED_QUARTERS) + [REFERENCE_INTERNAL_2026Q1]
FORBEARANCE_NARRATIVE = "Forbearance while the congregation completes its stewardship campaign"


def _five_period_loan(api):
    """
    The reference borrower with the four 2025 AUDITED periods plus the 2026Q1 INTERNAL
    period, funded at 225000000 with annual_debt_service_cents 36000000 and no interest
    reserve shortfall, plus one DSCR covenant at 1.2500 that the 1.2000 actual will fail.
    """
    chain = chain_through_loan(
        api,
        period_specs=FIVE_PERIODS,
        loan_overrides={
            "annual_debt_service_cents": 36000000,
            "interest_reserve_shortfall_cents": 0,
        },
    )
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2500)
    return chain, covenant


def test_workout_proposal_is_refused_while_the_loan_is_still_performing(api):
    """
    The plan's own body is valid; only the loan's posture — derived from a covenant — refuses it.

    PRD §3.9: "A workout plan is proposed by a `LoanServicer` against a `loan_id` whose
    loan is already showing distress: `risk_posture` must be `WATCH`, `RESTRICTED` or
    `WORKOUT_GATED`, and a proposal against a loan in `OPEN` is refused with
    `ERR_WORKOUT_INVALID_STATE`."

    PRD §3.8: "Writing it re-evaluates the loan's risk posture, which cannot change as a
    result — a brand-new covenant is compliant by construction."

    Design: Difficulty/cross_entity_state_dependency/workout_proposal_gated_by_loan_posture_derived_from_covenant
    """
    chain, _covenant = _five_period_loan(api)
    loan = chain.read_loan()
    assert_fields(loan, risk_posture="OPEN")

    validate_error(
        api.create_workout_plan(
            forbearance_payload(
                chain.loan_id,
                loan["version"],
                narrative="Attempt while the loan is still performing",
            ),
            LOAN_SERVICER,
        ),
        "ERR_WORKOUT_INVALID_STATE",
        409,
    )

    rows, meta = validate_paginated(api.list_workout_plans(LOAN_SERVICER, {"loan_id": chain.loan_id}))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_failing_covenant_test_unlocks_the_identical_forbearance_proposal(api):
    """
    Only the covenant changes, and the same proposal is accepted, scored 92.00 and gates the loan.

    PRD §3.9: "The four component scores are then weighted: 35 percent on
    `membership_trend_points`, 25 percent on `giving_trend_points`, 20 percent on
    `community_points` and 20 percent on `denominational_points`."

    PRD §3.9: "`community_points` is the institution's `community_program_count`
    multiplied by 20, capped at 100 — so five ongoing programs earn full marks and a
    sixth adds nothing."

    PRD §3.9: "`MISSION_IMPACT_FORBEARANCE` leaves every ledger figure on the loan
    unchanged. Its effect is entirely one of posture and record."

    PRD §3.9: "Approval then re-derives the loan's risk posture, which by the ordering of
    §3.8 lands on `WORKOUT_GATED`, the transition being `WATCH → WORKOUT_GATED` or
    `RESTRICTED → WORKOUT_GATED` according to where the loan stood, and no movement at
    all where a predecessor plan had already gated it — and `version` advances by 1 on
    the plan, by 1 on the loan, and by 1 on any superseded predecessor."

    Design: Difficulty/cross_entity_state_dependency/workout_proposal_gated_by_loan_posture_derived_from_covenant
    """
    chain, covenant = _five_period_loan(api)
    tested = get_success_data(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-10T00:00:00Z"), LOAN_SERVICER
        )
    )
    assert_fields(tested, status="BREACH_PENDING_CURE", last_test_result="FAIL")
    assert_fields(chain.read_loan(), risk_posture="WATCH")

    proposed = get_success_data(
        api.create_workout_plan(
            forbearance_payload(
                chain.loan_id, chain.read_loan()["version"], narrative=FORBEARANCE_NARRATIVE
            ),
            LOAN_SERVICER,
        ),
        201,
    )

    assert_fields(
        proposed,
        status="PROPOSED",
        membership_trend_points=100,
        giving_trend_points=100,
        community_points=60,
        denominational_points=100,
    )
    assert_score(proposed["mission_impact_score"], 92.00)
    assert_nulls(proposed, "approved_by_user_id")

    approved = get_success_data(
        api.approve_workout_plan(
            proposed["id"],
            workout_approval_payload(approval_note="Committee approved mission-impact forbearance"),
            COMMITTEE_MEMBER,
        )
    )
    assert_fields(approved, status="APPROVED", approved_by_user_id=COMMITTEE_1)
    assert_loan_ledger(
        chain.read_loan(),
        risk_posture="WORKOUT_GATED",
        term_months=240,
        annual_debt_service_cents=36000000,
        deferred_payments_count=0,
        forgiven_principal_cents=0,
        outstanding_principal_cents=0,
    )
    assert_fields(
        get_success_data(api.get_institution(chain.institution_id, CREDIT_ANALYST)),
        cumulative_forgiveness_cents=0,
    )


def _breached_loan_with_approved_draw(api):
    """
    The reference borrower funded at 225000000 with a 1500000 interest reserve shortfall,
    one 60000000 APPROVED draw, and a DSCR covenant at 1.2500 already failed once, so the
    covenant sits in BREACH_PENDING_CURE while the draw is still APPROVED.
    """
    chain = chain_through_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2500)
    draw = build_approved_draw(api, chain.loan_id)
    get_success_data(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-10T00:00:00Z"), LOAN_SERVICER
        )
    )
    return chain, covenant, draw


def test_disbursement_is_blocked_by_the_covenant_dimension_while_the_draw_is_approved(api):
    """
    The loan is squarely in its draw phase and the draw is APPROVED; the covenant refuses.

    PRD §3.7: "Every covenant on the loan must be `COMPLIANT` or `WAIVED`; if any sits in
    `BREACH_PENDING_CURE` or `BREACHED` the disbursement is refused with
    `ERR_DRAW_BLOCKED_BY_COVENANT_BREACH`."

    PRD §3.7: "A new request opens in `SUBMITTED` with `approved_amount_cents`,
    `inspector_note`, `void_reason` and every waterfall figure null."

    Design: Difficulty/cross_entity_state_dependency/draw_disburse_blocked_while_covenant_breached
    """
    chain, _covenant, draw = _breached_loan_with_approved_draw(api)
    assert_fields(chain.read_loan(), servicing_status="PENDING_FIRST_DRAW", risk_posture="WATCH")

    validate_error(
        api.disburse_draw_request(
            draw["id"], draw_disbursement_payload(disbursement_date="2026-08-12T00:00:00Z"), LOAN_SERVICER
        ),
        "ERR_DRAW_BLOCKED_BY_COVENANT_BREACH",
        409,
    )

    unchanged = get_success_data(api.get_draw_request(draw["id"], LOAN_SERVICER))
    assert_fields(unchanged, status="APPROVED")
    assert_nulls(
        unchanged,
        "retainage_cents",
        "interest_reserve_applied_cents",
        "inspection_fee_cents",
        "net_disbursed_cents",
        "completion_pct_at_disbursement",
    )
    assert_loan_ledger(chain.read_loan(), disbursed_principal_cents=0, reserved_draw_cents=60000000)


def test_a_term_extension_restores_coverage_and_the_identical_disbursement_succeeds(api):
    """
    A rescaled debt service returns the covenant to COMPLIANT, and the draw funds even
    though the approved plan has pinned the posture at WORKOUT_GATED.

    PRD §3.9: "`TERM_EXTENSION` sets the loan's `term_months` to its current value plus
    `extension_months`, then rescales the debt service: the new `annual_debt_service_cents`
    is the old annual debt service multiplied by the old term in months, divided by the new
    term in months, with the result floored to whole cents."

    PRD §3.8: "A passing test moves the covenant `BREACH_PENDING_CURE → COMPLIANT` and
    resets `consecutive_fail_count` to 0 — the auto-cure, which applies to a first breach
    only — and may return the loan `WATCH → OPEN`."

    PRD §3.7: "Step one establishes the completion tier from the **post-draw** cumulative
    position — the tier this very draw creates, not the one it started from."

    PRD §3.7: "Whatever is left is the third bucket, `net_disbursed_cents`, the cash
    actually released to the institution."

    Design: Difficulty/cross_entity_state_dependency/draw_disburse_blocked_while_covenant_breached
    """
    chain, covenant, draw = _breached_loan_with_approved_draw(api)
    validate_error(
        api.disburse_draw_request(
            draw["id"], draw_disbursement_payload(disbursement_date="2026-08-12T00:00:00Z"), LOAN_SERVICER
        ),
        "ERR_DRAW_BLOCKED_BY_COVENANT_BREACH",
        409,
    )

    plan = get_success_data(
        api.create_workout_plan(
            term_extension_payload(
                chain.loan_id,
                chain.read_loan()["version"],
                extension_months=60,
                narrative="Stretch the amortization to restore coverage during construction",
            ),
            LOAN_SERVICER,
        ),
        201,
    )
    assert_score(plan["mission_impact_score"], 72.00)
    assert_fields(plan, denominational_points=0, community_points=60)
    approved = get_success_data(
        api.approve_workout_plan(
            plan["id"],
            workout_approval_payload(approval_note="Committee approved the term extension"),
            COMMITTEE_MEMBER,
        )
    )
    assert_fields(approved, status="APPROVED")
    assert_fields(chain.read_loan(), term_months=300, annual_debt_service_cents=28800000)

    retested = get_success_data(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-20T00:00:00Z"), LOAN_SERVICER
        )
    )
    assert_fields(
        retested,
        status="COMPLIANT",
        consecutive_fail_count=0,
        test_count=2,
        last_test_denominator_dollars=288000,
        last_test_numerator_dollars=432001,
    )
    assert_ratio(retested["last_test_ratio"], 1.5000, "last_test_ratio")
    assert_fields(chain.read_loan(), risk_posture="WORKOUT_GATED")

    disbursed = get_success_data(
        api.disburse_draw_request(
            draw["id"], draw_disbursement_payload(disbursement_date="2026-08-25T00:00:00Z"), LOAN_SERVICER
        )
    )
    assert_fields(
        disbursed,
        status="DISBURSED",
        retainage_cents=6000000,
        interest_reserve_applied_cents=1500000,
        inspection_fee_cents=45000,
        net_disbursed_cents=52455000,
    )
    assert_ratio(
        disbursed["completion_pct_at_disbursement"], 0.2666, "completion_pct_at_disbursement"
    )
    assert_loan_ledger(
        chain.read_loan(),
        servicing_status="CONSTRUCTION_DRAW",
        disbursed_principal_cents=60000000,
        reserved_draw_cents=0,
        retainage_held_cents=6000000,
        interest_reserve_shortfall_cents=0,
    )

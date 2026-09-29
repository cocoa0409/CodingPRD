"""
Queue A — §1.8 rule ``non_linear_state_machine``.

Neither lifecycle in this file is a straight line: the application loop re-enters
underwriting and re-snapshots on the way round, and the loan carries two
dimensions that advance on disjoint triggers.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.assertions import assert_fields, assert_loan_ledger, assert_nulls, assert_ratio
from test_helpers.factories import (
    committee_referral_payload,
    construction_completion_payload,
    covenant_test_payload,
    draw_disbursement_payload,
    loan_payment_payload,
    submit_underwriting_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_covenant,
    build_giving_period,
    chain_through_assignment,
    chain_through_loan,
    refer_to_committee,
    render_committee_decision,
)
from test_helpers.test_users import (
    ANALYST_2,
    COMMITTEE_1,
    LOAN_SERVICER,
    make_credit_analyst_headers,
)

REVISION_NOTE = "Refile with the 2026Q2 audit before we vote"

# The audited quarter the analyst files during the revision cycle.
PERIOD_2026Q2 = {
    "period_label": "2026Q2",
    "period_start": "2026-04-01T00:00:00Z",
    "period_end": "2026-06-30T00:00:00Z",
    "source": "AUDITED",
    "total_contributions_cents": 70000000,
    "restricted_contributions_cents": 8000000,
    "donor_restricted_endowment_draw_cents": 2000000,
    "operating_expense_cents": 45000000,
    "member_household_count": 545,
}


def _chain_in_committee(api):
    chain = chain_through_assignment(api)
    chain.loan_application = refer_to_committee(api, chain.loan_application_id)
    return chain


def test_request_revision_records_the_note_and_keeps_the_collateral_assigned(api):
    """
    The revision arm is the only one that re-enters the cycle, and it holds the lien.

    PRD §3.6: "A **revision-requesting** decision moves the application
    `COMMITTEE_REVIEW → REVISION_REQUESTED`, stores the submitted note as
    `revision_reason`, raises `revision_count` by 1, and — in deliberate contrast to
    a decline — keeps every collateral assignment intact, since the analyst is
    expected to rework and re-submit against the same security."

    PRD §3.6: "All three arms set `decided_by_user_id` to the acting `X-User-ID` and
    advance the application's `version` by 1."

    Design: Difficulty/non_linear_state_machine/loan_application_revision_cycle_returns_to_underwriting
    """
    chain = _chain_in_committee(api)

    decided = render_committee_decision(
        api, chain.loan_application_id, "REQUEST_REVISION", note=REVISION_NOTE
    )

    assert_fields(
        decided,
        status="REVISION_REQUESTED",
        revision_count=1,
        revision_reason=REVISION_NOTE,
        decided_by_user_id=COMMITTEE_1,
    )

    asset = chain.read_asset()
    assert_fields(
        asset,
        assigned_loan_application_id=chain.loan_application_id,
        lien_position=1,
    )
    assert asset["lien_history"] == [], f"lien_history: got {asset['lien_history']!r}"


def test_resubmission_after_a_revision_request_recomputes_the_giving_snapshot(api):
    """
    The loop back through underwriting picks up the newly filed audit rather than replaying.

    PRD §3.5: "It serves both the first submission and every re-submission: an
    application in `DRAFT` moves `DRAFT → UNDERWRITING`, and an application that came
    back from committee or from an underperforming campaign moves
    `REVISION_REQUESTED → UNDERWRITING` through the very same act."

    PRD §3.5: "A re-submission overwrites all three snapshot figures with freshly
    computed values rather than preserving the earlier ones, which is the mechanism by
    which a revised application picks up newly filed giving periods."

    PRD §3.5: "`prepared_by_user_id` is set to the acting `X-User-ID`,
    `revision_reason` is cleared to null, and `version` advances by 1."

    Design: Difficulty/non_linear_state_machine/loan_application_revision_cycle_returns_to_underwriting
    """
    chain = _chain_in_committee(api)
    render_committee_decision(
        api, chain.loan_application_id, "REQUEST_REVISION", note=REVISION_NOTE
    )
    build_giving_period(api, chain.institution_id, PERIOD_2026Q2)

    resubmitted = get_success_data(
        api.submit_underwriting(
            chain.loan_application_id,
            submit_underwriting_payload(analyst_note="Refiled with the 2026Q2 audit"),
            make_credit_analyst_headers(ANALYST_2),
        )
    )

    assert_fields(
        resubmitted,
        status="UNDERWRITING",
        revision_count=1,
        prepared_by_user_id=ANALYST_2,
        giving_basis="AUDITED_ONLY",
        giving_base_cents=217000000,
        net_available_dollars=482000,
    )
    assert_nulls(resubmitted, "revision_reason")


def test_second_referral_and_approval_close_the_revision_loop(api):
    """
    The re-referred application is still collateral-bound and reaches APPROVED once.

    PRD §3.5: "On success two figures are snapshotted and the application moves
    `UNDERWRITING → COMMITTEE_REVIEW` with its `version` advanced by 1."

    PRD §3.5: "`collateral_lending_value_cents` becomes the sum of
    `lending_value_cents` over the collateral assets assigned to this application
    whose `lien_position` is 1 — second-lien and worse assignments are excluded from
    the snapshot entirely."

    PRD §3.6: "On success the application moves `COMMITTEE_REVIEW → APPROVED`."

    Design: Difficulty/non_linear_state_machine/loan_application_revision_cycle_returns_to_underwriting
    """
    chain = _chain_in_committee(api)
    render_committee_decision(
        api, chain.loan_application_id, "REQUEST_REVISION", note=REVISION_NOTE
    )
    build_giving_period(api, chain.institution_id, PERIOD_2026Q2)
    validate_success(
        api.submit_underwriting(
            chain.loan_application_id,
            submit_underwriting_payload(analyst_note="Refiled with the 2026Q2 audit"),
            make_credit_analyst_headers(ANALYST_2),
        )
    )

    referred = get_success_data(
        api.committee_referral(
            chain.loan_application_id,
            committee_referral_payload(referral_note="Re-referred on refreshed giving"),
            make_credit_analyst_headers(ANALYST_2),
        )
    )
    assert_fields(
        referred,
        status="COMMITTEE_REVIEW",
        collateral_lending_value_cents=225000000,
        max_supportable_principal_cents=225000000,
    )

    approved = render_committee_decision(
        api, chain.loan_application_id, "APPROVE", note="Approved on the refreshed audit"
    )
    assert_fields(approved, status="APPROVED", revision_count=1)


def _loan_in_construction_with_failing_covenant(api):
    """Reference loan, one 60000000 draw disbursed, one DSCR covenant at 1.2500."""
    chain = chain_through_loan(api)
    draw = build_approved_draw(
        api, chain.loan_id, project_phase="FOUNDATION", requested_amount_cents=60000000,
        percent_complete=0.3000,
    )
    validate_success(
        api.disburse_draw_request(
            draw["id"], draw_disbursement_payload(disbursement_date="2026-08-05T00:00:00Z"),
            LOAN_SERVICER,
        )
    )
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2500)
    return chain, draw, covenant


def test_failing_covenant_test_moves_the_risk_dimension_only(api):
    """
    A soft breach drives the posture to WATCH while servicing stays in CONSTRUCTION_DRAW.

    PRD §2.9: "A loan carries two state dimensions that move independently and never
    read each other."

    PRD §3.8: "From `COMPLIANT`, a failing test moves the covenant `COMPLIANT →
    BREACH_PENDING_CURE` and sets `consecutive_fail_count` to 1."

    PRD §3.8: "This is the soft-breach window, and it is what drives the loan `OPEN →
    WATCH` on the risk dimension."

    Design: Difficulty/non_linear_state_machine/loan_parallel_servicing_status_and_risk_posture_evolve_independently
    """
    chain, _draw, covenant = _loan_in_construction_with_failing_covenant(api)

    tested = get_success_data(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-10T00:00:00Z"), LOAN_SERVICER
        )
    )

    assert_fields(
        tested,
        status="BREACH_PENDING_CURE",
        last_test_result="FAIL",
        consecutive_fail_count=1,
    )
    assert_ratio(tested["last_test_ratio"], 1.2000, "last_test_ratio")
    assert_fields(chain.read_loan(), risk_posture="WATCH", servicing_status="CONSTRUCTION_DRAW")


def test_servicing_reaches_paid_off_while_the_posture_stays_watch(api):
    """
    Completion and payoff walk the servicing dimension alone; the frozen posture is still WATCH.

    PRD §3.7: "Both variants perform the same two ledger movements — the whole of
    `undrawn_commitment_cents` moves into `cancelled_commitment_cents` and
    `undrawn_commitment_cents` is set to 0, and the whole of `retainage_held_cents`
    moves into `retainage_released_cents` and `retainage_held_cents` is set to 0 — and
    both advance `version` by 1."

    PRD §3.7: "When the payment brings `outstanding_principal_cents` to exactly 0
    **and** the loan is in `AMORTIZING`, the loan moves `AMORTIZING → PAID_OFF`."

    PRD §2.9: "A loan under a hard covenant breach still sits in `CONSTRUCTION_DRAW`;
    a loan that reaches `PAID_OFF` freezes its `risk_posture` at whatever value that
    dimension last held."

    Design: Difficulty/non_linear_state_machine/loan_parallel_servicing_status_and_risk_posture_evolve_independently
    """
    chain, _draw, covenant = _loan_in_construction_with_failing_covenant(api)
    validate_success(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-10T00:00:00Z"), LOAN_SERVICER
        )
    )

    completed = get_success_data(
        api.construction_completion(
            chain.loan_id,
            construction_completion_payload(
                completion_note="Sanctuary shell complete, project closed out early"
            ),
            LOAN_SERVICER,
        )
    )
    assert_loan_ledger(
        completed,
        servicing_status="AMORTIZING",
        risk_posture="WATCH",
        undrawn_commitment_cents=0,
        cancelled_commitment_cents=165000000,
        retainage_held_cents=0,
        retainage_released_cents=6000000,
    )

    paid = get_success_data(
        api.record_loan_payment(
            chain.loan_id,
            loan_payment_payload(60000000, payment_date="2026-09-01T00:00:00Z"),
            LOAN_SERVICER,
        )
    )
    assert_loan_ledger(
        paid,
        servicing_status="PAID_OFF",
        risk_posture="WATCH",
        principal_repaid_cents=60000000,
        outstanding_principal_cents=0,
    )


def test_paid_off_loan_refuses_further_covenant_tests_without_curing_the_breach(api):
    """
    The coupling between the dimensions is one-way: the servicing terminal blocks testing.

    PRD §3.8: "Testing is a `LoanServicer` act carrying a single `as_of_date`, and it
    is refused with `ERR_LOAN_TERMINAL` on a `PAID_OFF` loan."

    PRD §2.10: "The loan's `servicing_status` is not `PAID_OFF` — `ERR_LOAN_TERMINAL`
    (HTTP 409), on covenant creation, a covenant test, a principal payment and a
    construction completion."

    Design: Difficulty/non_linear_state_machine/loan_parallel_servicing_status_and_risk_posture_evolve_independently
    """
    chain, _draw, covenant = _loan_in_construction_with_failing_covenant(api)
    validate_success(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-10T00:00:00Z"), LOAN_SERVICER
        )
    )
    validate_success(
        api.construction_completion(
            chain.loan_id, construction_completion_payload(), LOAN_SERVICER
        )
    )
    validate_success(
        api.record_loan_payment(
            chain.loan_id,
            loan_payment_payload(60000000, payment_date="2026-09-01T00:00:00Z"),
            LOAN_SERVICER,
        )
    )

    validate_error(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-09-10T00:00:00Z"), LOAN_SERVICER
        ),
        "ERR_LOAN_TERMINAL",
        409,
    )

    assert_fields(
        get_success_data(api.get_covenant(covenant["id"], LOAN_SERVICER)),
        status="BREACH_PENDING_CURE",
    )
    assert_fields(chain.read_loan(), servicing_status="PAID_OFF", risk_posture="WATCH")

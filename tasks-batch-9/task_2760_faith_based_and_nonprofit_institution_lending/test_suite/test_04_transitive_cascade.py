"""
Queue A — §1.8 rule ``transitive_cascade``.

Each instance fires one request and follows the reconciliation three or four
levels deep, checking both that the far end moved and that the near end moved
only when the PRD says it should.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.assertions import assert_fields, assert_loan_ledger, assert_ratio
from test_helpers.factories import covenant_test_payload, draw_reinstatement_payload, waiver_payload
from test_helpers.fixtures import (
    build_approved_draw,
    build_covenant,
    build_draft_application,
    build_house_campaign,
    chain_through_authorization,
    chain_through_loan,
    submit_to_underwriting,
)
from test_helpers.test_users import COMMITTEE_MEMBER, CREDIT_ANALYST, LOAN_SERVICER

WAIVER_NOTE = "Committee waived the DSCR test for one cycle on mission grounds"


def _loan_with_approved_draw_and_failing_covenant(api):
    chain = chain_through_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2500)
    draw = build_approved_draw(
        api, chain.loan_id, project_phase="FOUNDATION", requested_amount_cents=60000000,
        percent_complete=0.3000,
    )
    return chain, covenant, draw


def _run_test(api, covenant_id, as_of):
    return get_success_data(
        api.run_covenant_test(covenant_id, covenant_test_payload(as_of), LOAN_SERVICER)
    )


def test_first_failing_test_leaves_the_approved_draw_and_its_reservation_alone(api):
    """
    Only the first two levels of the cascade fire on a soft breach.

    PRD §3.8: "From `COMPLIANT`, a failing test moves the covenant `COMPLIANT →
    BREACH_PENDING_CURE` and sets `consecutive_fail_count` to 1."

    PRD §3.7: "When a loan's `risk_posture` becomes `RESTRICTED`, every draw on that
    loan sitting in `APPROVED` is moved `APPROVED → SUSPENDED` and the loan's
    `reserved_draw_cents` falls by that draw's `approved_amount_cents`, releasing the
    reservation; `version` advances by 1 on the draw and by 1 on the loan."

    Design: Difficulty/transitive_cascade/covenant_second_breach_cascade_suspends_approved_draws_and_releases_reserved
    """
    chain, covenant, draw = _loan_with_approved_draw_and_failing_covenant(api)

    tested = _run_test(api, covenant["id"], "2026-08-10T00:00:00Z")

    assert_fields(
        tested,
        status="BREACH_PENDING_CURE",
        consecutive_fail_count=1,
        test_count=1,
        last_test_result="FAIL",
    )
    assert_fields(chain.read_loan(), risk_posture="WATCH")
    assert_fields(
        get_success_data(api.get_draw_request(draw["id"], LOAN_SERVICER)), status="APPROVED"
    )
    assert_fields(chain.read_loan(), reserved_draw_cents=60000000)


def test_second_consecutive_failure_suspends_the_draw_and_releases_the_reservation(api):
    """
    The hard breach walks covenant, posture, draw and reserved commitment in one call.

    PRD §3.8: "A second consecutive failing test instead moves the covenant
    `BREACH_PENDING_CURE → BREACHED` and sets `consecutive_fail_count` to 2, driving
    the loan `WATCH → RESTRICTED` and thereby suspending every `APPROVED` draw on it."

    PRD §3.8: "The `WATCH → RESTRICTED` step carries the cascade described in §3.7:
    every `APPROVED` draw on the loan is suspended and its reservation released from
    `reserved_draw_cents`."

    PRD §2.11: "Approving a draw does not move money between those three buckets; it
    reserves capacity by increasing `reserved_draw_cents`, which is a claim against
    the undrawn balance rather than a fourth bucket of it."

    Design: Difficulty/transitive_cascade/covenant_second_breach_cascade_suspends_approved_draws_and_releases_reserved
    """
    chain, covenant, draw = _loan_with_approved_draw_and_failing_covenant(api)
    _run_test(api, covenant["id"], "2026-08-10T00:00:00Z")

    tested = _run_test(api, covenant["id"], "2026-11-10T00:00:00Z")

    assert_fields(
        tested, status="BREACHED", consecutive_fail_count=2, test_count=2, last_test_result="FAIL"
    )
    assert_ratio(tested["last_test_ratio"], 1.2000, "last_test_ratio")
    assert_fields(
        get_success_data(api.get_draw_request(draw["id"], LOAN_SERVICER)), status="SUSPENDED"
    )
    assert_loan_ledger(
        chain.read_loan(),
        risk_posture="RESTRICTED",
        servicing_status="PENDING_FIRST_DRAW",
        reserved_draw_cents=0,
        undrawn_commitment_cents=225000000,
        disbursed_principal_cents=0,
    )


def test_suspended_draw_disbursement_reports_the_draw_state_not_the_covenant_guard(api):
    """
    Position 21 outranks position 45, so the draw's own state answers the request.

    PRD §2.10: "The draw occupies the state the requested transition departs from, and
    a construction completion additionally requires that no draw on the loan sits in
    `SUBMITTED`, `APPROVED` or `SUSPENDED` — `ERR_DRAW_INVALID_STATE` (HTTP 409), on
    draw approval, disbursement, rejection, voiding and reinstatement, and on
    construction completion."

    PRD §2.10: "Every covenant on the loan is `COMPLIANT` or `WAIVED` —
    `ERR_DRAW_BLOCKED_BY_COVENANT_BREACH` (HTTP 409), on draw disbursement."

    PRD §2.10: "Validations are evaluated in the ascending order set out below; the
    **first** rule that a request violates determines the single error the response
    carries, and no later rule can mask an earlier one."

    Design: Difficulty/transitive_cascade/covenant_second_breach_cascade_suspends_approved_draws_and_releases_reserved
    """
    chain, covenant, draw = _loan_with_approved_draw_and_failing_covenant(api)
    _run_test(api, covenant["id"], "2026-08-10T00:00:00Z")
    _run_test(api, covenant["id"], "2026-11-10T00:00:00Z")

    validate_error(
        api.disburse_draw_request(draw["id"], {}, LOAN_SERVICER),
        "ERR_DRAW_INVALID_STATE",
        409,
    )
    assert_fields(
        get_success_data(api.get_draw_request(draw["id"], LOAN_SERVICER)), status="SUSPENDED"
    )
    assert_fields(chain.read_loan(), reserved_draw_cents=0, disbursed_principal_cents=0)


def test_waiver_then_reinstatement_replays_the_cascade_backwards(api):
    """
    Waiving the breach reopens the posture and the explicit reinstatement restores the reservation.

    PRD §3.8: "It is available only from `BREACHED`, moving the covenant `BREACHED →
    WAIVED` and raising `waiver_count` by 1; attempted on a covenant in any other
    state it is refused with `ERR_COVENANT_INVALID_STATE`."

    PRD §3.7: "Once the posture recovers, a `LoanServicer` must reinstate each one
    explicitly with a `reinstatement_note`: the draw moves `SUSPENDED → APPROVED`, the
    loan's `reserved_draw_cents` rises again by the approved amount, and `version`
    advances by 1 on the draw and on the loan."

    PRD §2.11: "Reinstating a suspended draw restores exactly the reservation that the
    suspension released."

    Design: Difficulty/transitive_cascade/covenant_second_breach_cascade_suspends_approved_draws_and_releases_reserved
    """
    chain, covenant, draw = _loan_with_approved_draw_and_failing_covenant(api)
    _run_test(api, covenant["id"], "2026-08-10T00:00:00Z")
    _run_test(api, covenant["id"], "2026-11-10T00:00:00Z")

    waived = get_success_data(
        api.waive_covenant(
            covenant["id"], waiver_payload(waiver_note=WAIVER_NOTE), COMMITTEE_MEMBER
        )
    )
    assert_fields(waived, status="WAIVED", waiver_count=1)
    assert_fields(chain.read_loan(), risk_posture="OPEN")

    reinstated = get_success_data(
        api.reinstate_draw_request(
            draw["id"],
            draw_reinstatement_payload(reinstatement_note="Reinstated after the covenant waiver"),
            LOAN_SERVICER,
        )
    )
    assert_fields(reinstated, status="APPROVED")
    assert_loan_ledger(
        chain.read_loan(),
        reserved_draw_cents=60000000,
        undrawn_commitment_cents=225000000,
        disbursed_principal_cents=0,
    )


LAPSE_REASON = "Donor relocated out of state and rescinded the commitment"


def _campaign_with_two_applications(api):
    """
    'Build His House' with LEAD/MAJOR/GENERAL pledges, plus a PLEDGE_ADVANCE
    application backed by that campaign and an unrelated SANCTUARY_CONSTRUCTION
    application on the same institution, both sitting in UNDERWRITING.
    """
    chain = chain_through_authorization(api)
    built = build_house_campaign(api, chain.institution_id, major_missed_months=())
    app_a = build_draft_application(
        api,
        chain.institution_id,
        chain.governance_authorization_id,
        pledge_campaign_id=built["campaign"]["id"],
        purpose="PLEDGE_ADVANCE",
        requested_amount_cents=60000000,
        term_months=120,
        interest_rate_bps=700,
    )
    submit_to_underwriting(api, app_a["id"], analyst_note="Pledge advance against the capital campaign")
    app_b = build_draft_application(
        api,
        chain.institution_id,
        chain.governance_authorization_id,
        purpose="SANCTUARY_CONSTRUCTION",
        requested_amount_cents=100000000,
        term_months=240,
        interest_rate_bps=625,
    )
    submit_to_underwriting(api, app_b["id"], analyst_note="Unrelated sanctuary request")
    return chain, built, app_a, app_b


def _read_application(api, application_id):
    return get_success_data(api.get_loan_application(application_id, CREDIT_ANALYST))


def test_servicer_lapse_reprices_the_campaign_and_trips_the_underperformance_gate(api):
    """
    Lapsing the MAJOR pledge moves buckets, drops the conservative value below the
    80 percent floor while the 90 percent maturity gate still holds, and flips the status.

    PRD §3.3: "A `LoanServicer` may also lapse an `ACTIVE` pledge on judgement,
    supplying the `lapse_reason` to be stored verbatim."

    PRD §3.3: "The bucket movement is identical to the automatic lapse: the pledged
    amount moves from `active_pledged_cents` to `lapsed_pledged_cents`, both projected
    values are recomputed, and `version` advances by 1 on the pledge and on the
    campaign."

    PRD §3.3: "Pledges in `LAPSED` or `FULFILLED` status contribute nothing beyond the
    cash already counted in the collected total."

    PRD §3.3: "The second is the underperformance condition proper:
    `attrition_adjusted_value_cents` must have fallen strictly below the floor of the
    goal multiplied by 80 percent."

    Design: Difficulty/transitive_cascade/pledge_lapse_cascade_flags_pledge_advance_application_for_revision
    """
    chain, built, _app_a, _app_b = _campaign_with_two_applications(api)
    campaign_id = built["campaign"]["id"]
    assert_fields(
        get_success_data(api.get_pledge_campaign(campaign_id, CREDIT_ANALYST)), status="OPEN"
    )

    lapsed = get_success_data(
        api.lapse_pledge(built["major"]["id"], {"lapse_reason": LAPSE_REASON}, LOAN_SERVICER)
    )

    assert_fields(lapsed, status="LAPSED", lapse_reason=LAPSE_REASON, collected_cents=8000000)
    campaign = get_success_data(api.get_pledge_campaign(campaign_id, CREDIT_ANALYST))
    assert_fields(
        campaign,
        status="UNDERPERFORMING",
        attrition_adjusted_value_cents=86200000,
        sponsor_projected_value_cents=87560000,
        active_pledged_cents=85000000,
        lapsed_pledged_cents=40000000,
        fulfilled_pledged_cents=0,
        total_pledged_cents=125000000,
        collected_to_date_cents=25000000,
    )


def test_lapse_cascade_flags_only_the_pledge_advance_application_on_that_campaign(api):
    """
    The third hop is selective: purpose and pledge_campaign_id both have to match.

    PRD §3.3: "Every loan application that names this campaign as its
    `pledge_campaign_id`, whose `purpose` is `PLEDGE_ADVANCE` and whose `status` is
    `UNDERWRITING`, is pushed `UNDERWRITING → REVISION_REQUESTED`: its
    `revision_reason` is set to the literal string `PLEDGE_CAMPAIGN_UNDERPERFORMING`,
    its `revision_count` rises by 1, and its `version` advances by 1."

    PRD §3.3: "When both hold after any pledge create, installment record or lapse,
    the campaign moves `OPEN → UNDERPERFORMING` and its `version` advances by 1."

    Design: Difficulty/transitive_cascade/pledge_lapse_cascade_flags_pledge_advance_application_for_revision
    """
    _chain, built, app_a, app_b = _campaign_with_two_applications(api)
    assert_fields(_read_application(api, app_a["id"]), status="UNDERWRITING", revision_count=0)
    assert_fields(_read_application(api, app_b["id"]), status="UNDERWRITING", revision_count=0)

    validate_success(
        api.lapse_pledge(built["major"]["id"], {"lapse_reason": LAPSE_REASON}, LOAN_SERVICER)
    )

    assert_fields(
        _read_application(api, app_a["id"]),
        status="REVISION_REQUESTED",
        revision_reason="PLEDGE_CAMPAIGN_UNDERPERFORMING",
        revision_count=1,
    )
    assert_fields(
        _read_application(api, app_b["id"]), status="UNDERWRITING", revision_count=0
    )
    assert _read_application(api, app_b["id"])["revision_reason"] is None

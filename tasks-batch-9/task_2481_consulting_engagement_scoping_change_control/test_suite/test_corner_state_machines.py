"""Transition tables: initial states, refused edges, terminal locks and loops."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_money,
    assert_two_dp,
)

DISQUALIFYING_BUDGET_CENTS = 30000000
FAILURE_NOTE = "Cost-to-serve model is not reconcilable to the client ledger"
SECOND_WINDOW_START = "2026-10-04"
SECOND_WINDOW_END = "2026-10-12"
RELEASE_CLOCK = "2026-10-05T09:00:00Z"


def test_a_new_pursuit_starts_screened_out_of_scoping(
    api: ConsultingApiClient,
) -> None:
    """SCREENING is the declared initial state, and SCOPING is not reachable from it.

    PRD 3.2: "The full pursuit lifecycle runs `SCREENING`, then `QUALIFIED`, then
    `SCOPING`, then `SCOPE_BASELINED`, then `SOW_ISSUED`, and terminates in
    `WON`, `LOST` or `DISQUALIFIED`; `WON`, `LOST` and `DISQUALIFIED` are
    terminal and admit no further transition."

    PRD 3.3: "The first such edit against a `QUALIFIED` pursuit is what moves it
    `QUALIFIED → SCOPING`; subsequent edits leave it in `SCOPING`."

    Design: Corner/state_machines/opportunity_initial_state_is_screening_not_checked
    """
    sc = fx.build_screening_pursuit(api)
    assert_fields(
        fx.read_opportunity(sc), status="SCREENING", conflict_status="NOT_CHECKED"
    )

    response = api.patch_scope(sc.opportunity_id, F.scope_payload(), sc.manager)

    validate_error(response, E.ERR_OPPORTUNITY_STATE_INVALID)
    assert_fields(fx.read_opportunity(sc), status="SCREENING", assumptions=[])


def test_qualifying_a_second_time_is_refused_rather_than_recomputed(
    api: ConsultingApiClient,
) -> None:
    """The decision is not idempotent: it is simply unavailable once taken.

    PRD 3.2: "The pursuit must still be in `SCREENING`, the acting partner must
    be its `owner_partner_consultant_id`, `verified_budget_cents` must be
    non-null — a decision attempted without it fails with
    `ERR_BUDGET_NOT_VERIFIED` — and the conflict position must not be
    `BLOCKED`."

    Design: Corner/state_machines/qualify_twice_returns_state_invalid
    """
    sc = fx.build_qualified_pursuit(api)
    before = fx.read_opportunity(sc)
    assert_fields(before, status="QUALIFIED")
    assert_two_dp(before, "qualification_score_verified", 68.00)

    response = api.qualify(sc.opportunity_id, {}, sc.partner)

    validate_error(response, E.ERR_OPPORTUNITY_STATE_INVALID)
    after = fx.read_opportunity(sc)
    assert_fields(after, status="QUALIFIED", version=before["version"])
    assert_two_dp(after, "qualification_score_verified", 68.00)


def test_a_disqualified_pursuit_admits_no_further_transition(
    api: ConsultingApiClient,
) -> None:
    """Both of the next two operations in the lifecycle are refused identically.

    PRD 3.2: "Any operation attempted against a pursuit whose status does not
    permit it is refused with `ERR_OPPORTUNITY_STATE_INVALID`."

    Design: Corner/state_machines/disqualified_opportunity_rejects_every_further_transition
    """
    sc = fx.build_screening_pursuit(api)
    fx.screen_conflicts(sc)
    fx.verify_budget(sc, DISQUALIFYING_BUDGET_CENTS)
    # 30 * 0.80 + 40 * 0.30 + 20 + 0 falls short of the inclusive 60.00 bar
    decided = get_success_data(api.qualify(sc.opportunity_id, {}, sc.partner))
    assert_fields(decided, status="DISQUALIFIED")
    assert_two_dp(decided, "qualification_score_verified", 56.00)

    validate_error(
        api.patch_scope(sc.opportunity_id, F.scope_payload(), sc.manager),
        E.ERR_OPPORTUNITY_STATE_INVALID,
    )
    validate_error(
        api.baseline_scope(sc.opportunity_id, {}, sc.manager),
        E.ERR_OPPORTUNITY_STATE_INVALID,
    )

    assert_fields(
        fx.read_opportunity(sc),
        status="DISQUALIFIED",
        assumptions=[],
        baselined_at=None,
    )


def test_acceptance_is_reachable_only_from_submitted(
    api: ConsultingApiClient,
) -> None:
    """The client cannot accept work that has not been submitted to it.

    PRD 3.6: "A deliverable's lifecycle is `PLANNED`, `IN_PROGRESS`,
    `SUBMITTED`, and then either `ACCEPTED` — which is terminal — or `REWORK`
    and back to `IN_PROGRESS`."

    PRD 3.6: "A target status not reachable from the deliverable's current
    status — including any attempt to move out of the terminal `ACCEPTED` — is
    refused with `ERR_DELIVERABLE_STATE_INVALID`."

    Design: Corner/state_machines/deliverable_accept_before_submit_returns_state_invalid
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)

    response = api.set_deliverable_status(
        sc.d1_id, {"target_status": C.DELIVERABLE_ACCEPTED}, sc.client_contact
    )

    validate_error(response, E.ERR_DELIVERABLE_STATE_INVALID)
    assert_fields(fx.read_deliverable(sc, sc.d1_id), status=C.DELIVERABLE_IN_PROGRESS)
    view = get_success_data(api.get_economics(sc.engagement_id, sc.partner))
    assert_two_dp(view, "completion_pct", 0.00)


def test_the_client_cannot_sign_a_document_still_in_internal_review(
    api: ConsultingApiClient,
) -> None:
    """The internal approval step cannot be skipped by going straight to signature.

    PRD 3.5: "The client's decision on a released document belongs to the
    `ClientContact` of the pursuit's own client and carries a `decision` of
    `SIGN`, `REQUEST_REVISION` or `DECLINE`, plus optionally `signature_name`
    and a `note`. All three require the document to be in `CLIENT_REVIEW`."

    Design: Corner/state_machines/sow_client_decision_from_internal_review_returns_state_invalid
    """
    sc = fx.build_sow_internal_review(api)

    response = api.sow_client_decision(
        sc.sow_id, F.sign_payload(), sc.client_contact
    )

    validate_error(response, E.ERR_SOW_STATE_INVALID)
    assert_fields(fx.read_sow(sc), status="INTERNAL_REVIEW", signed_at=None)
    assert_fields(fx.read_opportunity(sc), status="SOW_ISSUED")
    _, meta = validate_paginated(api.list_engagements(sc.partner, {"sow_id": sc.sow_id}))
    assert meta["total_count"] == 0


def test_baselining_a_narrative_with_no_deliverables_reports_the_count_gate(
    api: ConsultingApiClient,
) -> None:
    """The deliverable-count precondition is checked ahead of the narrative ones.

    PRD 2.10: "Note in particular that on scope baselining the four
    scope-completeness checks fire in exactly that sequence — deliverable count,
    then the assumption and exclusion and responsibility lists, then acceptance
    criteria, then the completion-weight sum — so a scope with no deliverables at
    all reports the count error rather than any of the later three."

    Design: Corner/state_machines/baseline_without_deliverables_returns_scope_has_no_deliverables
    """
    sc = fx.build_qualified_pursuit(api)
    fx.edit_scope(sc)

    response = api.baseline_scope(sc.opportunity_id, {}, sc.manager)

    validate_error(response, E.ERR_SCOPE_HAS_NO_DELIVERABLES)
    assert_fields(
        fx.read_opportunity(sc),
        status="SCOPING",
        baselined_at=None,
        total_estimated_hours=None,
    )


def test_rejecting_a_timesheet_line_moves_nothing_on_the_burn_ledger(
    api: ConsultingApiClient,
) -> None:
    """The REJECT branch carries no side effects at all, unlike APPROVE.

    PRD 3.7: "Rejection moves the line `SUBMITTED → REJECTED`, changes nothing in
    the ledger, and advances only the line's own `version`."

    Design: Corner/state_machines/time_entry_reject_leaves_burn_ledger_untouched
    """
    sc = fx.build_started_engagement(api)
    entry = fx.log_time(sc, 60.0, C.SEED_WEEK_1)

    rejected = get_success_data(
        api.time_entry_decision(entry["id"], {"decision": "REJECT"}, sc.manager)
    )

    assert_fields(rejected, status=C.TIME_ENTRY_REJECTED)
    # The priced figures written at submission survive the rejection
    assert_money(rejected, "cost_cents", 3720000)
    assert_money(rejected, "billed_value_cents", 5272500)

    engagement = fx.read_engagement(sc)
    assert_two_dp(engagement, "approved_hours_burned", 0.00)
    assert_money(engagement, "burned_cost_cents", 0)
    assert_fields(engagement, economics_state=C.ECONOMICS_ON_TRACK)
    assert_two_dp(fx.read_deliverable(sc, sc.d1_id), "hours_consumed", 0.00)


def _engagement_in_overrun(api: ConsultingApiClient) -> fx.Scenario:
    """75.00 approved partner hours against nothing accepted."""
    sc = fx.build_started_engagement(api)
    fx.log_and_approve_time(sc, 60.0, C.SEED_WEEK_1)
    fx.log_and_approve_time(sc, 15.0, C.SEED_WEEK_2)
    return sc


def test_acknowledgement_is_a_real_state_that_holds_nothing(
    api: ConsultingApiClient,
) -> None:
    """Two responses, two different cascades: the first has none at all.

    PRD 3.9: "Acknowledging moves the escalation `OPEN → ACKNOWLEDGED` and does
    nothing else."

    Design: Corner/state_machines/escalation_acknowledge_then_hold_two_step_path
    """
    sc = _engagement_in_overrun(api)
    escalation_id = fx.first_escalation(sc)["id"]

    acknowledged = fx.respond_to_escalation(sc, escalation_id, C.RESPONSE_ACKNOWLEDGE)

    assert_fields(
        acknowledged,
        status=C.ESCALATION_ACKNOWLEDGED,
        leadership_response=C.RESPONSE_ACKNOWLEDGE,
    )
    engagement = fx.read_engagement(sc)
    assert_fields(
        engagement,
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
    )

    held = fx.respond_to_escalation(sc, escalation_id, C.RESPONSE_HOLD_DELIVERY)

    assert_fields(
        held,
        status=C.ESCALATION_DELIVERY_HELD,
        leadership_response=C.RESPONSE_HOLD_DELIVERY,
    )
    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_ON_HOLD,
        suspended_deliverable_count=2,
    )
    assert_fields(
        fx.read_deliverable(sc, sc.d1_id),
        status=C.DELIVERABLE_SUSPENDED,
        prior_status=C.DELIVERABLE_IN_PROGRESS,
    )
    assert_fields(
        fx.read_deliverable(sc, sc.d2_id),
        status=C.DELIVERABLE_SUSPENDED,
        prior_status=C.DELIVERABLE_PLANNED,
    )


def test_releasing_a_hold_restores_each_deliverable_to_its_own_prior_status(
    api: ConsultingApiClient,
) -> None:
    """Two suspended rows, two different pre-hold states, restored independently.

    PRD 3.9: "Resolving from `DELIVERY_HELD` additionally releases the hold, but
    only when no other escalation of the same engagement remains in
    `DELIVERY_HELD`: at that point the engagement moves `ON_HOLD → ACTIVE`,
    every `SUSPENDED` deliverable is restored to its recorded `prior_status`
    with `prior_status` cleared to null, and `suspended_deliverable_count`
    returns to 0."

    Design: Corner/state_machines/hold_release_restores_each_deliverable_prior_status
    """
    sc = fx.build_active_engagement(api)
    fx.start_deliverable(sc, sc.d1_id, lead_id=sc.consultant_id)
    first_review = fx.schedule_review(sc)
    # Scheduled while the first window is still open, 4 days clear of it
    second_review = fx.schedule_review(
        sc,
        window_start_date=SECOND_WINDOW_START,
        window_end_date=SECOND_WINDOW_END,
    )

    fx.set_clock(api, C.SEED_REVIEW_CLOCK)
    fx.record_review_outcome(
        sc, first_review["id"], C.REVIEW_FAILED, C.SEVERITY_CRITICAL
    )
    assert_fields(fx.read_engagement(sc), delivery_state=C.DELIVERY_ON_HOLD)

    # The re-review is what makes a QUALITY escalation resolvable at all
    fx.set_clock(api, RELEASE_CLOCK)
    fx.record_review_outcome(sc, second_review["id"], C.REVIEW_PASSED, C.SEVERITY_NONE)
    escalation_id = fx.first_escalation(sc)["id"]

    resolved = fx.respond_to_escalation(sc, escalation_id, C.RESPONSE_RESOLVE)

    assert_fields(resolved, status=C.ESCALATION_RESOLVED)
    assert resolved["resolved_at"].startswith("2026-10-05T09:00:00")
    assert_fields(
        fx.read_engagement(sc),
        delivery_state=C.DELIVERY_ACTIVE,
        suspended_deliverable_count=0,
        leadership_review_required=False,
    )
    assert_fields(
        fx.read_deliverable(sc, sc.d1_id),
        status=C.DELIVERABLE_IN_PROGRESS,
        prior_status=None,
    )
    assert_fields(
        fx.read_deliverable(sc, sc.d2_id),
        status=C.DELIVERABLE_PLANNED,
        prior_status=None,
    )
    assert_fields(fx.read_client(sc), at_risk_engagement_count=0)


def test_the_negotiation_loop_stops_after_three_completed_rounds(
    api: ConsultingApiClient,
) -> None:
    """The cycle is bounded: a fourth revision request is refused outright.

    PRD 3.5: "A revision request moves the document
    `CLIENT_REVIEW → REVISION_REQUESTED`, but only while its `revision_round` is
    below 3 — a request against a document that has already turned three
    revision loops is refused with `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/state_machines/fourth_sow_revision_returns_revision_limit_reached
    """
    sc = fx.build_sow_client_review(api)
    for round_number in range(3):
        get_success_data(
            api.sow_client_decision(
                sc.sow_id,
                {"decision": "REQUEST_REVISION", "note": f"Pass {round_number + 1}"},
                sc.client_contact,
            )
        )
        fx.baseline_scope(sc)
        revised = get_success_data(api.revise_sow(sc.sow_id, {}, sc.partner))
        assert revised["revision_round"] == round_number + 1
        fx.submit_sow_internal(sc)
        fx.approve_sow_internally(sc)

    response = api.sow_client_decision(
        sc.sow_id, {"decision": "REQUEST_REVISION", "note": "One more pass"}, sc.client_contact
    )

    validate_error(response, E.ERR_REVISION_LIMIT_REACHED)
    assert_fields(fx.read_sow(sc), status="CLIENT_REVIEW", revision_round=3)
    opportunity = fx.read_opportunity(sc)
    assert_fields(opportunity, status="SOW_ISSUED")
    assert_two_dp(opportunity, "total_estimated_hours", C.CANON_TOTAL_ESTIMATED_HOURS)

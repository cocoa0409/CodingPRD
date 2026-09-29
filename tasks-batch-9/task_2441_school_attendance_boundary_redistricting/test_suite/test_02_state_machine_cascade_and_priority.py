"""Non-linear scenario/adoption state moves, multi-link cascades and validation precedence."""

import pytest

from test_helpers import (
    ApiErrorId,
    CommentPriority,
    CommentStatus,
    CommentTheme,
    EntitlementStatus,
    ImplementationStatus,
    OFFICER,
    PLANNER,
    ProjectionRunStatus,
    ScenarioStatus,
    StudyStatus,
    TransferWindowStatus,
    advance_entitlement_to,
    advance_to_board,
    api_client,
    assign_areas,
    create_adoption_payload,
    create_comment,
    create_housing_development,
    create_projection_run,
    create_scenario,
    make_guardian_headers,
    open_engagement,
    program_placement,
    request_revision,
    riverbend_adopted,
    riverbend_engagement_open,
    riverbend_locked,
    riverbend_scenario_draft,
    set_clock,
    submit_for_review,
    triage_comment,
    BOARD,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The engagement revision loop: UNDER_REVIEW -> REVISION -> UNDER_REVIEW
# ---------------------------------------------------------------------------
def _engagement_with_triaged_comment() -> dict:
    """Riverbend in ENGAGEMENT, Scenario A UNDER_REVIEW, one TRIAGED comment on A-02."""
    ctx = riverbend_engagement_open()
    comment = create_comment(
        ctx["scenario_id"],
        area_id=ctx["a2_id"],
        body="Moving A-02 to Cedar breaks our walking route along Mill Street.",
    )
    triage_comment(
        comment["id"], CommentTheme.TRANSPORTATION.value, CommentPriority.HIGH.value
    )
    ctx["comment"] = comment
    ctx["comment_id"] = comment["id"]
    return ctx


def test_revision_loop_returns_the_same_scenario_row_to_under_review():
    """A scenario pushed back for revision re-enters UNDER_REVIEW on the same row.

    PRD: "A scenario's `status` walks `DRAFT → UNDER_REVIEW`, then cycles
    `UNDER_REVIEW → REVISION → UNDER_REVIEW` as engagement proceeds, branches
    `UNDER_REVIEW → BOARD_READY`, can fall back `BOARD_READY → REVISION`, and
    terminates at either `ADOPTED` or `REJECTED`."
    PRD: "When the scenario is returning from `REVISION`, its `revision_reason` is
    cleared back to null and its `revision_round` is left unchanged, because that
    counter was already incremented when the scenario entered `REVISION`."

    Design: Difficulty/non_linear_state_machine/scenario_engagement_revision_loop_returns_to_under_review
    """
    ctx = _engagement_with_triaged_comment()
    scenario_id = ctx["scenario_id"]

    pushed_back = request_revision(
        scenario_id, [ctx["comment_id"]], revision_notes="Revisit the A-02 walk route."
    )
    assert pushed_back["status"] == ScenarioStatus.REVISION.value, (
        "request-revision must move the UNDER_REVIEW scenario to REVISION"
    )
    assert pushed_back["revision_reason"] == "COMMENT_CYCLE", (
        "a comment-driven push-back records revision_reason COMMENT_CYCLE"
    )

    resubmitted = submit_for_review(scenario_id, planner_notes="Walk route preserved.")
    assert resubmitted["id"] == scenario_id, (
        "the loop must reuse the same scenario row, not mint a new one"
    )
    assert resubmitted["status"] == ScenarioStatus.UNDER_REVIEW.value, (
        "REVISION -> UNDER_REVIEW closes the engagement loop"
    )
    assert resubmitted["revision_reason"] is None, (
        "returning from REVISION clears revision_reason back to null"
    )
    assert resubmitted["revision_round"] == 1, (
        "the counter incremented on entering REVISION is left unchanged by the resubmit"
    )

    scenarios, meta = validate_paginated(
        api_client.list_scenarios(PLANNER, params={"study_id": ctx["study_id"]})
    )
    assert meta["total_count"] == 1, (
        "the study still holds exactly one scenario after a full revision loop"
    )
    assert scenarios[0]["id"] == scenario_id, "the single scenario is the looped row"

    assert resubmitted["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        "the resubmission recomputes Cedar's utilization (452 assigned + 30 program "
        "seats over 540 effective seats), it does not reset it"
    )
    assert resubmitted["total_assigned_students"] == 588, (
        "the resubmission recomputes the assigned head count 271 + 181 + 136"
    )


def test_revision_loop_addresses_the_cited_comment_and_keeps_the_study_in_engagement():
    """The push-back cascade addresses cited comment and leaves ENGAGEMENT untouched.

    PRD: "Link two moves every comment named in `cited_comment_ids`
    `TRIAGED → ADDRESSED`, walked in comment creation order, incrementing each
    comment's `version`."
    PRD: "Link three reacts to the study: when the scenario left `BOARD_READY` and no
    scenario of the study remains in `BOARD_READY`, the study reverts
    `BOARD_DECISION → ENGAGEMENT` and `comment_intake_open` is recomputed to true,
    reopening intake for another round."

    Design: Difficulty/non_linear_state_machine/scenario_engagement_revision_loop_returns_to_under_review
    """
    ctx = _engagement_with_triaged_comment()

    request_revision(
        ctx["scenario_id"],
        [ctx["comment_id"]],
        revision_notes="Revisit the A-02 walk route.",
    )

    comment = validate_success(api_client.get_comment(ctx["comment_id"], PLANNER))
    assert comment["status"] == CommentStatus.ADDRESSED.value, (
        "a cited TRIAGED comment moves to ADDRESSED by link two of the cascade"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == StudyStatus.ENGAGEMENT.value, (
        "the study never entered BOARD_DECISION, so link three does not move it"
    )
    assert study["comment_intake_open"] is True, (
        "comment intake stays open while the study's status is ENGAGEMENT"
    )


# ---------------------------------------------------------------------------
# The adoption record's two independent status dimensions
# ---------------------------------------------------------------------------
def test_close_transfer_window_moves_only_the_window_dimension():
    """Closing the window leaves implementation_status at PENDING_EFFECTIVE.

    PRD: "The window dimension moves `TRANSFER_WINDOW_OPEN → TRANSFER_WINDOW_CLOSED`,
    `implementation_status` is untouched, and the undecided queue is cleared: every
    transfer request of this adoption still in `SUBMITTED` or `WAITLISTED` moves
    `SUBMITTED → DENIED` or `WAITLISTED → DENIED` with `decision_notes` set to
    `WINDOW_CLOSED` and `decided_by_user_id` left null, walked in request creation
    order, each request's `version` incremented."

    Design: Difficulty/non_linear_state_machine/adoption_transfer_window_dimension_moves_independently_of_implementation
    """
    ctx = riverbend_adopted()
    set_clock("2027-08-16T00:00:00Z", api_client, OFFICER)

    closed = validate_success(
        api_client.close_transfer_window(ctx["adoption_id"], OFFICER)
    )
    assert closed["transfer_window_status"] == TransferWindowStatus.TRANSFER_WINDOW_CLOSED.value, (
        "close-transfer-window advances the window dimension"
    )
    assert closed["implementation_status"] == ImplementationStatus.PENDING_EFFECTIVE.value, (
        "the implementation dimension is untouched by closing the window"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], OFFICER))
    assert study["status"] == StudyStatus.IMPLEMENTATION.value, (
        "closing the transfer window does not move the study out of IMPLEMENTATION"
    )


def test_activation_moves_only_the_implementation_dimension_after_the_window_closed():
    """Activation advances implementation_status and leaves the window closed.

    PRD: "The new record starts with `implementation_status` `PENDING_EFFECTIVE` and
    `transfer_window_status` `TRANSFER_WINDOW_OPEN`, and those two dimensions move
    independently from that moment on — the window may close while the adoption is
    still `PENDING_EFFECTIVE`, and the adoption may reach `IN_EFFECT` with the window
    still `TRANSFER_WINDOW_OPEN`."
    PRD: "Link two rewrites the map of record: for every planning area of the study,
    walked in area creation order, `previous_school_id` is set to the area's outgoing
    `current_school_id` and then `current_school_id` is set to the
    `assigned_school_id` of that area's non-superseded assignment under the adopted
    scenario."

    Design: Difficulty/non_linear_state_machine/adoption_transfer_window_dimension_moves_independently_of_implementation
    """
    ctx = riverbend_adopted()
    set_clock("2027-08-16T00:00:00Z", api_client, OFFICER)
    validate_success(api_client.close_transfer_window(ctx["adoption_id"], OFFICER))

    activated = validate_success(
        api_client.activate_adoption(ctx["adoption_id"], OFFICER)
    )
    assert activated["implementation_status"] == ImplementationStatus.IN_EFFECT.value, (
        "activation moves PENDING_EFFECTIVE -> IN_EFFECT"
    )
    assert activated["transfer_window_status"] == TransferWindowStatus.TRANSFER_WINDOW_CLOSED.value, (
        "activation must not reopen an already closed transfer window"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], OFFICER))
    assert study["status"] == StudyStatus.IMPLEMENTATION.value, (
        "the study stays in IMPLEMENTATION across both dimension moves"
    )

    cedar = validate_success(api_client.get_school(ctx["cedar_id"], OFFICER))
    birch = validate_success(api_client.get_school(ctx["birch_id"], OFFICER))
    assert cedar["enrolled_students_of_record"] == 500, (
        "the adopted map reproduces every area's school of record, so Cedar keeps "
        "A-01 300 + A-02 200 residents"
    )
    assert birch["enrolled_students_of_record"] == 150, (
        "Birch keeps A-03's 150 residents after the activation recount"
    )

    area = validate_success(api_client.get_planning_area(ctx["a1_id"], OFFICER))
    assert area["previous_school_id"] == ctx["cedar_id"], (
        "link two stamps the outgoing school of record onto previous_school_id"
    )
    assert area["current_school_id"] == ctx["cedar_id"], (
        "A-01's assignment points at Cedar, so its school of record is unchanged"
    )


# ---------------------------------------------------------------------------
# The four-link housing-pipeline cascade
# ---------------------------------------------------------------------------
def _riverbend_pipeline_in_engagement() -> dict:
    """Riverbend in ENGAGEMENT with one UNDER_CONSTRUCTION and two PROPOSED developments."""
    ctx = riverbend_locked()
    willow = create_housing_development(
        ctx["a1_id"],
        name="Willow Ridge",
        unit_type="SINGLE_FAMILY",
        total_units=120,
        first_occupancy_date="2027-01-01T00:00:00Z",
        buildout_months=24,
    )
    advance_entitlement_to(willow["id"], EntitlementStatus.UNDER_CONSTRUCTION.value)
    maple = create_housing_development(
        ctx["a2_id"],
        name="Maple Flats",
        unit_type="MULTI_FAMILY",
        total_units=200,
        first_occupancy_date="2027-03-01T00:00:00Z",
        buildout_months=20,
    )
    juniper = create_housing_development(
        ctx["a3_id"],
        name="Juniper Commons",
        unit_type="TOWNHOME",
        total_units=90,
        first_occupancy_date="2031-01-01T00:00:00Z",
        buildout_months=36,
    )

    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        ctx["study_id"], run["id"], [program_placement(ctx["cedar_id"], 30)]
    )
    assign_areas(
        scenario["id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["birch_id"]),
        ],
    )
    submit_for_review(scenario["id"])
    open_engagement(ctx["study_id"])

    ctx.update(
        {
            "willow_id": willow["id"],
            "maple_id": maple["id"],
            "juniper_id": juniper["id"],
            "run": run,
            "run_id": run["id"],
            "scenario": scenario,
            "scenario_id": scenario["id"],
        }
    )
    return ctx


def test_entitlement_advance_stales_the_run_and_flags_the_study():
    """Links one and two: the advanced development stales the COMPLETE run.

    PRD: "Link two recognises that the projection inputs have changed: every
    projection run of the study that owns the development's area whose `status` is
    `COMPLETE` moves to `STALE` with `stale_reason` set to
    `DEVELOPMENT_PIPELINE_CHANGED`, walked in run creation order, and the study's
    `projection_stale` flag is recomputed to true."

    Design: Difficulty/transitive_cascade/entitlement_advance_cascades_four_links_to_study_phase
    """
    ctx = _riverbend_pipeline_in_engagement()
    assert ctx["run"]["projected_total_students"] == 638, (
        "COHORT_SURVIVAL admits only Willow Ridge: 321 + 181 + 136"
    )

    advanced = validate_success(
        api_client.advance_entitlement(
            ctx["maple_id"], {"to_status": EntitlementStatus.ENTITLED.value}, PLANNER
        )
    )
    assert advanced["entitlement_status"] == EntitlementStatus.ENTITLED.value, (
        "link one sets entitlement_status to the requested stage"
    )

    run = validate_success(api_client.get_projection_run(ctx["run_id"], PLANNER))
    assert run["status"] == ProjectionRunStatus.STALE.value, (
        "link two moves the COMPLETE run of the owning study to STALE"
    )
    assert run["stale_reason"] == "DEVELOPMENT_PIPELINE_CHANGED", (
        "the stale_reason names the pipeline change that caused it"
    )
    assert run["projected_total_students"] == 638, (
        "a staled run keeps its numbers; link two marks it rather than recomputing it"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["projection_stale"] is True, (
        "the study's projection_stale flag is recomputed to true by link two"
    )

    willow = validate_success(
        api_client.get_housing_development(ctx["willow_id"], PLANNER)
    )
    juniper = validate_success(
        api_client.get_housing_development(ctx["juniper_id"], PLANNER)
    )
    assert willow["entitlement_status"] == EntitlementStatus.UNDER_CONSTRUCTION.value, (
        "the cascade advances only the named development"
    )
    assert juniper["entitlement_status"] == EntitlementStatus.PROPOSED.value, (
        "the sibling pipeline rows keep their own stages"
    )


def test_entitlement_advance_pushes_the_scenario_into_revision_and_reverts_the_study():
    """Links three and four: the staled run drags the scenario and the study back.

    PRD: "Link three follows the runs to the scenarios that cite them: every boundary
    scenario referencing one of those runs whose `status` is `DRAFT`, `UNDER_REVIEW`
    or `REVISION` sets its own `projection_stale` to true, and each such scenario that
    was in `UNDER_REVIEW` additionally transitions `UNDER_REVIEW → REVISION` with
    `revision_reason` set to `PROJECTION_STALE` and its `revision_round` incremented
    by 1, walked in scenario creation order."
    PRD: "Link four notices the consequence for the study: if link three emptied the
    study's `UNDER_REVIEW` and `BOARD_READY` sets and the study is in `ENGAGEMENT`,
    the study transitions `ENGAGEMENT → SCENARIO_DEVELOPMENT` and
    `comment_intake_open` is recomputed to false, because there is no longer a live
    scenario for the public to comment on."

    Design: Difficulty/transitive_cascade/entitlement_advance_cascades_four_links_to_study_phase
    """
    ctx = _riverbend_pipeline_in_engagement()

    validate_success(
        api_client.advance_entitlement(
            ctx["maple_id"], {"to_status": EntitlementStatus.ENTITLED.value}, PLANNER
        )
    )

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["projection_stale"] is True, (
        "link three marks the citing scenario's projection as stale"
    )
    assert scenario["status"] == ScenarioStatus.REVISION.value, (
        "an UNDER_REVIEW scenario over a staled run falls back to REVISION"
    )
    assert scenario["revision_reason"] == "PROJECTION_STALE", (
        "the pipeline cascade records PROJECTION_STALE, not COMMENT_CYCLE"
    )
    assert scenario["revision_round"] == 1, (
        "entering REVISION increments revision_round from 0 to 1"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == StudyStatus.SCENARIO_DEVELOPMENT.value, (
        "link four reverts ENGAGEMENT -> SCENARIO_DEVELOPMENT once nothing is live"
    )
    assert study["comment_intake_open"] is False, (
        "comment intake is recomputed to false when the study leaves ENGAGEMENT"
    )


# ---------------------------------------------------------------------------
# The three-link adoption cascade
# ---------------------------------------------------------------------------
def _board_decision_with_draft_sibling() -> dict:
    """Riverbend in BOARD_DECISION: Scenario A BOARD_READY, Scenario B DRAFT with a comment."""
    ctx = riverbend_scenario_draft()
    assign_areas(
        ctx["scenario_id"],
        [
            (ctx["a1_id"], ctx["cedar_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["birch_id"]),
        ],
    )
    sibling = create_scenario(
        ctx["study_id"],
        ctx["run_id"],
        [program_placement(ctx["cedar_id"], 24)],
        name="Scenario B",
    )
    submit_for_review(ctx["scenario_id"])
    open_engagement(ctx["study_id"])
    comment = create_comment(
        sibling["id"],
        headers=make_guardian_headers("guardian-9"),
        body="Scenario B splits our block from Cedar.",
    )
    advance_to_board(ctx["scenario_id"])

    ctx.update(
        {
            "sibling": sibling,
            "sibling_id": sibling["id"],
            "sibling_comment_id": comment["id"],
        }
    )
    return ctx


def test_adoption_records_the_vote_and_adopts_the_board_ready_scenario():
    """Link one: the adoption record opens on both dimensions and adopts the scenario.

    PRD: "Link one moves the named scenario `BOARD_READY → ADOPTED`."
    PRD: "The `supermajority_required` flag is then computed: it is true exactly when
    the scenario's `students_reassigned_pct`, as recomputed at its most recent
    submission for review, is **strictly greater than** 15.00 percent, so a scenario
    at exactly 15.00 percent needs only a simple majority."

    Design: Difficulty/transitive_cascade/adoption_cascades_three_links_to_sibling_comments
    """
    ctx = _board_decision_with_draft_sibling()

    adoption = validate_success(
        api_client.create_adoption(
            create_adoption_payload(ctx["study_id"], ctx["scenario_id"]), BOARD
        ),
        201,
    )
    assert adoption["implementation_status"] == ImplementationStatus.PENDING_EFFECTIVE.value, (
        "a new adoption record starts at PENDING_EFFECTIVE"
    )
    assert adoption["transfer_window_status"] == TransferWindowStatus.TRANSFER_WINDOW_OPEN.value, (
        "a new adoption record starts with its transfer window open"
    )
    assert adoption["supermajority_required"] is False, (
        "the adopted map reassigns nobody, so students_reassigned_pct 0.00 needs only "
        "a simple majority"
    )
    assert adoption["adopted_by_user_id"] == "board-1", (
        "adopted_by_user_id is stamped from the acting board member's X-User-ID"
    )

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], BOARD))
    assert scenario["status"] == ScenarioStatus.ADOPTED.value, (
        "link one moves the named scenario BOARD_READY -> ADOPTED"
    )

    study = validate_success(api_client.get_study(ctx["study_id"], BOARD))
    assert study["status"] == StudyStatus.IMPLEMENTATION.value, (
        "the owning study moves BOARD_DECISION -> IMPLEMENTATION"
    )
    assert study["comment_intake_open"] is False, (
        "intake is closed once the study is past ENGAGEMENT"
    )


def test_adoption_rejects_the_sibling_scenario_and_dismisses_its_open_comment():
    """Links two and three: the losing scenario is rejected and its comment closed.

    PRD: "Link two rejects the field: every sibling scenario of the same study still
    in `DRAFT`, `UNDER_REVIEW`, `REVISION` or `BOARD_READY` moves to `REJECTED` —
    `DRAFT → REJECTED`, `UNDER_REVIEW → REJECTED`, `REVISION → REJECTED` and
    `BOARD_READY → REJECTED` are all reachable only this way — with
    `rejection_reason` set to `SUPERSEDED_BY_ADOPTION`, walked in scenario creation
    order."
    PRD: "Link three closes the public record on those losers: every comment attached
    to a scenario rejected by link two that is still in `SUBMITTED` or `TRIAGED` moves
    to `DISMISSED` with `dismissal_reason` set to `SCENARIO_REJECTED`, walked in
    comment creation order."

    Design: Difficulty/transitive_cascade/adoption_cascades_three_links_to_sibling_comments
    """
    ctx = _board_decision_with_draft_sibling()

    validate_success(
        api_client.create_adoption(
            create_adoption_payload(ctx["study_id"], ctx["scenario_id"]), BOARD
        ),
        201,
    )

    sibling = validate_success(api_client.get_scenario(ctx["sibling_id"], BOARD))
    assert sibling["status"] == ScenarioStatus.REJECTED.value, (
        "the DRAFT sibling is rejected by link two of the adoption cascade"
    )
    assert sibling["rejection_reason"] == "SUPERSEDED_BY_ADOPTION", (
        "a sibling rejected by an adoption records SUPERSEDED_BY_ADOPTION"
    )

    comment = validate_success(
        api_client.get_comment(ctx["sibling_comment_id"], BOARD)
    )
    assert comment["status"] == CommentStatus.DISMISSED.value, (
        "a SUBMITTED comment on a rejected scenario is dismissed by link three"
    )
    assert comment["dismissal_reason"] == "SCENARIO_REJECTED", (
        "the dismissal names the scenario rejection that closed it"
    )

    rejected, meta = validate_paginated(
        api_client.list_scenarios(
            BOARD,
            params={
                "study_id": ctx["study_id"],
                "status": ScenarioStatus.REJECTED.value,
            },
        )
    )
    assert meta["total_count"] == 1, "exactly the one sibling scenario was rejected"
    assert rejected[0]["id"] == ctx["sibling_id"], (
        "the rejected scenario is the DRAFT sibling, not the adopted map"
    )


# ---------------------------------------------------------------------------
# Validation precedence: scenario state outranks the capacity/fiscal ceiling
# ---------------------------------------------------------------------------
def _engagement_with_cedar_over_critical() -> dict:
    """Scenario A UNDER_REVIEW while Cedar's live utilization sits above the ceiling."""
    ctx = riverbend_engagement_open()
    validate_success(
        api_client.patch_school(
            ctx["cedar_id"],
            {"core_capacity_seats": 430, "portable_capacity_seats": 0},
            PLANNER,
        )
    )
    return ctx


def test_resubmit_of_a_non_editable_scenario_reports_state_not_capacity():
    """A frozen scenario reports the state error even though capacity is critical too.

    PRD: "A scenario's content — its assignments and its program placements — may be
    edited only while its `status` is `DRAFT` or `REVISION`; in any other state the
    content is frozen and an edit or a resubmission is rejected with
    `ERR_SCENARIO_NOT_EDITABLE`."
    PRD: "The consequence worth internalising is that a state failure always masks a
    business failure, a concurrency failure always masks a temporal or business
    failure, and a structural failure on a scenario always masks the capacity
    ceiling."

    Design: Difficulty/priority_pair_validation_conflict/board_ready_resubmit_prefers_state_over_capacity_fiscal
    """
    ctx = _engagement_with_cedar_over_critical()

    response = api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER)
    error = validate_error(response, ApiErrorId.ERR_SCENARIO_NOT_EDITABLE.value)
    assert response.status_code == 409, (
        "ERR_SCENARIO_NOT_EDITABLE is catalogued as HTTP 409"
    )
    assert error["error_id"] != ApiErrorId.ERR_SCHOOL_CAPACITY_CRITICAL.value, (
        "the capacity ceiling is violated as well but must stay masked by the state "
        "failure"
    )

    scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == ScenarioStatus.UNDER_REVIEW.value, (
        "a rejected resubmission leaves the scenario's status unchanged"
    )
    assert scenario["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        "the rejected call persists nothing, so the score from the accepted "
        "submission survives"
    )


def test_capacity_violation_behind_the_state_error_is_visible_through_impact_analysis():
    """The masked fiscal rule is genuinely violated: live utilization is 112.09.

    PRD: "Utilization in percent is 100 multiplied by that load, divided by effective
    capacity, rounded half up to 2 decimal places."
    PRD: "A submission whose `max_utilization_pct` reaches or exceeds 110.00 is
    rejected with `ERR_SCHOOL_CAPACITY_CRITICAL`."

    Design: Difficulty/priority_pair_validation_conflict/board_ready_resubmit_prefers_state_over_capacity_fiscal
    """
    ctx = _engagement_with_cedar_over_critical()

    cedar = validate_success(api_client.get_school(ctx["cedar_id"], PLANNER))
    assert cedar["effective_capacity_seats"] == 430, (
        "the patch drops Cedar to 430 core seats and 0 portable seats"
    )

    validate_error(
        api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER),
        ApiErrorId.ERR_SCENARIO_NOT_EDITABLE.value,
    )

    analysis = validate_success(
        api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
    )
    assert analysis["max_utilization_pct"] == pytest.approx(112.09, abs=0.01), (
        "Cedar carries 452 assigned students plus 30 program seats over 430 effective "
        "seats, which is 112.09 percent"
    )
    assert ctx["cedar_id"] in analysis["critical_school_ids"], (
        "a school at or above 110.00 percent is reported as critical by the computed "
        "read"
    )

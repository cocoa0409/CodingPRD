"""Legal transitions, refused transitions, terminal states and re-entrant loops."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_area,
    assert_contractor_standing,
    assert_four_decimals,
    assert_index,
    assert_money,
    assert_pay_factor,
    assert_project_estimate,
    assert_project_scope,
    assert_project_states,
    assert_scenario_totals,
    assert_segment_condition,
    find_by,
)
from test_helpers.constants import (
    AREA_MAPLE,
    MAPLE_BUNDLE_BASE,
    MAPLE_CANDIDATE_COST,
    MAPLE_CONTINGENCY,
    MAPLE_TOTAL,
    MILL_AND_OVERLAY,
    OAK_CANDIDATE_COST,
    OBS_MILL_INDEX,
    PCI_MAPLE_MODEL,
    QC_ACCEPT_NOTE,
    RECONSTRUCTION,
    SOURCE_MODEL_PROJECTED,
)
from test_helpers.factories import (
    accept_payload,
    acceptance_decision_payload,
    acceptance_test_payload,
    advance_payload,
    close_payload,
    cut_decide_payload,
    override_payload,
    qc_payload,
)
from test_helpers.test_users import (
    COORDINATOR,
    ENGINEER,
    INSPECTOR,
    INSPECTOR_ACCEPTOR,
    INSPECTOR_DECIDER_2,
    INSPECTOR_WITNESS_2,
    INSPECTOR_WITNESS_2_USER_ID,
    INSPECTOR_DECIDER_USER_ID,
    OFFICER,
    OFFICER_ADOPT_USER_ID,
    make_officer_headers,
)

# A second adopting officer, so the sibling scenario is adopted by someone else.
OFFICER_ADOPT_2_USER_ID = "officer-adopt-2"
OFFICER_ADOPTER_2 = make_officer_headers(OFFICER_ADOPT_2_USER_ID)

CLOCK_2026_08_02 = "2026-08-02T00:00:00Z"
CLOCK_2026_08_10 = "2026-08-10T00:00:00Z"

FLAG_NOTE = "crack map looks light for a 1000-foot block"
REACCEPT_NOTE = "re-drive confirms the original reading"
REJECT_NOTE = "coverage window corrupt, discard the pass"
OVERRIDE_REASON = "subgrade failure found in the test pits"

# Maple St priced as generated: MILL_AND_OVERLAY on a 3333.33 sy LOCAL block.
MAPLE_MILL_LIFE_YEARS = 15
MAPLE_MILL_GAIN = 30.9
MAPLE_MILL_BCR = 14381.0110

# The same candidate re-priced as RECONSTRUCTION against the frozen 69.1 snapshot:
# 3333.33 * 9500 * 1.06 = 33566633, then the 850000-cent mobilisation.
MAPLE_RECON_COST = 34416633
MAPLE_RECON_LIFE_YEARS = 30
MAPLE_RECON_BCR = 8978.2080

# Funding levels for the re-run and supersession scenarios.
CONSTRAINED_FUNDING = 12000000
RECOMMENDED_FUNDING = 25000000
MAPLE_OAK_FUNDED = 15343298

# A retest that clears every floor: density 1.00 * smoothness 1.02 * thickness 1.00.
PASS_DENSITY_PCT = 96.0
PASS_IRI = 60.0
PASS_THICKNESS_IN = 2.0
PASS_PAY_FACTOR = 1.0200

# Round 1 of the remediation loop: density 91.9 sits below the 92.0 floor.
FAIL_DENSITY_PCT = 91.9
SUSPENDED_INTERIM_SCORE = 53.0

CUT_WINDOW_START = "2026-08-10T00:00:00Z"
CUT_WINDOW_END = "2026-08-12T00:00:00Z"
CUT_AREA_SQFT = 200.0
CUT_FEE_UNENCUMBERED = 170000

SLA_DUE_HIGH = "2026-08-04T00:00:00"


def _read_survey(api, survey_id):
    return validate_success(api.get_survey(survey_id, ENGINEER))


def _read_observation(api, observation_id):
    return validate_success(api.get_observation(observation_id, ENGINEER))


# ----------------------------------------------------------------------
# The condition survey: OPEN is the only door, sealing is the only exit
# ----------------------------------------------------------------------


def test_a_second_seal_on_a_sealed_survey_is_refused_and_changes_nothing(api):
    """SEALED is terminal, so the repeat call cannot restamp the campaign.

    PRD: "A `PavementEngineer` seals a survey, moving `survey_status` from `OPEN` to
    `SEALED`; a second attempt on an already-sealed survey reports
    `ERR_SURVEY_NOT_OPEN`."

    PRD: "`OPEN` and `SEALED` are the only two states a survey ever holds; sealing is
    the sole exit and there is no un-seal."

    The clock is moved a day forward before the retry, so a restamped `sealed_at`
    would be visible.

    Design: Corner/state_machines/survey_seal_attempted_twice_rejected
    """
    ctx = fixtures.sealed_survey(api, fixtures.MAPLE_ONLY)
    sealed = ctx["survey"]
    assert sealed["survey_status"] == "SEALED"
    assert_index(sealed["network_condition_index"], OBS_MILL_INDEX)
    assert sealed["sealed_at"].startswith("2026-08-01T00:00:00")

    fixtures.set_clock(api, CLOCK_2026_08_02)
    validate_error(
        api.seal_survey(sealed["id"], ENGINEER),
        ApiErrorId.SURVEY_NOT_OPEN,
        409,
    )

    after = _read_survey(api, sealed["id"])
    assert after["survey_status"] == "SEALED"
    assert after["sealed_at"] == sealed["sealed_at"]
    assert_index(after["network_condition_index"], OBS_MILL_INDEX)
    assert after["accepted_observation_count"] == 1


def test_one_observation_still_awaiting_quality_control_blocks_the_seal(api):
    """The readiness gate looks at every row, not just at the ones already decided.

    PRD: "Two readiness conditions guard it: no observation on the survey may still be
    `PENDING`, else `ERR_OBSERVATIONS_PENDING_QC`, and at least one observation must
    be `ACCEPTED`, else `ERR_SURVEY_HAS_NO_ACCEPTED_OBSERVATIONS`."

    PRD: "Sealing stamps `sealed_at` with the logical clock and computes
    `network_condition_index` as the area-weighted mean measured index over the
    accepted observations: for each accepted observation, multiply its segment's
    `area_sy` by the observation's `measured_condition_index`; sum those products;
    divide by the sum of the same segments' `area_sy`; round to one decimal place."

    Design: Corner/state_machines/survey_seal_with_a_pending_qc_observation_rejected
    """
    ctx = fixtures.open_survey_with_observations(
        api, fixtures.MAPLE_AND_OAK, accept_all=False
    )
    fixtures.accept_observation(api, ctx["observations"]["Maple St"]["id"])

    validate_error(
        api.seal_survey(ctx["survey"]["id"], ENGINEER),
        ApiErrorId.OBSERVATIONS_PENDING_QC,
        409,
    )

    survey = _read_survey(api, ctx["survey"]["id"])
    assert survey["survey_status"] == "OPEN"
    assert survey["sealed_at"] is None
    assert survey["network_condition_index"] is None
    assert survey["observation_count"] == 2
    assert survey["accepted_observation_count"] == 1
    assert _read_observation(api, ctx["observations"]["Oak St"]["id"])["qc_status"] == "PENDING"
    assert_segment_condition(
        fixtures.read_segment(api, fixtures.segment_for(ctx, "Maple St")["id"]),
        PCI_MAPLE_MODEL,
        SOURCE_MODEL_PROJECTED,
    )


def test_a_survey_whose_only_reading_was_rejected_cannot_be_sealed(api):
    """Nothing is pending, yet there is no accepted reading to weight.

    PRD: "Two readiness conditions guard it: no observation on the survey may still be
    `PENDING`, else `ERR_OBSERVATIONS_PENDING_QC`, and at least one observation must
    be `ACCEPTED`, else `ERR_SURVEY_HAS_NO_ACCEPTED_OBSERVATIONS`."

    PRD: "Rejecting moves it to `REJECTED`, records the note, and guarantees it never
    contributes to any condition index."

    Design: Corner/state_machines/survey_seal_with_only_a_rejected_observation_rejected
    """
    ctx = fixtures.open_survey_with_observations(
        api, fixtures.MAPLE_ONLY, accept_all=False
    )
    rejected = validate_success(
        api.qc_observation(
            ctx["observations"]["Maple St"]["id"],
            qc_payload("REJECT", qc_note=REJECT_NOTE),
            ENGINEER,
        )
    )
    assert rejected["qc_status"] == "REJECTED"
    assert rejected["qc_note"] == REJECT_NOTE

    validate_error(
        api.seal_survey(ctx["survey"]["id"], ENGINEER),
        ApiErrorId.SURVEY_HAS_NO_ACCEPTED_OBSERVATIONS,
        409,
    )

    survey = _read_survey(api, ctx["survey"]["id"])
    assert survey["survey_status"] == "OPEN"
    assert survey["sealed_at"] is None
    assert survey["network_condition_index"] is None
    assert survey["observation_count"] == 1
    assert survey["accepted_observation_count"] == 0


def test_a_flagged_reading_can_still_be_accepted_and_then_seals_the_campaign(api):
    """FLAGGED is a waypoint in both directions; the measurement itself never moves.

    PRD: "Flagging moves it to `FLAGGED`, records the note, and leaves it out of the
    accepted count and out of the seal cascade until it is decided again."

    PRD: "`FLAGGED` is revisitable in both directions — a flagged observation may
    later be accepted, which records the new note and increments the accepted count,
    or rejected, which records the note — while `ACCEPTED` and `REJECTED` are
    terminal."

    Design: Corner/state_machines/observation_flagged_then_accepted_reaches_the_accepted_terminal
    """
    ctx = fixtures.open_survey_with_observations(
        api, fixtures.MAPLE_ONLY, accept_all=False
    )
    observation_id = ctx["observations"]["Maple St"]["id"]

    flagged = validate_success(
        api.qc_observation(observation_id, qc_payload("FLAG", qc_note=FLAG_NOTE), ENGINEER)
    )
    assert flagged["qc_status"] == "FLAGGED"
    assert flagged["qc_note"] == FLAG_NOTE
    assert _read_survey(api, ctx["survey"]["id"])["accepted_observation_count"] == 0

    accepted = validate_success(
        api.qc_observation(
            observation_id, qc_payload("ACCEPT", qc_note=REACCEPT_NOTE), ENGINEER
        )
    )
    sealed = fixtures.seal_survey(api, ctx["survey"]["id"])

    assert accepted["qc_status"] == "ACCEPTED"
    assert accepted["qc_note"] == REACCEPT_NOTE
    assert_index(accepted["measured_condition_index"], OBS_MILL_INDEX)
    assert sealed["survey_status"] == "SEALED"
    assert sealed["observation_count"] == 1
    assert sealed["accepted_observation_count"] == 1
    assert_index(sealed["network_condition_index"], OBS_MILL_INDEX)


def test_quality_control_on_an_accepted_reading_is_refused(api):
    """ACCEPTED is terminal, so even a reasoned rejection cannot reopen it.

    PRD: "Every quality-control decision requires the parent survey to still be
    `OPEN`, failing with `ERR_SURVEY_NOT_OPEN` otherwise, and requires the
    observation's `qc_status` to be `PENDING` or `FLAGGED`, failing with
    `ERR_OBSERVATION_ALREADY_DECIDED` when the observation has already reached a
    terminal decision."

    The survey is still `OPEN`, so the lower-priority survey-state rule cannot be
    what refuses the call.

    Design: Corner/state_machines/observation_qc_on_an_already_accepted_observation_rejected
    """
    ctx = fixtures.open_survey_with_observations(api, fixtures.MAPLE_ONLY)
    observation_id = ctx["observations"]["Maple St"]["id"]
    assert _read_survey(api, ctx["survey"]["id"])["survey_status"] == "OPEN"

    validate_error(
        api.qc_observation(
            observation_id, qc_payload("REJECT", qc_note=REJECT_NOTE), ENGINEER
        ),
        ApiErrorId.OBSERVATION_ALREADY_DECIDED,
        409,
    )

    observation = _read_observation(api, observation_id)
    survey = _read_survey(api, ctx["survey"]["id"])
    assert observation["qc_status"] == "ACCEPTED"
    assert observation["qc_note"] == QC_ACCEPT_NOTE
    assert_index(observation["measured_condition_index"], OBS_MILL_INDEX)
    assert survey["accepted_observation_count"] == 1


# ----------------------------------------------------------------------
# Treatment candidates: RECOMMENDED, OVERRIDDEN and the locks around them
# ----------------------------------------------------------------------


def test_overriding_the_treatment_reprices_the_whole_candidate(api):
    """Four derived fields move together, all read off the frozen 69.1 snapshot.

    PRD: "A `PavementEngineer` may override a candidate's `treatment_type`, supplying
    the new type and a mandatory `override_reason`, which moves `candidate_status`
    from `RECOMMENDED` to `OVERRIDDEN`."

    PRD: "The override records the reason and re-derives
    `expected_service_life_years`, `treatment_pci_gain`, `estimated_cost_cents` and
    `benefit_cost_ratio` from the new treatment type against the unchanged
    `selection_condition_index` snapshot — the snapshot never moves, so re-pricing an
    overridden candidate is fully reproducible."

    Design: Corner/state_machines/candidate_override_to_reconstruction_recomputes_cost_life_gain_and_ratio
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_ONLY)
    candidate = fixtures.candidate_for(ctx, "Maple St")
    assert candidate["treatment_type"] == MILL_AND_OVERLAY
    assert candidate["candidate_status"] == "RECOMMENDED"
    assert_index(candidate["selection_condition_index"], OBS_MILL_INDEX)
    assert_money(candidate["estimated_cost_cents"], MAPLE_CANDIDATE_COST)
    assert candidate["expected_service_life_years"] == MAPLE_MILL_LIFE_YEARS
    assert_index(candidate["treatment_pci_gain"], MAPLE_MILL_GAIN)
    assert_four_decimals(candidate["benefit_cost_ratio"], MAPLE_MILL_BCR)

    overridden = validate_success(
        api.override_candidate(
            candidate["id"], override_payload(RECONSTRUCTION, OVERRIDE_REASON), ENGINEER
        )
    )

    assert overridden["treatment_type"] == RECONSTRUCTION
    assert overridden["candidate_status"] == "OVERRIDDEN"
    assert overridden["override_reason"] == OVERRIDE_REASON
    assert_index(overridden["selection_condition_index"], OBS_MILL_INDEX)
    assert_money(overridden["estimated_cost_cents"], MAPLE_RECON_COST)
    assert overridden["expected_service_life_years"] == MAPLE_RECON_LIFE_YEARS
    assert_index(overridden["treatment_pci_gain"], MAPLE_MILL_GAIN)
    assert_four_decimals(overridden["benefit_cost_ratio"], MAPLE_RECON_BCR)


def test_an_override_after_adoption_is_refused_by_the_program_lock(api):
    """The candidate is perfectly overridable; the frozen program of record is not.

    PRD: "And no scenario on the candidate's survey may have reached `ADOPTED`,
    because the program of record is frozen once adopted; an attempt after adoption
    reports `ERR_SURVEY_PROGRAM_LOCKED`."

    The candidate is still `RECOMMENDED` rather than `CONSUMED` or `SUPERSEDED`, so
    the state rule that raises `ERR_CANDIDATE_NOT_OVERRIDABLE` is not in play.

    Design: Corner/state_machines/candidate_override_after_a_scenario_is_adopted_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    candidate = fixtures.read_candidate(
        api, fixtures.candidate_for(ctx, "Maple St")["id"]
    )
    assert candidate["candidate_status"] == "RECOMMENDED"
    assert ctx["scenario"]["scenario_status"] == "ADOPTED"

    validate_error(
        api.override_candidate(
            candidate["id"], override_payload(RECONSTRUCTION, OVERRIDE_REASON), ENGINEER
        ),
        ApiErrorId.SURVEY_PROGRAM_LOCKED,
        409,
    )

    after = fixtures.read_candidate(api, candidate["id"])
    scenario = fixtures.read_scenario(api, ctx["scenario"]["id"])
    assert after["treatment_type"] == MILL_AND_OVERLAY
    assert after["candidate_status"] == "RECOMMENDED"
    assert after["override_reason"] is None
    assert_money(after["estimated_cost_cents"], MAPLE_CANDIDATE_COST)
    assert_money(scenario["funded_cost_cents"], MAPLE_CANDIDATE_COST)


def test_an_override_to_the_treatment_already_selected_is_refused(api):
    """A no-op override is a malformed request, not a state error.

    PRD: "The requested `treatment_type` must actually differ from the current one; an
    override that changes nothing reports `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/candidate_override_repeating_the_current_treatment_type_rejected
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_ONLY)
    candidate = fixtures.candidate_for(ctx, "Maple St")
    assert candidate["treatment_type"] == MILL_AND_OVERLAY

    validate_error(
        api.override_candidate(
            candidate["id"], override_payload(MILL_AND_OVERLAY, OVERRIDE_REASON), ENGINEER
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    after = fixtures.read_candidate(api, candidate["id"])
    assert after["candidate_status"] == "RECOMMENDED"
    assert after["override_reason"] is None
    assert after["treatment_type"] == MILL_AND_OVERLAY
    assert_money(after["estimated_cost_cents"], MAPLE_CANDIDATE_COST)


# ----------------------------------------------------------------------
# Budget scenarios: COMPUTED is re-entrant, ADOPTED supersedes its siblings
# ----------------------------------------------------------------------


def test_a_second_run_replaces_the_allocation_table_instead_of_appending_to_it(api):
    """COMPUTED loops back to itself and the table stays exactly two rows long.

    PRD: "A scenario may be re-run any number of times while nothing is committed,
    staying in `COMPUTED`."

    PRD: "A re-run first deletes every allocation on the scenario whose `source` is
    `AUTO_RUN` — including rows a prior seal cascade had already withdrawn — then
    re-allocates from the current pool; allocations whose `source` is `MANUAL_ADD`
    survive the re-run and keep their `rank`."

    At 12,000,000 cents Maple St's 10743323 fits and Oak St's 4599975 does not, so a
    correct re-run reproduces one funded and one deferred row rather than four.

    Design: Corner/state_machines/scenario_rerun_from_computed_replaces_its_auto_run_allocations
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_AND_OAK)
    scenario = fixtures.create_scenario(
        api, ctx["survey"]["id"], funding_cents=CONSTRAINED_FUNDING
    )
    first = fixtures.run_scenario(api, scenario["id"])
    assert first["scenario_status"] == "COMPUTED"
    assert_scenario_totals(first, 2, MAPLE_CANDIDATE_COST, OAK_CANDIDATE_COST)

    second = fixtures.run_scenario(api, scenario["id"])
    rows, meta = validate_paginated(
        api.list_allocations(OFFICER, {"scenario_id": scenario["id"], "limit": 100})
    )

    assert second["scenario_status"] == "COMPUTED"
    assert_scenario_totals(second, 2, MAPLE_CANDIDATE_COST, OAK_CANDIDATE_COST)
    assert second["version"] > first["version"]
    assert meta["total_count"] == 2
    funded = find_by(rows, "rank", 1)
    deferred = find_by(rows, "rank", 2)
    assert funded["allocation_status"] == "FUNDED"
    assert funded["source"] == "AUTO_RUN"
    assert_money(funded["allocated_cents"], MAPLE_CANDIDATE_COST)
    assert deferred["allocation_status"] == "DEFERRED"
    assert deferred["source"] == "AUTO_RUN"
    assert_money(deferred["allocated_cents"], 0)


def test_adopting_one_scenario_supersedes_the_sibling_on_the_same_survey(api):
    """The loser keeps every number it computed and the officer who signed it.

    PRD: "Adopting a scenario also moves every *other* `ADOPTED` scenario on the same
    survey to `SUPERSEDED`; projects already created under a superseded scenario keep
    their `scenario_id` but can no longer receive new awards, which surface as
    `ERR_SCENARIO_NOT_ADOPTED`."

    PRD: "Adoption records the acting officer's `X-User-ID` as `adopted_by_user_id`,
    which is the anchor for the award segregation rule of §2.1, and refreshes
    `uncommitted_cents` as `funding_cents` less `committed_cents`."

    Design: Corner/state_machines/scenario_adopt_supersedes_the_sibling_scenario_of_the_same_survey
    """
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_AND_OAK)
    constrained = fixtures.create_scenario(
        api,
        ctx["survey"]["id"],
        scenario_name="Constrained",
        funding_cents=CONSTRAINED_FUNDING,
    )
    recommended = fixtures.create_scenario(
        api,
        ctx["survey"]["id"],
        scenario_name="Recommended",
        funding_cents=RECOMMENDED_FUNDING,
    )
    fixtures.run_scenario(api, constrained["id"])
    fixtures.run_scenario(api, recommended["id"])

    adopted_first = fixtures.adopt_scenario(api, constrained["id"])
    assert adopted_first["scenario_status"] == "ADOPTED"
    assert adopted_first["adopted_by_user_id"] == OFFICER_ADOPT_USER_ID

    adopted_second = validate_success(
        api.adopt_scenario(recommended["id"], OFFICER_ADOPTER_2)
    )
    superseded = fixtures.read_scenario(api, constrained["id"])

    assert adopted_second["scenario_status"] == "ADOPTED"
    assert adopted_second["adopted_by_user_id"] == OFFICER_ADOPT_2_USER_ID
    assert_scenario_totals(adopted_second, 2, MAPLE_OAK_FUNDED, 0)
    assert superseded["scenario_status"] == "SUPERSEDED"
    assert superseded["adopted_by_user_id"] == OFFICER_ADOPT_USER_ID
    assert_scenario_totals(superseded, 2, MAPLE_CANDIDATE_COST, OAK_CANDIDATE_COST)


# ----------------------------------------------------------------------
# Resurfacing projects: the delivery dimension admits no shortcuts
# ----------------------------------------------------------------------


def test_a_draft_bundle_cannot_skip_coordination_and_go_straight_to_bid(api):
    """DRAFT reaches BID_READY only through COORDINATING; there is no direct edge.

    PRD: "It requires the project to be in `COORDINATING`, else
    `ERR_PROJECT_NOT_COORDINATING`; it requires at least one non-removed line, else
    `ERR_PROJECT_HAS_NO_SEGMENTS`; and it requires `clearance_outstanding_count` to
    have reached zero, meaning every utility row on the project is either `CLEARED` or
    `CLEARED_AFTER_WORK`, else `ERR_UTILITY_CLEARANCE_PENDING`."

    PRD: "The transition creates four **utility coordination** rows on the project —
    one each for `WATER`, `SEWER`, `FRANCHISE_GAS` and `FRANCHISE_TELECOM` — each with
    `coordination_status` `CLEARANCE_REQUESTED`, `round_count` 1, and
    `planned_work_start`, `planned_work_end`, `work_completed_at` and `response_note`
    null, and sets `clearance_outstanding_count` to 4."

    The bundle already carries a line, so the no-segments gate is satisfied and the
    refusal can only be the delivery-state gate.

    Design: Corner/state_machines/project_advance_to_bid_ready_directly_from_draft_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.draft_project(api, ctx, fixtures.MAPLE_LINE)
    assert_project_states(ctx["project"], "DRAFT", "NOT_STARTED")
    assert_project_scope(ctx["project"], 1, AREA_MAPLE)

    validate_error(
        api.advance_project(ctx["project"]["id"], advance_payload("BID_READY"), ENGINEER),
        ApiErrorId.PROJECT_NOT_COORDINATING,
        409,
    )

    refused = fixtures.read_project(api, ctx["project"]["id"])
    assert_project_states(refused, "DRAFT", "NOT_STARTED")
    assert refused["clearance_outstanding_count"] == 0
    assert fixtures.list_coordinations(api, refused["id"]) == []


def test_final_acceptance_is_refused_while_the_crews_are_still_on_site(api):
    """Quality is fully accepted, yet the delivery dimension has not reached its gate.

    PRD: "The project must be `SUBSTANTIALLY_COMPLETE`, else
    `ERR_PROJECT_NOT_SUBSTANTIALLY_COMPLETE`."

    PRD: "Acceptance stamps `accepted_at` from the logical clock and records the
    signer as `accepting_inspector_user_id`, then runs the system's widest cascade."

    The signing inspector witnessed nothing on this project, so the duty-segregation
    rule cannot be what refuses the call.

    Design: Corner/state_machines/project_accept_before_substantial_completion_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.quality_accepted_project(api, ctx, fixtures.MAPLE_LINE)
    assert_project_states(ctx["project"], "IN_CONSTRUCTION", "QUALITY_ACCEPTED")

    validate_error(
        api.accept_project(ctx["project"]["id"], accept_payload(), INSPECTOR_ACCEPTOR),
        ApiErrorId.PROJECT_NOT_SUBSTANTIALLY_COMPLETE,
        409,
    )

    project = fixtures.read_project(api, ctx["project"]["id"])
    line = fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])
    segment = fixtures.read_segment(api, fixtures.segment_for(ctx, "Maple St")["id"])
    assert_project_states(project, "IN_CONSTRUCTION", "QUALITY_ACCEPTED")
    assert project["accepted_at"] is None
    assert project["accepting_inspector_user_id"] is None
    assert line["work_state"] == "WORK_COMPLETE"
    assert segment["moratorium_until"] is None
    assert segment["last_treatment_type"] == "NONE"


# ----------------------------------------------------------------------
# Project lines: PLANNED is the only removable state, REMOVED is terminal
# ----------------------------------------------------------------------


def test_a_line_cannot_be_pulled_out_of_an_awarded_bundle(api):
    """The line itself is still PLANNED; the scope lock lives on the parent bundle.

    PRD: "Both adding and removing lines require the project's `delivery_status` to be
    `DRAFT` or `COORDINATING`; once the bundle has moved beyond coordination its scope
    is fixed and both operations report `ERR_PROJECT_SCOPE_LOCKED`."

    Design: Corner/state_machines/line_delete_on_an_awarded_project_rejected
    """
    ctx = fixtures.maple_awarded(api)
    line = ctx["lines"]["Maple St"]
    assert ctx["project"]["delivery_status"] == "AWARDED"
    assert fixtures.read_line(api, line["id"])["work_state"] == "PLANNED"

    validate_error(
        api.delete_project_segment(line["id"], ENGINEER),
        ApiErrorId.PROJECT_SCOPE_LOCKED,
        409,
    )

    project = fixtures.read_project(api, ctx["project"]["id"])
    candidate = fixtures.read_candidate(api, fixtures.candidate_for(ctx, "Maple St")["id"])
    assert fixtures.read_line(api, line["id"])["work_state"] == "PLANNED"
    assert project["delivery_status"] == "AWARDED"
    assert_project_scope(project, 1, AREA_MAPLE)
    assert_project_estimate(
        project, MAPLE_BUNDLE_BASE, MAPLE_CONTINGENCY, 0, MAPLE_TOTAL
    )
    assert candidate["candidate_status"] == "CONSUMED"


def test_deleting_an_already_removed_line_refuses_and_double_counts_nothing(api):
    """REMOVED is terminal, so the repeat call cannot decrement anything twice.

    PRD: "It moves the line's `work_state` from `PLANNED` to `REMOVED` and is
    permitted only from `PLANNED`; on any other work state it reports
    `ERR_PROJECT_SEGMENT_NOT_REMOVABLE`."

    PRD: "The freed candidate returns to the pool, and which state it returns to
    depends on its history: a candidate with a null `override_reason` returns to
    `RECOMMENDED`, while a candidate carrying an `override_reason` returns to
    `OVERRIDDEN` with its override intact."

    Design: Corner/state_machines/line_delete_repeated_on_a_removed_line_rejected
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.draft_project(api, ctx, fixtures.MAPLE_LINE)
    line = ctx["lines"]["Maple St"]
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    candidate_id = fixtures.candidate_for(ctx, "Maple St")["id"]

    removed = validate_success(api.delete_project_segment(line["id"], ENGINEER))
    assert removed["work_state"] == "REMOVED"
    assert fixtures.read_project(api, ctx["project"]["id"])["segment_count"] == 0

    validate_error(
        api.delete_project_segment(line["id"], ENGINEER),
        ApiErrorId.PROJECT_SEGMENT_NOT_REMOVABLE,
        409,
    )

    project = fixtures.read_project(api, ctx["project"]["id"])
    candidate = fixtures.read_candidate(api, candidate_id)
    assert fixtures.read_line(api, line["id"])["work_state"] == "REMOVED"
    assert project["segment_count"] == 0
    assert_area(project["planned_area_sy"], 0.0)
    assert candidate["candidate_status"] == "RECOMMENDED"
    assert candidate["override_reason"] is None
    assert fixtures.read_segment(api, segment_id)["active_project_count"] == 0


# ----------------------------------------------------------------------
# Acceptance tests: PASSED is terminal, FAILED can be superseded
# ----------------------------------------------------------------------


def _one_passed_test_on_maple(api):
    """Maple St under construction with a full-marks test already decided PASS."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.in_construction_project(api, ctx, fixtures.MAPLE_LINE)
    submitted = fixtures.submit_test(
        api,
        ctx["lines"]["Maple St"]["id"],
        core_density_pct=PASS_DENSITY_PCT,
        iri_in_per_mi=PASS_IRI,
        thickness_in=PASS_THICKNESS_IN,
    )
    assert_pay_factor(submitted, PASS_PAY_FACTOR, "PASS")
    decided = fixtures.decide_test(
        api, submitted["id"], "PASS", "test decision recorded"
    )
    assert decided["test_status"] == "PASSED"
    return ctx, decided


def test_a_second_decision_on_a_passed_test_is_refused(api):
    """A different inspector, a legal-looking FAIL, and the terminal state holds.

    PRD: "Every decision requires `test_status` to be `SUBMITTED`, else
    `ERR_TEST_ALREADY_DECIDED`, and requires the deciding `X-User-ID` to differ from
    the test's `witness_inspector_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "`PASSED` and `SUPERSEDED` are the terminal test states; a `FAILED` or
    `RETEST_ORDERED` test is superseded when a higher round is submitted on the same
    line, and the quality dimension can bounce from `TESTING` to
    `REMEDIATION_REQUIRED` and back once per failed line."

    Design: Corner/state_machines/acceptance_test_decided_twice_rejected
    """
    ctx, decided = _one_passed_test_on_maple(api)

    validate_error(
        api.decide_acceptance_test(
            decided["id"],
            acceptance_decision_payload("FAIL", "reversing the earlier call"),
            INSPECTOR_DECIDER_2,
        ),
        ApiErrorId.TEST_ALREADY_DECIDED,
        409,
    )

    test_row = validate_success(api.get_acceptance_test(decided["id"], INSPECTOR))
    line = fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])
    project = fixtures.read_project(api, ctx["project"]["id"])
    assert test_row["test_status"] == "PASSED"
    assert test_row["decided_by_user_id"] == INSPECTOR_DECIDER_USER_ID
    assert line["work_state"] == "WORK_COMPLETE"
    assert_four_decimals(line["pay_factor"], PASS_PAY_FACTOR, "pay_factor")
    assert project["quality_status"] == "QUALITY_ACCEPTED"
    assert project["open_remediation_count"] == 0


def test_the_refused_reversal_never_reaches_the_contractors_scorecard(api):
    """The weighted score counts one passed test and no failures at all.

    PRD: "The quality component is 100.00 when the contractor has no decided tests at
    all; otherwise it is 100 multiplied by the passed-test count, divided by the sum
    of the passed and failed counts, rounded to two decimal places."

    PRD: "`standing` is derived from `interim_performance_score` alone:
    `GOOD_STANDING` when the interim score is at least 80.0, `WATCH` when it is at
    least 60.0 but below 80.0, and `SUSPENDED` when it is below 60.0."

    Design: Corner/state_machines/acceptance_test_decided_twice_rejected
    """
    ctx, decided = _one_passed_test_on_maple(api)

    validate_error(
        api.decide_acceptance_test(
            decided["id"],
            acceptance_decision_payload("FAIL", "reversing the earlier call"),
            INSPECTOR_DECIDER_2,
        ),
        ApiErrorId.TEST_ALREADY_DECIDED,
        409,
    )

    scorecard = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )
    assert scorecard["passed_test_count"] == 1
    assert scorecard["failed_test_count"] == 0
    assert scorecard["remediation_event_count"] == 0
    assert scorecard["interim_performance_score"] == 100.0
    assert scorecard["standing"] == "GOOD_STANDING"


def test_a_retest_closes_the_remediation_loop_across_three_entities(api):
    """One submission supersedes the failure, reopens the line and clears the count.

    PRD: "Submitting a higher round supersedes the prior decided round — any test on
    the line whose `test_status` is `FAILED` or `RETEST_ORDERED` moves to
    `SUPERSEDED`."

    PRD: "When the superseded test was `FAILED`, the line returns from
    `REMEDIATION_REQUIRED` to `IN_PROGRESS` and the project's `open_remediation_count`
    decreases by 1; when it was `RETEST_ORDERED` there is no work-state change,
    because the line was already `IN_PROGRESS`."

    Design: Corner/state_machines/retest_submission_supersedes_the_failed_test_and_reopens_the_line
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.in_construction_project(api, ctx, fixtures.MAPLE_LINE)
    ctx = fixtures.failing_test_on(api, ctx, "Maple St", core_density_pct=FAIL_DENSITY_PCT)
    round_one = ctx["tests"]["Maple St"]
    line_id = ctx["lines"]["Maple St"]["id"]
    assert round_one["test_status"] == "FAILED"
    assert fixtures.read_line(api, line_id)["work_state"] == "REMEDIATION_REQUIRED"
    assert fixtures.read_project(api, ctx["project"]["id"])["open_remediation_count"] == 1

    retest = validate_success(
        api.create_acceptance_test(
            acceptance_test_payload(
                line_id,
                INSPECTOR_WITNESS_2_USER_ID,
                PASS_DENSITY_PCT,
                PASS_IRI,
                PASS_THICKNESS_IN,
            ),
            INSPECTOR_WITNESS_2,
        ),
        201,
    )

    superseded = validate_success(api.get_acceptance_test(round_one["id"], INSPECTOR))
    line = fixtures.read_line(api, line_id)
    project = fixtures.read_project(api, ctx["project"]["id"])
    assert retest["test_round"] == 2
    assert retest["test_status"] == "SUBMITTED"
    assert_pay_factor(retest, PASS_PAY_FACTOR, "PASS")
    assert superseded["test_status"] == "SUPERSEDED"
    assert line["work_state"] == "IN_PROGRESS"
    assert line["test_count"] == 2
    assert project["quality_status"] == "TESTING"
    assert project["open_remediation_count"] == 0


def test_the_repaired_defect_still_counts_against_the_contractor(api):
    """The loop closes on the pavement, but the remediation event is historical.

    PRD: "The contractor's `remediation_event_count` is *not* decremented when a line
    recovers: the event is historical."

    PRD: "The **interim** variant, stored as `interim_performance_score`, is
    recomputed on every acceptance-test decision, on substantial completion and on
    final acceptance, and it is the variant that derives `standing`."

    The retest is only submitted, not decided, so the failed-test count still stands
    alone and the interim score stays at 53.0.

    Design: Corner/state_machines/retest_submission_supersedes_the_failed_test_and_reopens_the_line
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.in_construction_project(api, ctx, fixtures.MAPLE_LINE)
    ctx = fixtures.failing_test_on(api, ctx, "Maple St", core_density_pct=FAIL_DENSITY_PCT)
    line_id = ctx["lines"]["Maple St"]["id"]
    before = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )
    assert before["remediation_event_count"] == 1
    assert_contractor_standing(before, "SUSPENDED", SUSPENDED_INTERIM_SCORE)

    validate_success(
        api.create_acceptance_test(
            acceptance_test_payload(
                line_id,
                INSPECTOR_WITNESS_2_USER_ID,
                PASS_DENSITY_PCT,
                PASS_IRI,
                PASS_THICKNESS_IN,
            ),
            INSPECTOR_WITNESS_2,
        ),
        201,
    )

    after = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )
    assert after["remediation_event_count"] == 1
    assert after["failed_test_count"] == 1
    assert after["passed_test_count"] == 0
    assert_contractor_standing(after, "SUSPENDED", SUSPENDED_INTERIM_SCORE)


# ----------------------------------------------------------------------
# Cut permits on unencumbered pavement: PENDING, and no waiver anywhere
# ----------------------------------------------------------------------


def test_a_cut_on_unprotected_pavement_opens_pending_on_the_bottom_fee_tier(api):
    """No moratorium means no remaining days, no tier uplift and no review state.

    PRD: "When the segment's `moratorium_until` is null, or has already passed the
    logical clock, or when the application is flagged as an emergency, the permit
    opens at `permit_status` `PENDING`."

    PRD: "First, `moratorium_remaining_days` is zero when the segment's
    `moratorium_until` is null; otherwise it is the whole seconds from the logical
    clock to `moratorium_until` divided by the 86,400 seconds in a day with the
    fraction discarded, floored at zero."

    PRD: "Fourth, the base fee is the trench area multiplied by 850 cents per square
    foot, rounded to whole cents, but never less than the 45,000-cent ($450) minimum."

    A 200-square-foot trench bills 170000 cents of base fee, and a 1.0 multiplier
    leaves it exactly there.

    Design: Corner/state_machines/cut_permit_on_an_unencumbered_segment_starts_pending_and_approves_without_a_waiver
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, fixtures.MAPLE_LINE)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    assert fixtures.read_segment(api, segment_id)["moratorium_until"] is None

    permit = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="WATER",
        requested_start=CUT_WINDOW_START,
        requested_end=CUT_WINDOW_END,
        cut_area_sqft=CUT_AREA_SQFT,
        emergency=False,
    )

    assert permit["permit_status"] == "PENDING"
    assert permit["moratorium_remaining_days"] == 0
    assert permit["fee_multiplier"] == 1.0
    assert_money(permit["degradation_fee_cents"], CUT_FEE_UNENCUMBERED)
    assert permit["waiver_reason"] is None
    assert permit["decided_at"] is None


def test_approving_a_pending_cut_needs_no_written_waiver(api):
    """The waiver demand belongs to MORATORIUM_REVIEW alone, not to every approval.

    PRD: "A `PENDING` permit needs no waiver, and its `waiver_reason` stays null."

    PRD: "Approval moves the permit to `APPROVED`, stamps `decided_at` and freezes
    `degradation_fee_cents` at its current value."

    The line beneath the trench is still `PLANNED` rather than in active
    construction, so the worker-safety block never engages.

    Design: Corner/state_machines/cut_permit_on_an_unencumbered_segment_starts_pending_and_approves_without_a_waiver
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx, fixtures.MAPLE_LINE)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    permit = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="WATER",
        requested_start=CUT_WINDOW_START,
        requested_end=CUT_WINDOW_END,
        cut_area_sqft=CUT_AREA_SQFT,
        emergency=False,
    )

    approved = validate_success(
        api.decide_cut_permit(permit["id"], cut_decide_payload("APPROVE"), ENGINEER)
    )

    assert approved["permit_status"] == "APPROVED"
    assert approved["waiver_reason"] is None
    assert approved["decided_at"].startswith("2026-08-01T00:00:00")
    assert_money(approved["degradation_fee_cents"], CUT_FEE_UNENCUMBERED)
    assert fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])["work_state"] == "PLANNED"
    assert validate_success(api.get_cut_permit(permit["id"], COORDINATOR))[
        "cut_completed_at"
    ] is None


# ----------------------------------------------------------------------
# Service requests: the one terminal reachable straight out of NEW
# ----------------------------------------------------------------------


def test_a_new_complaint_can_be_closed_as_a_duplicate_without_triage(api):
    """CLOSED_DUPLICATE is reachable from NEW, and the open count falls once.

    PRD: "`DUPLICATE` closes a request in `NEW`, `TRIAGED_PATCH` or
    `DEFERRED_TO_CAPITAL` to `CLOSED_DUPLICATE`, leaving any `capital_project_id` as
    it stands for audit."

    PRD: "`sla_due_at` is the request's `created_at` plus the response allowance for
    its severity: 72 hours for `HIGH`, 168 hours for `MEDIUM`, and 720 hours for
    `LOW`."

    Design: Corner/state_machines/service_request_closed_as_duplicate_straight_from_new
    """
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api)
    request = fixtures.file_service_request(
        api, segment["id"], location_note="deep pothole at 1200 block driveway"
    )
    assert request["request_status"] == "NEW"
    assert request["sla_due_at"].startswith(SLA_DUE_HIGH)
    assert fixtures.read_segment(api, segment["id"])["open_service_request_count"] == 1

    fixtures.set_clock(api, CLOCK_2026_08_02)
    closed = fixtures.close_service_request(api, request["id"], "DUPLICATE")

    assert closed["request_status"] == "CLOSED_DUPLICATE"
    assert closed["closure_code"] == "DUPLICATE"
    assert closed["closed_at"].startswith("2026-08-02T00:00:00")
    assert closed["triaged_at"] is None
    assert closed["capital_project_id"] is None
    assert fixtures.read_segment(api, segment["id"])["open_service_request_count"] == 0


def test_a_closed_complaint_freezes_its_breach_flag_at_the_closing_instant(api):
    """The reference instant stops moving once the request is closed.

    PRD: "The `sla_breached` flag compares a reference instant against that deadline —
    the reference is `closed_at` once the request has reached a closed state, and the
    logical clock while it is still open — and is true only when the reference is
    *strictly* later than `sla_due_at`; landing exactly on the deadline is not a
    breach."

    The clock ends six days past the 2026-08-04 deadline, and the flag still reads
    false because it is measured from the 2026-08-02 closure.

    Design: Corner/state_machines/service_request_closed_as_duplicate_straight_from_new
    """
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api)
    request = fixtures.file_service_request(
        api, segment["id"], location_note="deep pothole at 1200 block driveway"
    )
    fixtures.set_clock(api, CLOCK_2026_08_02)
    closed = fixtures.close_service_request(api, request["id"], "DUPLICATE")
    assert closed["sla_due_at"].startswith(SLA_DUE_HIGH)
    assert closed["sla_breached"] is False

    fixtures.set_clock(api, CLOCK_2026_08_10)
    later = validate_success(api.get_service_request(request["id"], ENGINEER))

    assert later["sla_breached"] is False
    assert later["closed_at"] == closed["closed_at"]
    assert later["sla_due_at"] == closed["sla_due_at"]


def test_closing_an_untriaged_complaint_as_patched_is_refused(api):
    """The same request accepts DUPLICATE, so it is the code that is illegal here.

    PRD: "`PATCHED` closes a `TRIAGED_PATCH` request to `CLOSED_PATCHED`; attempted
    from any other state it reports `ERR_SERVICE_REQUEST_NOT_TRIAGED`, so a `NEW` or
    `DEFERRED_TO_CAPITAL` request can only be closed as a duplicate."

    Design: Corner/state_machines/service_request_closed_as_patched_from_new_rejected
    """
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api)
    request = fixtures.file_service_request(
        api, segment["id"], location_note="deep pothole at 1200 block driveway"
    )
    assert request["request_status"] == "NEW"

    validate_error(
        api.close_service_request(request["id"], close_payload("PATCHED"), ENGINEER),
        ApiErrorId.SERVICE_REQUEST_NOT_TRIAGED,
        409,
    )

    after = validate_success(api.get_service_request(request["id"], ENGINEER))
    assert after["request_status"] == "NEW"
    assert after["closed_at"] is None
    assert after["closure_code"] is None
    assert fixtures.read_segment(api, segment["id"])["open_service_request_count"] == 1

"""State-machine behaviour: declared initial states, legal transitions, refused transitions and terminal lockdowns."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BOARD,
    COORDINATOR,
    OFFICER,
    PLANNER,
    PLANNER_USER_ID,
    RIVERBEND_CLOCK,
    RIVERBEND_SCHOOLS,
    ApiErrorId,
    OFFICER_USER_ID,
    advance_entitlement_to,
    api_client,
    create_adjacency,
    create_adoption_payload,
    create_comment,
    create_housing_development,
    create_planning_area,
    create_projection_run,
    create_scenario,
    create_school,
    create_scenario_payload,
    create_comment_payload,
    create_study,
    create_transfer_request,
    create_variance_observation_payload,
    decide_transfer,
    make_guardian_headers,
    open_engagement,
    program_placement,
    request_revision,
    riverbend_adopted,
    riverbend_engagement_open,
    riverbend_locked,
    riverbend_scenario_assigned,
    set_clock,
    setup_study_with_inventory,
    submit_for_review,
    travel_option,
    triage_comment,
    activate_adoption,
    advance_to_board,
)
from test_helpers.fixtures import riverbend_area_builders


# ---------------------------------------------------------------------------
# Local setup builders (each test still starts from an empty database)
# ---------------------------------------------------------------------------
def _riverbend_unlocked() -> dict:
    """Riverbend USD with its complete seed inventory, still in SETUP."""
    ctx = setup_study_with_inventory(
        school_payloads=RIVERBEND_SCHOOLS,
        area_builders=riverbend_area_builders(),
        adjacency_specs=(("A-01", "A-02", 5200), ("A-02", "A-03", 4100)),
        clock=RIVERBEND_CLOCK,
        lock=False,
    )
    ctx["cedar_id"] = ctx["school_ids"]["Cedar Elementary"]
    ctx["birch_id"] = ctx["school_ids"]["Birch Elementary"]
    ctx["a1_id"] = ctx["area_ids"]["A-01"]
    ctx["a2_id"] = ctx["area_ids"]["A-02"]
    ctx["a3_id"] = ctx["area_ids"]["A-03"]
    return ctx


def _engagement_with_draft_sibling() -> dict:
    """Scenario A under review with the study in ENGAGEMENT, plus a DRAFT sibling Scenario B."""
    ctx = riverbend_scenario_assigned()
    sibling = create_scenario(
        ctx["study_id"],
        ctx["run_id"],
        [program_placement(ctx["cedar_id"], 24)],
        name="Scenario B",
    )
    ctx["sibling"] = sibling
    ctx["sibling_id"] = sibling["id"]
    ctx["scenario"] = submit_for_review(ctx["scenario_id"])
    ctx["study"] = open_engagement(ctx["study_id"], api_client, COORDINATOR)
    return ctx


# ---------------------------------------------------------------------------
# Initial states and legal transitions
# ---------------------------------------------------------------------------
def test_lock_data_moves_study_from_setup_to_data_locked():
    """Locking a complete seed inventory moves SETUP to DATA_LOCKED and freezes the roll-up totals.

    PRD: "Locking the seed data is the planner's declaration that the map's inputs are
    final, and it moves the study `SETUP → DATA_LOCKED`."
    PRD: "On success the server stamps `data_locked_at` with the current logical-clock
    instant, recomputes `resident_student_total`, recomputes `enrolled_students_of_record`
    for every school of the study and then `enrolled_of_record_total`, and increments the
    study's `version`."

    Design: Corner/state_machines/lock_data_moves_study_from_setup_to_data_locked
    """
    ctx = _riverbend_unlocked()
    assert ctx["study"]["status"] == "SETUP", "the study must still be in SETUP before the lock"

    locked = validate_success(api_client.lock_study_data(ctx["study_id"], PLANNER), 200)

    assert locked["status"] == "DATA_LOCKED", (
        f"lock-data must move the study to DATA_LOCKED, got {locked['status']!r}"
    )
    assert locked["data_locked_at"] is not None, "data_locked_at must be stamped on the lock"
    assert locked["data_locked_at"].startswith("2026-09-01T00:00:00"), (
        "data_locked_at must carry the logical-clock instant 2026-09-01T00:00:00Z, got "
        f"{locked['data_locked_at']!r}"
    )
    assert locked["resident_student_total"] == 650, (
        f"resident_student_total must be 300 + 200 + 150 = 650, got {locked['resident_student_total']}"
    )
    assert locked["enrolled_of_record_total"] == 650, (
        f"enrolled_of_record_total must be 500 + 150 = 650, got {locked['enrolled_of_record_total']}"
    )
    assert locked["comment_intake_open"] is False, "intake is only open while the study is in ENGAGEMENT"
    assert locked["projection_stale"] is False, "no projection run exists yet, so nothing is stale"

    reread = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert reread["status"] == "DATA_LOCKED", "the locked status must be persisted"


def test_scenario_and_development_start_in_their_declared_initial_state():
    """A freshly created scenario lands in DRAFT with empty-scenario scores; a new development lands in PROPOSED.

    PRD: "On creation the scenario's `status` is `DRAFT`, its `revision_round` is 0, and
    `revision_reason` and `rejection_reason` are both null."
    PRD: "Every objective score is initialised to its empty-scenario value: `contiguity_ok`
    true, `noncontiguous_school_ids` an empty array, `total_assigned_students` 0,
    `max_utilization_pct` 0.00, `walk_eligible_pct` 0.00, `transport_cost_annual_usd` 0.00,
    `students_reassigned_count` 0, `students_reassigned_pct` 0.00 and
    `frl_dissimilarity_index` 0.0000."
    PRD: "A new development always begins at `entitlement_status` `PROPOSED`."

    Design: Corner/state_machines/scenario_and_transfer_request_start_in_their_declared_initial_state
    """
    ctx = riverbend_locked()

    willow = create_housing_development(
        ctx["a1_id"],
        name="Willow Ridge",
        unit_type="SINGLE_FAMILY",
        total_units=120,
        first_occupancy_date="2027-01-01T00:00:00Z",
        buildout_months=24,
    )
    advance_entitlement_to(willow["id"], "UNDER_CONSTRUCTION")
    create_housing_development(
        ctx["a2_id"],
        name="Maple Flats",
        unit_type="MULTI_FAMILY",
        total_units=200,
        first_occupancy_date="2027-03-01T00:00:00Z",
        buildout_months=20,
    )
    create_housing_development(
        ctx["a3_id"],
        name="Juniper Commons",
        unit_type="TOWNHOME",
        total_units=90,
        first_occupancy_date="2031-01-01T00:00:00Z",
        buildout_months=36,
    )
    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")

    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(ctx["cedar_id"], 30)],
        name="Scenario Z",
        impact_variant="RESIDENT_BASED",
    )
    beacon = create_housing_development(
        ctx["a3_id"],
        name="Beacon Hollow",
        unit_type="TOWNHOME",
        total_units=30,
        first_occupancy_date="2027-09-01T00:00:00Z",
        buildout_months=12,
    )

    assert scenario["status"] == "DRAFT", f"a new scenario starts in DRAFT, got {scenario['status']!r}"
    assert scenario["revision_round"] == 0, (
        f"a new scenario starts at revision_round 0, got {scenario['revision_round']}"
    )
    assert scenario["revision_reason"] is None, "revision_reason starts null"
    assert scenario["rejection_reason"] is None, "rejection_reason starts null"
    assert scenario["contiguity_ok"] is True, "an empty scenario is vacuously contiguous"
    assert scenario["noncontiguous_school_ids"] == [], "no school can be non-contiguous yet"
    assert scenario["total_assigned_students"] == 0, "no assignment exists yet"
    assert scenario["max_utilization_pct"] == pytest.approx(0.00, abs=0.01), (
        "scores are not pre-computed at create time, so max_utilization_pct is 0.00, got "
        f"{scenario['max_utilization_pct']}"
    )
    assert scenario["walk_eligible_pct"] == pytest.approx(0.00, abs=0.01), "walk_eligible_pct starts at 0.00"
    assert scenario["transport_cost_annual_usd"] == pytest.approx(0.00, abs=0.01), (
        "transport_cost_annual_usd starts at 0.00"
    )
    assert scenario["students_reassigned_count"] == 0, "students_reassigned_count starts at 0"
    assert scenario["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01), (
        "students_reassigned_pct starts at 0.00"
    )
    assert scenario["frl_dissimilarity_index"] == pytest.approx(0.0000, abs=0.0001), (
        "frl_dissimilarity_index starts at 0.0000"
    )
    assert scenario["author_user_id"] == PLANNER_USER_ID, (
        f"author_user_id is stamped from X-User-ID, expected {PLANNER_USER_ID!r}, got "
        f"{scenario['author_user_id']!r}"
    )
    assert scenario["version"] == 1, f"a new record starts at version 1, got {scenario['version']}"

    assert beacon["entitlement_status"] == "PROPOSED", (
        f"a new development starts at PROPOSED, got {beacon['entitlement_status']!r}"
    )

    _, meta = validate_paginated(
        api_client.list_housing_developments(
            ctx["a3_id"], PLANNER, {"entitlement_status": "PROPOSED"}
        )
    )
    assert meta["total_count"] == 2, (
        f"area A-03 must hold two PROPOSED developments, got {meta['total_count']}"
    )


def test_first_complete_projection_run_auto_advances_the_study_phase():
    """The first COMPLETE run advances DATA_LOCKED to SCENARIO_DEVELOPMENT; a second run only supersedes.

    PRD: "The study's `version` is incremented and its `projection_stale` flag recomputed,
    and if the study was in `DATA_LOCKED` it advances automatically to
    `SCENARIO_DEVELOPMENT` — the planner never posts that transition directly."
    PRD: "A successful run is stored with `status` `COMPLETE` and `stale_reason` null; any
    earlier run of the same study and the same `variant` whose `status` is `COMPLETE` or
    `STALE` moves to `SUPERSEDED`, walked in run creation order."
    PRD: "An area's baseline is its `resident_student_count` multiplied by the cohort
    survival rate of 0.98 raised to the power of `horizon_years`, rounded half up to a whole
    student; that value is the entry's `base_students`."

    Design: Corner/state_machines/first_complete_projection_run_auto_advances_the_study_phase
    """
    ctx = riverbend_locked()

    first = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")

    assert first["status"] == "COMPLETE", f"a successful run is COMPLETE, got {first['status']!r}"
    assert first["horizon_years"] == 5, (
        f"the run inherits the study's horizon_years of 5, got {first['horizon_years']}"
    )
    assert first.get("stale_reason") is None, "a COMPLETE run carries a null stale_reason"

    by_area = {row["area_id"]: row for row in first["area_projections"]}
    assert by_area[ctx["a1_id"]]["projected_students"] == 271, (
        "A-01 projects 300 * 0.98^5 = 271 students, got "
        f"{by_area[ctx['a1_id']]['projected_students']}"
    )
    assert by_area[ctx["a2_id"]]["projected_students"] == 181, (
        "A-02 projects 200 * 0.98^5 = 181 students, got "
        f"{by_area[ctx['a2_id']]['projected_students']}"
    )
    assert by_area[ctx["a3_id"]]["projected_students"] == 136, (
        "A-03 projects 150 * 0.98^5 = 136 students, got "
        f"{by_area[ctx['a3_id']]['projected_students']}"
    )
    assert by_area[ctx["a3_id"]]["development_students"] == pytest.approx(0.00, abs=0.01), (
        "no housing development exists, so every development term is 0.00"
    )
    assert first["projected_total_students"] == 588, (
        f"the study total is 271 + 181 + 136 = 588, got {first['projected_total_students']}"
    )

    after_first = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert after_first["status"] == "SCENARIO_DEVELOPMENT", (
        "the first COMPLETE run advances the study out of DATA_LOCKED, got "
        f"{after_first['status']!r}"
    )

    second = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")

    reread_first = get_success_data(api_client.get_projection_run(first["id"], PLANNER))
    assert reread_first["status"] == "SUPERSEDED", (
        f"the earlier run of the same variant is SUPERSEDED, got {reread_first['status']!r}"
    )
    reread_second = get_success_data(api_client.get_projection_run(second["id"], PLANNER))
    assert reread_second["status"] == "COMPLETE", (
        f"the newest run is COMPLETE, got {reread_second['status']!r}"
    )

    after_second = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert after_second["status"] == "SCENARIO_DEVELOPMENT", (
        "the auto-advance fires only out of DATA_LOCKED, so the study stays in "
        f"SCENARIO_DEVELOPMENT, got {after_second['status']!r}"
    )

    _, meta = validate_paginated(
        api_client.list_projection_runs(
            ctx["study_id"], PLANNER, {"variant": "COHORT_SURVIVAL"}
        )
    )
    assert meta["total_count"] == 2, (
        f"both COHORT_SURVIVAL runs remain readable, got total_count {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Preconditions on transitions
# ---------------------------------------------------------------------------
def test_lock_data_with_incomplete_seed_inventory_rejected():
    """Each clause of the seed-completeness rule is independently fatal, repaired one at a time.

    PRD: "It succeeds only from `SETUP` and only when the inventory is complete: the study
    must have at least 2 `ACTIVE` schools and at least 3 planning areas, every planning area
    must appear as the `area_id` of at least one adjacency row, and every planning area's
    `travel_options` must contain exactly one entry for each `ACTIVE` school of the study
    whose `level` equals that area's `grade_band` — no missing pair, no duplicate pair."
    PRD: "Any shortfall is rejected with `ERR_STUDY_SETUP_INCOMPLETE`."

    Design: Corner/state_machines/lock_data_with_incomplete_seed_inventory_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    study = create_study(
        name="2029 Boundary Pilot",
        district_name="Harborview USD",
        target_school_year=2029,
        horizon_years=5,
        capacity_target_low_pct=85.0,
        capacity_target_high_pct=100.0,
        portables_count_toward_capacity=False,
        required_program_types=["DUAL_LANGUAGE"],
    )
    study_id = study["id"]
    quay = create_school(
        study_id,
        name="Quay Elementary",
        level="ELEMENTARY",
        core_capacity_seats=500,
        program_types=["DUAL_LANGUAGE"],
    )
    pier = create_school(
        study_id, name="Pier Elementary", level="ELEMENTARY", core_capacity_seats=400
    )

    def both_travel_options():
        return [
            travel_option(quay["id"], 0.6, 10, True),
            travel_option(pier["id"], 0.9, 13, True),
        ]

    h01 = create_planning_area(
        study_id,
        quay["id"],
        both_travel_options(),
        area_code="H-01",
        grade_band="ELEMENTARY",
        resident_student_count=300,
        frl_student_count=90,
        ell_student_count=30,
        median_household_income_usd=74000,
        annual_absorption_cap_units=150,
    )
    h02 = create_planning_area(
        study_id,
        quay["id"],
        both_travel_options(),
        area_code="H-02",
        grade_band="ELEMENTARY",
        resident_student_count=200,
        frl_student_count=60,
        ell_student_count=20,
        median_household_income_usd=81000,
        annual_absorption_cap_units=150,
    )
    create_adjacency(h01["id"], h02["id"], shared_boundary_length_ft=4800)

    validate_error(
        api_client.lock_study_data(study_id, PLANNER),
        ApiErrorId.ERR_STUDY_SETUP_INCOMPLETE.value,
    )
    after_first = get_success_data(api_client.get_study(study_id, PLANNER))
    assert after_first["status"] == "SETUP", (
        f"a refused lock leaves the study in SETUP, got {after_first['status']!r}"
    )
    assert after_first["data_locked_at"] is None, "a refused lock stamps nothing"

    h03 = create_planning_area(
        study_id,
        pier["id"],
        [
            travel_option(quay["id"], 1.8, 18, False),
            travel_option(pier["id"], 0.7, 11, True),
        ],
        area_code="H-03",
        grade_band="ELEMENTARY",
        resident_student_count=150,
        frl_student_count=30,
        ell_student_count=10,
        median_household_income_usd=95000,
        annual_absorption_cap_units=150,
    )

    validate_error(
        api_client.lock_study_data(study_id, PLANNER),
        ApiErrorId.ERR_STUDY_SETUP_INCOMPLETE.value,
    )

    create_adjacency(h02["id"], h03["id"], shared_boundary_length_ft=3900)

    locked = validate_success(api_client.lock_study_data(study_id, PLANNER), 200)
    assert locked["status"] == "DATA_LOCKED", (
        f"with the inventory complete the lock succeeds, got {locked['status']!r}"
    )
    assert locked["resident_student_total"] == 650, (
        f"resident_student_total must be 300 + 200 + 150 = 650, got {locked['resident_student_total']}"
    )
    assert locked["data_locked_at"] is not None and locked["data_locked_at"].startswith(
        "2026-09-01T00:00:00"
    ), f"data_locked_at must carry the clock instant, got {locked['data_locked_at']!r}"

    rows, _ = validate_paginated(api_client.list_area_adjacencies(h03["id"], PLANNER))
    own_rows = [row for row in rows if row["area_id"] == h03["id"]]
    assert len(own_rows) == 1, (
        "the server-minted mirror gives H-03 exactly one row of its own, got "
        f"{len(own_rows)}"
    )
    assert own_rows[0]["is_reciprocal"] is True, "that row is the reciprocal mirror"
    assert own_rows[0]["neighbor_area_id"] == h02["id"], "H-03 mirrors the H-02 edge"


def test_open_engagement_without_a_reviewed_scenario_rejected():
    """Intake may not open while the study's only scenario is still DRAFT.

    PRD: "An `EngagementCoordinator` opens it, moving the study `SCENARIO_DEVELOPMENT →
    ENGAGEMENT`, and the operation succeeds only from `SCENARIO_DEVELOPMENT` and only when
    at least one scenario of the study is in `UNDER_REVIEW` — with nothing under review
    there is nothing for the public to react to, and the request is rejected with
    `ERR_NO_SCENARIO_UNDER_REVIEW`."

    Design: Corner/state_machines/open_engagement_without_a_reviewed_scenario_rejected
    """
    ctx = riverbend_scenario_assigned()

    validate_error(
        api_client.open_engagement(ctx["study_id"], COORDINATOR),
        ApiErrorId.ERR_NO_SCENARIO_UNDER_REVIEW.value,
    )

    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "SCENARIO_DEVELOPMENT", (
        f"the refused open-engagement leaves the phase untouched, got {study['status']!r}"
    )
    assert study["comment_intake_open"] is False, "intake must stay closed"

    scenario = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert scenario["status"] == "DRAFT", (
        f"the fully assigned scenario is still DRAFT, got {scenario['status']!r}"
    )


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------
def test_entitlement_advance_skipping_or_reversing_a_stage_rejected():
    """PERMITTED skips a stage from PROPOSED, and the terminal WITHDRAWN admits nothing at all.

    PRD: "The advance names a `to_status`, which must be the immediate successor of the
    development's current stage along `PROPOSED → ENTITLED → PERMITTED → UNDER_CONSTRUCTION
    → COMPLETE`, or `WITHDRAWN` from any non-terminal stage."
    PRD: "Stages may not be skipped and may not be walked backwards, and a development
    already at `COMPLETE` or `WITHDRAWN` has no further moves; every other request is
    rejected with `ERR_ENTITLEMENT_STAGE_INVALID`."

    Design: Corner/state_machines/entitlement_advance_skipping_or_reversing_a_stage_rejected
    """
    ctx = riverbend_locked()
    development = create_housing_development(
        ctx["a1_id"],
        name="Willow Ridge",
        unit_type="SINGLE_FAMILY",
        total_units=120,
        first_occupancy_date="2027-01-01T00:00:00Z",
        buildout_months=24,
    )
    development_id = development["id"]

    validate_error(
        api_client.advance_entitlement(development_id, {"to_status": "PERMITTED"}, PLANNER),
        ApiErrorId.ERR_ENTITLEMENT_STAGE_INVALID.value,
    )
    after_skip = get_success_data(
        api_client.get_housing_development(development_id, PLANNER)
    )
    assert after_skip["entitlement_status"] == "PROPOSED", (
        f"the refused skip leaves the stage at PROPOSED, got {after_skip['entitlement_status']!r}"
    )

    withdrawn = validate_success(
        api_client.advance_entitlement(development_id, {"to_status": "WITHDRAWN"}, PLANNER),
        200,
    )
    assert withdrawn["entitlement_status"] == "WITHDRAWN", (
        f"WITHDRAWN is legal from PROPOSED, got {withdrawn['entitlement_status']!r}"
    )

    validate_error(
        api_client.advance_entitlement(development_id, {"to_status": "ENTITLED"}, PLANNER),
        ApiErrorId.ERR_ENTITLEMENT_STAGE_INVALID.value,
    )
    final = get_success_data(api_client.get_housing_development(development_id, PLANNER))
    assert final["entitlement_status"] == "WITHDRAWN", (
        f"WITHDRAWN is terminal, got {final['entitlement_status']!r}"
    )


def test_advance_to_board_from_draft_rejected():
    """A DRAFT sibling cannot be certified for the board even though its study is already in ENGAGEMENT.

    PRD: "It requires the study to be in `ENGAGEMENT`, the scenario to be in `UNDER_REVIEW`
    (`ERR_SCENARIO_NOT_REVIEWABLE`), the scenario's `projection_stale` to be false
    (`ERR_PROJECTION_STALE`), and the public record to be clean: no comment of that scenario
    may still be in `SUBMITTED`, since every comment must be triaged or dismissed before the
    board reads the map, and an untriaged comment is rejected with
    `ERR_UNADDRESSED_COMMENTS`."

    Design: Corner/state_machines/advance_to_board_from_draft_rejected
    """
    ctx = _engagement_with_draft_sibling()

    validate_error(
        api_client.advance_scenario_to_board(ctx["sibling_id"], COORDINATOR),
        ApiErrorId.ERR_SCENARIO_NOT_REVIEWABLE.value,
    )

    sibling = get_success_data(api_client.get_scenario(ctx["sibling_id"], PLANNER))
    assert sibling["status"] == "DRAFT", (
        f"the refused certification leaves Scenario B in DRAFT, got {sibling['status']!r}"
    )
    reviewed = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert reviewed["status"] == "UNDER_REVIEW", (
        f"the sibling under review was not advanced either, got {reviewed['status']!r}"
    )
    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "ENGAGEMENT", (
        f"the study stays in ENGAGEMENT, got {study['status']!r}"
    )
    assert study["comment_intake_open"] is True, "intake stays open while the study is in ENGAGEMENT"


def test_adoption_of_a_scenario_that_is_not_board_ready_rejected():
    """The board may only adopt from BOARD_READY, even with the study already in BOARD_DECISION.

    PRD: "The study must be in `BOARD_DECISION` and the scenario must be in `BOARD_READY`,
    or the request is rejected with `ERR_SCENARIO_NOT_BOARD_READY`; the scenario must belong
    to the named study (`ERR_CROSS_STUDY_REFERENCE`); and the adopting member must not be
    the scenario's author (`ERR_SELF_ADOPTION_FORBIDDEN`)."

    Design: Corner/state_machines/adoption_of_a_scenario_that_is_not_board_ready_rejected
    """
    ctx = _engagement_with_draft_sibling()
    advance_to_board(ctx["scenario_id"], api_client, COORDINATOR)

    validate_error(
        api_client.create_adoption(
            create_adoption_payload(
                ctx["study_id"],
                ctx["sibling_id"],
                effective_date="2027-07-01T00:00:00Z",
                effective_school_year=2028,
                regime_years=3,
                transfer_deadline_date="2027-08-15T00:00:00Z",
                transfer_cap_pct=95.0,
                variance_tolerance_pct=5.0,
                votes_for=5,
                votes_against=2,
                votes_abstain=0,
                board_member_count=7,
            ),
            BOARD,
        ),
        ApiErrorId.ERR_SCENARIO_NOT_BOARD_READY.value,
    )

    sibling = get_success_data(api_client.get_scenario(ctx["sibling_id"], PLANNER))
    assert sibling["status"] == "DRAFT", (
        f"the refused vote leaves Scenario B in DRAFT, got {sibling['status']!r}"
    )
    board_ready = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert board_ready["status"] == "BOARD_READY", (
        f"the genuinely board-ready sibling was not adopted by accident, got {board_ready['status']!r}"
    )
    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "BOARD_DECISION", (
        f"the study stays in BOARD_DECISION, got {study['status']!r}"
    )

    _, meta = validate_paginated(
        api_client.list_adoptions(BOARD, {"study_id": ctx["study_id"]})
    )
    assert meta["total_count"] == 0, (
        f"no adoption record may be persisted, got total_count {meta['total_count']}"
    )


def test_create_scenario_after_implementation_rejected():
    """Once the study reaches IMPLEMENTATION, both scenario creation and comment intake are refused on phase.

    PRD: "A `DistrictPlanner` creates it against a `study_id` while the study is in
    `DATA_LOCKED` or `SCENARIO_DEVELOPMENT`, naming the `projection_run_id` of the run whose
    per-area projections the scenario will be scored against, a `name` unique within the
    study, an initial `program_placements` array, and an `impact_variant` of either
    `RESIDENT_BASED` or `PROJECTED_BASED` that governs which equity view the impact analysis
    reports and defaults to `RESIDENT_BASED`."
    PRD: "That single boolean is what admits public comment: `comment_intake_open` is true
    exactly while the study's `status` is `ENGAGEMENT`, and a comment submitted at any other
    time is rejected with `ERR_STUDY_PHASE_INVALID`."

    Design: Corner/state_machines/create_scenario_after_implementation_rejected
    """
    ctx = riverbend_adopted()
    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "IMPLEMENTATION", (
        f"the adoption cascade must leave the study in IMPLEMENTATION, got {study['status']!r}"
    )

    validate_error(
        api_client.create_scenario(
            create_scenario_payload(
                ctx["study_id"],
                ctx["run_id"],
                [program_placement(ctx["cedar_id"], 30)],
                name="Scenario Late",
                impact_variant="RESIDENT_BASED",
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_STUDY_PHASE_INVALID.value,
    )
    validate_error(
        api_client.create_comment(
            create_comment_payload(ctx["scenario_id"], body="Too late to comment."),
            make_guardian_headers("guardian-8"),
        ),
        ApiErrorId.ERR_STUDY_PHASE_INVALID.value,
    )

    _, scenario_meta = validate_paginated(
        api_client.list_scenarios(PLANNER, {"study_id": ctx["study_id"]})
    )
    assert scenario_meta["total_count"] == 1, (
        f"no late scenario may be persisted, got total_count {scenario_meta['total_count']}"
    )
    _, comment_meta = validate_paginated(
        api_client.list_comments(PLANNER, {"scenario_id": ctx["scenario_id"]})
    )
    assert comment_meta["total_count"] == 0, (
        f"no late comment may be persisted, got total_count {comment_meta['total_count']}"
    )

    reread = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert reread["status"] == "IMPLEMENTATION", (
        f"the refused calls change no phase, got {reread['status']!r}"
    )


# ---------------------------------------------------------------------------
# Terminal-state lockdown and non-idempotent transitions
# ---------------------------------------------------------------------------
def test_rescinded_adoption_cannot_be_activated_or_closed_again():
    """RESCINDED is terminal: activation, closure and variance recording are all refused.

    PRD: "Activation requires `implementation_status` to be `PENDING_EFFECTIVE`
    (`ERR_ADOPTION_STATE_INVALID`), the adopted scenario to be in `ADOPTED`, and the logical
    clock to have reached the `effective_date` — an attempt while the clock is strictly
    before that instant is rejected with `ERR_EFFECTIVE_DATE_NOT_REACHED`, and an attempt at
    exactly that instant succeeds."
    PRD: "It requires four conditions at once, and any failure is rejected with
    `ERR_ADOPTION_STATE_INVALID`: the adoption's `implementation_status` must be
    `IN_EFFECT`, its `transfer_window_status` must already be `TRANSFER_WINDOW_CLOSED`, every
    `ACTIVE` school of the study must have at least one variance observation recorded for
    this adoption, and no school may currently stand flagged
    `CORRECTIVE_ACTION_REQUIRED`."
    PRD: "The school must belong to the adoption's study (`ERR_CROSS_STUDY_REFERENCE`), and
    recording against an adoption in any other implementation state is rejected with
    `ERR_ADOPTION_STATE_INVALID`."

    Design: Corner/state_machines/rescinded_adoption_cannot_be_activated_or_closed_again
    """
    ctx = riverbend_adopted()
    adoption_id = ctx["adoption_id"]

    set_clock("2027-07-01T00:00:00Z", api_client, OFFICER)
    activate_adoption(adoption_id, api_client, OFFICER)
    rescinded = get_success_data(
        api_client.rescind_adoption(
            adoption_id, {"rescind_reason": "BOARD_RECONSIDERATION"}, BOARD
        )
    )
    assert rescinded["implementation_status"] == "RESCINDED", (
        f"the setup must leave the adoption RESCINDED, got {rescinded['implementation_status']!r}"
    )

    validate_error(
        api_client.activate_adoption(adoption_id, OFFICER),
        ApiErrorId.ERR_ADOPTION_STATE_INVALID.value,
    )
    validate_error(
        api_client.close_monitoring(adoption_id, OFFICER),
        ApiErrorId.ERR_ADOPTION_STATE_INVALID.value,
    )
    validate_error(
        api_client.create_variance_observation(
            adoption_id,
            create_variance_observation_payload(ctx["cedar_id"], 500, 500),
            OFFICER,
        ),
        ApiErrorId.ERR_ADOPTION_STATE_INVALID.value,
    )

    adoption = get_success_data(api_client.get_adoption(adoption_id, BOARD))
    assert adoption["implementation_status"] == "RESCINDED", (
        f"RESCINDED survives all three refused calls, got {adoption['implementation_status']!r}"
    )

    study = get_success_data(api_client.get_study(ctx["study_id"], PLANNER))
    assert study["status"] == "BOARD_DECISION", (
        "the rescission left the study at BOARD_DECISION and nothing moved it since, got "
        f"{study['status']!r}"
    )

    cedar = get_success_data(api_client.get_school(ctx["cedar_id"], PLANNER))
    birch = get_success_data(api_client.get_school(ctx["birch_id"], PLANNER))
    assert cedar["enrolled_students_of_record"] == 500, (
        "Cedar keeps A-01 and A-02, so 300 + 200 = 500 students of record, got "
        f"{cedar['enrolled_students_of_record']}"
    )
    assert birch["enrolled_students_of_record"] == 150, (
        f"Birch keeps A-03, so 150 students of record, got {birch['enrolled_students_of_record']}"
    )

    _, meta = validate_paginated(
        api_client.list_variance_observations(OFFICER, {"adoption_id": adoption_id})
    )
    assert meta["total_count"] == 0, (
        f"the refused observation persisted nothing, got total_count {meta['total_count']}"
    )


def test_denied_transfer_request_cannot_be_decided_again():
    """DENIED is terminal: neither a repeated DENY nor an upgrade to APPROVE is accepted.

    PRD: "The request must be in `SUBMITTED` or `WAITLISTED`, or the decision is rejected
    with `ERR_TRANSFER_NOT_DECIDABLE`; the adoption's `transfer_window_status` must still be
    `TRANSFER_WINDOW_OPEN` (`ERR_ADOPTION_STATE_INVALID`); and the officer must not be the
    filing guardian (`ERR_SELF_DECISION_FORBIDDEN`)."
    PRD: "If no rung matches, `resolved_reason` is `NONE` and `consumes_seat_pool` is false;
    such a request may be created and sits in `SUBMITTED`, but it can only ever be denied."

    Design: Corner/state_machines/denied_transfer_request_cannot_be_decided_again
    """
    ctx = riverbend_adopted()
    request = create_transfer_request(
        ctx["adoption_id"],
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-4"),
        student_reference="STU-200",
        student_grade=2,
        reason="PROGRAM",
    )
    request_id = request["id"]
    decide_transfer(request_id, "DENY", decision_notes="No eligibility basis.")

    validate_error(
        api_client.decide_transfer_request(
            request_id, {"decision": "DENY", "decision_notes": "Denied again."}, OFFICER
        ),
        ApiErrorId.ERR_TRANSFER_NOT_DECIDABLE.value,
    )
    validate_error(
        api_client.decide_transfer_request(
            request_id, {"decision": "APPROVE", "decision_notes": "Reconsidered."}, OFFICER
        ),
        ApiErrorId.ERR_TRANSFER_NOT_DECIDABLE.value,
    )

    final = get_success_data(api_client.get_transfer_request(request_id, OFFICER))
    assert final["status"] == "DENIED", f"DENIED is terminal, got {final['status']!r}"
    assert final["resolved_reason"] == "NONE", (
        f"no phase-in rule exists, so the waterfall resolves to NONE, got {final['resolved_reason']!r}"
    )
    assert final["consumes_seat_pool"] is False, "a NONE resolution consumes no seat"
    assert final["decision_notes"] == "No eligibility basis.", (
        f"the second call's note was not stored, got {final['decision_notes']!r}"
    )
    assert final["decided_by_user_id"] == OFFICER_USER_ID, (
        f"the first decision's officer stands, expected {OFFICER_USER_ID!r}, got "
        f"{final['decided_by_user_id']!r}"
    )
    assert final.get("promotion_source") is None, "a denial sets no promotion_source"

    _, meta = validate_paginated(
        api_client.list_transfer_requests(
            OFFICER, {"adoption_id": ctx["adoption_id"], "status": "DENIED"}
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one denied request exists, got total_count {meta['total_count']}"
    )


def test_second_triage_of_the_same_comment_rejected():
    """Triage is not idempotent, and the refused replay does not relabel the first triage.

    PRD: "Triage requires the comment to be in `SUBMITTED` and the commented scenario to be
    in `UNDER_REVIEW` or `BOARD_READY`; otherwise it is rejected with
    `ERR_COMMENT_STATE_INVALID`."

    Design: Corner/state_machines/second_triage_of_the_same_comment_rejected
    """
    ctx = riverbend_engagement_open()
    comment = create_comment(
        ctx["scenario_id"],
        api_client,
        make_guardian_headers("guardian-6"),
        area_id=ctx["a2_id"],
        body="The A-02 walk route crosses a highway.",
    )
    triage_comment(comment["id"], "TRANSPORTATION", "HIGH")

    validate_error(
        api_client.triage_comment(
            comment["id"], {"theme": "EQUITY", "priority": "LOW"}, COORDINATOR
        ),
        ApiErrorId.ERR_COMMENT_STATE_INVALID.value,
    )

    final = get_success_data(api_client.get_comment(comment["id"], COORDINATOR))
    assert final["status"] == "TRIAGED", f"the comment stays TRIAGED, got {final['status']!r}"
    assert final["theme"] == "TRANSPORTATION", (
        f"the first triage's theme is not overwritten, got {final['theme']!r}"
    )
    assert final["priority"] == "HIGH", (
        f"the first triage's priority is not overwritten, got {final['priority']!r}"
    )

    _, triaged_meta = validate_paginated(
        api_client.list_comments(
            COORDINATOR, {"scenario_id": ctx["scenario_id"], "status": "TRIAGED"}
        )
    )
    assert triaged_meta["total_count"] == 1, (
        f"exactly one triaged comment exists, got total_count {triaged_meta['total_count']}"
    )
    _, equity_meta = validate_paginated(
        api_client.list_comments(
            COORDINATOR, {"scenario_id": ctx["scenario_id"], "theme": "EQUITY"}
        )
    )
    assert equity_meta["total_count"] == 0, (
        f"no comment carries the refused EQUITY theme, got total_count {equity_meta['total_count']}"
    )


def test_revision_loop_beyond_the_third_round_rejected():
    """Three revision passes are allowed; the resubmission of a scenario at round 3 is refused.

    PRD: "The revision loop is bounded."

    PRD: "`revision_round` counts the completed passes through `REVISION`, and the maximum
    is 3: a scenario whose `revision_round` has already reached 3 may not be pushed back
    again, and the request is rejected with `ERR_REVISION_LIMIT_EXCEEDED`; the same limit
    blocks a further resubmission of such a scenario."

    PRD: "Link one moves the scenario `UNDER_REVIEW → REVISION` or `BOARD_READY →
    REVISION`, sets `revision_reason` to `COMMENT_CYCLE`, increments `revision_round` by 1
    and increments the scenario's `version`."

    PRD: "When the scenario is returning from `REVISION`, its `revision_reason` is cleared
    back to null and its `revision_round` is left unchanged, because that counter was
    already incremented when the scenario entered `REVISION`."

    PRD: "A rejected submission, at any precedence level, leaves `status`, `revision_round`,
    `version` and every stored score field byte-identical to their pre-call values."

    Design: Corner/state_machines/revision_loop_beyond_the_third_round_rejected
    """
    ctx = riverbend_engagement_open()

    # One triaged comment per round: each push-back consumes the comments it cites.
    comments = []
    for guardian in ("guardian-1", "guardian-2", "guardian-3"):
        comment = create_comment(
            ctx["scenario_id"],
            headers=make_guardian_headers(guardian),
            area_id=ctx["a2_id"],
            body=f"Round input from {guardian}: this walk is too long for a third grader.",
        )
        triage_comment(comment["id"], "TRANSPORTATION", "MEDIUM")
        comments.append(comment)

    # The coordinator is not the scenario's author, so each push-back is admissible.
    for expected_round, comment in enumerate(comments, start=1):
        pushed_back = request_revision(ctx["scenario_id"], [comment["id"]], headers=COORDINATOR)
        assert pushed_back["status"] == "REVISION", (
            f"push-back {expected_round} moves the scenario into REVISION, "
            f"got {pushed_back['status']!r}"
        )
        assert pushed_back["revision_round"] == expected_round, (
            f"push-back {expected_round} leaves revision_round at {expected_round}, "
            f"got {pushed_back['revision_round']}"
        )
        assert pushed_back["revision_reason"] == "COMMENT_CYCLE", (
            f"the push-back reason is COMMENT_CYCLE, got {pushed_back['revision_reason']!r}"
        )

        if expected_round == 3:
            break

        resubmitted = submit_for_review(ctx["scenario_id"], headers=PLANNER)
        assert resubmitted["status"] == "UNDER_REVIEW", (
            f"resubmission {expected_round} returns the scenario to UNDER_REVIEW, "
            f"got {resubmitted['status']!r}"
        )
        assert resubmitted["revision_round"] == expected_round, (
            "a resubmission leaves revision_round unchanged, "
            f"expected {expected_round}, got {resubmitted['revision_round']}"
        )
        assert resubmitted["revision_reason"] is None, (
            f"returning from REVISION clears revision_reason, got {resubmitted['revision_reason']!r}"
        )

    before = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert before["revision_round"] == 3, (
        f"the third push-back has exhausted the budget, got revision_round {before['revision_round']}"
    )

    # The scenario is in REVISION, so it is editable, and its run is still COMPLETE:
    # the revision cap is the only gate left that this resubmission can trip.
    validate_error(
        api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value,
    )

    after = get_success_data(api_client.get_scenario(ctx["scenario_id"], PLANNER))
    assert after["status"] == "REVISION", (
        f"the refused resubmission leaves the scenario in REVISION, got {after['status']!r}"
    )
    assert after["revision_round"] == 3, (
        f"the refused resubmission does not advance revision_round, got {after['revision_round']}"
    )
    assert after["version"] == before["version"], (
        f"the refused resubmission does not bump version, "
        f"expected {before['version']}, got {after['version']}"
    )
    assert after["revision_reason"] == "COMMENT_CYCLE", (
        f"the refused resubmission does not clear revision_reason, got {after['revision_reason']!r}"
    )
    for field in (
        "total_assigned_students",
        "max_utilization_pct",
        "walk_eligible_pct",
        "transport_cost_annual_usd",
        "students_reassigned_count",
        "students_reassigned_pct",
        "frl_dissimilarity_index",
        "contiguity_ok",
        "noncontiguous_school_ids",
    ):
        assert after[field] == before[field], (
            f"the refused resubmission leaves {field} byte-identical, "
            f"expected {before[field]!r}, got {after[field]!r}"
        )

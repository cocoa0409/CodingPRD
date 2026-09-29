"""Endpoint semantics, optimistic-concurrency guards and immediate-consistency behaviour."""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_immutable_record_fields,
    create_assignment_payload,
    create_projection_run_payload,
    create_scenario,
    create_projection_run,
    create_school,
    create_study,
    create_transfer_request,
    create_transfer_request_payload,
    create_variance_observation_payload,
    decide_transfer,
    make_guardian_headers,
    program_placement,
    riverbend_adopted,
    riverbend_locked,
    riverbend_scenario_assigned,
    riverbend_under_review,
    scenario_version,
    set_clock,
    setup_study_with_inventory,
    study_version,
    travel_option,
)

PLANNER = TEST_USERS["planner_headers"]
OFFICER = TEST_USERS["officer_headers"]

RIVERBEND_SCHOOL_PAYLOADS = (
    {
        "name": "Cedar Elementary",
        "level": "ELEMENTARY",
        "core_capacity_seats": 500,
        "portable_capacity_seats": 40,
        "program_types": ["DUAL_LANGUAGE"],
    },
    {
        "name": "Birch Elementary",
        "level": "ELEMENTARY",
        "core_capacity_seats": 400,
        "portable_capacity_seats": 0,
    },
)


def _riverbend_area_builders():
    """The three canonical Riverbend planning areas, built against both schools."""

    def a01(school_ids):
        return {
            "area_code": "A-01",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Cedar Elementary"],
            "resident_student_count": 300,
            "frl_student_count": 90,
            "ell_student_count": 40,
            "median_household_income_usd": 78000,
            "annual_absorption_cap_units": 120,
            "travel_options": [
                travel_option(school_ids["Cedar Elementary"], 0.6, 10, True),
                travel_option(school_ids["Birch Elementary"], 2.2, 22, False),
            ],
        }

    def a02(school_ids):
        return {
            "area_code": "A-02",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Cedar Elementary"],
            "resident_student_count": 200,
            "frl_student_count": 100,
            "ell_student_count": 30,
            "median_household_income_usd": 52000,
            "annual_absorption_cap_units": 150,
            "travel_options": [
                travel_option(school_ids["Cedar Elementary"], 1.4, 9, False),
                travel_option(school_ids["Birch Elementary"], 0.8, 12, True),
            ],
        }

    def a03(school_ids):
        return {
            "area_code": "A-03",
            "grade_band": "ELEMENTARY",
            "current_school_id": school_ids["Birch Elementary"],
            "resident_student_count": 150,
            "frl_student_count": 30,
            "ell_student_count": 10,
            "median_household_income_usd": 96000,
            "annual_absorption_cap_units": 90,
            "travel_options": [
                travel_option(school_ids["Cedar Elementary"], 3.0, 26, False),
                travel_option(school_ids["Birch Elementary"], 0.9, 14, True),
            ],
        }

    return (a01, a02, a03)


def _per_school_ids(analysis: dict) -> list:
    """Pull the school ids out of an impact analysis per_school breakdown."""
    per_school = analysis["per_school"]
    if isinstance(per_school, dict):
        return list(per_school.keys())
    ids = []
    for entry in per_school:
        if isinstance(entry, dict):
            ids.append(entry.get("school_id") or entry.get("id"))
        else:
            ids.append(entry)
    return ids


# ---------------------------------------------------------------------------
# Endpoint semantics
# ---------------------------------------------------------------------------
def test_patch_school_changes_only_the_supplied_field():
    """A school PATCH is a partial update that re-derives capacity and bumps version once.

    "Schools may later be adjusted — capacity, hostable programs or operational
    status — and only fields present in that request change; omitted fields keep
    their stored values, and `effective_capacity_seats` is recomputed from the new
    seat counts and the study's portables flag."

    "Most records additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that is initialised to 1
    at creation and incremented by exactly 1 on every mutation of that record —
    including mutations the record's owner never requested, such as a recomputed
    roll-up total or a state change driven by a cascade from another entity."

    Design: Corner/endpoints/patch_school_updates_only_the_supplied_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    study = create_study()
    assert study["portables_count_toward_capacity"] is True

    cedar = create_school(
        study["id"],
        name="Cedar Elementary",
        level="ELEMENTARY",
        core_capacity_seats=500,
        portable_capacity_seats=40,
        program_types=["DUAL_LANGUAGE"],
    )
    assert cedar["version"] == 1, "a freshly created school starts at version 1"
    assert cedar["effective_capacity_seats"] == 540, "500 core plus 40 portable seats"
    assert cedar["status"] == "ACTIVE"

    patched = validate_success(
        api_client.patch_school(cedar["id"], {"portable_capacity_seats": 75}, PLANNER)
    )

    assert patched["portable_capacity_seats"] == 75
    assert patched["effective_capacity_seats"] == 575, (
        "effective capacity is re-derived as 500 core plus the new 75 portable seats"
    )
    assert patched["core_capacity_seats"] == 500, "the omitted seat count is unchanged"
    assert patched["program_types"] == ["DUAL_LANGUAGE"], (
        "an omitted array field keeps its stored value instead of being nulled"
    )
    assert patched["status"] == "ACTIVE", "an omitted status field is not reset"
    assert patched["version"] == 2, "one mutation moves the school from version 1 to 2"

    reread = validate_success(api_client.get_school(cedar["id"], PLANNER))
    assert reread == patched, "the follow-up read returns the identical body"


def test_close_monitoring_requires_a_closed_window_and_full_observation_coverage():
    """close-monitoring is refused until the window is closed and every ACTIVE school is observed.

    "It requires four conditions at once, and any failure is rejected with
    `ERR_ADOPTION_STATE_INVALID`: the adoption's `implementation_status` must be
    `IN_EFFECT`, its `transfer_window_status` must already be
    `TRANSFER_WINDOW_CLOSED`, every `ACTIVE` school of the study must have at least
    one variance observation recorded for this adoption, and no school may currently
    stand flagged `CORRECTIVE_ACTION_REQUIRED`."

    "On success `implementation_status` moves `IN_EFFECT → MONITORING_CLOSED`, the
    adoption's `version` is incremented, and the owning study moves `IMPLEMENTATION →
    CLOSED`, which is its terminal state."

    Design: Corner/endpoints/close_monitoring_needs_a_closed_window_and_a_clean_observation_for_every_active_school
    """
    ctx = riverbend_adopted()
    adoption_id = ctx["adoption_id"]

    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    activated = validate_success(api_client.activate_adoption(adoption_id, OFFICER))
    assert activated["implementation_status"] == "IN_EFFECT"

    first_observation = validate_success(
        api_client.create_variance_observation(
            adoption_id,
            create_variance_observation_payload(
                ctx["cedar_id"], 500, 500, observed_on="2027-09-15T00:00:00Z"
            ),
            OFFICER,
        ),
        201,
    )
    assert first_observation["variance_pct"] == pytest.approx(0.00, abs=0.01)
    assert first_observation["flag"] == "WITHIN_TOLERANCE", (
        "a zero absolute variance sits at or below the 5.00 tolerance"
    )

    validate_error(
        api_client.close_monitoring(adoption_id, OFFICER),
        ApiErrorId.ERR_ADOPTION_STATE_INVALID,
    )

    set_clock("2027-08-16T00:00:00Z", headers=OFFICER)
    closed_window = validate_success(
        api_client.close_transfer_window(adoption_id, OFFICER)
    )
    assert closed_window["transfer_window_status"] == "TRANSFER_WINDOW_CLOSED"
    assert closed_window["implementation_status"] == "IN_EFFECT", (
        "closing the window leaves the implementation dimension untouched"
    )

    validate_error(
        api_client.close_monitoring(adoption_id, OFFICER),
        ApiErrorId.ERR_ADOPTION_STATE_INVALID,
    )

    second_observation = validate_success(
        api_client.create_variance_observation(
            adoption_id,
            create_variance_observation_payload(
                ctx["birch_id"], 150, 150, observed_on="2027-09-15T00:00:00Z"
            ),
            OFFICER,
        ),
        201,
    )
    assert second_observation["variance_pct"] == pytest.approx(0.00, abs=0.01)
    assert second_observation["flag"] == "WITHIN_TOLERANCE"

    closed = validate_success(
        api_client.close_monitoring(
            adoption_id, OFFICER, {"closure_notes": "Monitoring complete."}
        )
    )
    assert closed["implementation_status"] == "MONITORING_CLOSED"

    study = validate_success(api_client.get_study(ctx["study_id"], OFFICER))
    assert study["status"] == "CLOSED", "closing monitoring drives the study terminal"

    _, meta = validate_paginated(
        api_client.list_variance_observations(OFFICER, {"adoption_id": adoption_id})
    )
    assert meta["total_count"] == 2, "both observations remain readable"


def test_close_transfer_window_denies_every_undecided_request_in_one_call():
    """Closing the window sweeps the undecided queue and leaves hand decisions intact.

    "The window dimension moves `TRANSFER_WINDOW_OPEN → TRANSFER_WINDOW_CLOSED`,
    `implementation_status` is untouched, and the undecided queue is cleared: every
    transfer request of this adoption still in `SUBMITTED` or `WAITLISTED` moves
    `SUBMITTED → DENIED` or `WAITLISTED → DENIED` with `decision_notes` set to
    `WINDOW_CLOSED` and `decided_by_user_id` left null, walked in request creation
    order, each request's `version` incremented."

    Design: Corner/endpoints/close_transfer_window_denies_every_undecided_request_in_one_call
    """
    ctx = riverbend_adopted()
    adoption_id = ctx["adoption_id"]

    first = create_transfer_request(
        adoption_id,
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-1"),
        student_reference="STU-501",
        student_grade=3,
        reason="HARDSHIP",
    )
    second = create_transfer_request(
        adoption_id,
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-2"),
        student_reference="STU-502",
        student_grade=4,
        reason="HARDSHIP",
    )
    third = create_transfer_request(
        adoption_id,
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-3"),
        student_reference="STU-503",
        student_grade=5,
        reason="HARDSHIP",
    )
    decide_transfer(
        third["id"], "DENY", api_client, OFFICER, decision_notes="Reviewed and denied"
    )

    set_clock("2027-08-16T00:00:00Z", headers=OFFICER)
    adoption = validate_success(api_client.close_transfer_window(adoption_id, OFFICER))

    assert adoption["transfer_window_status"] == "TRANSFER_WINDOW_CLOSED"
    assert adoption["implementation_status"] == "PENDING_EFFECTIVE", (
        "the implementation dimension moves independently and is untouched here"
    )

    for swept in (first, second):
        record = validate_success(api_client.get_transfer_request(swept["id"], OFFICER))
        assert record["status"] == "DENIED", "an undecided request is denied by the sweep"
        assert record["decision_notes"] == "WINDOW_CLOSED"
        assert record.get("decided_by_user_id") is None, (
            "a system denial records no deciding officer"
        )

    hand_decided = validate_success(api_client.get_transfer_request(third["id"], OFFICER))
    assert hand_decided["status"] == "DENIED"
    assert hand_decided["decision_notes"] == "Reviewed and denied", (
        "the sweep touches only SUBMITTED and WAITLISTED rows"
    )
    assert hand_decided["decided_by_user_id"] == OFFICER_USER_ID

    _, denied_meta = validate_paginated(
        api_client.list_transfer_requests(
            OFFICER, {"adoption_id": adoption_id, "status": "DENIED"}
        )
    )
    assert denied_meta["total_count"] == 3

    _, submitted_meta = validate_paginated(
        api_client.list_transfer_requests(
            OFFICER, {"adoption_id": adoption_id, "status": "SUBMITTED"}
        )
    )
    assert submitted_meta["total_count"] == 0, "no request is left undecided"


def test_assignment_resolves_three_references_and_snapshots_the_projection():
    """An assignment refuses unknown references and snapshots the run's projection.

    "A school id is resolved wherever it appears — in a path, in
    `current_school_id`, `assigned_school_id`, `requested_school_id` or `school_id`,
    and inside a program placement entry — and a planning-area id is resolved
    wherever it appears, including `neighbor_area_id`."

    "At creation the server snapshots `projected_students` from the
    `area_projections` entry for this `area_id` on the scenario's projection run,
    taking that entry's `projected_students` value; the snapshot is what every later
    score uses, so it does not drift when a newer run is created."

    Design: Corner/endpoints/assignment_links_a_scenario_area_and_school_and_snapshots_the_projection
    """
    ctx = riverbend_locked()
    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(ctx["cedar_id"], 30)],
        name="Link Draft",
    )
    creation_version = scenario["version"]
    assert scenario["status"] == "DRAFT"

    a01_projection = next(
        entry for entry in run["area_projections"] if entry["area_id"] == ctx["a1_id"]
    )
    assert a01_projection["projected_students"] == 271, (
        "300 residents surviving five years at 0.98 project to 271 students"
    )

    validate_error(
        api_client.create_assignment(
            create_assignment_payload(
                scenario["id"], NON_EXISTENT_UUID, ctx["cedar_id"], creation_version
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_AREA_NOT_FOUND,
    )
    validate_error(
        api_client.create_assignment(
            create_assignment_payload(
                scenario["id"], ctx["a1_id"], NON_EXISTENT_UUID, creation_version
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_SCHOOL_NOT_FOUND,
    )

    assert scenario_version(scenario["id"]) == creation_version, (
        "neither refusal wrote anything, so the scenario version stands still"
    )

    assignment = validate_success(
        api_client.create_assignment(
            create_assignment_payload(
                scenario["id"], ctx["a1_id"], ctx["cedar_id"], creation_version
            ),
            PLANNER,
        ),
        201,
    )
    assert assignment["scenario_id"] == scenario["id"]
    assert assignment["area_id"] == ctx["a1_id"]
    assert assignment["assigned_school_id"] == ctx["cedar_id"]
    assert assignment["projected_students"] == 271, (
        "the projection is snapshotted onto the junction row, not recomputed on read"
    )
    assert assignment["is_superseded"] is False
    assert assignment.get("superseded_at") is None

    _, meta = validate_paginated(
        api_client.list_assignments(
            PLANNER, {"scenario_id": scenario["id"], "is_superseded": "false"}
        )
    )
    assert meta["total_count"] == 1, "exactly one live assignment was created"


def test_impact_analysis_is_a_pure_computed_read():
    """The impact analysis recomputes every objective and persists nothing.

    "The freshly computed numbers are observable in a rejected case only through the
    scenario's impact analysis, a computed read that recomputes on demand under the
    scenario's stored `impact_variant` and never writes anything."

    "That read answers with the `scenario_id`, the `impact_variant` in force,
    `total_assigned_students`, `frl_dissimilarity_index`, `students_reassigned_count`,
    `students_reassigned_pct`, `max_utilization_pct`, `critical_school_ids` (the
    `ACTIVE` schools at or above the critical ceiling, ordered by school creation
    time), `walk_eligible_pct`, `transport_cost_annual_usd`, `contiguity_ok`,
    `noncontiguous_school_ids`, and a `per_school` breakdown giving each `ACTIVE`
    school's utilization and the band it falls in."

    Design: Corner/endpoints/impact_analysis_is_a_pure_computed_read
    """
    ctx = riverbend_under_review()
    scenario_id = ctx["scenario_id"]
    before = validate_success(api_client.get_scenario(scenario_id, PLANNER))

    first = validate_success(api_client.get_impact_analysis(scenario_id, PLANNER))
    second = validate_success(
        api_client.get_impact_analysis(scenario_id, make_guardian_headers("guardian-9"))
    )
    assert first == second, "two consecutive computed reads answer identically"

    assert first["scenario_id"] == scenario_id
    assert first["impact_variant"] == "RESIDENT_BASED"
    assert first["total_assigned_students"] == 588, "271 plus 181 plus 136 students"
    assert first["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
        "Cedar carries 452 assigned students plus 30 program seats against 540 seats, "
        "so 100 * 482 / 540 == 89.26"
    )
    assert first["walk_eligible_pct"] == pytest.approx(69.22, abs=0.01), (
        "407 of 588 students are walk-eligible"
    )
    assert first["transport_cost_annual_usd"] == pytest.approx(66285.00, abs=0.01), (
        "three buses at a 15-minute billed floor over 180 school days"
    )
    assert first["frl_dissimilarity_index"] == pytest.approx(0.1427, abs=0.00005)
    assert first["students_reassigned_count"] == 0, (
        "every area keeps its school of record under this map"
    )
    assert first["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01)
    assert first["contiguity_ok"] is True
    assert first["noncontiguous_school_ids"] == []
    assert first["critical_school_ids"] == []

    per_school_ids = _per_school_ids(first)
    assert len(per_school_ids) == 2, "one entry per ACTIVE school"
    assert ctx["cedar_id"] in per_school_ids
    assert ctx["birch_id"] in per_school_ids

    after = validate_success(api_client.get_scenario(scenario_id, PLANNER))
    assert after["version"] == before["version"], (
        "the computed read persisted nothing, so the scenario version is unchanged"
    )
    assert after["max_utilization_pct"] == pytest.approx(
        first["max_utilization_pct"], abs=0.01
    ), "the computed read reproduces the stored objective"


def test_transfer_intake_and_decisions_are_refused_once_the_window_is_closed():
    """A closed window bars new transfer requests and any further decision.

    "Intake is gated twice over: a request filed when the logical clock is strictly
    after the adoption's `transfer_deadline_date` is rejected with
    `ERR_TRANSFER_WINDOW_EXPIRED`, and a request filed once `transfer_window_status`
    is `TRANSFER_WINDOW_CLOSED` is rejected with `ERR_TRANSFER_WINDOW_CLOSED`
    regardless of the deadline date."

    "The request must be in `SUBMITTED` or `WAITLISTED`, or the decision is rejected
    with `ERR_TRANSFER_NOT_DECIDABLE`; the adoption's `transfer_window_status` must
    still be `TRANSFER_WINDOW_OPEN` (`ERR_ADOPTION_STATE_INVALID`); and the officer
    must not be the filing guardian (`ERR_SELF_DECISION_FORBIDDEN`)."

    Design: Corner/endpoints/transfer_intake_and_decisions_are_refused_once_the_window_is_closed
    """
    ctx = riverbend_adopted()
    adoption_id = ctx["adoption_id"]

    existing = create_transfer_request(
        adoption_id,
        ctx["a3_id"],
        ctx["cedar_id"],
        api_client,
        make_guardian_headers("guardian-1"),
        student_reference="STU-601",
        student_grade=3,
        reason="HARDSHIP",
    )

    set_clock("2027-08-16T00:00:00Z", headers=OFFICER)
    validate_success(api_client.close_transfer_window(adoption_id, OFFICER))

    validate_error(
        api_client.create_transfer_request(
            create_transfer_request_payload(
                adoption_id,
                ctx["a3_id"],
                ctx["cedar_id"],
                student_reference="STU-602",
                student_grade=3,
                reason="HARDSHIP",
            ),
            make_guardian_headers("guardian-2"),
        ),
        ApiErrorId.ERR_TRANSFER_WINDOW_CLOSED,
    )

    _, meta = validate_paginated(
        api_client.list_transfer_requests(OFFICER, {"adoption_id": adoption_id})
    )
    assert meta["total_count"] == 1, "the refused intake created nothing"

    validate_error_is_one_of(
        api_client.decide_transfer_request(
            existing["id"], {"decision": "APPROVE"}, OFFICER
        ),
        [
            ApiErrorId.ERR_ADOPTION_STATE_INVALID,
            ApiErrorId.ERR_TRANSFER_NOT_DECIDABLE,
        ],
    )

    record = validate_success(api_client.get_transfer_request(existing["id"], OFFICER))
    assert record["status"] == "DENIED", "the swept request was never approved"
    assert record["decision_notes"] == "WINDOW_CLOSED"

    adoption = validate_success(api_client.get_adoption(adoption_id, OFFICER))
    assert adoption["transfer_window_status"] == "TRANSFER_WINDOW_CLOSED"
    assert adoption["implementation_status"] == "PENDING_EFFECTIVE"


# ---------------------------------------------------------------------------
# Optimistic concurrency on parent records
# ---------------------------------------------------------------------------
def test_stale_scenario_version_on_assignment_create_is_rejected():
    """An assignment create replaying a three-writes-old scenario version is a 412.

    "`POST /redistricting/assignments` requires `expected_scenario_version`, carrying
    the client's last observed `version` of the parent `BoundaryScenario`."

    "If `expected_scenario_version` does not equal the scenario's current `version`,
    the request is rejected with `ERR_STALE_SCENARIO_VERSION` (HTTP 412) and nothing
    is created."

    Design: Corner/cross_cutting_complexity_layers/stale_scenario_version_on_assignment_create_rejected
    """
    ctx = riverbend_scenario_assigned()
    scenario_id = ctx["scenario_id"]
    stale = ctx["scenario"]["version"]
    assert stale == 1, "the scenario was at version 1 when it was created"

    validate_error(
        api_client.create_assignment(
            create_assignment_payload(
                scenario_id, ctx["a1_id"], ctx["birch_id"], stale
            ),
            PLANNER,
        ),
        ApiErrorId.ERR_STALE_SCENARIO_VERSION,
    )

    _, meta = validate_paginated(
        api_client.list_assignments(PLANNER, {"scenario_id": scenario_id})
    )
    assert meta["total_count"] == 3, "the refusal wrote nothing"

    fresh = scenario_version(scenario_id)
    assert fresh == 4, "three accepted assignment creates advanced the version to 4"

    replacement = validate_success(
        api_client.create_assignment(
            create_assignment_payload(
                scenario_id, ctx["a1_id"], ctx["birch_id"], fresh
            ),
            PLANNER,
        ),
        201,
    )
    assert replacement["assigned_school_id"] == ctx["birch_id"]
    assert replacement["is_superseded"] is False

    _, all_meta = validate_paginated(
        api_client.list_assignments(PLANNER, {"scenario_id": scenario_id})
    )
    assert all_meta["total_count"] == 4, "the superseded row remains readable as history"

    _, live_meta = validate_paginated(
        api_client.list_assignments(
            PLANNER, {"scenario_id": scenario_id, "is_superseded": "false"}
        )
    )
    assert live_meta["total_count"] == 3, "one area still holds exactly one live row"

    assert scenario_version(scenario_id) == 5, "the accepted retry bumped the version"


def test_stale_study_version_on_projection_run_create_is_rejected():
    """A projection run replaying the version the previous run consumed is a 412.

    "A new run supersedes the study's prior run of the same variant, so a create
    carrying a stale study `version` is acting on an outdated picture of which run is
    authoritative; a mismatch is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412)
    and nothing is created."

    "A successful run is stored with `status` `COMPLETE` and `stale_reason` null; any
    earlier run of the same study and the same `variant` whose `status` is `COMPLETE`
    or `STALE` moves to `SUPERSEDED`, walked in run creation order."

    Design: Corner/cross_cutting_complexity_layers/stale_study_version_on_projection_run_create_rejected
    """
    ctx = riverbend_locked()
    study_id = ctx["study_id"]
    st_v1 = study_version(study_id)

    cohort_run = create_projection_run(
        study_id, variant="COHORT_SURVIVAL", expected_study_version=st_v1
    )
    assert cohort_run["status"] == "COMPLETE"

    validate_error(
        api_client.create_projection_run(
            study_id,
            create_projection_run_payload(st_v1, variant="DEVELOPMENT_WEIGHTED"),
            PLANNER,
        ),
        ApiErrorId.ERR_STALE_STUDY_VERSION,
    )

    _, meta = validate_paginated(api_client.list_projection_runs(study_id, PLANNER))
    assert meta["total_count"] == 1, "the refusal created no run"

    st_v2 = study_version(study_id)
    assert st_v2 > st_v1, "the accepted run itself incremented the study version"

    weighted_run = validate_success(
        api_client.create_projection_run(
            study_id,
            create_projection_run_payload(st_v2, variant="DEVELOPMENT_WEIGHTED"),
            PLANNER,
        ),
        201,
    )
    assert weighted_run["variant"] == "DEVELOPMENT_WEIGHTED"
    assert weighted_run["status"] == "COMPLETE"
    assert weighted_run["projected_total_students"] == 588

    reread_cohort = validate_success(
        api_client.get_projection_run(cohort_run["id"], PLANNER)
    )
    assert reread_cohort["status"] == "COMPLETE", (
        "supersession is per variant, so the cohort-survival run survives"
    )
    assert reread_cohort["projected_total_students"] == 588, (
        "with no housing pipeline the two variants agree"
    )

    study = validate_success(api_client.get_study(study_id, PLANNER))
    assert study["status"] == "SCENARIO_DEVELOPMENT"
    assert study["version"] > st_v2, "the second accepted run bumped the study again"


def test_stale_scenario_version_on_program_placement_replace_is_rejected():
    """A wholesale placement replace holding the creation-time version is a 412.

    "The replacement overwrites the prior placement set wholesale, so a replace
    carrying a stale scenario `version` would erase placements the client never saw;
    a mismatch is rejected with `ERR_STALE_SCENARIO_VERSION` (HTTP 412) and nothing
    is changed."

    "A successful replacement increments the scenario's `version`; it deliberately
    does not recompute `max_utilization_pct`, even though program seats feed that
    number, because utilization is recomputed only when the scenario is submitted for
    review."

    Design: Corner/cross_cutting_complexity_layers/stale_scenario_version_on_program_placement_replace_rejected
    """
    ctx = riverbend_scenario_assigned()
    scenario_id = ctx["scenario_id"]
    stale = ctx["scenario"]["version"]
    assert stale == 1, "the scenario was at version 1 when it was created"

    replacement = [program_placement(ctx["cedar_id"], 45)]

    validate_error(
        api_client.replace_program_placements(
            scenario_id,
            {
                "program_placements": replacement,
                "expected_scenario_version": stale,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_STALE_SCENARIO_VERSION,
    )

    unchanged = validate_success(api_client.get_scenario(scenario_id, PLANNER))
    assert len(unchanged["program_placements"]) == 1
    assert unchanged["program_placements"][0]["seats"] == 30, (
        "the prior placement survives the refused replace"
    )
    assert unchanged["version"] == 4, "three assignment creates advanced the version"

    replaced = validate_success(
        api_client.replace_program_placements(
            scenario_id,
            {
                "program_placements": replacement,
                "expected_scenario_version": unchanged["version"],
            },
            PLANNER,
        )
    )
    assert len(replaced["program_placements"]) == 1
    assert replaced["program_placements"][0]["seats"] == 45
    assert replaced["program_placements"][0]["school_id"] == ctx["cedar_id"]
    assert replaced["version"] == 5, "the accepted replace bumped the version once"
    assert replaced["status"] == "DRAFT", "a placement replace is not a state change"


def test_version_increments_on_every_write_and_never_on_a_read():
    """Versions move only on writes, and immutable adjacency rows carry none at all.

    "Most records additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that is initialised to 1
    at creation and incremented by exactly 1 on every mutation of that record —
    including mutations the record's owner never requested, such as a recomputed
    roll-up total or a state change driven by a cascade from another entity."

    "Three record types are immutable once written and therefore carry only `id` and
    `created_at`; for these, both `updated_at` and `version` are absent from the
    response entirely: **area adjacencies**, **phase-in rules** and **variance
    observations**."

    "On success the server stamps `data_locked_at` with the current logical-clock
    instant, recomputes `resident_student_total`, recomputes
    `enrolled_students_of_record` for every school of the study and then
    `enrolled_of_record_total`, and increments the study's `version`."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
    """
    ctx = setup_study_with_inventory(
        school_payloads=RIVERBEND_SCHOOL_PAYLOADS,
        area_builders=_riverbend_area_builders(),
        adjacency_specs=(("A-01", "A-02", 5200), ("A-02", "A-03", 4100)),
        lock=False,
    )
    study_id = ctx["study_id"]
    assert ctx["study"]["version"] == 1, (
        "a freshly created BoundaryStudy starts at version 1"
    )
    assert ctx["schools"]["Cedar Elementary"]["version"] == 1, (
        "a freshly created School starts at version 1"
    )

    before = validate_success(api_client.get_study(study_id, PLANNER))
    again = validate_success(api_client.get_study(study_id, PLANNER))
    assert again["version"] == before["version"], "a read never increments the version"
    assert before["status"] == "SETUP"

    locked = validate_success(api_client.lock_study_data(study_id, PLANNER))
    assert locked["version"] == before["version"] + 1, "lock-data is exactly one write"
    assert locked["status"] == "DATA_LOCKED"
    assert locked["data_locked_at"].startswith("2026-09-01T00:00:00"), (
        "data_locked_at is stamped from the logical clock"
    )

    cedar_id = ctx["schools"]["Cedar Elementary"]["id"]
    cedar_before = validate_success(api_client.get_school(cedar_id, PLANNER))
    patched = validate_success(
        api_client.patch_school(cedar_id, {"portable_capacity_seats": 60}, PLANNER)
    )
    assert patched["version"] == cedar_before["version"] + 1, (
        "a PATCH is exactly one write on the school"
    )
    assert patched["effective_capacity_seats"] == 560, "500 core plus 60 portable seats"

    cedar_after = validate_success(api_client.get_school(cedar_id, PLANNER))
    assert cedar_after["version"] == patched["version"], (
        "reading the school back does not bump it again"
    )

    adjacency_rows, _ = validate_paginated(
        api_client.list_area_adjacencies(ctx["area_ids"]["A-01"], PLANNER)
    )
    assert adjacency_rows, "A-01 appears on at least one adjacency row"
    for row in adjacency_rows:
        assert_immutable_record_fields(row)


# ---------------------------------------------------------------------------
# Consistency model
# ---------------------------------------------------------------------------
def test_every_activation_side_effect_is_visible_in_the_same_response():
    """Activation's whole cascade is visible immediately, with no settling period.

    "Link one moves `implementation_status` `PENDING_EFFECTIVE → IN_EFFECT` and
    increments the adoption's `version`."

    "Link three recomputes the head counts that link two invalidated: every school of
    the study recomputes `enrolled_students_of_record` as the sum of
    `resident_student_count` over the planning areas now pointing at it, walked in
    school creation order, and then the study's `enrolled_of_record_total` is
    recomputed as the sum over its schools."

    "The new record starts with `implementation_status` `PENDING_EFFECTIVE` and
    `transfer_window_status` `TRANSFER_WINDOW_OPEN`, and those two dimensions move
    independently from that moment on — the window may close while the adoption is
    still `PENDING_EFFECTIVE`, and the adoption may reach `IN_EFFECT` with the window
    still `TRANSFER_WINDOW_OPEN`."

    Design: Corner/consistency_model/every_activation_side_effect_is_visible_in_the_same_response
    """
    ctx = riverbend_adopted()
    adoption_id = ctx["adoption_id"]

    set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
    activated = validate_success(api_client.activate_adoption(adoption_id, OFFICER))
    assert activated["implementation_status"] == "IN_EFFECT"
    assert activated["transfer_window_status"] == "TRANSFER_WINDOW_OPEN", (
        "the window dimension is untouched by activation"
    )

    adoption_read = validate_success(api_client.get_adoption(adoption_id, OFFICER))
    assert adoption_read["implementation_status"] == "IN_EFFECT", "no lag on the read"
    assert adoption_read["transfer_window_status"] == "TRANSFER_WINDOW_OPEN"

    study = validate_success(api_client.get_study(ctx["study_id"], OFFICER))
    assert study["status"] == "IMPLEMENTATION"

    area = validate_success(api_client.get_planning_area(ctx["a1_id"], OFFICER))
    assert area["current_school_id"] == ctx["cedar_id"], (
        "A-01 carries the school its adopted assignment names"
    )

    cedar = validate_success(api_client.get_school(ctx["cedar_id"], OFFICER))
    birch = validate_success(api_client.get_school(ctx["birch_id"], OFFICER))
    assert cedar["enrolled_students_of_record"] == 500, (
        "A-01's 300 residents plus A-02's 200 now point at Cedar"
    )
    assert birch["enrolled_students_of_record"] == 150, "A-03's 150 residents"

    assert (
        validate_success(api_client.get_adoption(adoption_id, OFFICER)) == adoption_read
    ), "repeating the adoption read returns an identical body"
    assert validate_success(api_client.get_study(ctx["study_id"], OFFICER)) == study
    assert validate_success(api_client.get_planning_area(ctx["a1_id"], OFFICER)) == area
    assert validate_success(api_client.get_school(ctx["cedar_id"], OFFICER)) == cedar
    assert validate_success(api_client.get_school(ctx["birch_id"], OFFICER)) == birch

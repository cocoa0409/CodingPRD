"""Threshold edges, cross-entity gates, interval arithmetic and compensating actions."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_district_enrollment_conserved,
    assign_area,
    assign_areas,
    create_adoption,
    create_adoption_payload,
    create_housing_development,
    create_housing_development_payload,
    create_phase_in_rule_payload,
    create_projection_run,
    create_scenario,
    create_transfer_request,
    decide_transfer,
    make_guardian_headers,
    open_engagement,
    program_placement,
    riverbend_adopted,
    riverbend_locked,
    riverbend_scenario_assigned,
    riverbend_scenario_draft,
    advance_entitlement,
    advance_to_board,
    setup_study_with_inventory,
    set_clock,
    submit_for_review,
    travel_option,
)

PLANNER = TEST_USERS["planner_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BOARD = TEST_USERS["board_headers"]
OFFICER = TEST_USERS["officer_headers"]


# ===========================================================================
# Shared builders. Every test starts from an empty database, so each of these
# rebuilds its whole world through the public API.
# ===========================================================================
def _westvale_stress_scenario() -> dict:
    """Westvale USD engineered so Aspen Elementary lands on exactly 110.00 percent.

    Portables do not count toward capacity, so Aspen's effective capacity is its
    500 core seats. The five-year cohort-survival projection gives E-01 271,
    E-02 271 and E-03 90; Aspen carries 542 assigned students plus 8 program
    seats against 500 seats.
    """
    ctx = setup_study_with_inventory(
        study_payload={
            "name": "2028 Capacity Stress Study",
            "district_name": "Westvale USD",
            "target_school_year": 2028,
            "horizon_years": 5,
            "capacity_target_low_pct": 85.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": False,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Aspen Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 500,
                "portable_capacity_seats": 60,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {
                "name": "Larch Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 900,
            },
        ),
        area_builders=(
            lambda ids: {
                "area_code": "E-01",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Aspen Elementary"],
                "resident_student_count": 300,
                "frl_student_count": 90,
                "ell_student_count": 30,
                "median_household_income_usd": 72000,
                "annual_absorption_cap_units": 200,
                "travel_options": [
                    travel_option(ids["Aspen Elementary"], 0.5, 10, True),
                    travel_option(ids["Larch Elementary"], 2.4, 24, False),
                ],
            },
            lambda ids: {
                "area_code": "E-02",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Aspen Elementary"],
                "resident_student_count": 300,
                "frl_student_count": 80,
                "ell_student_count": 25,
                "median_household_income_usd": 76000,
                "annual_absorption_cap_units": 200,
                "travel_options": [
                    travel_option(ids["Aspen Elementary"], 0.6, 11, True),
                    travel_option(ids["Larch Elementary"], 1.9, 20, False),
                ],
            },
            lambda ids: {
                "area_code": "E-03",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Larch Elementary"],
                "resident_student_count": 100,
                "frl_student_count": 20,
                "ell_student_count": 5,
                "median_household_income_usd": 98000,
                "annual_absorption_cap_units": 200,
                "travel_options": [
                    travel_option(ids["Aspen Elementary"], 2.6, 25, False),
                    travel_option(ids["Larch Elementary"], 0.5, 9, True),
                ],
            },
        ),
        adjacency_specs=(("E-01", "E-02", 5100), ("E-02", "E-03", 4700)),
    )
    aspen_id = ctx["school_ids"]["Aspen Elementary"]
    larch_id = ctx["school_ids"]["Larch Elementary"]
    run = create_projection_run(ctx["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        ctx["study_id"],
        run["id"],
        [program_placement(aspen_id, 8)],
        name="Stress Draft",
        impact_variant="RESIDENT_BASED",
    )
    assign_areas(
        scenario["id"],
        [
            (ctx["area_ids"]["E-01"], aspen_id),
            (ctx["area_ids"]["E-02"], aspen_id),
            (ctx["area_ids"]["E-03"], larch_id),
        ],
    )
    ctx.update(
        {
            "aspen_id": aspen_id,
            "larch_id": larch_id,
            "run": run,
            "scenario_id": scenario["id"],
        }
    )
    return ctx


def _pool_exhausted_context() -> dict:
    """The adopted Riverbend map with Cedar's transfer seat pool driven to exactly 0.

    Cedar carries 452 post-boundary students against 540 effective seats; the
    84.10 percent cap floors to 454 seats, so the pool opens at 2 and two
    approved hardship transfers consume both.
    """
    ctx = riverbend_adopted()
    requests = []
    for token, reference, grade in (
        ("guardian-1", "STU-001", 3),
        ("guardian-2", "STU-002", 4),
        ("guardian-3", "STU-003", 5),
    ):
        requests.append(
            create_transfer_request(
                ctx["adoption_id"],
                ctx["a3_id"],
                ctx["cedar_id"],
                headers=make_guardian_headers(token),
                student_reference=reference,
                student_grade=grade,
                reason="HARDSHIP",
            )
        )
    decide_transfer(requests[0]["id"], "APPROVE", decision_notes="Documented hardship.")
    decide_transfer(requests[1]["id"], "APPROVE", decision_notes="Documented hardship.")
    ctx["requests"] = requests
    return ctx


def _stale_projection_context() -> dict:
    """The DRAFT Riverbend scenario whose projection run is staled by a housing move."""
    ctx = riverbend_scenario_assigned()
    development = create_housing_development(
        ctx["a2_id"],
        name="Maple Flats",
        unit_type="MULTI_FAMILY",
        total_units=200,
        first_occupancy_date="2027-03-01T00:00:00Z",
        buildout_months=20,
    )
    advance_entitlement(development["id"], "ENTITLED")
    ctx["development"] = development
    return ctx


def _second_riverbend_board_ready() -> dict:
    """Two Riverbend USD studies: the first already adopted, the second BOARD_READY.

    The first study's adoption occupies the half-open school-year interval
    [2028, 2031). The second study's Scenario W reproduces every area's current
    school, so it reassigns nobody and needs only a simple majority.
    """
    first = riverbend_adopted()
    second = setup_study_with_inventory(
        study_payload={
            "name": "2031 Elementary Boundary Study",
            "district_name": "Riverbend USD",
            "target_school_year": 2031,
            "horizon_years": 5,
            "capacity_target_low_pct": 85.0,
            "capacity_target_high_pct": 100.0,
            "portables_count_toward_capacity": True,
            "required_program_types": ["DUAL_LANGUAGE"],
        },
        school_payloads=(
            {
                "name": "Willowmere Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 600,
                "portable_capacity_seats": 0,
                "program_types": ["DUAL_LANGUAGE"],
            },
            {
                "name": "Fernbank Elementary",
                "level": "ELEMENTARY",
                "core_capacity_seats": 600,
                "portable_capacity_seats": 0,
            },
        ),
        area_builders=(
            lambda ids: {
                "area_code": "F-01",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Willowmere Elementary"],
                "resident_student_count": 300,
                "frl_student_count": 100,
                "ell_student_count": 30,
                "median_household_income_usd": 65000,
                "annual_absorption_cap_units": 150,
                "travel_options": [
                    travel_option(ids["Willowmere Elementary"], 0.7, 10, True),
                    travel_option(ids["Fernbank Elementary"], 2.5, 23, False),
                ],
            },
            lambda ids: {
                "area_code": "F-02",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Willowmere Elementary"],
                "resident_student_count": 200,
                "frl_student_count": 70,
                "ell_student_count": 20,
                "median_household_income_usd": 71000,
                "annual_absorption_cap_units": 150,
                "travel_options": [
                    travel_option(ids["Willowmere Elementary"], 0.9, 12, True),
                    travel_option(ids["Fernbank Elementary"], 2.1, 20, False),
                ],
            },
            lambda ids: {
                "area_code": "F-03",
                "grade_band": "ELEMENTARY",
                "current_school_id": ids["Fernbank Elementary"],
                "resident_student_count": 150,
                "frl_student_count": 40,
                "ell_student_count": 10,
                "median_household_income_usd": 88000,
                "annual_absorption_cap_units": 150,
                "travel_options": [
                    travel_option(ids["Willowmere Elementary"], 2.9, 25, False),
                    travel_option(ids["Fernbank Elementary"], 0.8, 13, True),
                ],
            },
        ),
        adjacency_specs=(("F-01", "F-02", 5000), ("F-02", "F-03", 4300)),
        clock=None,
    )
    willowmere_id = second["school_ids"]["Willowmere Elementary"]
    fernbank_id = second["school_ids"]["Fernbank Elementary"]
    run = create_projection_run(second["study_id"], variant="COHORT_SURVIVAL")
    scenario = create_scenario(
        second["study_id"],
        run["id"],
        [program_placement(willowmere_id, 20)],
        name="Scenario W",
        impact_variant="RESIDENT_BASED",
    )
    assign_areas(
        scenario["id"],
        [
            (second["area_ids"]["F-01"], willowmere_id),
            (second["area_ids"]["F-02"], willowmere_id),
            (second["area_ids"]["F-03"], fernbank_id),
        ],
    )
    submit_for_review(scenario["id"])
    open_engagement(second["study_id"], headers=COORDINATOR)
    advance_to_board(scenario["id"], headers=COORDINATOR)
    second.update(
        {
            "first": first,
            "willowmere_id": willowmere_id,
            "fernbank_id": fernbank_id,
            "scenario_id": scenario["id"],
        }
    )
    return second


def _regime_candidate(study_id, scenario_id, effective_date, school_year, deadline) -> dict:
    return create_adoption_payload(
        study_id,
        scenario_id,
        effective_date=effective_date,
        effective_school_year=school_year,
        regime_years=2,
        transfer_deadline_date=deadline,
        transfer_cap_pct=105.0,
        variance_tolerance_pct=5.0,
        votes_for=5,
        votes_against=2,
        votes_abstain=0,
        board_member_count=7,
    )


def _absorption_context() -> dict:
    """Riverbend locked, with area A-03 carrying a 90-unit annual absorption cap."""
    return riverbend_locked()


def _sable_ridge_pair(a3_id) -> list:
    """The two individually-legal developments that lift A-03's peak to 89.83."""
    first = create_housing_development(
        a3_id,
        name="Sable Ridge",
        unit_type="SINGLE_FAMILY",
        total_units=60,
        first_occupancy_date="2027-01-01T00:00:00Z",
        buildout_months=12,
    )
    second = create_housing_development(
        a3_id,
        name="Sable Ridge II",
        unit_type="SINGLE_FAMILY",
        total_units=60,
        first_occupancy_date="2027-07-01T00:00:00Z",
        buildout_months=12,
    )
    return [first, second]


def _boundary_changing_adoption() -> dict:
    """A Riverbend adoption that swaps A-01 to Birch and A-03 to Cedar.

    A-01 (271 projected) leaves Cedar for Birch and A-03 (136 projected) leaves
    Birch for Cedar, so 407 of 588 projected students move and the board needs a
    two-thirds majority, which 6 for / 1 against of 7 seated members clears.
    """
    ctx = riverbend_scenario_draft()
    assign_areas(
        ctx["scenario_id"],
        [
            (ctx["a1_id"], ctx["birch_id"]),
            (ctx["a2_id"], ctx["cedar_id"]),
            (ctx["a3_id"], ctx["cedar_id"]),
        ],
    )
    submit_for_review(ctx["scenario_id"])
    open_engagement(ctx["study_id"], headers=COORDINATOR)
    advance_to_board(ctx["scenario_id"], headers=COORDINATOR)
    adoption = create_adoption(
        ctx["study_id"],
        ctx["scenario_id"],
        headers=BOARD,
        effective_date="2027-07-01T00:00:00Z",
        effective_school_year=2028,
        regime_years=3,
        transfer_deadline_date="2027-08-15T00:00:00Z",
        transfer_cap_pct=84.1,
        variance_tolerance_pct=5.0,
        votes_for=6,
        votes_against=1,
        votes_abstain=0,
        board_member_count=7,
    )
    ctx.update({"adoption": adoption, "adoption_id": adoption["id"]})
    return ctx


# ===========================================================================
# boundary_precision_check
# ===========================================================================
class TestUtilizationExactlyAtCriticalCeiling:
    """The critical ceiling is reached, not exceeded, and portables are excluded."""

    def test_impact_analysis_reports_exactly_110_pct_with_portables_excluded(self):
        """Utilization lands on 110.00 exactly because the 60 portable seats do not count.

        "A school's effective capacity is its `core_capacity_seats` plus, only
        when the study's `portables_count_toward_capacity` is true, its
        `portable_capacity_seats`."

        Design: Difficulty/boundary_precision_check/utilization_exactly_110_is_critical_at_submit
        """
        ctx = _westvale_stress_scenario()

        aspen = validate_success(api_client.get_school(ctx["aspen_id"], PLANNER))
        assert aspen["effective_capacity_seats"] == 500, (
            "portables_count_toward_capacity is false, so Aspen's effective capacity "
            f"must stay at its 500 core seats, got {aspen['effective_capacity_seats']}"
        )

        analysis = validate_success(
            api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
        )
        assert analysis["total_assigned_students"] == 632, (
            "271 + 271 + 90 projected students are assigned, got "
            f"{analysis['total_assigned_students']}"
        )
        assert analysis["max_utilization_pct"] == pytest.approx(110.00, abs=0.01), (
            "100 * (542 assigned + 8 program seats) / 500 is exactly 110.00, got "
            f"{analysis['max_utilization_pct']} (98.21 would mean the portables were counted)"
        )
        assert ctx["aspen_id"] in analysis["critical_school_ids"], (
            "a school at exactly 110.00 percent is CRITICAL"
        )
        assert ctx["larch_id"] not in analysis["critical_school_ids"], (
            "Larch sits at 10.00 percent and is not critical"
        )

    def test_submit_for_review_rejects_the_exact_110_pct_edge(self):
        """Submission is refused at exactly 110.00 and persists no score.

        "A submission whose `max_utilization_pct` reaches or exceeds 110.00 is
        rejected with `ERR_SCHOOL_CAPACITY_CRITICAL`."

        Design: Difficulty/boundary_precision_check/utilization_exactly_110_is_critical_at_submit
        """
        ctx = _westvale_stress_scenario()

        validate_error(
            api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER),
            ApiErrorId.ERR_SCHOOL_CAPACITY_CRITICAL.value,
        )

        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
        assert scenario["status"] == "DRAFT", (
            f"a rejected submission leaves the scenario in DRAFT, got {scenario['status']}"
        )
        assert scenario["revision_round"] == 0, (
            f"a rejected submission leaves revision_round at 0, got {scenario['revision_round']}"
        )
        assert scenario["max_utilization_pct"] == pytest.approx(0.00, abs=0.01), (
            "a rejected submission persists no score, so max_utilization_pct stays at its "
            f"empty-scenario 0.00, got {scenario['max_utilization_pct']}"
        )


class TestTransferSeatPoolExactlyZero:
    """A pool of exactly 0 blocks approval but is the correct case for a waitlist."""

    def test_approve_is_refused_when_the_pool_is_exactly_zero(self):
        """Cedar's pool stands at 454 - 454 == 0, one seat short of the approval minimum.

        "For a pool-consuming request, approval requires the requested school's
        pool to be at least 1 free seat and is otherwise rejected with
        `ERR_NO_TRANSFER_SEATS`, while waitlisting is the correct outcome when
        that pool is 0 or negative; a request whose `consumes_seat_pool` is false
        bypasses the pool entirely and can be approved however full the school is."

        Design: Difficulty/boundary_precision_check/transfer_seat_pool_exactly_zero_forces_waitlist
        """
        ctx = _pool_exhausted_context()
        third = ctx["requests"][2]

        validate_error(
            api_client.decide_transfer_request(
                third["id"],
                {"decision": "APPROVE", "decision_notes": "Third hardship."},
                OFFICER,
            ),
            ApiErrorId.ERR_NO_TRANSFER_SEATS.value,
        )

        reread = validate_success(api_client.get_transfer_request(third["id"], OFFICER))
        assert reread["status"] == "SUBMITTED", (
            f"the refused approval leaves the request in SUBMITTED, got {reread['status']}"
        )
        assert reread.get("decided_by_user_id") is None, (
            "a refused decision stamps no deciding officer, got "
            f"{reread.get('decided_by_user_id')!r}"
        )

        approved, meta = validate_paginated(
            api_client.list_transfer_requests(
                OFFICER, {"adoption_id": ctx["adoption_id"], "status": "APPROVED"}
            )
        )
        assert meta["total_count"] == 2, (
            f"only the two seats in the pool were ever granted, got {meta['total_count']}"
        )
        assert len(approved) == 2

    def test_waitlist_succeeds_on_the_same_request_at_pool_zero(self):
        """The request refused for approval is legitimately waitlisted at pool 0.

        "`APPROVE` moves the request `SUBMITTED → APPROVED` or `WAITLISTED →
        APPROVED` and sets `promotion_source` to `OFFICER_DECISION`; `DENY` moves
        it `SUBMITTED → DENIED`, which is terminal; `WAITLIST` moves it
        `SUBMITTED → WAITLISTED`, from which a later officer approval or an
        activation auto-promotion can still rescue it."

        Design: Difficulty/boundary_precision_check/transfer_seat_pool_exactly_zero_forces_waitlist
        """
        ctx = _pool_exhausted_context()
        third = ctx["requests"][2]

        validate_error(
            api_client.decide_transfer_request(
                third["id"],
                {"decision": "APPROVE", "decision_notes": "Third hardship."},
                OFFICER,
            ),
            ApiErrorId.ERR_NO_TRANSFER_SEATS.value,
        )

        decided = validate_success(
            api_client.decide_transfer_request(
                third["id"],
                {"decision": "WAITLIST", "decision_notes": "No seats remain at Cedar."},
                OFFICER,
            )
        )
        assert decided["status"] == "WAITLISTED", (
            f"a pool of 0 is exactly the waitlist case, got {decided['status']}"
        )
        assert decided["resolved_reason"] == "HARDSHIP_REVIEW", (
            "with no phase-in rule attached, a HARDSHIP request resolves on rung four, got "
            f"{decided['resolved_reason']}"
        )
        assert decided["consumes_seat_pool"] is True, (
            "a HARDSHIP_REVIEW entitlement consumes the seat pool"
        )
        assert decided.get("promotion_source") is None, (
            "waitlisting sets no promotion_source, got "
            f"{decided.get('promotion_source')!r}"
        )
        assert decided["decided_by_user_id"] == "officer-1", (
            "every decision stamps the acting officer, got "
            f"{decided.get('decided_by_user_id')!r}"
        )


class TestPhaseInBandEdges:
    """Grade bands are closed on both endpoints, scoped by rule type."""

    def test_abutting_band_is_accepted(self):
        """[6,6] abuts an existing [4,5] with gap zero and must be accepted.

        "Bands that merely abut, where the existing `grade_high` plus one equals
        the candidate `grade_low`, are accepted."

        Design: Difficulty/boundary_precision_check/phase_in_band_abutting_accepted_overlap_by_one_rejected
        """
        ctx = riverbend_adopted()

        first = validate_success(
            api_client.create_phase_in_rule(
                ctx["adoption_id"],
                create_phase_in_rule_payload(
                    rule_type="TERMINAL_GRADE_GRANDFATHER",
                    grade_low=4,
                    grade_high=5,
                    sunset_school_year=2030,
                ),
                BOARD,
            ),
            201,
        )
        assert first["consumes_seat_pool"] is False, (
            "a TERMINAL_GRADE_GRANDFATHER entitlement bypasses the seat pool"
        )

        abutting = validate_success(
            api_client.create_phase_in_rule(
                ctx["adoption_id"],
                create_phase_in_rule_payload(
                    rule_type="TERMINAL_GRADE_GRANDFATHER",
                    grade_low=6,
                    grade_high=6,
                    sunset_school_year=2030,
                ),
                BOARD,
            ),
            201,
        )
        assert abutting["grade_low"] == 6 and abutting["grade_high"] == 6, (
            "the accepted band is the single grade 6"
        )
        assert abutting["consumes_seat_pool"] is False

    def test_band_overlapping_by_one_grade_is_rejected_but_another_rule_type_is_not(self):
        """[5,7] intersects [4,5] at exactly grade 5, while [4,5] under another rule type is free.

        "Bands may not overlap **within the same rule type**: a candidate is
        rejected with `ERR_PHASE_IN_BAND_OVERLAP` when an existing rule of the
        same adoption and the same `rule_type` has a band that intersects it,
        which is the case when the existing `grade_low` is at or below the
        candidate `grade_high` and the candidate `grade_low` is at or below the
        existing `grade_high`."

        Design: Difficulty/boundary_precision_check/phase_in_band_abutting_accepted_overlap_by_one_rejected
        """
        ctx = riverbend_adopted()
        for low, high in ((4, 5), (6, 6)):
            get_success_data(
                api_client.create_phase_in_rule(
                    ctx["adoption_id"],
                    create_phase_in_rule_payload(
                        rule_type="TERMINAL_GRADE_GRANDFATHER",
                        grade_low=low,
                        grade_high=high,
                        sunset_school_year=2030,
                    ),
                    BOARD,
                ),
                201,
            )

        validate_error(
            api_client.create_phase_in_rule(
                ctx["adoption_id"],
                create_phase_in_rule_payload(
                    rule_type="TERMINAL_GRADE_GRANDFATHER",
                    grade_low=5,
                    grade_high=7,
                    sunset_school_year=2031,
                ),
                BOARD,
            ),
            ApiErrorId.ERR_PHASE_IN_BAND_OVERLAP.value,
        )

        other_type = validate_success(
            api_client.create_phase_in_rule(
                ctx["adoption_id"],
                create_phase_in_rule_payload(
                    rule_type="PHASE_IN_GRADE_BAND",
                    grade_low=4,
                    grade_high=5,
                    sunset_school_year=2031,
                ),
                BOARD,
            ),
            201,
        )
        assert other_type["consumes_seat_pool"] is False, (
            "a PHASE_IN_GRADE_BAND entitlement bypasses the seat pool"
        )

        _, all_meta = validate_paginated(
            api_client.list_phase_in_rules(ctx["adoption_id"], BOARD)
        )
        assert all_meta["total_count"] == 3, (
            f"three rules were accepted and one rejected, got {all_meta['total_count']}"
        )
        _, grandfather_meta = validate_paginated(
            api_client.list_phase_in_rules(
                ctx["adoption_id"], BOARD, {"rule_type": "TERMINAL_GRADE_GRANDFATHER"}
            )
        )
        assert grandfather_meta["total_count"] == 2, (
            "only the two disjoint grandfather bands survive, got "
            f"{grandfather_meta['total_count']}"
        )


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
class TestSubmitBlockedByStaleProjectionRun:
    """A housing move two hops away decides whether a scenario may leave DRAFT."""

    def test_entitlement_advance_stales_the_run_and_marks_the_draft_scenario(self):
        """Advancing a development to ENTITLED stales the run and flags the DRAFT scenario.

        "Link two recognises that the projection inputs have changed: every
        projection run of the study that owns the development's area whose
        `status` is `COMPLETE` moves to `STALE` with `stale_reason` set to
        `DEVELOPMENT_PIPELINE_CHANGED`, walked in run creation order, and the
        study's `projection_stale` flag is recomputed to true."

        Design: Difficulty/cross_entity_state_dependency/submit_for_review_blocked_by_stale_projection_run
        """
        ctx = _stale_projection_context()

        run = validate_success(api_client.get_projection_run(ctx["run_id"], PLANNER))
        assert run["status"] == "STALE", (
            f"the COMPLETE run is staled by the pipeline move, got {run['status']}"
        )
        assert run["stale_reason"] == "DEVELOPMENT_PIPELINE_CHANGED", (
            f"unexpected stale_reason {run.get('stale_reason')!r}"
        )

        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
        assert scenario["projection_stale"] is True, (
            "a scenario citing a staled run is marked projection_stale"
        )
        assert scenario["status"] == "DRAFT", (
            "a DRAFT scenario is marked rather than pushed to REVISION, got "
            f"{scenario['status']}"
        )
        assert scenario["revision_round"] == 0, (
            f"only an UNDER_REVIEW scenario burns a revision round, got {scenario['revision_round']}"
        )

        study = validate_success(api_client.get_study(ctx["study_id"], PLANNER))
        assert study["projection_stale"] is True
        assert study["status"] == "SCENARIO_DEVELOPMENT", (
            "the study only reverts out of ENGAGEMENT, got " f"{study['status']}"
        )

    def test_submit_for_review_is_refused_while_the_cited_run_is_stale(self):
        """The scenario's own content is complete and valid, yet submission is refused.

        "Either way the study must be in `DATA_LOCKED`, `SCENARIO_DEVELOPMENT` or
        `ENGAGEMENT`, the scenario must be in `DRAFT` or `REVISION`
        (`ERR_SCENARIO_NOT_EDITABLE`), and the projection run it cites must still
        be `COMPLETE` — a scenario whose `projection_stale` is true, whether
        because its run went `STALE` or because a newer run superseded it, cannot
        have its scores certified and is rejected with `ERR_PROJECTION_STALE`."

        Design: Difficulty/cross_entity_state_dependency/submit_for_review_blocked_by_stale_projection_run
        """
        ctx = _stale_projection_context()

        validate_error(
            api_client.submit_scenario_for_review(ctx["scenario_id"], PLANNER),
            ApiErrorId.ERR_PROJECTION_STALE.value,
        )

        _, meta = validate_paginated(
            api_client.list_assignments(PLANNER, {"scenario_id": ctx["scenario_id"]})
        )
        assert meta["total_count"] == 3, (
            f"the refusal disturbed no assignment, got {meta['total_count']}"
        )

        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
        assert scenario["status"] == "DRAFT"
        assert scenario["revision_round"] == 0
        assert scenario["max_utilization_pct"] == pytest.approx(0.00, abs=0.01), (
            "the scenario was never certified, so no score was persisted, got "
            f"{scenario['max_utilization_pct']}"
        )


class TestTransferBlockedByMothballedSchool:
    """The referenced school's lifecycle state refuses an otherwise valid request."""

    def test_filing_against_a_mothballed_school_is_refused(self):
        """A valid hardship request is refused because the requested school is MOTHBALLED.

        "The requested school must not be `MOTHBALLED`
        (`ERR_SCHOOL_NOT_ACTIVE`), and a repeated `student_reference` within the
        same adoption is rejected with `ERR_DUPLICATE_NAME`."

        Design: Difficulty/cross_entity_state_dependency/transfer_request_blocked_by_mothballed_requested_school
        """
        ctx = riverbend_adopted()
        get_success_data(
            api_client.patch_school(ctx["cedar_id"], {"status": "MOTHBALLED"}, PLANNER)
        )

        validate_error(
            api_client.create_transfer_request(
                {
                    "adoption_id": ctx["adoption_id"],
                    "area_id": ctx["a3_id"],
                    "requested_school_id": ctx["cedar_id"],
                    "student_reference": "STU-101",
                    "student_grade": 5,
                    "reason": "HARDSHIP",
                },
                make_guardian_headers("guardian-7"),
            ),
            ApiErrorId.ERR_SCHOOL_NOT_ACTIVE.value,
        )

        _, meta = validate_paginated(
            api_client.list_transfer_requests(
                OFFICER, {"adoption_id": ctx["adoption_id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused filing persisted nothing, got {meta['total_count']}"
        )

        adoption = validate_success(api_client.get_adoption(ctx["adoption_id"], OFFICER))
        assert adoption["implementation_status"] == "PENDING_EFFECTIVE", (
            f"the refusal moved no adoption dimension, got {adoption['implementation_status']}"
        )
        assert adoption["transfer_window_status"] == "TRANSFER_WINDOW_OPEN", (
            f"the refusal did not close the window, got {adoption['transfer_window_status']}"
        )

    def test_mothballing_one_school_leaves_the_adopted_scores_alone(self):
        """Only Cedar's own status moves; the adopted scenario keeps its stored 89.26.

        "Adjustment is also the only route to `MOTHBALLED`: a mothballed school
        may not receive new area assignments, may not host a program placement
        and may not be the requested school of a transfer (all rejected with
        `ERR_SCHOOL_NOT_ACTIVE`), and it drops out of the input set of both the
        utilization maximum and the contiguity evaluation."

        Design: Difficulty/cross_entity_state_dependency/transfer_request_blocked_by_mothballed_requested_school
        """
        ctx = riverbend_adopted()
        get_success_data(
            api_client.patch_school(ctx["cedar_id"], {"status": "MOTHBALLED"}, PLANNER)
        )
        validate_error(
            api_client.create_transfer_request(
                {
                    "adoption_id": ctx["adoption_id"],
                    "area_id": ctx["a3_id"],
                    "requested_school_id": ctx["cedar_id"],
                    "student_reference": "STU-101",
                    "student_grade": 5,
                    "reason": "HARDSHIP",
                },
                make_guardian_headers("guardian-7"),
            ),
            ApiErrorId.ERR_SCHOOL_NOT_ACTIVE.value,
        )

        cedar = validate_success(api_client.get_school(ctx["cedar_id"], PLANNER))
        birch = validate_success(api_client.get_school(ctx["birch_id"], PLANNER))
        assert cedar["status"] == "MOTHBALLED", f"unexpected Cedar status {cedar['status']}"
        assert birch["status"] == "ACTIVE", f"unexpected Birch status {birch['status']}"

        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], PLANNER))
        assert scenario["status"] == "ADOPTED", (
            f"the adopted scenario is terminal, got {scenario['status']}"
        )
        assert scenario["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
            "the score certified at submission — 100 * (452 assigned + 30 program seats) / 540 "
            f"== 89.26 — is not recomputed later, got {scenario['max_utilization_pct']}"
        )


# ===========================================================================
# resource_temporal_overlap
# ===========================================================================
class TestRegimeWindowQuietPeriod:
    """Half-open school-year intervals plus a two-school-year quiet period."""

    def test_abutting_regime_window_is_rejected(self):
        """[2031, 2033) abuts [2028, 2031) with gap zero and must be refused.

        "Exactly abutting regimes, with a gap of zero, are therefore rejected,
        and a one-school-year gap is rejected too; the first legal gap is 2
        school years."

        Design: Difficulty/resource_temporal_overlap/district_regime_abutting_school_year_rejected_by_two_year_buffer
        """
        ctx = _second_riverbend_board_ready()

        validate_error(
            api_client.create_adoption(
                _regime_candidate(
                    ctx["study_id"],
                    ctx["scenario_id"],
                    "2030-07-01T00:00:00Z",
                    2031,
                    "2030-08-15T00:00:00Z",
                ),
                BOARD,
            ),
            ApiErrorId.ERR_REGIME_WINDOW_CONFLICT.value,
        )

        study = validate_success(api_client.get_study(ctx["study_id"], BOARD))
        assert study["status"] == "BOARD_DECISION", (
            f"the refused vote committed nothing, got {study['status']}"
        )
        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], BOARD))
        assert scenario["status"] == "BOARD_READY", (
            f"the scenario was not adopted, got {scenario['status']}"
        )
        _, meta = validate_paginated(
            api_client.list_adoptions(BOARD, {"study_id": ctx["study_id"]})
        )
        assert meta["total_count"] == 0, (
            f"no adoption record was written for the second study, got {meta['total_count']}"
        )

    def test_gap_of_exactly_two_school_years_is_accepted(self):
        """[2033, 2035) sits exactly two school years past [2028, 2031) and must be accepted.

        "The candidate is rejected with `ERR_REGIME_WINDOW_CONFLICT` when the two
        intervals intersect — that is, when the candidate begins before the
        existing interval ends and the existing interval begins before the
        candidate's ends — **or** when the intervals are disjoint but the gap
        between them is smaller than the 2-school-year quiet-period buffer,
        meaning the later interval begins fewer than 2 school years after the
        earlier one ends."

        Design: Difficulty/resource_temporal_overlap/district_regime_abutting_school_year_rejected_by_two_year_buffer
        """
        ctx = _second_riverbend_board_ready()

        adoption = validate_success(
            api_client.create_adoption(
                _regime_candidate(
                    ctx["study_id"],
                    ctx["scenario_id"],
                    "2032-07-01T00:00:00Z",
                    2033,
                    "2032-08-15T00:00:00Z",
                ),
                BOARD,
            ),
            201,
        )
        assert adoption["effective_school_year"] == 2033
        assert adoption["regime_years"] == 2
        assert adoption["supermajority_required"] is False, (
            "Scenario W reassigns nobody, so students_reassigned_pct 0.00 is not strictly "
            "greater than 15.00 and a simple majority suffices"
        )
        assert adoption["implementation_status"] == "PENDING_EFFECTIVE"
        assert adoption["transfer_window_status"] == "TRANSFER_WINDOW_OPEN"

        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], BOARD))
        assert scenario["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01), (
            "every area keeps its current school, got "
            f"{scenario['students_reassigned_pct']}"
        )
        assert scenario["max_utilization_pct"] == pytest.approx(78.67, abs=0.01), (
            "100 * (452 assigned + 20 program seats) / 600 == 78.67, got "
            f"{scenario['max_utilization_pct']}"
        )

        study = validate_success(api_client.get_study(ctx["study_id"], BOARD))
        assert study["status"] == "IMPLEMENTATION", (
            f"the adoption cascade carries the study forward, got {study['status']}"
        )
        first = validate_success(
            api_client.get_adoption(ctx["first"]["adoption_id"], BOARD)
        )
        assert first["implementation_status"] == "PENDING_EFFECTIVE", (
            f"the earlier regime is untouched, got {first['implementation_status']}"
        )
        assert first["effective_school_year"] == 2028


class TestAreaRollingAbsorptionPeak:
    """A sliding 12-month probe over half-open delivery windows."""

    def test_aggregate_peak_above_the_cap_rejects_a_small_development(self):
        """Two legal developments plus a 40-unit third lift A-03's peak to 129.83.

        "The area's absorption peak is the largest of those probe totals, rounded
        half up to 2 decimal places, and the creation is rejected with
        `ERR_AREA_ABSORPTION_EXCEEDED` when that peak is strictly greater than
        the area's `annual_absorption_cap_units`."

        Design: Difficulty/resource_temporal_overlap/area_rolling_absorption_peak_exceeds_annual_cap
        """
        ctx = _absorption_context()
        _sable_ridge_pair(ctx["a3_id"])

        validate_error(
            api_client.create_housing_development(
                ctx["a3_id"],
                create_housing_development_payload(
                    name="Cypress Bend",
                    unit_type="TOWNHOME",
                    total_units=40,
                    first_occupancy_date="2027-04-01T00:00:00Z",
                    buildout_months=12,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_AREA_ABSORPTION_EXCEEDED.value,
        )

        _, meta = validate_paginated(
            api_client.list_housing_developments(ctx["a3_id"], PLANNER)
        )
        assert meta["total_count"] == 2, (
            "the two 89.83-peak developments stand and the rejected creation persisted "
            f"nothing, got {meta['total_count']}"
        )
        area = validate_success(api_client.get_planning_area(ctx["a3_id"], PLANNER))
        assert area["annual_absorption_cap_units"] == 90, (
            f"the cap itself never moves, got {area['annual_absorption_cap_units']}"
        )

    def test_a_window_that_merely_touches_contributes_nothing_to_the_probe(self):
        """A development starting the instant another's window ends is accepted.

        "For a given probe, the units delivered inside it are the sum, over every
        candidate, of that candidate's monthly rate multiplied by the length of
        the intersection between its delivery window and the probe, expressed in
        30-day months and carried unrounded; two windows that merely touch, where
        one's end instant equals the other's start instant, intersect in zero
        length and contribute exactly nothing."

        Design: Difficulty/resource_temporal_overlap/area_rolling_absorption_peak_exceeds_annual_cap
        """
        ctx = _absorption_context()
        pair = _sable_ridge_pair(ctx["a3_id"])
        validate_error(
            api_client.create_housing_development(
                ctx["a3_id"],
                create_housing_development_payload(
                    name="Cypress Bend",
                    unit_type="TOWNHOME",
                    total_units=40,
                    first_occupancy_date="2027-04-01T00:00:00Z",
                    buildout_months=12,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_AREA_ABSORPTION_EXCEEDED.value,
        )

        touching = validate_success(
            api_client.create_housing_development(
                ctx["a3_id"],
                create_housing_development_payload(
                    name="Northgate Meadows",
                    unit_type="SINGLE_FAMILY",
                    total_units=60,
                    first_occupancy_date="2028-06-25T00:00:00Z",
                    buildout_months=12,
                ),
                PLANNER,
            ),
            201,
        )
        assert touching["entitlement_status"] == "PROPOSED", (
            f"a new development always begins at PROPOSED, got {touching['entitlement_status']}"
        )
        first = validate_success(
            api_client.get_housing_development(pair[0]["id"], PLANNER)
        )
        assert first["entitlement_status"] == "PROPOSED", (
            f"the earlier development did not move either, got {first['entitlement_status']}"
        )

        _, meta = validate_paginated(
            api_client.list_housing_developments(ctx["a3_id"], PLANNER)
        )
        assert meta["total_count"] == 3, (
            "the two Sable Ridge phases plus Northgate Meadows stand, got "
            f"{meta['total_count']}"
        )
        area = validate_success(api_client.get_planning_area(ctx["a3_id"], PLANNER))
        assert area["annual_absorption_cap_units"] == 90


# ===========================================================================
# compensating_invariant
# ===========================================================================
class TestRescindRestoresEnrollmentOfRecord:
    """The district head count is conserved while the per-school split moves."""

    def test_activation_moves_the_split_but_conserves_the_district_total(self):
        """Activation moves 150 seats each way and leaves the district total at 650.

        "Link three recomputes the head counts that link two invalidated: every
        school of the study recomputes `enrolled_students_of_record` as the sum
        of `resident_student_count` over the planning areas now pointing at it,
        walked in school creation order, and then the study's
        `enrolled_of_record_total` is recomputed as the sum over its schools."

        Design: Difficulty/compensating_invariant/rescind_restores_district_enrolled_of_record_exactly
        """
        ctx = _boundary_changing_adoption()

        cedar_before = validate_success(api_client.get_school(ctx["cedar_id"], OFFICER))
        birch_before = validate_success(api_client.get_school(ctx["birch_id"], OFFICER))
        assert cedar_before["enrolled_students_of_record"] == 500, (
            "Cedar holds A-01's 300 and A-02's 200 residents before activation, got "
            f"{cedar_before['enrolled_students_of_record']}"
        )
        assert birch_before["enrolled_students_of_record"] == 150, (
            f"Birch holds A-03's 150 residents, got {birch_before['enrolled_students_of_record']}"
        )
        assert_district_enrollment_conserved([cedar_before, birch_before], 650)

        set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
        get_success_data(api_client.activate_adoption(ctx["adoption_id"], OFFICER))

        cedar_after = validate_success(api_client.get_school(ctx["cedar_id"], OFFICER))
        birch_after = validate_success(api_client.get_school(ctx["birch_id"], OFFICER))
        assert cedar_after["enrolled_students_of_record"] == 350, (
            "Cedar now holds A-02's 200 and A-03's 150 residents, got "
            f"{cedar_after['enrolled_students_of_record']}"
        )
        assert birch_after["enrolled_students_of_record"] == 300, (
            f"Birch now holds A-01's 300 residents, got {birch_after['enrolled_students_of_record']}"
        )
        assert_district_enrollment_conserved([cedar_after, birch_after], 650)

        a1 = validate_success(api_client.get_planning_area(ctx["a1_id"], OFFICER))
        a3 = validate_success(api_client.get_planning_area(ctx["a3_id"], OFFICER))
        assert a1["current_school_id"] == ctx["birch_id"]
        assert a1["previous_school_id"] == ctx["cedar_id"]
        assert a3["current_school_id"] == ctx["cedar_id"]
        assert a3["previous_school_id"] == ctx["birch_id"]

        study = validate_success(api_client.get_study(ctx["study_id"], OFFICER))
        assert study["enrolled_of_record_total"] == 650, (
            f"the conserved district total never changes, got {study['enrolled_of_record_total']}"
        )

    def test_rescind_restores_every_field_activation_wrote(self):
        """Rescission returns both counters and both pointers to their pre-activation values.

        "Link two restores the old map: for every planning area of the study
        whose `previous_school_id` is non-null, walked in area creation order,
        `current_school_id` is set back to `previous_school_id` and
        `previous_school_id` is reset to null."

        Design: Difficulty/compensating_invariant/rescind_restores_district_enrolled_of_record_exactly
        """
        ctx = _boundary_changing_adoption()
        assert ctx["adoption"]["supermajority_required"] is True, (
            "407 of 588 projected students move, so the two-thirds threshold applies"
        )
        scenario = validate_success(api_client.get_scenario(ctx["scenario_id"], BOARD))
        assert scenario["students_reassigned_pct"] == pytest.approx(69.22, abs=0.01), (
            f"100 * 407 / 588 == 69.22, got {scenario['students_reassigned_pct']}"
        )

        set_clock("2027-07-01T00:00:00Z", headers=OFFICER)
        get_success_data(api_client.activate_adoption(ctx["adoption_id"], OFFICER))
        rescinded = validate_success(
            api_client.rescind_adoption(
                ctx["adoption_id"], {"rescind_reason": "BOARD_RECONSIDERATION"}, BOARD
            )
        )
        assert rescinded["implementation_status"] == "RESCINDED", (
            f"unexpected implementation_status {rescinded['implementation_status']}"
        )

        cedar = validate_success(api_client.get_school(ctx["cedar_id"], BOARD))
        birch = validate_success(api_client.get_school(ctx["birch_id"], BOARD))
        assert cedar["enrolled_students_of_record"] == 500, (
            "the compensating action reverses the recorded delta rather than recomputing "
            f"from assignments, got {cedar['enrolled_students_of_record']}"
        )
        assert birch["enrolled_students_of_record"] == 150, (
            f"Birch is back to A-03's 150 residents, got {birch['enrolled_students_of_record']}"
        )
        assert_district_enrollment_conserved([cedar, birch], 650)

        a1 = validate_success(api_client.get_planning_area(ctx["a1_id"], BOARD))
        a3 = validate_success(api_client.get_planning_area(ctx["a3_id"], BOARD))
        assert a1["current_school_id"] == ctx["cedar_id"]
        assert a1["previous_school_id"] is None, (
            f"previous_school_id is reset to null, got {a1['previous_school_id']!r}"
        )
        assert a3["current_school_id"] == ctx["birch_id"]
        assert a3["previous_school_id"] is None

        study = validate_success(api_client.get_study(ctx["study_id"], BOARD))
        assert study["enrolled_of_record_total"] == 650
        assert study["status"] == "BOARD_DECISION", (
            f"the study reverts IMPLEMENTATION to BOARD_DECISION, got {study['status']}"
        )
        final_scenario = validate_success(
            api_client.get_scenario(ctx["scenario_id"], BOARD)
        )
        assert final_scenario["status"] == "ADOPTED", (
            f"a rescind does not un-adopt the scenario, got {final_scenario['status']}"
        )


class TestSupersedeAndRestoreConservesAssignedStudents:
    """Superseding is append-only, so scoring must read the live rows only."""

    def test_repointing_an_area_conserves_the_assigned_total(self):
        """Moving A-03 to Cedar keeps total_assigned_students at 588 while the split moves.

        "The scenario's `total_assigned_students` is the sum of
        `projected_students` over all its non-superseded assignments, and
        `max_utilization_pct` is the largest utilization across the study's
        `ACTIVE` schools, or 0.00 when the study has no `ACTIVE` school."

        Design: Difficulty/compensating_invariant/assignment_supersede_and_restore_conserves_total_assigned_students
        """
        ctx = riverbend_scenario_assigned()

        first = validate_success(
            api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
        )
        assert first["total_assigned_students"] == 588, (
            f"271 + 181 + 136 projected students are live, got {first['total_assigned_students']}"
        )
        assert first["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
            "100 * (452 assigned + 30 program seats) / 540 == 89.26, got "
            f"{first['max_utilization_pct']}"
        )
        assert first["students_reassigned_count"] == 0
        assert first["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01)
        assert first["contiguity_ok"] is True

        assign_area(ctx["scenario_id"], ctx["a3_id"], ctx["cedar_id"])

        second = validate_success(
            api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
        )
        assert second["total_assigned_students"] == 588, (
            "the conserved total is unchanged even though the split moved, got "
            f"{second['total_assigned_students']}"
        )
        assert second["max_utilization_pct"] == pytest.approx(114.44, abs=0.01), (
            "100 * (588 assigned + 30 program seats) / 540 == 114.44, got "
            f"{second['max_utilization_pct']}"
        )
        assert second["students_reassigned_count"] == 136, (
            f"only A-03 now leaves its school of record, got {second['students_reassigned_count']}"
        )
        assert second["students_reassigned_pct"] == pytest.approx(23.13, abs=0.01), (
            f"100 * 136 / 588 == 23.13, got {second['students_reassigned_pct']}"
        )

    def test_repointing_back_restores_every_score_and_grows_the_audit_trail(self):
        """Reversing the re-assignment restores 89.26 while the row count climbs to five.

        "Every downstream calculation and constraint reads only the
        non-superseded rows, and a row whose `is_superseded` is true is invisible
        to scoring while remaining readable as history — assignment listings are
        filterable by `scenario_id`, `area_id`, `assigned_school_id` and
        `is_superseded`."

        Design: Difficulty/compensating_invariant/assignment_supersede_and_restore_conserves_total_assigned_students
        """
        ctx = riverbend_scenario_assigned()
        assign_area(ctx["scenario_id"], ctx["a3_id"], ctx["cedar_id"])
        assign_area(ctx["scenario_id"], ctx["a3_id"], ctx["birch_id"])

        third = validate_success(
            api_client.get_impact_analysis(ctx["scenario_id"], PLANNER)
        )
        assert third["total_assigned_students"] == 588, (
            f"the conserved total survives both moves, got {third['total_assigned_students']}"
        )
        assert third["max_utilization_pct"] == pytest.approx(89.26, abs=0.01), (
            f"every derived score is restored exactly, got {third['max_utilization_pct']}"
        )
        assert third["students_reassigned_count"] == 0, (
            f"every area is back at its school of record, got {third['students_reassigned_count']}"
        )
        assert third["students_reassigned_pct"] == pytest.approx(0.00, abs=0.01)

        live, live_meta = validate_paginated(
            api_client.list_assignments(
                PLANNER, {"scenario_id": ctx["scenario_id"], "is_superseded": "false"}
            )
        )
        assert live_meta["total_count"] == 3, (
            f"exactly one live row per area, got {live_meta['total_count']}"
        )
        assert all(row["is_superseded"] is False for row in live)

        every, every_meta = validate_paginated(
            api_client.list_assignments(PLANNER, {"scenario_id": ctx["scenario_id"], "limit": 20})
        )
        assert every_meta["total_count"] == 5, (
            "three originals plus two superseded A-03 rows remain readable, got "
            f"{every_meta['total_count']}"
        )
        superseded = [row for row in every if row["is_superseded"]]
        assert len(superseded) == 2, (
            f"two A-03 rows were superseded, got {len(superseded)}"
        )
        for row in superseded:
            assert row["superseded_at"], (
                "a superseded row is stamped with the instant it was superseded"
            )
            assert row["area_id"] == ctx["a3_id"], (
                "only A-03 was ever re-assigned"
            )

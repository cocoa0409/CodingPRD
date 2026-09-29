"""Validation coverage: violation-to-error, conditional and cascading rules,
per-parent uniqueness scoping and the rejection ladder."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    Craft,
    NON_EXISTENT_UUID,
    Priority,
    RwpStatus,
    SchedulePosture,
    StationUnit,
    WorkOrderStatus,
    WorkOrderType,
    WorkerStatus,
    api_client,
    assert_dose_budget_consistent,
    assert_priority_band_matches_score,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_badged_worker,
    given_draft_rwp,
    given_outage,
    given_planned_work_order,
    given_rad_area,
    given_schedule_activity,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_reactor_engineer_headers,
    read_outage,
    read_rwp,
    read_work_order,
    read_worker,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShutdownMarginFloor:
    def test_a_subcritical_margin_below_the_floor_persists_nothing(self):
        """20 fresh assemblies against a 30000 MWd/MTU cycle compute
        800 + 240 - 450 = 590.00 pcm; the submission is refused and no pattern row
        or parent version bump survives it.

        PRD 3.3: "A core that cannot be held subcritical is never persisted: if the
        computed `reactivity_margin_pcm` falls below 1000 pcm, the submission is
        rejected with `ERR_SHUTDOWN_MARGIN_INSUFFICIENT` (HTTP 422) and no pattern
        row is written."

        Design: Corner/validations/shutdown_margin_below_the_floor_rejects_the_create
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        version_before = outage["version"]

        response = api_client.create_core_load_pattern(
            outage["id"],
            {
                "cycle_length_mwd_mtu": 30000,
                "fresh_assembly_count": 20,
                "discharge_assembly_count": 80,
                "expected_outage_version": version_before,
            },
            make_reactor_engineer_headers(),
        )
        validate_error(response, ApiErrorId.SHUTDOWN_MARGIN_INSUFFICIENT.value, 422)

        rows, meta = validate_paginated(
            api_client.list_core_load_patterns(
                outage["id"], make_reactor_engineer_headers()
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        assert read_outage(outage["id"])["version"] == version_before, (
            "a rejected create must not bump the parent version"
        )

        # PRD 3.6 states the two scope-lock preconditions in order: the outage
        # must own an APPROVED work order (otherwise
        # ERR_WORK_ORDER_STATE_INVALID) and then an APPROVED core loading
        # pattern (otherwise ERR_CORE_LOAD_PATTERN_NOT_APPROVED). Satisfying
        # the first precondition is what makes the missing pattern the reported
        # failure.
        given_approved_work_order(outage["id"])
        validate_error(
            api_client.lock_scope(outage["id"], make_outage_director_headers()),
            ApiErrorId.CORE_LOAD_PATTERN_NOT_APPROVED.value,
        )


class TestBadgeNumberUniquenessScope:
    def test_the_same_badge_number_is_admitted_on_a_second_outage(self):
        """Badge B-1000 is issued twice, once per outage, and each outage's
        badged headcount rises to 1 independently because the uniqueness predicate
        is qualified by outage.

        PRD 3.5: "The submitted `badge_number`, 1 to 24 characters, must not already
        be held by another worker of the same outage whose status is `BADGED`,
        otherwise `ERR_BADGE_NUMBER_TAKEN`; badge numbers held by denied or
        not-yet-badged workers do not block reuse."

        Design: Corner/validations/badge_number_uniqueness_is_scoped_per_outage
        """
        set_clock(CLOCK_EPOCH)
        first_outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        second_outage = given_outage(station_unit=StationUnit.UNIT_2, designation="2R24")

        first_worker = given_badged_worker(
            first_outage["id"],
            badge_number="B-1000",
            full_name="R. Kowalski",
            craft=Craft.PIPEFITTER,
            sponsoring_contractor="Northline Mechanical",
        )
        second_worker = given_badged_worker(
            second_outage["id"],
            badge_number="B-1000",
            full_name="T. Abiodun",
            craft=Craft.ELECTRICIAN,
            sponsoring_contractor="Northline Mechanical",
        )

        assert first_worker["status"] == WorkerStatus.BADGED
        assert second_worker["status"] == WorkerStatus.BADGED
        assert read_worker(first_worker["id"])["badge_number"] == "B-1000"
        assert read_worker(second_worker["id"])["badge_number"] == "B-1000"

        assert read_outage(first_outage["id"])["badged_worker_count"] == 1
        assert read_outage(second_outage["id"])["badged_worker_count"] == 1


class TestAlaraReviewReferenceIsConditional:
    def _locked_outage_with_a_heavy_and_a_light_permit(self):
        set_clock(CLOCK_EPOCH)
        heavy_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="CTMT-EL471",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        light_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="CTMT-EL500",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            dose_budget_total_mrem=5000,
        )
        given_approved_core_load_pattern(outage["id"])
        heavy_work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Heavy containment survey",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        light_work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Light containment survey",
            estimated_hours=20,
            estimated_cost_usd=40000,
            estimated_dose_mrem=50,
            requires_rad_work=True,
        )
        heavy = given_draft_rwp(
            heavy_work_order["id"],
            heavy_area["id"],
            worker_count=5,
            shielding_factor=0,
            planned_start_offset_hours=0,
            planned_duration_hours=5,
        )
        light = given_draft_rwp(
            light_work_order["id"],
            light_area["id"],
            worker_count=2,
            shielding_factor=0.5,
            planned_start_offset_hours=0,
            planned_duration_hours=6,
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        return outage, heavy, light

    def test_the_reference_is_demanded_for_the_heavy_permit_and_not_the_light_one(self):
        """The 625.00-mrem collective permit is refused without a reference and
        admitted with one, while the 150.00-mrem permit is approved with no
        reference supplied at all.

        PRD 3.7: "When the permit's `alara_review_required` is true, the approval
        payload must supply a non-empty `alara_review_reference` of 1 to 64
        characters, otherwise `ERR_ALARA_REVIEW_REQUIRED`; when the flag is false
        the reference is optional and, if supplied, is simply recorded."

        Design: Corner/validations/alara_review_reference_required_only_when_the_flag_is_set
        """
        outage, heavy, light = self._locked_outage_with_a_heavy_and_a_light_permit()
        assert heavy["alara_review_required"] is True
        assert heavy["collective_dose_mrem"] == pytest.approx(625.00, abs=0.01)
        assert heavy["committed_dose_mrem"] == pytest.approx(750.00, abs=0.01)
        assert light["alara_review_required"] is False
        assert light["collective_dose_mrem"] == pytest.approx(150.00, abs=0.01)
        assert light["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)

        validate_error(
            api_client.approve_rwp(heavy["id"], make_rad_protection_manager_headers()),
            ApiErrorId.ALARA_REVIEW_REQUIRED.value,
            422,
        )
        assert read_rwp(heavy["id"])["status"] == RwpStatus.DRAFT

        approved_light = validate_success(
            api_client.approve_rwp(light["id"], make_rad_protection_manager_headers())
        )
        assert approved_light["status"] == RwpStatus.APPROVED

        approved_heavy = validate_success(
            api_client.approve_rwp(
                heavy["id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-2026-0142",
            )
        )
        assert approved_heavy["status"] == RwpStatus.APPROVED
        assert approved_heavy["alara_review_reference"] == "ALARA-2026-0142"

        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(930.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(4070.00, abs=0.01)
        assert_dose_budget_consistent(after)


class TestDiscretionaryScopeGateReadsTheDurationPosture:
    def test_the_freeze_bites_the_discretionary_band_and_spares_the_high_band(self):
        """A 200-hour activity against a 100-hour target drives the posture to
        RECOVERY_REQUIRED, which closes the window for the 23.00-point work order
        while the 50.00-point one approves normally.

        PRD 3.2: "if the work order's `priority` is `DISCRETIONARY` the outage's
        `schedule_posture` must be exactly `ON_TRACK` — once the duration posture has
        slipped to `AT_RISK` or `RECOVERY_REQUIRED` the discretionary scope window is
        closed and the request is rejected with `ERR_SCOPE_FROZEN`."

        Design: Corner/validations/discretionary_scope_gate_reads_a_posture_computed_earlier_in_the_same_pipeline
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=100,
        )
        given_schedule_activity(
            outage["id"],
            label="Long lead rotor work",
            planned_start_offset_hours=0,
            planned_duration_hours=200,
        )
        discretionary = given_planned_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="WO-D discretionary lagging repair",
            estimated_hours=1,
            estimated_cost_usd=5000,
            estimated_dose_mrem=0,
        )
        high = given_planned_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="WO-H feedwater pump overhaul",
            estimated_hours=10,
            estimated_cost_usd=50000,
            estimated_dose_mrem=0,
        )

        before = read_outage(outage["id"])
        assert before["projected_duration_hours"] == pytest.approx(200.00, abs=0.01)
        assert before["schedule_posture"] == SchedulePosture.RECOVERY_REQUIRED
        assert discretionary["priority_score"] == pytest.approx(23.00, abs=0.01)
        assert discretionary["priority"] == Priority.DISCRETIONARY
        assert high["priority_score"] == pytest.approx(50.00, abs=0.01)
        assert high["priority"] == Priority.HIGH
        assert_priority_band_matches_score(discretionary)

        validate_error(
            api_client.approve_work_order_scope(
                discretionary["id"], make_outage_director_headers()
            ),
            ApiErrorId.SCOPE_FROZEN.value,
            409,
        )
        assert read_work_order(discretionary["id"])["status"] == WorkOrderStatus.PLANNED

        approved = validate_success(
            api_client.approve_work_order_scope(high["id"], make_outage_director_headers())
        )
        assert approved["status"] == WorkOrderStatus.APPROVED

        after = read_outage(outage["id"])
        assert after["approved_scope_cost_usd"] == pytest.approx(50000.00, abs=0.01), (
            "only the HIGH work order entered the roll-up"
        )


class TestRejectionLadderAcrossPathRoleAndBody:
    _MALFORMED = {
        "wo_type": WorkOrderType.MAINTENANCE,
        "title": "Malformed and orphaned",
        "estimated_cost_usd": 1000,
        "estimated_dose_mrem": 0,
    }

    def test_the_role_check_beats_the_path_check_which_beats_the_body_check(self):
        """One body that omits the required estimated_hours is sent three ways:
        unknown parent gives 404, unknown parent from an unauthorized role gives
        403, and only the clean path and role let the 400 surface.

        PRD 2.8: "Checks are evaluated in the order below, and the first violated
        check decides the response; no later check is evaluated, and no earlier
        check is skipped because a later one also fails."

        Design: Corner/validations/path_and_role_checks_outrank_body_schema_checks
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")

        validate_error(
            api_client.create_work_order(
                NON_EXISTENT_UUID, dict(self._MALFORMED), make_outage_planner_headers()
            ),
            ApiErrorId.OUTAGE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_work_order(
                NON_EXISTENT_UUID,
                dict(self._MALFORMED),
                make_rad_protection_manager_headers(),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api_client.create_work_order(
                outage["id"], dict(self._MALFORMED), make_outage_planner_headers()
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        rows, meta = validate_paginated(
            api_client.list_work_orders(
                make_outage_planner_headers(), outage_id=outage["id"]
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

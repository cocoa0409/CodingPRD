"""Service conversions: parallel state dimensions, panel sizing boundary,
the energize gate, and the denormalized project key.

PRD §3.5 (conversion work/temp axes, panel rule), §3.3 (energize gate).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_project,
    create_parcel,
    create_service_conversion_payload,
    create_service_conversion,
    work_transition,
    temp_transition,
    setup_mobilized_project,
    create_scheduled_segment,
    create_parcel_with_recorded_easement,
    create_issued_permit,
    lifecycle,
    transition_segment,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]
ROW = TEST_USERS["row_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]


class TestPanelUpgradeComputed:
    def test_panel_upgrade_computed_at_80_percent(self, api):
        """PRD §3.5: "At parcel creation the system derives
        `panel_upgrade_required`: true exactly when the calculated load reaches
        at least eighty percent of the existing panel rating — an exact
        eighty-percent match requires the upgrade. This flag is a read-only
        consequence of `load_calc_amps` and `existing_panel_amps`, not an
        input."

        Design: Corner/entities/parcel_panel_upgrade_computed_at_80_percent
        """
        project = create_project(name="PanelCalc", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        p80 = validate_success(api.create_parcel(
            {"project_id": project["id"], "address": "1 A St", "owner_name": "O",
             "existing_panel_amps": 100, "load_calc_amps": 80}, ROW), 201)
        p79 = validate_success(api.create_parcel(
            {"project_id": project["id"], "address": "2 A St", "owner_name": "O",
             "existing_panel_amps": 100, "load_calc_amps": 79}, ROW), 201)
        assert p80["panel_upgrade_required"] is True, (
            "exactly 80% triggers the upgrade (>= boundary)"
        )
        assert p79["panel_upgrade_required"] is False


class TestPanelCapacityBoundary:
    def _setup(self, api):
        """Mobilized project in TRENCHING; two parcels (load 100) with a
        conversion each in ROUGH_IN."""
        project, _parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            name="Panel Project", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        create_scheduled_segment(project["id"])
        lifecycle(project["id"], "START_TRENCHING")
        parcel_a = create_parcel(project["id"], address="6 Cedar St", owner_name="Owner Six",
                                 existing_panel_amps=200, load_calc_amps=100)
        parcel_b = create_parcel(project["id"], address="7 Cedar St", owner_name="Owner Seven",
                                 existing_panel_amps=200, load_calc_amps=100)
        conv_a = create_service_conversion(parcel_a["id"], project["id"])
        work_transition(conv_a["id"], "ROUGH_IN")
        conv_b = create_service_conversion(parcel_b["id"], project["id"])
        work_transition(conv_b["id"], "ROUGH_IN")
        return project, conv_a, conv_b

    def test_panel_at_exact_headroom_passes(self, api):
        """PRD §3.5: "Setting the panel takes a `panel_capacity_amps` value in
        the request: the new panel's rating must be at least the parcel's
        calculated load multiplied by 1.25 and rounded up to a whole amp —
        equality passes, one amp less is rejected with
        `ERR_PANEL_CAPACITY_INADEQUATE` — and the accepted rating is recorded
        on the conversion."

        Design: Difficulty/boundary_precision_check/panel_capacity_exact_headroom_boundary
        """
        _project, conv_a, _conv_b = self._setup(api)
        resp = api.work_transition(
            conv_a["id"], {"to": "PANEL_SET", "panel_capacity_amps": 125}, CONTRACTOR)
        data = validate_success(resp, 200)
        assert data["work_status"] == "PANEL_SET"
        assert data["panel_capacity_amps"] == 125, (
            "125 == ceil(100 * 1.25) passes exactly and is recorded"
        )

    def test_panel_one_amp_short_rejected(self, api):
        """PRD §3.5: "Setting the panel takes a `panel_capacity_amps` value in
        the request: the new panel's rating must be at least the parcel's
        calculated load multiplied by 1.25 and rounded up to a whole amp —
        equality passes, one amp less is rejected with
        `ERR_PANEL_CAPACITY_INADEQUATE` — and the accepted rating is recorded
        on the conversion."

        Design: Difficulty/boundary_precision_check/panel_capacity_exact_headroom_boundary
        """
        _project, _conv_a, conv_b = self._setup(api)
        resp = api.work_transition(
            conv_b["id"], {"to": "PANEL_SET", "panel_capacity_amps": 124}, CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_PANEL_CAPACITY_INADEQUATE)
        after = validate_success(api.get_service_conversion(conv_b["id"], PM), 200)
        assert after["work_status"] == "ROUGH_IN", (
            f"rejection leaves the conversion in ROUGH_IN, got {after['work_status']}"
        )


class TestParallelStateDimensions:
    def _setup(self, api):
        """Mobilized 2-party project in TRENCHING with segment BACKFILLED; one
        conversion created (PLANNED / NONE)."""
        project, _parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            name="Parallel Project", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        parcel, _es = create_parcel_with_recorded_easement(
            project["id"], address="4 Pine St", owner_name="Owner Four",
            existing_panel_amps=200, load_calc_amps=100)
        create_issued_permit(project["id"])
        seg = create_scheduled_segment(project["id"], parcel_ids=[parcel["id"]])
        lifecycle(project["id"], "START_TRENCHING")
        transition_segment(seg["id"], "EXCAVATING")
        transition_segment(seg["id"], "BACKFILLING")
        transition_segment(seg["id"], "BACKFILLED")
        conv = create_service_conversion(parcel["id"], project["id"])
        return project, conv

    def test_temp_service_advances_independently_and_gates_completion(self, api):
        """PRD §3.5: "The new conversion carries two independent state
        dimensions that evolve in parallel: `work_status`, starting at
        `PLANNED`, and `temp_service_status`, starting at `NONE`."
        PRD §3.5: "Completion (`INSPECTED → COMPLETE`) additionally requires
        that temporary service is fully out of the picture —
        `temp_service_status` of `NONE` or `TEMP_REMOVED` (`ERR_INVALID_STATE`
        otherwise)."

        Design: Difficulty/non_linear_state_machine/conversion_parallel_state_dimensions
        """
        _project, conv = self._setup(api)
        t1 = temp_transition(conv["id"], "TEMP_INSTALLED")
        assert t1["temp_service_status"] == "TEMP_INSTALLED"
        assert t1["work_status"] == "PLANNED", (
            "the temp axis advances while work is still PLANNED"
        )
        temp_transition(conv["id"], "TEMP_ACTIVE")

        work_transition(conv["id"], "ROUGH_IN")
        work_transition(conv["id"], "PANEL_SET", panel_capacity_amps=200)
        work_transition(conv["id"], "READY_TO_ENERGIZE")
        w2 = work_transition(conv["id"], "ENERGIZED")
        assert w2["work_status"] == "ENERGIZED"
        assert w2["temp_service_status"] == "TEMP_ACTIVE", (
            "temp service stays active across work-axis progress"
        )
        work_transition(conv["id"], "INSPECTED", outcome="PASS")

        resp = api.work_transition(conv["id"], {"to": "COMPLETE"}, CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fail_inspection_rework_loop_resets_panel(self, api):
        """PRD §3.5: "a `FAIL` sends the conversion back to `ROUGH_IN` for
        rework, records `last_inspection_outcome` as `FAIL`, and resets
        `panel_capacity_amps` to null so the panel must be sized and set again;
        any `outcome` value other than the one the chosen transition expects is
        `ERR_VALIDATION`."
        PRD §3.5: "Removal is the only gated step: `TEMP_ACTIVE → TEMP_REMOVED`
        requires the work axis to be `ENERGIZED` or `INSPECTED`, so temporary
        power cannot come down before permanent power is live."

        Design: Difficulty/non_linear_state_machine/conversion_parallel_state_dimensions
        """
        _project, conv = self._setup(api)
        temp_transition(conv["id"], "TEMP_INSTALLED")
        temp_transition(conv["id"], "TEMP_ACTIVE")
        work_transition(conv["id"], "ROUGH_IN")
        work_transition(conv["id"], "PANEL_SET", panel_capacity_amps=200)
        work_transition(conv["id"], "READY_TO_ENERGIZE")
        work_transition(conv["id"], "ENERGIZED")

        failed = work_transition(conv["id"], "ROUGH_IN", outcome="FAIL")
        assert failed["work_status"] == "ROUGH_IN", (
            f"FAIL inspection loops back to ROUGH_IN, got {failed['work_status']}"
        )
        assert failed["last_inspection_outcome"] == "FAIL"
        assert failed["panel_capacity_amps"] is None, (
            "the rework loop resets the panel so it must be sized again"
        )

        work_transition(conv["id"], "PANEL_SET", panel_capacity_amps=200)
        work_transition(conv["id"], "READY_TO_ENERGIZE")
        work_transition(conv["id"], "ENERGIZED")
        t4 = temp_transition(conv["id"], "TEMP_REMOVED")
        assert t4["temp_service_status"] == "TEMP_REMOVED", (
            "temp removal is allowed once ENERGIZED"
        )
        work_transition(conv["id"], "INSPECTED", outcome="PASS")
        done = work_transition(conv["id"], "COMPLETE")
        assert done["work_status"] == "COMPLETE"
        assert done["temp_service_status"] == "TEMP_REMOVED"


class TestEnergizeGate:
    def test_energize_before_backfill_rejected(self, api):
        """PRD §3.5: "Energization (`READY_TO_ENERGIZE → ENERGIZED`) is gated
        on civil completion: the trench segment whose `parcel_ids` contains
        this parcel must be `BACKFILLED` or `CLOSED`
        (`ERR_SEGMENT_NOT_BACKFILLED`), and success stamps `energized_on` with
        the clock."

        Design: Corner/validations/energize_before_backfill_rejected
        """
        project, _parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 9999, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 1, "sequence_order": 2},
            ],
            name="V14", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        parcel, _es = create_parcel_with_recorded_easement(
            project["id"], address="9 B St", owner_name="O",
            existing_panel_amps=200, load_calc_amps=100)
        create_issued_permit(project["id"])
        seg = create_scheduled_segment(project["id"], parcel_ids=[parcel["id"]])
        lifecycle(project["id"], "START_TRENCHING")
        transition_segment(seg["id"], "EXCAVATING")

        conv = create_service_conversion(parcel["id"], project["id"])
        work_transition(conv["id"], "ROUGH_IN")
        work_transition(conv["id"], "PANEL_SET", panel_capacity_amps=125)
        work_transition(conv["id"], "READY_TO_ENERGIZE")
        resp = api.work_transition(conv["id"], {"to": "ENERGIZED"}, CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_BACKFILLED)


class TestConversionProjectKey:
    def test_conversion_project_mismatch_rejected(self, api):
        """PRD §3.5: "A `ConversionContractor` opens a service conversion with
        `parcel_id` and `project_id`; the project reference is a denormalized
        filter key and must equal the parcel's own project, with a mismatch
        rejected as `ERR_VALIDATION`."

        Design: Corner/errors/conversion_project_mismatch_rejected
        """
        proj_a = create_project(name="E2A", rule20_credit_cents=0,
                                estimated_total_cost_cents=1000,
                                target_cutover_on="2026-12-31T00:00:00Z")
        proj_b = create_project(name="E2B", rule20_credit_cents=0,
                                estimated_total_cost_cents=1000,
                                target_cutover_on="2026-12-31T00:00:00Z")
        parcel = create_parcel(proj_a["id"], address="14 B St", owner_name="O",
                               existing_panel_amps=100, load_calc_amps=50)
        resp = api.create_service_conversion(
            create_service_conversion_payload(parcel["id"], proj_b["id"]), CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

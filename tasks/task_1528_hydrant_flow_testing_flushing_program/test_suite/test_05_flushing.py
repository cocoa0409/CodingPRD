"""Unidirectional flushing: per-step rounding, dechlorination dose, safety
ordering, step sequencing, zone cooldown, completion/abort cascades."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_flush_sequence,
    api_client,
    TEST_USERS,
    create_program,
    create_zone,
    create_hydrant,
    create_flush_sequence_payload,
    create_planned_sequence,
    create_sequence_in_progress,
    start_sequence,
    execute_step,
    complete_sequence,
    setup_sequence_with_linked_complaint,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]

TWO_STEPS = [
    {"step_index": 1, "valve_tag": "V-A", "action": "OPEN"},
    {"step_index": 2, "valve_tag": "V-B", "action": "CLOSE"},
]


class TestFlushVolumeRounding:
    def test_flush_volume_per_step_rounding_total(self, api):
        """PRD §3.4: "The total flushed volume comes first: for each executed
        step, the step volume is the step's `flow_gpm` multiplied by its
        `duration_minutes`, rounded half up to a whole number of gallons;
        `total_flushed_gallons` is the sum of those per-step rounded volumes.
        The rounding order is normative — round each step first, then sum;
        summing first and rounding once at the end yields a different total and
        is forbidden."

        Design: Difficulty/combinatorial_formula/flush_volume_per_step_rounding
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_sequence_in_progress(
            program["id"], zone["id"], hydrant["id"],
            steps=TWO_STEPS,
            executed_steps=[(1, 250.5, 7), (2, 310.12, 5)],
            source_residual=2.0,
        )
        completed = complete_sequence(seq["id"], final_discharge_residual_mg_L=0.05)
        # 250.5*7 = 1753.5 -> 1754; 310.12*5 = 1550.6 -> 1551; total 3305.
        assert completed["total_flushed_gallons"] == 3305, (
            f"per-step rounding must yield 3305 (sum-then-round would give 3304), "
            f"got {completed['total_flushed_gallons']}"
        )

    def test_flush_volume_per_step_rounding_tablets_and_status(self, api):
        """PRD §3.4: "the chlorine mass in milligrams is `total_flushed_gallons`
        multiplied by 3.785 (liters per gallon) multiplied by
        `source_chlorine_residual_mg_L`; `dechlorination_tablets_required` is
        the ceiling of that mass divided by 8500 milligrams per tablet."

        Design: Difficulty/combinatorial_formula/flush_volume_per_step_rounding
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_sequence_in_progress(
            program["id"], zone["id"], hydrant["id"],
            steps=TWO_STEPS,
            executed_steps=[(1, 250.5, 7), (2, 310.12, 5)],
            source_residual=2.0,
        )
        completed = complete_sequence(seq["id"], final_discharge_residual_mg_L=0.05)
        # ceil(3305 * 3.785 * 2.0 / 8500) = ceil(2.9436...) = 3
        assert completed["dechlorination_tablets_required"] == 3, (
            f"tablets must be 3, got {completed['dechlorination_tablets_required']}"
        )
        assert completed["status"] == "COMPLETED"


class TestSafetyBeforeConstraint:
    def test_complete_safety_before_constraint_error(self, api):
        """PRD §3.4: "Completion is gated by two checks evaluated in a specific
        order. The safety check is evaluated first: the supplied
        `final_discharge_residual_mg_L` must be at most 0.1 mg/L — the
        dechlorination limit — and a reading above that limit is rejected with
        `ERR_DECHLORINATION_LIMIT_EXCEEDED` (HTTP 422)."
        PRD §3.4: "Because safety outranks structure, a completion attempt that
        both exceeds the chlorine limit and has unfinished steps surfaces the
        chlorine error."

        Design: Difficulty/priority_pair_validation_conflict/complete_safety_before_constraint
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_sequence_in_progress(
            program["id"], zone["id"], hydrant["id"],
            steps=TWO_STEPS,
            executed_steps=[(1, 500, 10)],  # step 2 left PENDING
            source_residual=2.0,
        )
        resp = api.complete_flush_sequence(
            seq["id"], {"final_discharge_residual_mg_L": 0.5}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_DECHLORINATION_LIMIT_EXCEEDED, 422)

    def test_complete_safety_before_constraint_no_mutation(self, api):
        """PRD §3.4: "Only after the safety gate passes does the structural
        check apply: every step must be `EXECUTED`, else
        `ERR_STEPS_INCOMPLETE`."
        PRD §3.4: "A successful completion computes two derived quantities in a
        pinned order."

        Design: Difficulty/priority_pair_validation_conflict/complete_safety_before_constraint
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_sequence_in_progress(
            program["id"], zone["id"], hydrant["id"],
            steps=TWO_STEPS,
            executed_steps=[(1, 500, 10)],
            source_residual=2.0,
        )
        resp = api.complete_flush_sequence(
            seq["id"], {"final_discharge_residual_mg_L": 0.5}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_DECHLORINATION_LIMIT_EXCEEDED, 422)

        after = validate_success(api.get_flush_sequence(seq["id"], OP1))
        assert after["status"] == "IN_PROGRESS", (
            "a rejected completion must leave the sequence IN_PROGRESS"
        )
        assert after.get("total_flushed_gallons") is None, (
            "no totals may be computed when completion is rejected"
        )


class TestZoneCooldown:
    def test_sequence_zone_cooldown_buffer_violation(self, api):
        """PRD §3.4: "The gap between the new sequence's window and any other
        `PLANNED` or `IN_PROGRESS` sequence in the same zone must be at least
        the zone's `cooldown_minutes`; adjacency closer than that buffer — even
        by a minute — is rejected with `ERR_SEQUENCE_ZONE_COOLDOWN`."

        Design: Difficulty/resource_temporal_overlap/sequence_zone_cooldown_buffer
        """
        program, zone, hydrants = self._zone_with_three_hydrants()
        h1, h2, h3 = hydrants
        create_planned_sequence(program["id"], zone["id"], h1["id"],
                                window_start="2026-08-03T10:00:00Z",
                                window_end="2026-08-03T11:00:00Z")

        resp = api.create_flush_sequence(
            create_flush_sequence_payload(
                program["id"], zone["id"], h2["id"],
                window_start="2026-08-03T11:30:00Z", window_end="2026-08-03T12:00:00Z",
            ),
            OP1,
        )
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_ZONE_COOLDOWN, 409)

    def test_sequence_zone_cooldown_buffer_exactly_met(self, api):
        """PRD §3.4: "The gap between the new sequence's window and any other
        `PLANNED` or `IN_PROGRESS` sequence in the same zone must be at least
        the zone's `cooldown_minutes`; adjacency closer than that buffer — even
        by a minute — is rejected with `ERR_SEQUENCE_ZONE_COOLDOWN`."
        PRD §3.1: "each zone has a `name` and an optional `cooldown_minutes`,
        defaulting to 60 minutes, which is the minimum gap between the windows
        of any two non-terminal flush sequences in that zone"

        Design: Difficulty/resource_temporal_overlap/sequence_zone_cooldown_buffer
        """
        program, zone, hydrants = self._zone_with_three_hydrants()
        h1, h2, h3 = hydrants
        create_planned_sequence(program["id"], zone["id"], h1["id"],
                                window_start="2026-08-03T10:00:00Z",
                                window_end="2026-08-03T11:00:00Z")

        resp = api.create_flush_sequence(
            create_flush_sequence_payload(
                program["id"], zone["id"], h3["id"],
                window_start="2026-08-03T12:00:00Z", window_end="2026-08-03T13:00:00Z",
            ),
            OP1,
        )
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "PLANNED", (
            "a gap of exactly cooldown_minutes (60) satisfies 'at least' and must be allowed"
        )

    @staticmethod
    def _zone_with_three_hydrants():
        program = create_program()
        zone = create_zone(cooldown_minutes=60)
        hydrants = [
            create_hydrant(program["id"], zone["id"], hydrant_number=f"H-{i}")
            for i in (1, 2, 3)
        ]
        return program, zone, hydrants


class TestDechlorinationCeiling:
    def test_dechlorination_tablet_ceiling(self, api):
        """PRD §3.4: "the chlorine mass in milligrams is `total_flushed_gallons`
        multiplied by 3.785 (liters per gallon) multiplied by
        `source_chlorine_residual_mg_L`; `dechlorination_tablets_required` is
        the ceiling of that mass divided by 8500 milligrams per tablet."

        Design: Corner/calculations/dechlorination_tablet_ceiling
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_sequence_in_progress(
            program["id"], zone["id"], hydrant["id"],
            executed_steps=[(1, 100, 10)],  # 1000 gallons exactly
            source_residual=0.5,
        )
        completed = complete_sequence(seq["id"], final_discharge_residual_mg_L=0.05)
        assert completed["total_flushed_gallons"] == 1000
        # 1000 * 3.785 * 0.5 = 1892.5 mg; ceil(1892.5 / 8500) = 1
        assert completed["dechlorination_tablets_required"] == 1, (
            f"a small flush still requires exactly 1 tablet, "
            f"got {completed['dechlorination_tablets_required']}"
        )


class TestStepOrdering:
    def test_step_execution_out_of_order_rejected(self, api):
        """PRD §3.4: "The sequence must be `IN_PROGRESS` (else
        `ERR_SEQUENCE_NOT_IN_PROGRESS`); the addressed step must exist and be
        `PENDING`; and every step with a smaller `step_index` must already be
        `EXECUTED`. A violation of either step condition is rejected with
        `ERR_STEP_OUT_OF_SEQUENCE`."

        Design: Corner/validations/step_execution_out_of_order_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_planned_sequence(program["id"], zone["id"], hydrant["id"],
                                      steps=TWO_STEPS)
        start_sequence(seq["id"], source_chlorine_residual_mg_L=1.0)

        resp = api.execute_flush_step(
            seq["id"], {"step_index": 2, "flow_gpm": 400, "duration_minutes": 5}, OP1
        )
        validate_error(resp, ApiErrorId.ERR_STEP_OUT_OF_SEQUENCE, 409)

        after = validate_success(api.get_flush_sequence(seq["id"], OP1))
        statuses = {s["step_index"]: s["status"] for s in after["steps"]}
        assert statuses == {1: "PENDING", 2: "PENDING"}, (
            f"no step may be executed by the rejected call, got {statuses}"
        )


class TestAbortTerminalLockdown:
    def test_sequence_abort_from_completed_rejected(self, api):
        """PRD §3.4: "A `FieldOperator` may abort a sequence in `IN_PROGRESS`
        (else `ERR_SEQUENCE_NOT_IN_PROGRESS`)."

        Design: Corner/state_machines/sequence_abort_from_completed_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq = create_sequence_in_progress(
            program["id"], zone["id"], hydrant["id"],
            executed_steps=[(1, 400, 10)],
            source_residual=1.0,
        )
        complete_sequence(seq["id"], final_discharge_residual_mg_L=0.05)

        resp = api.abort_flush_sequence(seq["id"], OP1)
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_NOT_IN_PROGRESS, 409)

        after = validate_success(api.get_flush_sequence(seq["id"], OP1))
        assert after["status"] == "COMPLETED", "COMPLETED must be terminal for abort"
        assert after["total_flushed_gallons"] == 4000, (
            f"pinned totals must survive the rejected abort, "
            f"got {after['total_flushed_gallons']}"
        )


class TestComplaintCascades:
    def test_sequence_complete_resolves_linked_complaint(self, api):
        """PRD §3.4: "Completion also fires two cascades: every
        `WaterQualityComplaint` whose `flush_sequence_id` is this sequence and
        whose status is `LINKED` moves to `RESOLVED`, and the target hydrant's
        `targeted_flush_pending` is cleared to false with the hydrant's version
        incremented."

        Design: Corner/state_machines/sequence_complete_resolves_linked_complaint
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq, complaint = setup_sequence_with_linked_complaint(program, zone, hydrant)

        completed = complete_sequence(seq["id"], final_discharge_residual_mg_L=0.05)
        assert completed["status"] == "COMPLETED"

        after = validate_success(api.get_complaint(complaint["id"], OP1))
        assert after["status"] == "RESOLVED", (
            f"linked complaint must resolve on completion, got {after['status']}"
        )

    def test_sequence_abort_returns_linked_complaint_to_open(self, api):
        """PRD §3.4: "Abortion moves the sequence to `ABORTED` and runs
        compensation: every complaint whose `flush_sequence_id` is this
        sequence reverts to `OPEN` with its `flush_sequence_id` cleared, and
        the hydrant's `targeted_flush_pending` is cleared to false with the
        hydrant's version incremented."

        Design: Corner/state_machines/sequence_abort_returns_linked_complaint_to_open
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        seq, complaint = setup_sequence_with_linked_complaint(program, zone, hydrant,
                                                              execute=False)

        aborted = validate_success(api.abort_flush_sequence(seq["id"], OP1))
        assert aborted["status"] == "ABORTED"

        after = validate_success(api.get_complaint(complaint["id"], OP1))
        assert after["status"] == "OPEN", (
            f"compensation must return the complaint to OPEN, got {after['status']}"
        )
        assert after.get("flush_sequence_id") is None, (
            "compensation must clear flush_sequence_id"
        )


class TestProgramMatch:
    def test_sequence_program_mismatch_rejected(self, api):
        """PRD §3.4: "The sequence's `program_id` must equal the target
        hydrant's own `program_id`; a mismatch is rejected with
        `ERR_PROGRAM_MISMATCH` (HTTP 422)."

        Design: Corner/validations/sequence_program_mismatch_rejected
        """
        prog1 = create_program(program_year=2026, season="SPRING")
        prog2 = create_program(program_year=2026, season="FALL")
        zone = create_zone()
        hydrant = create_hydrant(prog1["id"], zone["id"], hydrant_number="H-100")

        resp = api.create_flush_sequence(
            create_flush_sequence_payload(
                prog2["id"], zone["id"], hydrant["id"],
                window_start="2026-08-03T10:00:00Z", window_end="2026-08-03T11:00:00Z",
            ),
            OP1,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_MISMATCH, 422)

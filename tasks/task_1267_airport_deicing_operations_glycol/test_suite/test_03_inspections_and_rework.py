"""Tests for inspections, segregation of duties, and the rework cascade."""
import pytest

from test_helpers import (

    ApiErrorId,
    TEST_USERS,
    create_inspection_payload,
    get_operation_for_request,
    make_inspector_headers,
    record_acceptance_inspection,
    record_post_treatment_inspection,
    setup_operation_awaiting_inspection,
    setup_operation_spraying,
    setup_request_assigned,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestInspectionImmutability:
    def test_inspection_is_immutable_event(self, api):
        """PRD §2.4: "Two resources deviate from this convention: `Inspection`
        and `EffluentReading` are immutable records that carry only `id` and
        `created_at`; both `updated_at` and `version` are absent from them, and
        they never participate in optimistic concurrency checks."

        Design: Corner/entities/inspection_is_immutable_event
        """
        station, permit, tank, pad, airline, request, operation = setup_request_assigned()
        resp = api.create_inspection(
            create_inspection_payload(operation["id"], kind="ACCEPTANCE", result="PASS"),
            make_inspector_headers("insp-1"),
        )
        data = validate_success(resp, expected_status=201)
        assert "id" in data
        assert "created_at" in data
        assert "operation_id" in data
        assert "kind" in data
        assert "result" in data
        assert "inspector_id" in data
        assert "version" not in data
        assert "updated_at" not in data


class TestInspectionUniqueness:
    def test_second_acceptance_inspection_rejected(self, api):
        """PRD §3.6: "Each kind may be recorded at most once per operation: a
        second inspection of a kind that already exists is rejected with
        `ERR_INSPECTION_EXISTS`."

        Design: Corner/errors/second_acceptance_inspection_rejected
        """
        station, permit, tank, pad, airline, request, operation = setup_request_assigned()
        record_acceptance_inspection(operation["id"], inspector_id="insp-1")

        resp = api.create_inspection(
            create_inspection_payload(operation["id"], kind="ACCEPTANCE", result="FAIL"),
            make_inspector_headers("insp-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_EXISTS)


class TestInspectionSegregationOfDuties:
    def test_post_treatment_same_inspector_sod_rejected(self, api):
        """PRD §3.6: "its `inspector_id` must differ from the `inspector_id` of
        the operation's acceptance inspection; the same person signing off both
        stages is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/rbac/post_treatment_same_inspector_sod_rejected
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_awaiting_inspection(actual_liters=300, collected_liters=200)
        )
        # Acceptance was recorded by insp-1 in the fixture.

        # Same inspector rejected.
        resp = api.create_inspection(
            create_inspection_payload(
                operation["id"], kind="POST_TREATMENT", result="PASS"
            ),
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "AWAITING_INSPECTION"

        # Different inspector succeeds.
        resp = api.create_inspection(
            create_inspection_payload(
                operation["id"], kind="POST_TREATMENT", result="PASS"
            ),
            make_inspector_headers("insp-2"),
        )
        validate_success(resp, expected_status=201)

        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "CLEARED"

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "COMPLETED"

        resp = api.get_pad(pad["id"], TEST_USERS["pad_operator_headers"])
        assert validate_success(resp)["status"] == "AVAILABLE"


class TestReworkCascade:
    def test_inspection_fail_rework_cascade(self, api):
        """PRD §3.6: "A post-treatment `FAIL` triggers a four-link cascade.
        First, the inspected operation moves to `REWORK_REQUIRED`, terminal for
        that operation. Second, the system auto-creates a rework
        **DeiceOperation**: its `parent_operation_id` points at the failed
        operation, it starts in `PLANNED` status, it inherits the same
        `request_id`, `station_id`, `pad_id`, and `tank_id`, its occupancy
        window is copied from the failed operation, and its `estimated_liters`
        is the failed operation's `actual_liters` multiplied by one half,
        rounded up to a whole liter. Third, that rework estimate immediately
        joins the tank's `reserved_liters` per §2.7, with `available_liters`
        and tank status recomputed. Fourth, the station's posture is recomputed
        — and if the rework reservation has dragged total station availability
        below `fluid_ops_minimum_liters`, the posture flips to
        `FLUID_CONSTRAINED` and blocks subsequent assignments until fluid
        recovers."

        Design: Difficulty/transitive_cascade/inspection_fail_rework_cascade
        """
        from test_helpers import (
            assign_request_payload,
            create_reserved_request,
            setup_operational_base,
        )

        station, permit, tank, pad, airline = setup_operational_base(
            station_overrides={"fluid_ops_minimum_liters": 2000},
            tank_overrides={
                "fluid_type": "TYPE_I",
                "concentration_pct": 100,
                "capacity_liters": 5000,
                "on_hand_liters": 3500,
                "reorder_threshold_liters": 300,
            },
            pad_overrides={"max_size_class": "LARGE"},
        )
        r1 = create_reserved_request(
            airline, station, tank, size_class="MEDIUM",
            flight_number="AA1", scheduled_departure="2026-05-01T12:00:00Z"
        )
        r2 = create_reserved_request(
            airline, station, tank, size_class="SMALL",
            flight_number="AA2", scheduled_departure="2026-05-01T13:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:00:00Z",
            window_end="2026-05-01T10:30:00Z",
        )
        api.assign_deice_request(
            r1["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op1 = get_operation_for_request(r1["id"])
        record_acceptance_inspection(op1["id"], inspector_id="insp-1")
        from test_helpers import start_operation, complete_operation
        start_operation(op1["id"], oat_celsius=0)
        complete_operation(op1["id"], actual_liters=600, collected_liters=400)

        # Trigger the FAIL inspection.
        resp = api.create_inspection(
            create_inspection_payload(
                op1["id"],
                kind="POST_TREATMENT",
                result="FAIL",
                findings="fluid residue on wing",
            ),
            make_inspector_headers("insp-2"),
        )
        validate_success(resp, expected_status=201)

        # Link 1: parent operation REWORK_REQUIRED.
        resp = api.get_deice_operation(
            op1["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "REWORK_REQUIRED"

        # Link 2: rework child created.
        resp = api.list_deice_operations(
            TEST_USERS["pad_operator_headers"],
            params={"parent_operation_id": op1["id"]},
        )
        children = validate_success(resp)
        assert len(children) == 1
        child = children[0]
        assert child["parent_operation_id"] == op1["id"]
        assert child["status"] == "PLANNED"
        assert child["estimated_liters"] == 300

        # Link 3: tank reserved/available recomputed.
        resp = api.get_fluid_tank(tank["id"], TEST_USERS["pad_operator_headers"])
        tank_after = validate_success(resp)
        assert tank_after["on_hand_liters"] == 2900
        assert tank_after["reserved_liters"] == 1000
        assert tank_after["available_liters"] == 1900

        # Link 4: station posture FLUID_CONSTRAINED.
        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["posture"] == "FLUID_CONSTRAINED"

        # Observable consequence: assign of R2 rejected.
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T11:00:00Z",
            window_end="2026-05-01T11:30:00Z",
        )
        resp = api.assign_deice_request(
            r2["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FLUID_CONSTRAINED)

    def test_rework_child_clears_lineage_request(self, api):
        """PRD §3.6: "When a rework lineage's child is ultimately cleared, the
        request completes at that point, not at the parent's failure."

        Design: Difficulty/transitive_cascade/inspection_fail_rework_cascade
        """
        from test_helpers import (
            assign_request_payload,
            create_reserved_request,
            setup_operational_base,
            start_operation,
            complete_operation,
        )

        station, permit, tank, pad, airline = setup_operational_base(
            station_overrides={"fluid_ops_minimum_liters": 2000},
            tank_overrides={
                "fluid_type": "TYPE_I",
                "concentration_pct": 100,
                "capacity_liters": 5000,
                "on_hand_liters": 3500,
                "reorder_threshold_liters": 300,
            },
            pad_overrides={"max_size_class": "LARGE"},
        )
        r1 = create_reserved_request(
            airline, station, tank, size_class="MEDIUM",
            flight_number="AA1", scheduled_departure="2026-05-01T12:00:00Z"
        )
        payload = assign_request_payload(
            pad["id"],
            window_start="2026-05-01T10:00:00Z",
            window_end="2026-05-01T10:30:00Z",
        )
        api.assign_deice_request(
            r1["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        op1 = get_operation_for_request(r1["id"])
        record_acceptance_inspection(op1["id"], inspector_id="insp-1")
        start_operation(op1["id"], oat_celsius=0)
        complete_operation(op1["id"], actual_liters=600, collected_liters=400)
        record_post_treatment_inspection(
            op1["id"], result="FAIL", inspector_id="insp-2"
        )

        # Request is still IN_PROGRESS after parent failure.
        resp = api.get_deice_request(
            r1["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "IN_PROGRESS"

        # Drive the rework child through to CLEARED.
        resp = api.list_deice_operations(
            TEST_USERS["pad_operator_headers"],
            params={"parent_operation_id": op1["id"]},
        )
        child = validate_success(resp)[0]
        record_acceptance_inspection(child["id"], inspector_id="insp-1")
        start_operation(child["id"], oat_celsius=0)
        complete_operation(child["id"], actual_liters=300, collected_liters=200)
        record_post_treatment_inspection(
            child["id"], result="PASS", inspector_id="insp-2"
        )

        # Now the lineage request completes.
        resp = api.get_deice_request(
            r1["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "COMPLETED"


class TestValidationPriority:
    def test_start_state_violation_beats_sod_safety(self, api):
        """PRD §2.8: "State admissibility is evaluated fourth: wrong-from-state
        transitions, terminal-state lockdown, stale OCC versions, and
        duplicate-unique-child violations such as a second acceptance inspection
        yield `ERR_INVALID_STATE`, `ERR_STALE_VERSION`, or
        `ERR_INSPECTION_EXISTS` respectively. Regulatory and safety gates are
        fifth — a suspended permit blocking assignment
        (`ERR_PERMIT_SUSPENDED`), a missing acceptance pass blocking spray start
        (`ERR_ACCEPTANCE_REQUIRED`), and segregation-of-duties violations
        (`ERR_SOD_VIOLATION`)."

        Design: Difficulty/priority_pair_validation_conflict/start_state_violation_beats_sod_safety
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_spraying()
        )
        # Operation is SPRAYING; acceptance was recorded by insp-1.
        # A POST_TREATMENT by the same inspector would breach SoD, but the
        # wrong from-state must win.
        resp = api.create_inspection(
            create_inspection_payload(
                operation["id"], kind="POST_TREATMENT", result="FAIL"
            ),
            make_inspector_headers("insp-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "SPRAYING"

    def test_acceptance_on_spraying_operation_invalid_state(self, api):
        """PRD §3.6: "An acceptance inspection requires the operation to be
        `PLANNED`; otherwise the recording is rejected with
        `ERR_INVALID_STATE`."
        PRD §2.8: "State admissibility is evaluated fourth: wrong-from-state
        transitions... yield `ERR_INVALID_STATE`..."

        Design: Difficulty/priority_pair_validation_conflict/start_state_violation_beats_sod_safety
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_spraying()
        )
        # Operation is SPRAYING; an acceptance inspection is out of state.
        # PRD §2.8 places wrong-from-state (`ERR_INVALID_STATE`) and
        # duplicate-unique-child (`ERR_INSPECTION_EXISTS`) at the same (fourth)
        # priority level without ordering within it, so either may surface.
        resp = api.create_inspection(
            create_inspection_payload(
                operation["id"], kind="ACCEPTANCE", result="PASS"
            ),
            make_inspector_headers("insp-2"),
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_INSPECTION_EXISTS]
        )

"""ESD audit closure gates, customer-equipment calibration discipline at the
inclusive due boundary, closed-interval maintenance windows, and the fixture
maintenance cascade (PRD §3.2, §3.7, §3.8)."""
from datetime import datetime, timezone

from test_helpers import (
    create_customer,
    create_equipment,
    create_esd_audit_payload,
    create_maintenance_order,
    create_test_result_payload,
    parse_iso8601,
    reserve,
    setup_in_test_lot,
    setup_reservation_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ENG1, OPS, QE


class TestEsdAuditClose:
    def test_missing_corrective_action_on_audit_close(self, api):
        """PRD §3.8: "Every `MAJOR` finding index must be covered by a corrective
        action — an incomplete covering is rejected with
        `ERR_MISSING_CORRECTIVE_ACTION`."

        Design: Corner/validations/missing_corrective_action_on_audit_close
        """
        audit = validate_success(
            api.create_esd_audit(
                create_esd_audit_payload(
                    area_code="AREA-G",
                    findings=[{"severity": "MAJOR", "description": "mat resistance high"}],
                ),
                QE,
            ),
            201,
        )
        res = api.close_esd_audit(audit["id"], {"corrective_actions": []}, QE)
        validate_error(res, "ERR_MISSING_CORRECTIVE_ACTION", expected_status=422)
        audit_after = validate_success(api.get_esd_audit(audit["id"], QE), 200)
        assert audit_after["status"] == "OPEN", "rejected close must change nothing"

    def test_esd_audit_terminal_lockdown(self, api):
        """PRD §3.8: "Closing an audit moves it from `OPEN` to `CLOSED`."
        PRD §3.8: "On a successful close the `outcome` is computed: `PASS` when the
        audit recorded no findings at all, `PASS_WITH_MINOR` when findings exist but
        all are `MINOR`, and `FAIL` when any finding is `MAJOR`."
        PRD §2.11: "the target resource's own state permits the operation — a lot
        `IN_TEST` for result recording, a unit `FAILED` for retest authorization, a
        review `PENDING` for a decision, an audit `OPEN` for close, a reservation
        `RESERVED` for start, cancel, or reschedule, a program `DRAFT` or `VALIDATED`
        for validate or release — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/esd_audit_terminal_lockdown
        """
        audit = validate_success(
            api.create_esd_audit(
                create_esd_audit_payload(area_code="AREA-Z", findings=[]), QE
            ),
            201,
        )
        closed = validate_success(
            api.close_esd_audit(audit["id"], {"corrective_actions": []}, QE), 200
        )
        assert closed["outcome"] == "PASS", "no findings -> PASS"
        assert closed["status"] == "CLOSED"
        res = api.close_esd_audit(audit["id"], {"corrective_actions": []}, QE)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestEquipmentCalibrationGate:
    def _setup_equipment_due_at_clock_default(self, api):
        """IN_TEST lot of 1 plus equipment whose next_calibration_due lands exactly
        on the startup clock default: 2026-04-01T00:00:00Z + 30 days."""
        ctx = setup_in_test_lot(quantity=1, part_number="PN-131",
                                bin_map={"1": "PASS", "9": "HARD_FAIL"},
                                max_retests_per_unit=1)
        equipment = create_equipment(
            ctx["customer"]["id"],
            equipment_type="TESTER",
            serial_number="EQ-1",
            calibration_interval_days=30,
            last_calibrated_at="2026-04-01T00:00:00Z",
        )
        return ctx, equipment

    def test_calibration_due_at_exact_due_instant(self, api):
        """PRD §3.7: "Registration computes `next_calibration_due` as
        `last_calibrated_at` plus the calibration interval in days, and the
        equipment begins `IN_SERVICE`."
        PRD §3.7: "Equipment whose stored status is `IN_SERVICE` is effectively
        `CALIBRATION_DUE` whenever the logical clock has reached or passed
        `next_calibration_due` — the boundary is inclusive, so a clock exactly equal
        to the due timestamp already reads as due."
        PRD §2.5: "At startup the logical clock reads exactly
        `2026-05-01T00:00:00Z`; before any operator intervention the clock holds
        this default and never drifts with real time."

        Design: Difficulty/cross_entity_state_dependency/result_requires_equipment_in_service
        """
        _ctx, equipment = self._setup_equipment_due_at_clock_default(api)
        # The clock is left at its startup default, exactly the due instant.
        fetched = validate_success(api.get_customer_equipment(equipment["id"], OPS), 200)
        assert parse_iso8601(fetched["next_calibration_due"]) == datetime(
            2026, 5, 1, 0, 0, tzinfo=timezone.utc
        ), "due = last_calibrated_at 2026-04-01 + 30 days"
        assert fetched["status"] == "CALIBRATION_DUE", "inclusive >= at the due instant"

    def test_result_recording_with_due_equipment_rejected(self, api):
        """PRD §3.7: "Only effectively in-service equipment may be named on a test
        insertion; anything else — due for calibration, in maintenance, or returned
        — is rejected with `ERR_EQUIPMENT_NOT_IN_SERVICE`, as described in §3.5."

        Design: Difficulty/cross_entity_state_dependency/result_requires_equipment_in_service
        """
        ctx, equipment = self._setup_equipment_due_at_clock_default(api)
        res = api.create_test_result(
            create_test_result_payload(
                ctx["units"][0]["id"], ctx["fixture"]["id"], bin_code=1,
                equipment_id=equipment["id"],
            ),
            ENG1,
        )
        validate_error(res, "ERR_EQUIPMENT_NOT_IN_SERVICE", expected_status=409)
        unit = validate_success(api.get_unit(ctx["units"][0]["id"], ENG1), 200)
        assert unit["test_status"] == "UNTESTED", "rejected insert must persist nothing"


class TestMaintenanceWindows:
    def test_touching_windows_conflict_on_same_target(self, api):
        """PRD §2.9: "A new order conflicts with an existing `OPEN` or `IN_PROGRESS`
        order on the same target whenever the new `window_start` falls at or before
        the existing window's end and the existing window's start falls at or before
        the new `window_end` — which means two windows that merely touch, one's
        start landing exactly on the other's end, still conflict. Such a collision
        is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/equipment_maintenance_closed_interval_conflict
        """
        customer = create_customer(name="MaintCo")
        equipment = create_equipment(
            customer["id"], serial_number="EQ-M", calibration_interval_days=365,
            last_calibrated_at="2026-04-15T00:00:00Z",
        )
        mo1 = create_maintenance_order(
            "EQUIPMENT", equipment["id"], kind="CALIBRATION",
            window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T11:00:00Z",
        )
        assert mo1["status"] == "OPEN"
        # Closed-interval semantics: window_start 11:00 == existing window_end
        # 11:00 still conflicts.
        res = api.create_maintenance_order(
            {
                "target_type": "EQUIPMENT", "target_id": equipment["id"],
                "kind": "PREVENTIVE",
                "window_start": "2026-06-01T11:00:00Z",
                "window_end": "2026-06-01T12:00:00Z",
            },
            OPS,
        )
        validate_error(res, "ERR_MAINTENANCE_WINDOW_CONFLICT", expected_status=409)

    def test_one_minute_gap_between_windows_accepted(self, api):
        """PRD §2.9: "Maintenance orders, by contrast, use closed interval
        semantics: a maintenance window occupies both its `window_start` and its
        `window_end`, and a well-formed order satisfies `window_start` at or before
        `window_end`."
        PRD §2.9: "A new order conflicts with an existing `OPEN` or `IN_PROGRESS`
        order on the same target whenever the new `window_start` falls at or before
        the existing window's end and the existing window's start falls at or before
        the new `window_end` — which means two windows that merely touch, one's
        start landing exactly on the other's end, still conflict."

        Design: Difficulty/resource_temporal_overlap/equipment_maintenance_closed_interval_conflict
        """
        customer = create_customer(name="MaintCo")
        equipment = create_equipment(
            customer["id"], serial_number="EQ-M", calibration_interval_days=365,
            last_calibrated_at="2026-04-15T00:00:00Z",
        )
        create_maintenance_order(
            "EQUIPMENT", equipment["id"], kind="CALIBRATION",
            window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T11:00:00Z",
        )
        # A real gap of one minute is required and sufficient under closed
        # semantics: 11:01 > existing window_end 11:00, so no conflict.
        mo3 = validate_success(
            api.create_maintenance_order(
                {
                    "target_type": "EQUIPMENT", "target_id": equipment["id"],
                    "kind": "PREVENTIVE",
                    "window_start": "2026-06-01T11:01:00Z",
                    "window_end": "2026-06-01T12:00:00Z",
                },
                OPS,
            ),
            201,
        )
        assert mo3["status"] == "OPEN"
        rows, meta = validate_paginated(
            api.list_maintenance_orders(OPS, params={"target_id": equipment["id"]})
        )
        assert len(rows) == 2 and meta["total_count"] == 2


class TestFixtureMaintenanceCascade:
    def test_fixture_maintenance_cascades_cancel_future_reservations(self, api):
        """PRD §3.2: "Sending a fixture to maintenance has scheduling consequences
        beyond the fixture itself: every chamber reservation in `RESERVED` status
        that references the fixture is cancelled, and each such cancellation frees
        the reservation's slots in the affected chamber's ledger."

        Design: Corner/state_machines/fixture_maintenance_cascades_cancel_future_reservations
        """
        ctx = setup_reservation_scenario(
            part_number="PN-211", max_retests_per_unit=1, slot_count=4
        )
        r1 = reserve(ctx, start_at="2026-06-02T10:00:00Z",
                     end_at="2026-06-02T11:00:00Z", slot_count=2)
        chamber_before = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber_before["available_slots"] == 2

        fixture = validate_success(api.fixture_maintenance(ctx["fixture"]["id"], ENG1), 200)
        assert fixture["status"] == "UNDER_MAINTENANCE"

        r1_after = validate_success(api.get_chamber_reservation(r1["id"], ENG1), 200)
        assert r1_after["status"] == "CANCELLED", "cascade from fixture maintenance"
        chamber_after = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber_after["available_slots"] == 4, "the 2 slots are freed"

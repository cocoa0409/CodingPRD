"""Inspection windows and plant license governance: suspension, terminal
revocation and its cascade (PRD §3.1, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_inspection_payload,
    drive_plant_score_to_zero,
    get_charge,
    get_cylinder,
    get_plant,
    load_charge,
    set_clock,
    setup_cycle_complete_charge,
    setup_cylinder,
    setup_inspection,
    setup_plant,
    setup_shop,
    validate_error,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
INSP = TEST_USERS["inspector_headers"]

WINDOW = {"inspection_window_start": "2026-08-10T09:00:00Z",
          "inspection_window_end": "2026-08-10T17:00:00Z"}


class TestInspectionWindow:
    def test_inspection_begin_outside_window_rejected(self, api):
        """PRD §3.9: "Beginning the inspection is permitted only while the
        plant is `LICENSED` and only inside the declared window: a begin
        attempted outside the window is rejected with
        `ERR_INSPECTION_WINDOW_MISSED` (409)".

        Design: Corner/state_machines/inspection_begin_outside_window_rejected
        """
        plant = setup_plant()
        inspection = validate_success(
            api.create_inspection(plant["id"], create_inspection_payload(**WINDOW), INSP),
            201)
        # Logical clock sits one hour past the window's end.
        set_clock("2026-08-10T18:00:00Z")
        resp = api.begin_inspection(plant["id"], inspection["id"], INSP)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_WINDOW_MISSED.value)

    def test_begin_before_window_rejected_mid_window_allowed(self, api):
        """PRD §3.9: "Beginning the inspection is permitted only while the
        plant is `LICENSED` and only inside the declared window: a begin
        attempted outside the window is rejected with
        `ERR_INSPECTION_WINDOW_MISSED` (409), and a begin against an
        inspection that is not `SCHEDULED` fails with
        `ERR_INSPECTION_NOT_SCHEDULED` (409). A successful begin moves the
        inspection to `IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/quality_inspection_window_membership_check
        """
        plant = setup_plant()
        inspection = validate_success(
            api.create_inspection(plant["id"], create_inspection_payload(**WINDOW), INSP),
            201)

        # One second before the window opens -> rejected.
        set_clock("2026-08-10T08:59:59Z")
        resp = api.begin_inspection(plant["id"], inspection["id"], INSP)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_WINDOW_MISSED.value)

        # Comfortably inside the window -> succeeds.
        set_clock("2026-08-10T12:00:00Z")
        begun = validate_success(api.begin_inspection(plant["id"], inspection["id"], INSP))
        assert begun["status"] == "IN_PROGRESS"

    def test_begin_at_window_start_is_inside(self, api):
        """PRD §3.9: "Beginning the inspection is permitted only while the
        plant is `LICENSED` and only inside the declared window" — the window
        is declared by its `inspection_window_start` and
        `inspection_window_end`, so the start instant itself is inside it.

        Design: Difficulty/resource_temporal_overlap/quality_inspection_window_membership_check
        """
        plant = setup_plant()
        inspection = validate_success(
            api.create_inspection(plant["id"], create_inspection_payload(**WINDOW), INSP),
            201)
        set_clock("2026-08-10T09:00:00Z")  # exactly inspection_window_start
        begun = validate_success(api.begin_inspection(plant["id"], inspection["id"], INSP))
        assert begun["status"] == "IN_PROGRESS"


class TestPlantGovernance:
    def test_plant_terminal_revoked_no_transitions(self, api):
        """PRD §3.1: "`REVOKED` is terminal, and the cascade is severe".
        PRD §2.9: "with `ERR_INVALID_STATE` (409) as the generic form when a
        resource is simply not in a valid from-state."
        PRD §3.1: "When a suspended plant's `compliance_score` reaches exactly
        0, a `ComplianceOfficer` may instead revoke the license".

        Design: Corner/state_machines/plant_terminal_revoked_no_transitions
        """
        plant = setup_plant()
        # Five CRITICAL findings (5 x 200) drive the score to exactly 0.
        drive_plant_score_to_zero(plant["id"])
        assert get_plant(plant["id"])["compliance_score"] == 0

        suspended = validate_success(api.suspend_plant(plant["id"], CO))
        assert suspended["status"] == "SUSPENDED"
        revoked = validate_success(api.revoke_plant(plant["id"], CO))
        assert revoked["status"] == "REVOKED"

        # Terminal: every further transition attempt is an invalid from-state.
        resp = api.suspend_plant(plant["id"], CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        resp = api.reinstate_plant(plant["id"], CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cascading_side_effects_plant_revoke(self, api):
        """PRD §3.1: "`REVOKED` is terminal, and the cascade is severe: every
        cylinder moves to `DECOMMISSIONED` and every charge not already in a
        terminal state is moved to `SCRAPPED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_plant_revoke
        """
        shop = setup_shop()
        plant_id, cyl1_id = shop["plant"]["id"], shop["cylinder"]["id"]
        # Cylinder 2 stays IDLE; charge Q1 is driven to CYCLE_COMPLETE.
        cyl2 = setup_cylinder(plant_id, cylinder_code="CYL-2")
        q1, _cycle = setup_cycle_complete_charge(shop, volume_mbf=5.0)
        assert q1["status"] == "CYCLE_COMPLETE"

        # Drive the score to exactly 0, then suspend and revoke.
        drive_plant_score_to_zero(plant_id)
        validate_success(api.suspend_plant(plant_id, CO))
        validate_success(api.revoke_plant(plant_id, CO))

        assert get_cylinder(plant_id, cyl1_id)["status"] == "DECOMMISSIONED"
        assert get_cylinder(plant_id, cyl2["id"])["status"] == "DECOMMISSIONED"
        assert get_charge(plant_id, q1["id"])["status"] == "SCRAPPED"

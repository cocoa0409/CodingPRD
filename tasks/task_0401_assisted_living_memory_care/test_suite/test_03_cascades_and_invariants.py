"""Multi-resource cascades and conserved-quantity invariants: the discharge cascade
(resident -> unit -> facility occupancy), the incident-escalation cascade
(incident -> deficiency -> facility), the empty-bed-set occupancy edge, and the
bed-availability conservation across activate-then-cancel.

Citations are verbatim from PRD.md §3.1, §3.5, §3.6, §3.9, §3.10.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_facility, create_unit,
    setup_discharge_pending_resident, setup_incident_under_investigation,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["staff_headers"]


class TestFinalizeDischargeCascade:
    """A depth-3 chain: resident DISCHARGED -> unit OCCUPIED->CLEANING -> facility occupancy drops."""

    def test_discharge_drives_resident_unit_and_facility(self, api):
        """PRD §3.6: "On finalize the resident advances `DISCHARGE_PENDING → DISCHARGED`,
        `discharge_disposition` is set to the supplied disposition, the bound unit advances
        `OCCUPIED → CLEANING` with its `current_resident_id` cleared, the facility's
        `occupied_bed_count` and `occupancy_rate_bps` are recomputed, the resident's `ACTIVE`
        move-in agreement advances to `TERMINATED`, the resident's care plan is archived — an
        `ACTIVE` plan and a `DRAFT` plan alike advance to `ARCHIVED` — and the resident's
        `assigned_unit_id` is cleared."

        Design: Difficulty/transitive_cascade/finalize_discharge_cascade_resident_unit_facility_depth3
        """
        ctx = setup_discharge_pending_resident(
            care_point_rate_cents=2000, base_rent_cents=400000, move_in_date="2026-04-01",
        )
        validate_success(
            api.finalize_discharge(ctx["resident"]["id"], {"disposition": "TRANSFER_TO_SNF"}, REGISTRAR), 200,
        )
        res = validate_success(api.get_resident(ctx["resident"]["id"], STAFF), 200)
        assert res["status"] == "DISCHARGED"
        assert res["discharge_disposition"] == "TRANSFER_TO_SNF"
        assert res["assigned_unit_id"] is None

        unit = validate_success(api.get_unit(ctx["unit"]["id"], STAFF), 200)
        assert unit["status"] == "CLEANING"
        assert unit["current_resident_id"] is None

        fac = validate_success(api.get_facility(ctx["facility"]["id"], STAFF), 200)
        assert fac["occupied_bed_count"] == 0
        assert fac["occupancy_rate_bps"] == 0
        assert fac["bed_count"] == 1

    def test_occupancy_starts_full_before_discharge(self, api):
        """PRD §3.1: "A reserved unit advances `RESERVED → OCCUPIED` automatically when the
        resident is admitted, which prompts a recomputation of the facility's
        `occupied_bed_count` and `occupancy_rate_bps`."

        Design: Difficulty/transitive_cascade/finalize_discharge_cascade_resident_unit_facility_depth3
        """
        ctx = setup_discharge_pending_resident(
            care_point_rate_cents=2000, base_rent_cents=400000, move_in_date="2026-04-01",
        )
        # Before finalize-discharge, the single bed is occupied -> full occupancy.
        fac = validate_success(api.get_facility(ctx["facility"]["id"], STAFF), 200)
        assert fac["occupied_bed_count"] == 1
        assert fac["occupancy_rate_bps"] == 10000


class TestIncidentEscalationCascade:
    """Escalation spawns a CITED deficiency and raises the facility's open count."""

    def test_escalate_spawns_deficiency_and_raises_open_count(self, api):
        """PRD §3.9: "As its cascade, escalation creates a new survey deficiency on the
        resident's facility in `CITED` status with that scope/severity, sets the incident's
        `linked_deficiency_id` to the new deficiency's id, and recomputes the facility's
        `open_deficiency_count`."

        Design: Difficulty/transitive_cascade/incident_escalate_cascade_incident_deficiency_facility
        """
        ctx = setup_incident_under_investigation(severity="SEVERE", incident_type="FALL")
        escalated = validate_success(
            api.escalate_incident(
                ctx["incident"]["id"],
                {"scope_severity": "D_F_NO_HARM", "tag_code": "F-689", "cited_at": "2026-03-03T10:00:00Z"},
                COMPLIANCE,
            ), 200,
        )
        assert escalated["status"] == "ESCALATED"
        def_id = escalated["linked_deficiency_id"]
        assert def_id is not None

        deff = validate_success(api.get_deficiency(def_id, STAFF), 200)
        assert deff["status"] == "CITED"

        fac = validate_success(api.get_facility(ctx["facility"]["id"], STAFF), 200)
        assert fac["open_deficiency_count"] == 1

    def test_spawned_deficiency_poc_due_date_standard_window(self, api):
        """PRD §3.10: "when the scope/severity band is `J_L_IMMEDIATE_JEOPARDY` the window is
        two calendar days, and for every other band the window is ten calendar days; the
        `poc_due_date` is the calendar date of `cited_at` plus the selected number of days."

        Design: Difficulty/transitive_cascade/incident_escalate_cascade_incident_deficiency_facility
        """
        ctx = setup_incident_under_investigation(severity="SEVERE", incident_type="FALL")
        escalated = validate_success(
            api.escalate_incident(
                ctx["incident"]["id"],
                {"scope_severity": "D_F_NO_HARM", "tag_code": "F-689", "cited_at": "2026-03-03T10:00:00Z"},
                COMPLIANCE,
            ), 200,
        )
        deff = validate_success(api.get_deficiency(escalated["linked_deficiency_id"], STAFF), 200)
        # cited 2026-03-03 + 10 standard days = 2026-03-13.
        assert deff["poc_due_date"] == "2026-03-13"


class TestOccupancyEmptyBedSet:
    """The empty-collection edge returns zero, not a divide error."""

    def test_zero_beds_yields_zero_occupancy(self, api):
        """PRD §3.1: "when `bed_count` is zero the `occupancy_rate_bps` is exactly zero
        (the empty-facility case never raises a division error)"

        Design: Difficulty/boundary_precision_check/occupancy_rate_empty_bed_set_returns_zero
        """
        fac = create_facility(care_point_rate_cents=2000)
        unit = create_unit(fac["id"])
        # Retiring the only unit returns bed_count to 0.
        validate_success(api.retire_unit(fac["id"], unit["id"], REGISTRAR), 200)
        got = validate_success(api.get_facility(fac["id"], STAFF), 200)
        assert got["bed_count"] == 0
        assert got["occupied_bed_count"] == 0
        assert got["occupancy_rate_bps"] == 0

    def test_retire_recomputes_bed_count(self, api):
        """PRD §3.1: "Retiring a unit recomputes the facility's `bed_count` and
        `occupancy_rate_bps`."

        Design: Difficulty/boundary_precision_check/occupancy_rate_empty_bed_set_returns_zero
        """
        fac = create_facility(care_point_rate_cents=2000)
        unit = create_unit(fac["id"])
        before = validate_success(api.get_facility(fac["id"], STAFF), 200)
        assert before["bed_count"] == 1
        validate_success(api.retire_unit(fac["id"], unit["id"], REGISTRAR), 200)
        after = validate_success(api.get_facility(fac["id"], STAFF), 200)
        assert after["bed_count"] == 0

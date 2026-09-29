"""Herbicide permits: window capacity, activation windows and field application."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, approve_permit, assert_herbicide_permit, new_permit,
    read_permit, read_span, set_clock, setup_active_permit, setup_circuit,
    setup_in_progress_span, validate_error, validate_paginated, validate_success,
    make_crew_foreman_headers,
)

ARBORIST_A = TEST_USERS["arborist_headers"]
FORESTER = TEST_USERS["forester_headers"]


class TestPermitWindowCapacity:
    """Closed intervals, one chemical per overlap, at most two mutual overlaps."""

    @staticmethod
    def _circuit_with_two_approved_permits():
        world = setup_circuit(herbicide_allowed=True)
        circuit_id = world["circuit"]["id"]
        first = new_permit(circuit_id, chemical_code="GLYPHOSATE",
                           window_start="2026-08-05", window_end="2026-08-20")
        approve_permit(first["id"])
        second = new_permit(circuit_id, chemical_code="TRICLOPYR",
                            window_start="2026-08-15", window_end="2026-08-25")
        approve_permit(second["id"])
        world["permit_one"] = first
        world["permit_two"] = second
        return world

    def test_a_third_mutually_overlapping_window_is_rejected(self, api):
        """PRD §3.7: "Two conditions must both hold: the candidate's closed
        `[window_start, window_end]` interval must not intersect the closed interval of any
        counted permit carrying the same `chemical_code`, and approving the candidate must not
        produce a group of more than two permits whose closed windows all mutually intersect.
        Either violation is rejected with `ERR_PERMIT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/herbicide_permit_closed_interval_capacity_two_per_circuit
        """
        world = self._circuit_with_two_approved_permits()
        third = new_permit(world["circuit"]["id"], chemical_code="IMAZAPYR",
                           window_start="2026-08-18", window_end="2026-08-19")

        resp = api.decide_herbicide_permit(third["id"], {"outcome": "APPROVE"}, FORESTER)

        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT.value)
        assert resp.status_code == 409
        assert read_permit(third["id"])["status"] == "REQUESTED"
        assert read_permit(world["permit_one"]["id"])["status"] == "APPROVED"
        assert read_permit(world["permit_two"]["id"])["status"] == "APPROVED"

    def test_same_chemical_sharing_one_endpoint_conflicts_while_a_pairwise_overlap_passes(self, api):
        """PRD §3.7: "Because the intervals are closed, two windows that merely share an
        endpoint date do intersect."
        PRD §3.7: "Second comes window capacity on that circuit, counting only the circuit's
        other permits whose `status` is `APPROVED` or `ACTIVE` — permits in `REQUESTED`,
        `DENIED`, `REVOKED` or `EXPIRED` are invisible to this count."

        Design: Difficulty/resource_temporal_overlap/herbicide_permit_closed_interval_capacity_two_per_circuit
        """
        world = self._circuit_with_two_approved_permits()
        circuit_id = world["circuit"]["id"]
        same_chemical = new_permit(circuit_id, chemical_code="GLYPHOSATE",
                                   window_start="2026-08-20", window_end="2026-08-22")
        disjoint_from_first = new_permit(circuit_id, chemical_code="AMINOPYRALID",
                                         window_start="2026-08-21", window_end="2026-08-22")

        clash = api.decide_herbicide_permit(
            same_chemical["id"], {"outcome": "APPROVE"}, FORESTER)
        validate_error(clash, ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT.value)
        assert read_permit(same_chemical["id"])["status"] == "REQUESTED"

        allowed = validate_success(api.decide_herbicide_permit(
            disjoint_from_first["id"], {"outcome": "APPROVE"}, FORESTER), 200)

        assert_herbicide_permit(allowed)
        assert allowed["status"] == "APPROVED", \
            "it overlaps only one counted permit, so no group of three forms"

    def test_approval_on_a_no_chemical_prescription_is_rejected(self, api):
        """PRD §3.7: "First, the prescription currently resolved onto the permit's circuit must
        have `herbicide_allowed` true; a circuit governed by a no-chemical prescription is
        rejected with `ERR_HERBICIDE_NOT_PRESCRIBED` (HTTP 422)."

        Design: Corner/validations/corner_permit_approval_on_non_herbicide_prescription_is_rejected
        """
        world = setup_circuit(herbicide_allowed=False)
        permit = new_permit(world["circuit"]["id"], chemical_code="GLYPHOSATE",
                            window_start="2026-08-01", window_end="2026-08-31")

        resp = api.decide_herbicide_permit(permit["id"], {"outcome": "APPROVE"}, FORESTER)

        validate_error(resp, ApiErrorId.ERR_HERBICIDE_NOT_PRESCRIBED.value)
        assert resp.status_code == 422
        assert read_permit(permit["id"])["status"] == "REQUESTED"
        assert world["prescription"]["herbicide_allowed"] is False

    def test_activation_outside_the_closed_window_is_rejected(self, api):
        """PRD §3.7: "A `CertifiedArborist` activates an approved permit, moving it
        `APPROVED → ACTIVE`, and activation is allowed only while the logical clock's date lies
        inside the closed `[window_start, window_end]` interval — on the first day and on the
        last day included. Activating too early or too late is rejected with
        `ERR_PERMIT_WINDOW_NOT_OPEN` (HTTP 422)."

        Design: Corner/state_machines/corner_permit_activate_outside_window_returns_window_not_open
        """
        world = setup_circuit()
        permit = new_permit(world["circuit"]["id"], chemical_code="GLYPHOSATE",
                            window_start="2026-08-01", window_end="2026-08-31")
        approve_permit(permit["id"])
        set_clock("2026-09-05T00:00:00Z")

        resp = api.activate_herbicide_permit(permit["id"], ARBORIST_A)

        validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_NOT_OPEN.value)
        assert resp.status_code == 422
        assert read_permit(permit["id"])["status"] == "APPROVED"


class TestHerbicideFieldApplication:
    """Permit-active, then window date, then buffer, then crew capability."""

    def test_a_revoked_permit_is_reported_before_the_crew_type_problem(self, api):
        """PRD §3.4: "Herbicide entries face additional gates described in §3.7; of the two
        crew-side checks, note that the permit checks are evaluated before the crew-capability
        check, so an entry filed by a `BUCKET` crew against a permit that is not `ACTIVE`
        reports the permit problem rather than the crew-type problem."
        PRD §3.7: "The named `herbicide_permit_id` must resolve to a permit whose `status` is
        `ACTIVE`; anything else — still merely `APPROVED`, already `EXPIRED`, `REVOKED`,
        `DENIED` or `REQUESTED` — is rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_active_precedes_crew_type_mismatch_on_herbicide_entry
        """
        world = setup_in_progress_span(crew_code="CRW-BUCKET", crew_type="BUCKET",
                                       herbicide_allowed=True)
        permit = new_permit(world["circuit"]["id"], chemical_code="GLYPHOSATE",
                            buffer_ft=25, window_start="2026-08-01", window_end="2026-08-31")
        approve_permit(permit["id"])
        validate_success(api.revoke_herbicide_permit(
            permit["id"], FORESTER, {"reason": "label restriction"}), 200)

        resp = api.create_production_entry({
            "crew_assignment_id": world["booking"]["id"], "work_date": "2026-08-03",
            "units_trimmed": 0, "labor_hours": 4, "equipment_hours": 2,
            "gallons_applied": 5, "herbicide_permit_id": permit["id"]},
            make_crew_foreman_headers(world["crew"]["id"]))

        error = validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value)
        assert resp.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_CREW_TYPE_MISMATCH.value
        assert read_span(world["span"]["id"])["actual_units_completed"] == 0
        assert read_permit(permit["id"])["status"] == "REVOKED"

    def test_an_active_permit_lets_the_crew_type_check_surface(self, api):
        """PRD §3.7: "And the filing crew's `crew_type` must be `HERBICIDE`; a `BUCKET`,
        `CLIMBING`, `MANUAL` or `STORM` crew reporting gallons is rejected with
        `ERR_CREW_TYPE_MISMATCH` (HTTP 422)."
        PRD §3.7: "Field application is where the permit does its real work. Whenever a
        production entry reports `gallons_applied` greater than zero, four checks run against
        it, in this order."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_active_precedes_crew_type_mismatch_on_herbicide_entry
        """
        world = setup_in_progress_span(crew_code="CRW-BUCKET", crew_type="BUCKET",
                                       herbicide_allowed=True)
        permit = setup_active_permit(world["circuit"]["id"], chemical_code="GLYPHOSATE",
                                     window_start="2026-08-01", window_end="2026-08-31")
        assert permit["status"] == "ACTIVE"

        resp = api.create_production_entry({
            "crew_assignment_id": world["booking"]["id"], "work_date": "2026-08-03",
            "units_trimmed": 0, "labor_hours": 4, "equipment_hours": 2,
            "gallons_applied": 5, "herbicide_permit_id": permit["id"]},
            make_crew_foreman_headers(world["crew"]["id"]))

        validate_error(resp, ApiErrorId.ERR_CREW_TYPE_MISMATCH.value)
        assert resp.status_code == 422
        assert read_span(world["span"]["id"])["actual_units_completed"] == 0

    def test_application_dated_outside_the_permit_window_is_rejected(self, api):
        """PRD §3.7: "The entry's `work_date` must lie inside that permit's closed
        `[window_start, window_end]` interval, endpoints included; outside it the entry is
        rejected with `ERR_APPLICATION_OUTSIDE_PERMIT_WINDOW` (HTTP 422)."
        PRD §3.7: "That window is a **closed** interval: both the start date and the end date
        are themselves inside the window."

        Design: Corner/errors/corner_herbicide_application_outside_permit_window_is_rejected
        """
        world = setup_in_progress_span(
            crew_type="HERBICIDE", headcount=2, hourly_rate_cents=7000,
            herbicide_allowed=True, start_at="2026-08-30T06:00:00Z",
            end_at="2026-09-03T20:00:00Z")
        permit = setup_active_permit(world["circuit"]["id"], chemical_code="GLYPHOSATE",
                                     window_start="2026-08-01", window_end="2026-08-31")
        foreman = make_crew_foreman_headers(world["crew"]["id"])

        late = api.create_production_entry({
            "crew_assignment_id": world["booking"]["id"], "work_date": "2026-09-02",
            "units_trimmed": 0, "labor_hours": 4, "equipment_hours": 2,
            "gallons_applied": 5, "herbicide_permit_id": permit["id"]}, foreman)
        validate_error(late, ApiErrorId.ERR_APPLICATION_OUTSIDE_PERMIT_WINDOW.value)
        assert late.status_code == 422

        on_last_day = api.create_production_entry({
            "crew_assignment_id": world["booking"]["id"], "work_date": "2026-08-31",
            "units_trimmed": 0, "labor_hours": 4, "equipment_hours": 2,
            "gallons_applied": 5, "herbicide_permit_id": permit["id"]}, foreman)
        entry = validate_success(on_last_day, 201)

        assert entry["gallons_applied"] == pytest.approx(5, abs=0.001)
        assert read_permit(permit["id"])["status"] == "ACTIVE"
        _, meta = validate_paginated(api.list_production_entries(
            FORESTER, params={"herbicide_permit_id": permit["id"]}))
        assert meta["total_count"] == 1

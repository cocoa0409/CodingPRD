"""Resource temporal overlap semantics: chair slots are half-open intervals;
machine maintenance windows are closed intervals."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_program, create_machine, create_active_home_patient, create_chair,
    create_slot, api_client, make_admin_headers, make_patient_headers,
    make_biomed_headers, create_maintenance_event_payload,
)


class TestChairHalfOpenOverlapAdjacencyAllowed:
    """Half-open [slot_start, slot_end): touching endpoints are adjacency."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        chair = create_chair(ctx["program"]["id"], chair_code="CH-1")
        slot1 = create_slot(pat, chair["id"], "2026-05-10T10:00:00Z",
                            "2026-05-10T12:00:00Z")
        return pat, chair, slot1

    def test_strict_intersection_rejected(self, api):
        """PRD §3.7: "and the new slot must not collide — chair slots are
        **half-open intervals**, so a reservation starting exactly when another
        ends is adjacency, not conflict, while a genuine intersection with
        another `RESERVED` reservation on the same chair is
        `ERR_CHAIR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/chair_half_open_overlap_adjacency_allowed
        """
        pat, chair, slot1 = self._setup(api)
        resp = api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-05-10T11:00:00Z",
             "slot_end": "2026-05-10T13:00:00Z"},
            make_patient_headers(pat))
        validate_error(resp, ApiErrorId.ERR_CHAIR_SLOT_OVERLAP)
        # The rejected attempt leaves the original reservation untouched.
        slots = get_success_data(api.list_chair_slot_reservations(
            chair["id"], make_admin_headers("admin-1")))
        assert len(slots) == 1
        assert slots[0]["status"] == "RESERVED"

    def test_adjacent_slot_allowed(self, api):
        """PRD §3.7: "and the new slot must not collide — chair slots are
        **half-open intervals**, so a reservation starting exactly when another
        ends is adjacency, not conflict, while a genuine intersection with
        another `RESERVED` reservation on the same chair is
        `ERR_CHAIR_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/chair_half_open_overlap_adjacency_allowed
        """
        pat, chair, slot1 = self._setup(api)
        slot2 = validate_success(api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-05-10T12:00:00Z",
             "slot_end": "2026-05-10T14:00:00Z"},
            make_patient_headers(pat)), 201)
        assert slot2["status"] == "RESERVED", (
            "[12:00,14:00) shares only the endpoint 12:00 — adjacency, not conflict")


class TestMachineClosedIntervalTouchingConflicts:
    """Closed [window_start, window_end]: endpoint contact counts as conflict."""

    def test_touching_windows_conflict(self, api):
        """PRD §3.4: "Maintenance windows on a machine are **closed
        intervals**: a new event whose window touches or overlaps another
        `SCHEDULED` or `IN_PROGRESS` event on the same machine — endpoint
        contact counts as conflict here — is rejected with
        `ERR_EVENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/machine_closed_interval_touching_conflicts
        """
        program = create_program()
        mach = create_machine(program["id"])
        validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                mach["id"], window_start="2026-05-10T09:00:00Z",
                window_end="2026-05-10T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        resp = api.create_maintenance_event(
            create_maintenance_event_payload(
                mach["id"], event_type="REPAIR",
                window_start="2026-05-10T12:00:00Z",
                window_end="2026-05-10T15:00:00Z"),
            make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)

    def test_disjoint_window_accepted_and_rejected_event_not_persisted(self, api):
        """PRD §3.4: "Maintenance windows on a machine are **closed
        intervals**: a new event whose window touches or overlaps another
        `SCHEDULED` or `IN_PROGRESS` event on the same machine — endpoint
        contact counts as conflict here — is rejected with
        `ERR_EVENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/machine_closed_interval_touching_conflicts
        """
        program = create_program()
        mach = create_machine(program["id"])
        validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                mach["id"], window_start="2026-05-10T09:00:00Z",
                window_end="2026-05-10T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        resp = api.create_maintenance_event(
            create_maintenance_event_payload(
                mach["id"], event_type="REPAIR",
                window_start="2026-05-10T12:00:00Z",
                window_end="2026-05-10T15:00:00Z"),
            make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP)
        nxt = validate_success(api.create_maintenance_event(
            create_maintenance_event_payload(
                mach["id"], event_type="DECONTAMINATION",
                window_start="2026-05-11T09:00:00Z",
                window_end="2026-05-11T12:00:00Z"),
            make_biomed_headers("biomed-1")), 201)
        assert nxt["status"] == "SCHEDULED"
        events = get_success_data(api.list_machine_events(
            mach["id"], make_admin_headers("admin-1")))
        assert len(events) == 2, "the rejected event was not persisted"
        assert events[1]["id"] == nxt["id"]

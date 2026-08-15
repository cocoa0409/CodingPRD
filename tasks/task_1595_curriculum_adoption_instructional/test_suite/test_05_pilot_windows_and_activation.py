"""Pilot planning window conflicts (half-open semantics), activation timing,
and the close-pilots gate on unresolved pilots."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_pilot,
    get_material,
    get_pilot,
    set_clock,
    setup_active_pilot,
    setup_cycle_in_pilot_open,
    transition_cycle,
    transition_pilot,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["curriculum_director_headers"]


class TestPilotWindowConflicts:
    def test_pilot_window_adjacency_accepted_overlap_rejected(self, api):
        """PRD §3.3: "if the new pilot's window — occupying every date from
        `starts_on` up to but not including `ends_on` — overlaps the window of
        any `PLANNED` or `ACTIVE` pilot at the same `school_code` belonging to
        a cycle of the same `subject_area`, the request is rejected with
        `ERR_PILOT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/pilot_window_half_open_adjacency
        """
        ctx = setup_cycle_in_pilot_open()
        cycle_id, material_id = ctx["cycle"]["id"], ctx["material"]["id"]
        create_pilot(cycle_id, material_id, school_code="SCH-A",
                     starts_on="2026-08-10", ends_on="2026-08-20",
                     teacher_count=2)

        # Half-open adjacency: [2026-08-20, 2026-08-31) touches but does not
        # overlap [2026-08-10, 2026-08-20).
        resp = api.create_pilot(cycle_id, {
            "material_id": material_id, "school_code": "SCH-A",
            "starts_on": "2026-08-20", "ends_on": "2026-08-31",
            "teacher_count": 2}, DIRECTOR)
        validate_success(resp, expected_status=201)

        # Strict overlap with the adjacent pilot is rejected.
        validate_error(
            api.create_pilot(cycle_id, {
                "material_id": material_id, "school_code": "SCH-A",
                "starts_on": "2026-08-25", "ends_on": "2026-09-05",
                "teacher_count": 2}, DIRECTOR),
            ApiErrorId.ERR_PILOT_WINDOW_CONFLICT)

    def test_pilot_window_released_on_cancel_and_scoped_to_school(self, api):
        """PRD §3.3: "if the new pilot's window — occupying every date from
        `starts_on` up to but not including `ends_on` — overlaps the window of
        any `PLANNED` or `ACTIVE` pilot at the same `school_code` belonging to
        a cycle of the same `subject_area`, the request is rejected with
        `ERR_PILOT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/pilot_window_half_open_adjacency
        """
        ctx = setup_cycle_in_pilot_open()
        cycle_id, material_id = ctx["cycle"]["id"], ctx["material"]["id"]
        blocker = create_pilot(cycle_id, material_id, school_code="SCH-A",
                               starts_on="2026-08-20", ends_on="2026-08-31",
                               teacher_count=2)

        # Overlaps the PLANNED blocker.
        validate_error(
            api.create_pilot(cycle_id, {
                "material_id": material_id, "school_code": "SCH-A",
                "starts_on": "2026-08-25", "ends_on": "2026-09-05",
                "teacher_count": 2}, DIRECTOR),
            ApiErrorId.ERR_PILOT_WINDOW_CONFLICT)

        # A CANCELLED pilot is neither PLANNED nor ACTIVE: it releases the
        # window, so the identical request now succeeds.
        transition_pilot(blocker["id"], "CANCELLED")
        resp = api.create_pilot(cycle_id, {
            "material_id": material_id, "school_code": "SCH-A",
            "starts_on": "2026-08-25", "ends_on": "2026-09-05",
            "teacher_count": 2}, DIRECTOR)
        validate_success(resp, expected_status=201)

        # The resource is school-scoped: the same window at another school
        # coexists with the window above.
        resp = api.create_pilot(cycle_id, {
            "material_id": material_id, "school_code": "SCH-B",
            "starts_on": "2026-08-25", "ends_on": "2026-09-05",
            "teacher_count": 2}, DIRECTOR)
        validate_success(resp, expected_status=201)


class TestPilotActivationTiming:
    def test_pilot_activate_before_start_rejected(self, api):
        """PRD §3.3: "A `CurriculumDirector` moves a pilot from `PLANNED` to
        `ACTIVE` only while the pilot's cycle is `PILOT_OPEN`
        (`ERR_INVALID_STATE` otherwise) and only once the logical clock's date
        has reached `starts_on`; an early activation is rejected with
        `ERR_PILOT_NOT_STARTED`."
        PRD §3.3: "if the piloted material is still `VETTED`, it becomes a
        `PILOT_CANDIDATE` automatically."

        Design: Corner/state_machines/pilot_activate_before_start_rejected
        """
        # Default logical clock is 2026-08-01; the pilot starts 2026-08-10.
        ctx = setup_cycle_in_pilot_open()
        pilot = create_pilot(ctx["cycle"]["id"], ctx["material"]["id"],
                             school_code="SCH-A", starts_on="2026-08-10",
                             ends_on="2026-08-20", teacher_count=2)

        validate_error(api.transition_pilot(pilot["id"], {"to_state": "ACTIVE"},
                                            DIRECTOR),
                       ApiErrorId.ERR_PILOT_NOT_STARTED)

        # Exactly on starts_on the activation succeeds (inclusive boundary).
        set_clock("2026-08-10T00:00:00Z")
        updated = transition_pilot(pilot["id"], "ACTIVE")
        assert updated["status"] == "ACTIVE"
        assert get_material(ctx["material"]["id"])["adoption_status"] == \
            "PILOT_CANDIDATE"


class TestClosePilotsGate:
    def test_close_pilots_blocked_by_active_pilot(self, api):
        """PRD §3.3: "The move requires that every pilot of the cycle has
        reached `CLOSED` or `CANCELLED`; a lingering `PLANNED` or `ACTIVE`
        pilot blocks it with `ERR_UNRESOLVED_PILOTS`."

        Design: Difficulty/cross_entity_state_dependency/close_pilots_requires_all_pilots_closed
        """
        ctx = setup_active_pilot(reviews=((4, 4, 4, 4),))
        validate_error(api.transition_cycle(ctx["cycle"]["id"],
                                            {"to_state": "SCORING"}, DIRECTOR),
                       ApiErrorId.ERR_UNRESOLVED_PILOTS)
        transition_pilot(ctx["pilot"]["id"], "CLOSED")
        updated = transition_cycle(ctx["cycle"]["id"], "SCORING")
        assert updated["status"] == "SCORING"

    def test_close_pilots_blocked_by_planned_pilot_then_cancelled(self, api):
        """PRD §3.3: "The move requires that every pilot of the cycle has
        reached `CLOSED` or `CANCELLED`; a lingering `PLANNED` or `ACTIVE`
        pilot blocks it with `ERR_UNRESOLVED_PILOTS`."
        PRD §3.3: "A pilot that will never run can be cancelled while
        `PLANNED`, moving to `CANCELLED`"

        Design: Difficulty/cross_entity_state_dependency/close_pilots_requires_all_pilots_closed
        """
        ctx = setup_cycle_in_pilot_open()
        pilot = create_pilot(ctx["cycle"]["id"], ctx["material"]["id"],
                             school_code="SCH-A", teacher_count=1)
        assert get_pilot(pilot["id"])["status"] == "PLANNED"
        validate_error(api.transition_cycle(ctx["cycle"]["id"],
                                            {"to_state": "SCORING"}, DIRECTOR),
                       ApiErrorId.ERR_UNRESOLVED_PILOTS)
        transition_pilot(pilot["id"], "CANCELLED")
        updated = transition_cycle(ctx["cycle"]["id"], "SCORING")
        assert updated["status"] == "SCORING"

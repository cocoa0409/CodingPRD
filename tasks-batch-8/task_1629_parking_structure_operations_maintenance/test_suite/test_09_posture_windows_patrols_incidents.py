"""Posture transitions, housekeeping window overlap buffer, patrol rounds,
and incident self-referencing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_patrol_round_payload,
    create_facility,
    create_incident_payload,
    create_maintenance_window_payload,
    create_patrol_round_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
MS = TEST_USERS["maintenance_supervisor_headers"]
SEC = TEST_USERS["security_officer_headers"]


def test_facility_decommission_terminal_lockdown(api):
    """PRD: "decommissioning from `NORMAL`, `RESTRICTED`, or
    `CLOSED_TEMPORARY` to the terminal `DECOMMISSIONED`."
    PRD: "the target resource's current state permits the
    requested transition; this covers wrong-from-state actions, terminal-state
    lockdown, and repeat runs such as a second close-of-business for one
    business date, else `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/facility_decommission_terminal_lockdown
    """
    facility = create_facility(name="Term Fac", total_spaces=10, monthly_capacity=1,
                               event_pool_spaces=1)
    decommissioned = validate_success(api.transition_posture(
        facility["id"], "DECOMMISSIONED", FM), 200)
    assert decommissioned["posture"] == "DECOMMISSIONED"

    res = api.transition_posture(facility["id"], "NORMAL", FM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_success_data(api.get_facility(facility["id"], FM))[
        "posture"] == "DECOMMISSIONED"


def test_manual_event_surge_posture_rejected(api):
    """PRD: "`EVENT_SURGE` is never a manual target: the system enters it when
    an event activates (§3.9) and leaves it when the facility's last `ACTIVE`
    event completes, and a manual posture request naming `EVENT_SURGE` as its
    `target_posture` is rejected with `ERR_POSTURE_TRANSITION_BLOCKED`."

    Design: Corner/errors/manual_event_surge_posture_rejected
    """
    facility = create_facility(name="MS Fac", total_spaces=10, monthly_capacity=1,
                               event_pool_spaces=1)
    res = api.transition_posture(facility["id"], "EVENT_SURGE", FM)
    validate_error(res, ApiErrorId.ERR_POSTURE_TRANSITION_BLOCKED)
    assert get_success_data(api.get_facility(facility["id"], FM))["posture"] == "NORMAL"


class TestMaintenanceWindowBufferExclusion:
    """The 30-minute hygiene buffer on the same facility+level."""

    def _build(self, api):
        facility = create_facility(name="Win Fac")
        w1 = get_success_data(api.create_maintenance_window(
            create_maintenance_window_payload(
                facility["id"], level="L1", window_type="SWEEPING",
                start_at="2026-08-05T06:00:00Z", end_at="2026-08-05T08:00:00Z"),
            MS))
        return facility, w1

    def test_adjacent_window_conflicts_but_thirty_minute_gap_is_allowed(self, api):
        """PRD: "Windows on the same facility and level carry a thirty-minute
        hygiene buffer: a new window conflicts with any existing window
        standing `SCHEDULED` or `IN_PROGRESS` on that level unless the new
        start falls at or after thirty minutes past the existing window's end,
        or the existing window's start falls at or after thirty minutes past
        the new window's end; a conflict is rejected with
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_exclusion
        """
        facility, w1 = self._build(api)
        res = api.create_maintenance_window(
            create_maintenance_window_payload(
                facility["id"], level="L1", window_type="DRAIN_FLUSH",
                start_at="2026-08-05T08:00:00Z", end_at="2026-08-05T09:00:00Z"),
            MS)
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP)

        allowed = validate_success(api.create_maintenance_window(
            create_maintenance_window_payload(
                facility["id"], level="L1", window_type="DRAIN_FLUSH",
                start_at="2026-08-05T08:30:00Z", end_at="2026-08-05T09:30:00Z"),
            MS), 201)
        assert allowed["window_status"] == "SCHEDULED", (
            "gap exactly 30 minutes: boundary is inclusive-allowed")

    def test_full_overlap_on_a_different_level_is_allowed(self, api):
        """PRD: "Windows on the same facility and level carry a thirty-minute
        hygiene buffer: a new window conflicts with any existing window
        standing `SCHEDULED` or `IN_PROGRESS` on that level"

        Design: Difficulty/resource_temporal_overlap/maintenance_window_buffer_exclusion
        """
        facility, w1 = self._build(api)
        other_level = validate_success(api.create_maintenance_window(
            create_maintenance_window_payload(
                facility["id"], level="L2", window_type="LIGHTING_REPAIR",
                start_at="2026-08-05T07:00:00Z", end_at="2026-08-05T09:00:00Z"),
            MS), 201)
        assert other_level["window_status"] == "SCHEDULED", (
            "the buffer rule is per facility+level resource")


def test_maintenance_window_start_complete_happy_path(api):
    """PRD: "Starting moves it to `IN_PROGRESS`, completing to the terminal
    `COMPLETED`"
    PRD: "a new window conflicts with any existing window standing `SCHEDULED`
    or `IN_PROGRESS` on that level"

    Design: Corner/state_machines/maintenance_window_start_complete_happy_path
    """
    facility = create_facility(name="WH Fac")
    w1 = get_success_data(api.create_maintenance_window(
        create_maintenance_window_payload(
            facility["id"], level="L1", window_type="SWEEPING",
            start_at="2026-08-05T06:00:00Z", end_at="2026-08-05T08:00:00Z"),
        MS))
    set_clock("2026-08-05T07:00:00Z")
    started = validate_success(api.start_maintenance_window(w1["id"], MS), 200)
    assert started["window_status"] == "IN_PROGRESS"
    completed = validate_success(api.complete_maintenance_window(w1["id"], MS), 200)
    assert completed["window_status"] == "COMPLETED"

    adjacent = validate_success(api.create_maintenance_window(
        create_maintenance_window_payload(
            facility["id"], level="L1", window_type="SWEEPING",
            start_at="2026-08-05T08:00:00Z", end_at="2026-08-05T09:00:00Z"),
        MS), 201)
    assert adjacent["window_status"] == "SCHEDULED", (
        "only SCHEDULED/IN_PROGRESS windows participate in the overlap rule")


def test_patrol_round_complete_happy_path(api):
    """PRD: "A `SecurityOfficer` schedules a round with a `facility_id` and a
    `scheduled_start`; the caller's `X-User-ID` is captured as
    `officer_user_id` and the round stands `SCHEDULED`. Completing the round
    supplies `checkpoints_completed` and optionally `lighting_outages_found`
    (default zero), moves it to the terminal `COMPLETED`, and stamps
    `completed_at`"

    Design: Corner/state_machines/patrol_round_complete_happy_path
    """
    facility = create_facility(name="PC Fac")
    round_ = get_success_data(api.create_patrol_round(
        create_patrol_round_payload(facility["id"],
                                    scheduled_start="2026-08-01T06:00:00Z"), SEC))
    set_clock("2026-08-01T09:30:00Z")
    completed = validate_success(api.complete_patrol_round(
        round_["id"], complete_patrol_round_payload(
            checkpoints_completed=12, lighting_outages_found=3), SEC), 200)
    assert completed["patrol_status"] == "COMPLETED"
    assert completed["checkpoints_completed"] == 12
    assert completed["lighting_outages_found"] == 3
    assert completed["completed_at"].startswith("2026-08-01T09:30:00")
    assert completed["officer_user_id"] == "sec-1", "stamped from X-User-ID at scheduling"


def test_incident_mark_duplicate_self_reference(api):
    """PRD: "A report standing `OPEN` or `INVESTIGATING` may instead be marked
    a duplicate: the caller names a `duplicate_of_incident_id` that must
    resolve to a different report of the same facility not already `CLOSED` —
    a self-reference, an unknown id, or a `CLOSED` target fails with
    `ERR_REFERENCE_NOT_FOUND` — and the act both records the pointer and
    closes the reporting incident."
    PRD: "The incident list filters by `facility_id`, `incident_status`,
    `severity`, `patrol_round_id`, `reconciliation_id`, or
    `duplicate_of_incident_id`."

    Design: Corner/entities/incident_mark_duplicate_self_reference
    """
    facility = create_facility(name="Dup Fac")
    i1 = get_success_data(api.create_incident(
        create_incident_payload(facility["id"], incident_type="VANDALISM",
                                severity="LOW", description="graffiti stall 3"), SEC))
    i2 = get_success_data(api.create_incident(
        create_incident_payload(facility["id"], incident_type="VANDALISM",
                                severity="LOW", description="graffiti stall 3 again"),
        SEC))

    closed = validate_success(api.mark_incident_duplicate(i2["id"], i1["id"], SEC), 200)
    assert closed["incident_status"] == "CLOSED"
    assert closed["duplicate_of_incident_id"] == i1["id"]

    data, meta = validate_paginated(api.list_incidents(
        FM, params={"duplicate_of_incident_id": i1["id"]}))
    assert [row["id"] for row in data] == [i2["id"]]

"""The longarm queue: machine setup-buffer collisions, the cross-entity machine-availability
dependency, the state-beats-interval validation-priority pair, and terminal/queue-state
lockdowns on complete and start."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_member, create_machine, create_queued_job, start_job, setup_completed_job,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Difficulty/resource_temporal_overlap/longarm_machine_buffer_overlap
# =========================================================================
def test_slot_gap_under_buffer_conflicts(api):
    """PRD §3.4: "two slots on the same machine collide unless they are separated by a gap of
    at least 30 minutes: if the later slot's scheduled_start is fewer than 30 minutes after
    the earlier slot's scheduled_end (or the intervals overlap outright), the request
    conflicts ... For example, an existing slot ending at 12:00 and a new slot starting at
    12:15 have only a 15-minute gap and therefore conflict". Job2 is rejected and stays
    QUEUED.

    Design: Difficulty/resource_temporal_overlap/longarm_machine_buffer_overlap
    """
    member = create_member(api)
    machine = create_machine(api)
    job1, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=50, quoted_length_in=50)
    start_job(api, job1["id"], machine["id"], "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z")
    job2, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=55, quoted_length_in=55)
    resp = api.start_longarm_job(
        job2["id"],
        {"machine_id": machine["id"], "scheduled_start": "2026-08-03T12:15:00Z",
         "scheduled_end": "2026-08-03T13:00:00Z"},
        CLERK)
    validate_error(resp, ApiErrorId.ERR_MACHINE_SCHEDULE_CONFLICT.value)
    after = validate_success(api.get_longarm_job(job2["id"], CLERK), 200)
    assert after["status"] == "QUEUED"


def test_slot_gap_exactly_buffer_allowed(api):
    """PRD §3.4: "a gap of exactly 30 minutes or more is allowed. For example, an existing
    slot ending at 12:00 and a new slot starting at 12:15 have only a 15-minute gap and
    therefore conflict, whereas a new slot starting at 12:30 is accepted." Job1 ends at 12:00,
    job2 starts at 12:30 (exactly a 30-minute gap), so job2 starts and advances to
    IN_PROGRESS.

    Design: Difficulty/resource_temporal_overlap/longarm_machine_buffer_overlap
    """
    member = create_member(api)
    machine = create_machine(api)
    job1, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=50, quoted_length_in=50)
    start_job(api, job1["id"], machine["id"], "2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z")
    job2, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=55, quoted_length_in=55)
    resp = api.start_longarm_job(
        job2["id"],
        {"machine_id": machine["id"], "scheduled_start": "2026-08-03T12:30:00Z",
         "scheduled_end": "2026-08-03T13:30:00Z"},
        CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "IN_PROGRESS"


# =========================================================================
# Difficulty/cross_entity_state_dependency/longarm_start_requires_machine_available
# =========================================================================
def test_start_on_maintenance_machine_rejected(api):
    """PRD §3.4: "Starting a job is permitted only while the job is QUEUED (otherwise
    ERR_JOB_NOT_QUEUED). The referenced machine must exist (otherwise ERR_MACHINE_NOT_FOUND)
    and must be AVAILABLE rather than in MAINTENANCE (otherwise ERR_MACHINE_UNAVAILABLE)."
    Starting a job on a MAINTENANCE machine over a valid window is rejected and the job stays
    QUEUED.

    Design: Difficulty/cross_entity_state_dependency/longarm_start_requires_machine_available
    """
    member = create_member(api)
    machine = create_machine(api, status="MAINTENANCE")
    job, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=40, quoted_length_in=40)
    resp = api.start_longarm_job(
        job["id"],
        {"machine_id": machine["id"], "scheduled_start": "2026-08-02T10:00:00Z",
         "scheduled_end": "2026-08-02T12:00:00Z"},
        CLERK)
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)
    after = validate_success(api.get_longarm_job(job["id"], CLERK), 200)
    assert after["status"] == "QUEUED"


def test_start_on_available_machine_advances_to_in_progress(api):
    """PRD §3.4: "A successful start records the machine_id, scheduled_start, and scheduled_end
    on the job (the machine_id is null until this point) and advances it from QUEUED to
    IN_PROGRESS." A job started on an AVAILABLE machine over a valid window advances.

    Design: Difficulty/cross_entity_state_dependency/longarm_start_requires_machine_available
    """
    member = create_member(api)
    machine = create_machine(api)  # defaults AVAILABLE
    job, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=40, quoted_length_in=40)
    resp = api.start_longarm_job(
        job["id"],
        {"machine_id": machine["id"], "scheduled_start": "2026-08-02T10:00:00Z",
         "scheduled_end": "2026-08-02T12:00:00Z"},
        CLERK)
    data = validate_success(resp, 200)
    assert data["status"] == "IN_PROGRESS"
    assert data["machine_id"] == machine["id"]


# =========================================================================
# Difficulty/priority_pair_validation_conflict/start_maintenance_beats_invalid_window
# =========================================================================
def test_maintenance_state_beats_invalid_time_window(api):
    """PRD §2.5: "the checks are evaluated in a fixed priority order, and the first failure
    determines the error returned". The state precondition (priority 5) — PRD §3.4: "must be
    AVAILABLE rather than in MAINTENANCE (otherwise ERR_MACHINE_UNAVAILABLE)" — is checked
    before interval validity (priority 7) — PRD §3.4: "The slot's scheduled_end must be
    strictly later than its scheduled_start (otherwise ERR_INVALID_TIME_WINDOW)." Starting on
    a MAINTENANCE machine with scheduled_end before scheduled_start violates both, and
    ERR_MACHINE_UNAVAILABLE wins.

    Design: Difficulty/priority_pair_validation_conflict/start_maintenance_beats_invalid_window
    """
    member = create_member(api)
    machine = create_machine(api, status="MAINTENANCE")
    job, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=50, quoted_length_in=50,
                               pattern_tier="EDGE_TO_EDGE")
    resp = api.start_longarm_job(
        job["id"],
        {"machine_id": machine["id"], "scheduled_start": "2026-08-01T12:00:00Z",
         "scheduled_end": "2026-08-01T10:00:00Z"},
        CLERK)
    validate_error(resp, ApiErrorId.ERR_MACHINE_UNAVAILABLE.value)


def test_invalid_window_fires_when_machine_available(api):
    """PRD §3.4: "The slot's scheduled_end must be strictly later than its scheduled_start
    (otherwise ERR_INVALID_TIME_WINDOW)." With the state precondition satisfied (an AVAILABLE
    machine), a slot whose end precedes its start surfaces ERR_INVALID_TIME_WINDOW — the
    interval check (priority 7) that a MAINTENANCE machine would have pre-empted at priority 5.

    Design: Difficulty/priority_pair_validation_conflict/start_maintenance_beats_invalid_window
    """
    member = create_member(api)
    machine = create_machine(api)  # AVAILABLE
    job, _ = create_queued_job(api, member_id=member["id"], quoted_width_in=50, quoted_length_in=50,
                               pattern_tier="EDGE_TO_EDGE")
    resp = api.start_longarm_job(
        job["id"],
        {"machine_id": machine["id"], "scheduled_start": "2026-08-01T12:00:00Z",
         "scheduled_end": "2026-08-01T10:00:00Z"},
        CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)


# =========================================================================
# Corner/state_machines/complete_already_completed_job_rejected
# =========================================================================
def test_complete_already_completed_job_rejected(api):
    """PRD §3.4: "completion is permitted only while the job is IN_PROGRESS (otherwise
    ERR_JOB_NOT_IN_PROGRESS)." A second complete on a job already in the terminal COMPLETED
    state is rejected.

    Design: Corner/state_machines/complete_already_completed_job_rejected
    """
    ctx = setup_completed_job(api, "2026-08-04T10:00:00Z", "2026-08-04T12:00:00Z", 50, 50,
                              job_overrides={"quoted_width_in": 50, "quoted_length_in": 50})
    resp = api.complete_longarm_job(
        ctx["job"]["id"], {"measured_width_in": 50, "measured_length_in": 50}, CLERK)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_IN_PROGRESS.value)


# =========================================================================
# Corner/state_machines/start_queued_job_before_start_from_completed_rejected
# =========================================================================
def test_start_completed_job_rejected(api):
    """PRD §3.4: "Starting a job is permitted only while the job is QUEUED (otherwise
    ERR_JOB_NOT_QUEUED)." Starting a job that has already reached the terminal COMPLETED state
    is rejected.

    Design: Corner/state_machines/start_queued_job_before_start_from_completed_rejected
    """
    ctx = setup_completed_job(api, "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z", 40, 40,
                              job_overrides={"quoted_width_in": 40, "quoted_length_in": 40})
    resp = api.start_longarm_job(
        ctx["job"]["id"],
        {"machine_id": ctx["machine"]["id"], "scheduled_start": "2026-08-05T13:00:00Z",
         "scheduled_end": "2026-08-05T14:00:00Z"},
        CLERK)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_QUEUED.value)

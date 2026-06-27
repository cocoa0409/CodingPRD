"""Assignment-creation business rules and temporal conflicts: role/kind,
inactive resource, duplicate role, interpreter language, realtime capability,
half-open overlap, the 30-minute reporter travel buffer, and the time-window
validation on job notice.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    make_attorney,
    make_case,
    make_reporter,
    make_videographer,
    make_interpreter,
    make_job,
    add_assignment,
    deactivate_resource,
    current_job_version,
    make_schedule_coordinator_headers,
    create_job_payload,
)

COORD = make_schedule_coordinator_headers()


def test_role_kind_mismatch_rejected(api):
    """PRD §3.2: "First, the assignment `role` must equal the referenced
    resource's `kind`; a mismatch is `ERR_ROLE_KIND_MISMATCH`." Assigning a
    VIDEOGRAPHER resource with role=REPORTER on a NOTICED job is rejected.

    Design: Corner/errors/error_role_kind_mismatch_triggerable
    """
    att = make_attorney()
    case = make_case(att["id"])
    vid = make_videographer()
    job = make_job(case["id"], scheduled_start="2026-07-29T09:00:00Z",
                   scheduled_end="2026-07-29T11:00:00Z")
    resp = api.create_assignment(job["id"], {
        "resource_id": vid["id"], "role": "REPORTER",
        "expected_job_version": job["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_ROLE_KIND_MISMATCH.value)


def test_assign_inactive_resource_rejected(api):
    """PRD §3.2: "Next, the resource must be active — assigning a resource whose
    `active` is false is rejected with `ERR_RESOURCE_INACTIVE`." A deactivated
    reporter cannot be newly assigned.

    Design: Corner/validations/assign_inactive_resource_returns_resource_inactive
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    deactivate_resource(rep["id"])
    job = make_job(case["id"], scheduled_start="2026-07-18T09:00:00Z",
                   scheduled_end="2026-07-18T11:00:00Z")
    resp = api.create_assignment(job["id"], {
        "resource_id": rep["id"], "role": "REPORTER",
        "expected_job_version": job["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_INACTIVE.value)


def test_duplicate_reporter_role_rejected(api):
    """PRD §3.2: "Then the job may hold at most one active assignment per role, so
    attempting to add a second active reporter, videographer, or interpreter is
    rejected with `ERR_ROLE_ALREADY_FILLED`." A second REPORTER on a job that
    already has an ACTIVE reporter is rejected.

    Design: Corner/validations/assign_duplicate_reporter_role_returns_role_already_filled
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep1 = make_reporter(full_name="Rep One", certifications=["CSR_CA"])
    rep2 = make_reporter(full_name="Rep Two", certifications=["CSR_CA"])
    job = make_job(case["id"], scheduled_start="2026-07-19T09:00:00Z",
                   scheduled_end="2026-07-19T11:00:00Z")
    add_assignment(job["id"], rep1["id"], "REPORTER")
    resp = api.create_assignment(job["id"], {
        "resource_id": rep2["id"], "role": "REPORTER",
        "expected_job_version": current_job_version(job["id"])}, COORD)
    validate_error(resp, ApiErrorId.ERR_ROLE_ALREADY_FILLED.value)


def test_interpreter_language_mismatch_rejected(api):
    """PRD §3.2: "If the role is `INTERPRETER`, the resource's `certifications`
    must contain the job's `interpreter_language`, failing which the system
    returns `ERR_INTERPRETER_LANGUAGE_MISMATCH`." Job needs SPANISH; interpreter
    holds only FRENCH.

    Design: Corner/validations/assign_interpreter_wrong_language_returns_language_mismatch
    """
    att = make_attorney()
    case = make_case(att["id"])
    interp = make_interpreter(certifications=["FRENCH"])
    job = make_job(case["id"], scheduled_start="2026-07-20T09:00:00Z",
                   scheduled_end="2026-07-20T11:00:00Z",
                   requires_interpreter=True, interpreter_language="SPANISH")
    resp = api.create_assignment(job["id"], {
        "resource_id": interp["id"], "role": "INTERPRETER",
        "expected_job_version": job["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_LANGUAGE_MISMATCH.value)


def test_non_realtime_reporter_on_realtime_job_rejected(api):
    """PRD §3.2: "If the role is `REPORTER` and the job requires real-time, the
    resource's `realtime_capable` must be true, failing which the system returns
    `ERR_REALTIME_NOT_CAPABLE`." A reporter with realtime_capable=false cannot be
    assigned to a requires_realtime job.

    Design: Corner/validations/assign_non_realtime_reporter_to_realtime_job_returns_not_capable
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"], realtime_capable=False)
    job = make_job(case["id"], scheduled_start="2026-07-21T09:00:00Z",
                   scheduled_end="2026-07-21T11:00:00Z", requires_realtime=True)
    resp = api.create_assignment(job["id"], {
        "resource_id": rep["id"], "role": "REPORTER",
        "expected_job_version": job["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_REALTIME_NOT_CAPABLE.value)


def test_resource_double_booked_on_overlapping_window_rejected(api):
    """PRD §3.3: "if any of those assignments belongs to a job whose half-open
    window overlaps the new job's half-open window, the assignment is rejected
    with `ERR_RESOURCE_DOUBLE_BOOKED`." A videographer on 09:00..12:00 cannot also
    take an overlapping 11:00..13:00 job.

    Design: Difficulty/resource_temporal_overlap/half_open_overlap_on_any_resource_kind
    """
    att = make_attorney()
    case = make_case(att["id"])
    vid = make_videographer()
    j1 = make_job(case["id"], scheduled_start="2026-06-15T09:00:00Z",
                  scheduled_end="2026-06-15T12:00:00Z", requires_videographer=True)
    add_assignment(j1["id"], vid["id"], "VIDEOGRAPHER")
    j2 = make_job(case["id"], scheduled_start="2026-06-15T11:00:00Z",
                  scheduled_end="2026-06-15T13:00:00Z", requires_videographer=True)
    resp = api.create_assignment(j2["id"], {
        "resource_id": vid["id"], "role": "VIDEOGRAPHER",
        "expected_job_version": j2["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_DOUBLE_BOOKED.value)


def test_reporter_buffer_under_30_min_gap_rejected(api):
    """PRD §3.3: "a reporter assignment must respect a thirty-minute travel buffer
    between adjacent job windows on the same reporter. Even when two job windows do
    not overlap, if the gap between one job's end and the adjacent job's start is
    less than thirty minutes, the reporter assignment is rejected with
    `ERR_REPORTER_BUFFER_CONFLICT`." A reporter ending 12:00 cannot take a job
    starting 12:29 (29-min gap).

    Design: Difficulty/boundary_precision_check/reporter_buffer_29_vs_30_min_gap_on_assignment
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    j1 = make_job(case["id"], scheduled_start="2026-06-12T09:00:00Z",
                  scheduled_end="2026-06-12T12:00:00Z")
    add_assignment(j1["id"], rep["id"], "REPORTER")
    j2 = make_job(case["id"], scheduled_start="2026-06-12T12:29:00Z",
                  scheduled_end="2026-06-12T14:00:00Z")
    resp = api.create_assignment(j2["id"], {
        "resource_id": rep["id"], "role": "REPORTER",
        "expected_job_version": j2["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_REPORTER_BUFFER_CONFLICT.value)


def test_reporter_buffer_exactly_30_min_gap_allowed(api):
    """PRD §3.3: "if the gap between one job's end and the adjacent job's start is
    less than thirty minutes, the reporter assignment is rejected." A gap of
    exactly 30 minutes (12:00 end -> 12:30 start) satisfies the buffer and the
    assignment is accepted.

    Design: Difficulty/boundary_precision_check/reporter_buffer_29_vs_30_min_gap_on_assignment
    """
    from test_helpers import validate_success
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    j1 = make_job(case["id"], scheduled_start="2026-06-12T09:00:00Z",
                  scheduled_end="2026-06-12T12:00:00Z")
    add_assignment(j1["id"], rep["id"], "REPORTER")
    j2 = make_job(case["id"], scheduled_start="2026-06-12T12:30:00Z",
                  scheduled_end="2026-06-12T14:00:00Z")
    resp = api.create_assignment(j2["id"], {
        "resource_id": rep["id"], "role": "REPORTER",
        "expected_job_version": j2["version"]}, COORD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", (
        f"assignment at exactly 30-min buffer should be ACTIVE, got {data['status']}")


def test_reporter_buffer_distinct_from_plain_overlap(api):
    """PRD §3.3: "Even when two job windows do not overlap, if the gap between one
    job's end and the adjacent job's start is less than thirty minutes, the
    reporter assignment is rejected with `ERR_REPORTER_BUFFER_CONFLICT`." Two
    non-overlapping reporter jobs with a 15-min gap (12:00 end -> 12:15 start) are
    still rejected on the buffer, not on plain overlap.

    Design: Difficulty/resource_temporal_overlap/reporter_buffer_interval_semantics_distinct_from_plain_overlap
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    j1 = make_job(case["id"], scheduled_start="2026-06-16T09:00:00Z",
                  scheduled_end="2026-06-16T12:00:00Z")
    add_assignment(j1["id"], rep["id"], "REPORTER")
    j2 = make_job(case["id"], scheduled_start="2026-06-16T12:15:00Z",
                  scheduled_end="2026-06-16T14:00:00Z")
    resp = api.create_assignment(j2["id"], {
        "resource_id": rep["id"], "role": "REPORTER",
        "expected_job_version": j2["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_REPORTER_BUFFER_CONFLICT.value)


def test_job_end_before_start_rejected(api):
    """PRD §3.2: "The end must be strictly after the start; a window where
    `scheduled_end` is not strictly later than `scheduled_start` is rejected with
    `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/create_job_end_before_start_returns_invalid_time_window
    """
    att = make_attorney()
    case = make_case(att["id"])
    resp = api.create_job(create_job_payload(
        case_id=case["id"], scheduled_start="2026-07-22T11:00:00Z",
        scheduled_end="2026-07-22T09:00:00Z"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)

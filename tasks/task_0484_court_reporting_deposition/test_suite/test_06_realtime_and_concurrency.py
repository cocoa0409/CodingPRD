"""Real-time stream provisioning / go-live / adjourn-stop cascade, the OCC guard
on assignment creation (stale vs current job version), and immediate consistency
of the derived staffing posture.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_insession_realtime_job,
    provision_stream,
    go_live,
    set_clock,
    adjourn_job,
    make_attorney,
    make_case,
    make_reporter,
    make_videographer,
    make_job,
    add_assignment,
    current_job_version,
    make_schedule_coordinator_headers,
    make_reporter_headers,
)

COORD = make_schedule_coordinator_headers()


# ---------------------------------------------------------------------------
# Real-time streams (PRD §3.7)
# ---------------------------------------------------------------------------
def test_realtime_stream_provision_then_go_live(api):
    """PRD §3.7: "Taking the stream live is a `Reporter` action that advances it
    from `STARTING` to `LIVE`." On an IN_SESSION requires_realtime job with a
    realtime-capable reporter assignment, provisioning then go-live moves the
    stream to LIVE.

    Design: Corner/state_machines/realtime_stream_provision_then_go_live_happy_path
    """
    sc = setup_insession_realtime_job(
        hourly_appearance_cents=15000,
        scheduled_start="2026-08-10T09:00:00Z",
        scheduled_end="2026-08-10T13:00:00Z",
        session_start="2026-08-10T09:00:00Z")
    provision_stream(sc)
    stream = go_live(sc)
    assert stream["status"] == "LIVE", f"stream should be LIVE, got {stream['status']}"


def test_realtime_stream_provision_on_non_realtime_job_rejected(api):
    """PRD §3.7: "A real-time **stream** is provisioned only while its job is
    `IN_SESSION` and `requires_realtime` is true, and only against a
    `reporter_assignment_id` that names an `ACTIVE` reporter assignment whose
    underlying resource is `realtime_capable`; if any of these conditions is
    unmet, provisioning is rejected with `ERR_REALTIME_NOT_PROVISIONABLE`." A job
    whose requires_realtime is false rejects provisioning.

    Design: Corner/state_machines/realtime_stream_provision_on_non_realtime_job_rejected
    """
    # Build a non-realtime IN_SESSION job with a (realtime-capable) reporter.
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(hourly_appearance_cents=12000, realtime_capable=True,
                        certifications=["CSR_CA"])
    job = make_job(case["id"], scheduled_start="2026-08-11T09:00:00Z",
                   scheduled_end="2026-08-11T13:00:00Z")
    asg = add_assignment(job["id"], rep["id"], "REPORTER")
    from test_helpers import confirm_job, start_job
    confirm_job(job["id"])
    set_clock("2026-08-11T09:00:00Z")
    start_job(job["id"])
    resp = api.create_realtime_stream(
        job["id"], {"reporter_assignment_id": asg["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_REALTIME_NOT_PROVISIONABLE.value)


def test_realtime_stream_stopped_by_adjourn_cascade(api):
    """PRD §3.7: "A stream is also stopped automatically by the job-adjourn cascade
    of §3.5: a stream that was `LIVE` is stopped, and a stream that never went live
    — still `STARTING` when the job adjourns — is likewise driven to `STOPPED` with
    its `stopped_at` set to the clock." Adjourning the job stops a LIVE stream.

    Design: Corner/state_machines/realtime_stream_stopped_by_job_adjourn_cascade
    """
    sc = setup_insession_realtime_job(
        hourly_appearance_cents=15000,
        scheduled_start="2026-08-12T09:00:00Z",
        scheduled_end="2026-08-12T13:00:00Z",
        session_start="2026-08-12T09:00:00Z")
    provision_stream(sc)
    go_live(sc)
    set_clock("2026-08-12T11:00:00Z")
    adjourn_job(sc.job_id)
    stream = validate_success(api.get_realtime_stream(sc.extra["stream_id"], COORD))
    assert stream["status"] == "STOPPED", (
        f"adjourn cascade should stop the stream, got {stream['status']}")


# ---------------------------------------------------------------------------
# OCC on assignment creation (PRD §2.6)
# ---------------------------------------------------------------------------
def test_assignment_create_stale_job_version_rejected(api):
    """PRD §2.6: "If `expected_job_version` does not equal the job's current
    `version` — that is, if another writer has added or released an assignment on
    that job since the client last read it — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)." After one assignment advances the version, a
    second create carrying the pre-advance version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_job_version_on_assignment_create
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    vid = make_videographer()
    job = make_job(case["id"], scheduled_start="2026-08-01T09:00:00Z",
                   scheduled_end="2026-08-01T11:00:00Z", requires_videographer=True)
    stale_version = job["version"]
    add_assignment(job["id"], rep["id"], "REPORTER", expected_job_version=stale_version)
    # Second create reuses the now-stale pre-advance version.
    resp = api.create_assignment(job["id"], {
        "resource_id": vid["id"], "role": "VIDEOGRAPHER",
        "expected_job_version": stale_version}, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_assignment_create_correct_version_succeeds_and_increments(api):
    """PRD §2.6: "A request that assigns a resource to a job must carry
    `expected_job_version`, a non-optional field that conveys the client's last
    observed `version` of the target `Job`." PRD §2.4: "`version` is an integer
    that starts at its initial value on creation and increments by one on every
    mutation of the resource." Two successful assignments take a v1 job to v3.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_job_version_succeeds_and_increments
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    vid = make_videographer()
    job = make_job(case["id"], scheduled_start="2026-08-02T09:00:00Z",
                   scheduled_end="2026-08-02T11:00:00Z", requires_videographer=True)
    assert job["version"] == 1, f"new job should be version 1, got {job['version']}"
    add_assignment(job["id"], rep["id"], "REPORTER")
    resp = api.create_assignment(job["id"], {
        "resource_id": vid["id"], "role": "VIDEOGRAPHER",
        "expected_job_version": current_job_version(job["id"])}, COORD)
    validate_success(resp, expected_status=201)
    refreshed = validate_success(api.get_job(job["id"], COORD))
    assert refreshed["version"] == 3, (
        f"two assignments should take version to 3, got {refreshed['version']}")
    assert refreshed["staffing_posture"] == "READY", (
        f"posture should be READY with both roles covered, got {refreshed['staffing_posture']}")


def test_assignment_immediately_reflected_in_staffing_posture(api):
    """PRD §3.4: "If every required role is covered, the posture is `READY`." PRD
    §3.4: "A job's `staffing_posture` is a derived field, recomputed whenever an
    assignment is created or released." An immediately-following GET reflects
    posture READY for a reporter-only job.

    Design: Corner/consistency_model/immediate_assignment_reflected_in_job_posture_same_flow
    """
    att = make_attorney()
    case = make_case(att["id"])
    rep = make_reporter(certifications=["CSR_CA"])
    job = make_job(case["id"], scheduled_start="2026-08-04T09:00:00Z",
                   scheduled_end="2026-08-04T11:00:00Z")
    add_assignment(job["id"], rep["id"], "REPORTER")
    refreshed = validate_success(api.get_job(job["id"], COORD))
    assert refreshed["staffing_posture"] == "READY", (
        f"posture should be READY immediately after assign, got "
        f"{refreshed['staffing_posture']}")

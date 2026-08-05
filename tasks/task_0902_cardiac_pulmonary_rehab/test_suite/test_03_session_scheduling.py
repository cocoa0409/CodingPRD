"""Session scheduling: booking guards, OCC, capacity cap, and precedence conflicts.

Queue A (Difficulty): resource_temporal_overlap, boundary_precision_check (cap),
priority_pair_validation_conflict. Queue B (Corner): time range, OCC stale version,
session listing.
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import fixtures as X


# ---------------------------------------------------------------------------
# Difficulty: station half-open overlap
# ---------------------------------------------------------------------------
def test_station_double_booking_overlap_rejected(api):
    """PRD §2.10: "A session's proposed interval must not overlap another `SCHEDULED`
    session on the same station: the interval is treated as half-open on
    `[scheduled_start, scheduled_end)`, so exact adjacency (one session's end equal to
    the next session's start) is allowed, but any true overlap is rejected with
    `ERR_STATION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/station_double_booking_halfopen
    """
    ctx = X.setup_active_program(api)
    clin_b = X.create_clinician(api)
    X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    resp = X.schedule_session(
        ctx, clinician_id=clin_b["id"],
        scheduled_start="2026-05-04T09:30:00Z", scheduled_end="2026-05-04T10:30:00Z",
        return_response=True,
    )
    validate_error(resp, ApiErrorId.ERR_STATION_OVERLAP, expected_status=409)


def test_station_adjacent_interval_allowed(api):
    """PRD §2.10: "the interval is treated as half-open on `[scheduled_start,
    scheduled_end)`, so exact adjacency (one session's end equal to the next session's
    start) is allowed, but any true overlap is rejected with `ERR_STATION_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/station_double_booking_halfopen
    """
    ctx = X.setup_active_program(api)
    clin_b = X.create_clinician(api)
    X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    data = X.schedule_session(
        ctx, clinician_id=clin_b["id"],
        scheduled_start="2026-05-04T10:00:00Z", scheduled_end="2026-05-04T11:00:00Z",
    )
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: clinician turnover buffer
# ---------------------------------------------------------------------------
def test_clinician_turnover_buffer_violation_rejected(api):
    """PRD §2.10: "The supervising clinician must additionally be free within a
    15-minute turnover buffer of any other `SCHEDULED` session; two of that clinician's
    sessions must therefore be separated by more than 15 minutes, and adjacency within
    15 minutes is not allowed, with violations rejected as `ERR_CLINICIAN_UNAVAILABLE`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/clinician_turnover_buffer_overlap
    """
    ctx = X.setup_active_program(api)
    station_2 = X.create_station(api, station_type="TELEMETRY")
    X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    resp = X.schedule_session(
        ctx, station_id=station_2["id"],
        scheduled_start="2026-05-04T10:10:00Z", scheduled_end="2026-05-04T11:10:00Z",  # 10-min gap < 15
        return_response=True,
    )
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_UNAVAILABLE, expected_status=409)


def test_clinician_gap_beyond_buffer_allowed(api):
    """PRD §2.10: "two of that clinician's sessions must therefore be separated by
    more than 15 minutes, and adjacency within 15 minutes is not allowed, with
    violations rejected as `ERR_CLINICIAN_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/clinician_turnover_buffer_overlap
    """
    ctx = X.setup_active_program(api)
    station_2 = X.create_station(api, station_type="TELEMETRY")
    X.schedule_session(ctx, scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    data = X.schedule_session(
        ctx, station_id=station_2["id"],
        scheduled_start="2026-05-04T10:20:00Z", scheduled_end="2026-05-04T11:20:00Z",  # 20-min gap > 15
    )
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: session cap boundary
# ---------------------------------------------------------------------------
def test_session_cap_two_allowed_third_rejected(api):
    """PRD §2.8: "Scheduling (whether creating a new session or rescheduling a missed
    one) is permitted only while the sum of `sessions_used` and `sessions_scheduled` is
    strictly less than `authorized_session_cap`; a request that would push that sum to
    or past the cap is rejected with `ERR_SESSION_CAP_REACHED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/session_cap_last_allowed_next_rejected
    """
    ctx = X.setup_active_program(api, authorized_session_cap=2)
    s1 = X.schedule_session(ctx)
    s2 = X.schedule_session(ctx)
    assert s1["status"] == "SCHEDULED"
    assert s2["status"] == "SCHEDULED"
    resp = X.schedule_session(ctx, return_response=True)
    validate_error(resp, ApiErrorId.ERR_SESSION_CAP_REACHED, expected_status=409)


def test_session_cap_one_allowed_second_rejected(api):
    """PRD §2.8: "Scheduling (whether creating a new session or rescheduling a missed
    one) is permitted only while the sum of `sessions_used` and `sessions_scheduled` is
    strictly less than `authorized_session_cap`; a request that would push that sum to
    or past the cap is rejected with `ERR_SESSION_CAP_REACHED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/session_cap_last_allowed_next_rejected
    """
    ctx = X.setup_active_program(api, authorized_session_cap=1)
    s1 = X.schedule_session(ctx)
    assert s1["status"] == "SCHEDULED"
    resp = X.schedule_session(ctx, return_response=True)
    validate_error(resp, ApiErrorId.ERR_SESSION_CAP_REACHED, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: state legality precedes fiscal cap
# ---------------------------------------------------------------------------
def test_state_error_precedes_cap_on_held_program(api):
    """PRD §2.10: "The system evaluates, in order: authentication, then role and
    ownership authorization, then existence of every path and foreign-key resource,
    then (for session scheduling only) the optimistic-concurrency version check, then
    the target's state legality, then cross-aggregate reference consistency, then the
    telemetry-station safety rule, then station overlap, then clinician turnover
    availability, then the strictly-positive time range, and finally the 36-session
    capacity cap."
    PRD §3.4: "scheduling against a program in any other status is rejected with
    `ERR_PROGRAM_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/session_hold_state_beats_cap_fiscal
    """
    ctx = X.setup_active_program(api, authorized_session_cap=1)
    s1 = X.schedule_session(ctx)
    X.complete_session(ctx, s1["id"])  # sessions_used=1 -> cap exhausted
    validate_success(api.hold_program(ctx["program_id"], ctx["coord"], {"reason": "chest pain"}))
    resp = X.schedule_session(ctx, return_response=True)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, expected_status=409)


def test_cap_error_fires_when_program_active(api):
    """PRD §2.10: "then the target's state legality, ... and finally the 36-session
    capacity cap."
    PRD §2.8: "a request that would push that sum to or past the cap is rejected with
    `ERR_SESSION_CAP_REACHED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/session_hold_state_beats_cap_fiscal
    """
    ctx = X.setup_active_program(api, authorized_session_cap=1)
    s1 = X.schedule_session(ctx)
    X.complete_session(ctx, s1["id"])  # sessions_used=1 -> cap exhausted, program still ACTIVE
    resp = X.schedule_session(ctx, return_response=True)
    validate_error(resp, ApiErrorId.ERR_SESSION_CAP_REACHED, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty: telemetry safety precedes station overlap
# ---------------------------------------------------------------------------
def test_telemetry_error_precedes_station_overlap(api):
    """PRD §2.10: "A program stratified as `HIGH` risk may only run a
    `MONITORED_EXERCISE` session on a `TELEMETRY` station; booking or rescheduling such
    a session onto a non-telemetry station is rejected with
    `ERR_TELEMETRY_STATION_REQUIRED` (HTTP 422)."
    PRD §2.10: "then the telemetry-station safety rule, then station overlap".

    Design: Difficulty/priority_pair_validation_conflict/session_telemetry_safety_beats_overlap_temporal
    """
    ctx = X.setup_active_program(api, risk_stratification="HIGH", station_type="STANDARD")
    # EDUCATION session is not subject to the telemetry rule, so it can occupy the STANDARD station.
    X.schedule_session(ctx, session_type="EDUCATION",
                       scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    resp = X.schedule_session(
        ctx, session_type="MONITORED_EXERCISE",
        scheduled_start="2026-05-04T09:30:00Z", scheduled_end="2026-05-04T10:30:00Z",  # overlaps too
        return_response=True,
    )
    validate_error(resp, ApiErrorId.ERR_TELEMETRY_STATION_REQUIRED, expected_status=422)


def test_station_overlap_fires_when_telemetry_satisfied(api):
    """PRD §2.10: "then the telemetry-station safety rule, then station overlap".
    PRD §2.10: "any true overlap is rejected with `ERR_STATION_OVERLAP` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/session_telemetry_safety_beats_overlap_temporal
    """
    ctx = X.setup_active_program(api, risk_stratification="HIGH", station_type="TELEMETRY")
    clin_b = X.create_clinician(api)
    X.schedule_session(ctx, session_type="MONITORED_EXERCISE",
                       scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    resp = X.schedule_session(
        ctx, session_type="MONITORED_EXERCISE", clinician_id=clin_b["id"],
        scheduled_start="2026-05-04T09:30:00Z", scheduled_end="2026-05-04T10:30:00Z",
        return_response=True,
    )
    validate_error(resp, ApiErrorId.ERR_STATION_OVERLAP, expected_status=409)


# ---------------------------------------------------------------------------
# Corner: time range, OCC, listing
# ---------------------------------------------------------------------------
def test_session_end_before_start_returns_invalid_time_range(api):
    """PRD §2.10: "Finally, `scheduled_end` must be strictly after `scheduled_start`,
    or the request is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 400)."

    Design: Corner/validations/session_end_before_start_returns_invalid_time_range
    """
    ctx = X.setup_active_program(api)
    resp = X.schedule_session(
        ctx, scheduled_start="2026-05-04T10:00:00Z", scheduled_end="2026-05-04T09:00:00Z",
        return_response=True,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, expected_status=400)


def test_session_create_stale_program_version_returns_412(api):
    """PRD §2.6: "If `expected_program_version` does not equal the program's current
    `version`, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/session_create_stale_program_version_returns_412
    """
    ctx = X.setup_active_program(api)
    stale_version = validate_success(api.get_program(ctx["program_id"], ctx["coord"]))["version"]
    # First schedule with the observed version succeeds and advances program.version.
    X.schedule_session(ctx, expected_program_version=stale_version,
                       scheduled_start="2026-05-04T09:00:00Z", scheduled_end="2026-05-04T10:00:00Z")
    # Second schedule still carries the now-stale version.
    resp = X.schedule_session(
        ctx, expected_program_version=stale_version,
        scheduled_start="2026-05-04T11:00:00Z", scheduled_end="2026-05-04T12:00:00Z",
        return_response=True,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION, expected_status=412)


def test_sessions_list_filtered_by_program_paginates(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §3.5: "Sessions may be listed and filtered by `program_id`, `clinician_id`,
    `station_id`, or `status`."

    Design: Corner/entities/sessions_list_filtered_by_program_paginates
    """
    ctx = X.setup_active_program(api)
    s1 = X.schedule_session(ctx)
    s2 = X.schedule_session(ctx)
    data, meta = validate_paginated(api.list_sessions(ctx["coord"], params={"program_id": ctx["program_id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    ids = {row["id"] for row in data}
    assert s1["id"] in ids and s2["id"] in ids

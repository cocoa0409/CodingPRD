"""Incident response, weather, stoppage/resume, and end-of-day lifecycle."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    is_iso8601_timestamp,
    ApiErrorId,
    make_track, make_track_day, make_open_track_day, make_block,
    make_session, report_incident, investigate_and_clear, get_day,
    day_version, resume_day,
    setup_running_day_with_session, setup_stopped_day_via_incident,
    TEST_USERS,
)

OPS = TEST_USERS["trackops_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def test_incident_low_severity_direct_clear_allowed(api):
    """PRD §3.6: "Clearing resolves it: from `INVESTIGATING` unconditionally,
    or directly from `OPEN` only when the `severity` is `LOW`." PRD §3.6:
    "Clearing decrements `open_incident_count` by one, recomputes posture,
    advances the day's `version`, and lands the incident in the terminal
    `CLEARED` state."

    Design: Corner/state_machines/incident_low_severity_direct_clear_allowed
    """
    env = setup_running_day_with_session("2026-09-18")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    incident = report_incident(tid, tdid, env["session"]["id"], "LOW", "opsX")
    resp = api.clear_incident(tid, tdid, incident["id"],
                              {"cleared_by_user_id": "safetyX"}, SAFETY)
    data = validate_success(resp)
    assert data["status"] == "CLEARED", "LOW incidents may skip INVESTIGATING"
    assert get_day(tid, tdid)["open_incident_count"] == 0


def test_segregation_of_duties_incident_clearer_is_reporter(api):
    """PRD §3.6: "Segregation of duties is enforced on clear — the supplied
    `cleared_by_user_id` must differ from the incident's
    `reported_by_user_id`, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (422) — and the state check fires before the
    segregation check."

    Design: Corner/validations/segregation_of_duties_incident_clearer_is_reporter
    """
    env = setup_running_day_with_session("2026-09-26")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    incident = report_incident(tid, tdid, env["session"]["id"], "LOW",
                               "same_user")
    resp = api.clear_incident(tid, tdid, incident["id"],
                              {"cleared_by_user_id": "same_user"}, SAFETY)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_high_incident_stops_day_and_reddens_sessions(api):
    """PRD §3.6: "Severity drives the cascade: at `MEDIUM`, `HIGH`, or
    `CRITICAL` the session where it happened drops from `GREEN` to `RED`; at
    `HIGH` or `CRITICAL` the whole day stops — a `RUNNING` day transitions to
    `STOPPED`, every `GREEN` session on it cascades to `RED`, and the posture
    recomputes to `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/trackday_open_running_stopped_cyclic
    """
    env = setup_stopped_day_via_incident("2026-08-26", severity="HIGH")
    tid, tdid, sid = (env["track"]["id"], env["day"]["id"],
                      env["session"]["id"])
    day = env["day"]
    assert day["status"] == "STOPPED", "HIGH incident auto-stops the day"
    assert day["posture"] == "SUSPENDED"
    session = validate_success(api.get_session(tid, tdid, sid, OPS))
    assert session["status"] == "RED", "the GREEN session cascades to RED"


def test_clear_and_resume_returns_day_to_running(api):
    """PRD §3.6: "Three conditions must all hold for the resume itself: no
    open incidents, the weather flag not at `STOP`, and the noise breach count
    below 3; a violation is rejected with `ERR_INVALID_STATE` (409). A
    successful resume moves the day from `STOPPED` back to `RUNNING`, returns
    every `RED` session to `GREEN`, recomputes posture — `NORMAL` or `CAUTION`
    depending on the remaining breach count — and advances the day's `version`
    by one."

    Design: Difficulty/non_linear_state_machine/trackday_open_running_stopped_cyclic
    """
    env = setup_stopped_day_via_incident("2026-08-26", severity="HIGH")
    tid, tdid, sid = (env["track"]["id"], env["day"]["id"],
                      env["session"]["id"])
    investigate_and_clear(tid, tdid, env["incident"]["id"], "safety1")
    day = get_day(tid, tdid)
    assert day["status"] == "STOPPED", "clearing alone does not resume the day"
    assert day["open_incident_count"] == 0
    resumed = resume_day(tid, tdid)
    assert resumed["status"] == "RUNNING"
    assert resumed["posture"] == "NORMAL", "no breaches remain, so NORMAL"
    session = validate_success(api.get_session(tid, tdid, sid, OPS))
    assert session["status"] == "GREEN", "the RED session returns to GREEN"


def test_medium_incident_reddens_only_its_session(api):
    """PRD §3.6: "Severity drives the cascade: at `MEDIUM`, `HIGH`, or
    `CRITICAL` the session where it happened drops from `GREEN` to `RED`; at
    `HIGH` or `CRITICAL` the whole day stops — a `RUNNING` day transitions to
    `STOPPED`, every `GREEN` session on it cascades to `RED`, and the posture
    recomputes to `SUSPENDED`." PRD §3.6: "Otherwise, if any incident is open,
    or the breach count is at least 1, or the weather flag stands at `WATCH`,
    posture is `CAUTION`."

    Design: Difficulty/non_linear_state_machine/session_green_red_black_branching
    """
    env = setup_running_day_with_session("2026-08-27",
                                         run_group_class="INTERMEDIATE")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    first = env["session"]
    second = make_session(tid, tdid, rbid, "ADVANCED")
    report_incident(tid, tdid, first["id"], "MEDIUM", "ops1")
    first_after = validate_success(api.get_session(tid, tdid, first["id"], OPS))
    second_after = validate_success(api.get_session(tid, tdid, second["id"], OPS))
    assert first_after["status"] == "RED", "the affected session drops to RED"
    assert second_after["status"] == "GREEN", "MEDIUM does not stop the day"
    day = get_day(tid, tdid)
    assert day["status"] == "RUNNING"
    assert day["posture"] == "CAUTION"


def test_running_day_cancel_blacks_out_all_sessions(api):
    """PRD §3.9: "From `RUNNING`, the accepted reasons are `WEATHER` and
    `SAFETY`." and "Every door writes `cancelled_reason`, sets the day
    `CANCELLED`, and cascades all bookings on the day to `CANCELLED` with
    refunds computed under the variant the reason forces; cancelling a
    `RUNNING` day additionally blacks out the session layer, moving every
    `GREEN` and every `RED` session to `BLACK` with `ended_at_utc` stamped."

    Design: Difficulty/non_linear_state_machine/session_green_red_black_branching
    """
    env = setup_running_day_with_session("2026-08-27",
                                         run_group_class="INTERMEDIATE")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    first = env["session"]
    second = make_session(tid, tdid, rbid, "ADVANCED")
    incident = report_incident(tid, tdid, first["id"], "MEDIUM", "ops1")
    # MEDIUM clears only via INVESTIGATING; resolve it before the day cancel.
    investigate_and_clear(tid, tdid, incident["id"], "safety1")
    validate_success(api.cancel_track_day(tid, tdid, {"reason": "WEATHER"}, OPS))
    for session in (first, second):
        after = validate_success(api.get_session(tid, tdid, session["id"], OPS))
        assert after["status"] == "BLACK", "GREEN and RED both black out"
        assert after.get("ended_at_utc"), "ended_at_utc is stamped"
        assert is_iso8601_timestamp(after["ended_at_utc"])


def test_critical_incident_cascades_day_stop_and_sessions_red(api):
    """PRD §3.6: "A new incident opens in `OPEN` status and bumps the day's
    `open_incident_count` by one." and "Severity drives the cascade: at
    `MEDIUM`, `HIGH`, or `CRITICAL` the session where it happened drops from
    `GREEN` to `RED`; at `HIGH` or `CRITICAL` the whole day stops — a
    `RUNNING` day transitions to `STOPPED`, every `GREEN` session on it
    cascades to `RED`, and the posture recomputes to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/incident_open_to_trackday_stop_to_session_red
    """
    env = setup_running_day_with_session("2026-08-28", run_group_class="NOVICE")
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    first = env["session"]
    second = make_session(tid, tdid, rbid, "ADVANCED")
    incident = report_incident(tid, tdid, first["id"], "CRITICAL", "ops1")
    assert incident["status"] == "OPEN"
    day = get_day(tid, tdid)
    assert day["open_incident_count"] == 1
    assert day["status"] == "STOPPED"
    assert day["posture"] == "SUSPENDED"
    for session in (first, second):
        after = validate_success(api.get_session(tid, tdid, session["id"], OPS))
        assert after["status"] == "RED", \
            "every GREEN session cascades to RED when the day stops"


def test_incident_report_advances_day_version_by_one(api):
    """PRD §3.6: "A new incident opens in `OPEN` status and bumps the day's
    `open_incident_count` by one." and "In all cases the posture is recomputed
    and the day's `version` advances by one." PRD §2.4: "Most resources
    additionally carry `updated_at`, refreshed to the current logical time on
    every mutation, and `version`, an integer that increments by exactly one
    on every mutation of that resource."

    Design: Difficulty/transitive_cascade/incident_open_to_trackday_stop_to_session_red
    """
    env = setup_running_day_with_session("2026-08-28", run_group_class="NOVICE")
    tid, tdid = env["track"]["id"], env["day"]["id"]
    version_before = day_version(tid, tdid)
    # Incident reports are shared between TrackOps and SafetyOfficer.
    incident = report_incident(tid, tdid, env["session"]["id"], "CRITICAL",
                               "safetyReporter", headers=SAFETY)
    assert incident["status"] == "OPEN"
    day = get_day(tid, tdid)
    assert day["version"] == version_before + 1
    assert day["open_incident_count"] == 1
    assert day["status"] == "STOPPED"


def test_resume_from_scheduled_day_rejected(api):
    """PRD §3.6: "A successful resume moves the day from `STOPPED` back to
    `RUNNING`". PRD §2.9: "State-machine preconditions — the resource stands
    in a state that permits the requested transition, on every state-transition
    endpoint: `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/trackday_invalid_transition_schedule_to_running_rejected
    """
    track = make_track(name="T1")
    day = make_track_day(track["id"], "2026-09-14")
    assert day["status"] == "SCHEDULED"
    resp = api.resume_track_day(
        track["id"], day["id"],
        {"expected_track_day_version": day["version"]}, SAFETY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_weather_hold_on_cancelled_day_rejected(api):
    """PRD §3.6: "Declaring a weather hold is permitted from `OPEN` or
    `RUNNING` while the flag stands at `CLEAR` or `WATCH`". PRD §3.9:
    "`CANCELLED` is terminal."

    Design: Corner/state_machines/trackday_terminal_states_lockdown
    """
    track = make_track(name="T3")
    day = make_open_track_day(track["id"], "2026-09-16")
    validate_success(api.cancel_track_day(track["id"], day["id"],
                                          {"reason": "CUSTOMER"}, OPS))
    resp = api.weather_hold(track["id"], day["id"], OPS)
    assert resp.status_code == 409
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_TRACK_DAY_NOT_LIVE])


def test_stale_trackday_version_on_resume_returns_412(api):
    """PRD §2.6: "Resuming a stopped track day requires
    `expected_track_day_version`, matched against the day's current `version`;
    a mismatch is rejected with `ERR_STALE_VERSION` (412), since a prior
    resume or a fresh incident may already have advanced the day's state."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_trackday_version_on_resume
    """
    track = make_track(name="X1")
    day = make_open_track_day(track["id"], "2026-10-05")
    stale_version = day["version"]
    block = make_block(track["id"], day["id"])
    session = make_session(track["id"], day["id"], block["id"])
    incident = report_incident(track["id"], day["id"], session["id"], "HIGH",
                               "oX1")
    investigate_and_clear(track["id"], day["id"], incident["id"], "sX1")
    assert get_day(track["id"], day["id"])["status"] == "STOPPED"
    resp = api.resume_track_day(
        track["id"], day["id"],
        {"expected_track_day_version": stale_version}, SAFETY)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_run_ops_increments_ops_run_index(api):
    """PRD §3.6: "The operations checkpoint, a `TrackOps`-run sweep, bumps
    `ops_run_index` by one, expires every waiver whose `expires_at_utc` is
    strictly before the current logical time (flipping those drivers'
    `waiver_status` to `EXPIRED`), recomputes posture, and advances the day's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_increments_ops_run_index
    """
    track = make_track(name="X4")
    day = make_open_track_day(track["id"], "2026-10-08")
    first = validate_success(api.run_ops(track["id"], day["id"], OPS))
    assert first["ops_run_index"] == 1
    second = validate_success(api.run_ops(track["id"], day["id"], OPS))
    assert second["ops_run_index"] == 2

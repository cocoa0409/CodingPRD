"""Sessions, property-line noise monitoring, and the track-day posture."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_track, make_coach, make_open_track_day, make_block, make_booking,
    make_session, post_noise_reading, report_incident, get_day, set_clock,
    setup_running_day_with_session, setup_suspended_day_via_noise,
    TEST_USERS,
)

OPS = TEST_USERS["trackops_headers"]


def test_session_checkered_requires_minimum_laps(api):
    """PRD §3.5: "When a group has run its allotted driving, `TrackOps` throws
    the checkered flag — permitted only from `GREEN`, and only once the
    session has logged at least `MIN_LAPS_FOR_CHECKERED` laps, the configured
    minimum-lap threshold; a short session is rejected with
    `ERR_INVALID_STATE` (409)."

    Design: Corner/endpoints/session_checkered_requires_minimum_laps
    """
    env = setup_running_day_with_session("2026-09-30")
    assert env["session"]["lap_count"] == 0
    resp = api.checkered(env["track"]["id"], env["day"]["id"],
                         env["session"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_noise_reading_equal_to_limit_is_not_breach(api):
    """PRD §3.7: "The `breach` flag is computed immediately and strictly:
    `breach` is true when `db_level` is greater than the track's
    `noise_limit_db` — a reading exactly equal to the limit is not a breach."

    Design: Difficulty/boundary_precision_check/noise_breach_strictly_greater_boundary
    """
    env = setup_running_day_with_session(
        "2026-09-02", track_overrides={"noise_limit_db": 90})
    tid, tdid, sid = (env["track"]["id"], env["day"]["id"],
                      env["session"]["id"])
    set_clock("2026-09-02T09:06:00Z")
    reading = post_noise_reading(tid, tdid, sid, 90, "2026-09-02T09:00:00Z")
    assert reading["breach"] is False, "equality with the limit is not a breach"
    day = get_day(tid, tdid)
    assert day["noise_breach_count"] == 0
    assert day["posture"] == "NORMAL"


def test_noise_reading_above_limit_is_breach_and_counts(api):
    """PRD §3.7: "The `breach` flag is computed immediately and strictly:
    `breach` is true when `db_level` is greater than the track's
    `noise_limit_db` — a reading exactly equal to the limit is not a breach."
    PRD §3.7: "The day's `noise_breach_count` is recomputed on every reading
    as the number of breaching readings on that day whose `recorded_at_utc`
    falls within the trailing sixty-minute window — readings taken at least as
    recently as sixty minutes before the current logical time count; older
    ones fall out."

    Design: Difficulty/boundary_precision_check/noise_breach_strictly_greater_boundary
    """
    env = setup_running_day_with_session(
        "2026-09-02", track_overrides={"noise_limit_db": 90})
    tid, tdid, sid = (env["track"]["id"], env["day"]["id"],
                      env["session"]["id"])
    set_clock("2026-09-02T09:06:00Z")
    post_noise_reading(tid, tdid, sid, 90, "2026-09-02T09:00:00Z")
    reading = post_noise_reading(tid, tdid, sid, 91, "2026-09-02T09:05:00Z")
    assert reading["breach"] is True, "one dB above the limit breaches"
    day = get_day(tid, tdid)
    assert day["noise_breach_count"] == 1, \
        "only the strict-greater reading counts"
    assert day["posture"] == "CAUTION"


def test_noise_breach_ladder_caution_then_suspended(api):
    """PRD §3.6: "The day's `posture` is derived in exactly this order. If
    `weather_flag` stands at `STOP`, posture is `SUSPENDED`. Otherwise, if at
    least one incident is open and any `OPEN` incident carries `HIGH` or
    `CRITICAL` severity, posture is `SUSPENDED`. Otherwise, if the noise
    breach count is at least 3, posture is `SUSPENDED`. Otherwise, if any
    incident is open, or the breach count is at least 1, or the weather flag
    stands at `WATCH`, posture is `CAUTION`. In every other case, posture is
    `NORMAL`."

    Design: Difficulty/combinatorial_formula/trackday_posture_multibranch_threshold
    """
    env = setup_running_day_with_session(
        "2026-08-22", run_group_class="INTERMEDIATE",
        track_overrides={"noise_limit_db": 90})
    tid, tdid, sid = (env["track"]["id"], env["day"]["id"],
                      env["session"]["id"])
    set_clock("2026-08-22T09:25:00Z")
    post_noise_reading(tid, tdid, sid, 91, "2026-08-22T09:00:00Z")
    day = get_day(tid, tdid)
    assert day["noise_breach_count"] == 1
    assert day["posture"] == "CAUTION", "one breach lifts the day to CAUTION"
    post_noise_reading(tid, tdid, sid, 92, "2026-08-22T09:10:00Z")
    post_noise_reading(tid, tdid, sid, 93, "2026-08-22T09:20:00Z")
    day = get_day(tid, tdid)
    assert day["noise_breach_count"] == 3
    assert day["posture"] == "SUSPENDED", "a third breach suspends the day"


def test_suspended_posture_dominates_incident_and_weather_hold(api):
    """PRD §3.6: "Otherwise, if the noise breach count is at least 3, posture
    is `SUSPENDED`. Otherwise, if any incident is open, or the breach count is
    at least 1, or the weather flag stands at `WATCH`, posture is `CAUTION`."
    PRD §3.6: "Declaring a weather hold is permitted from `OPEN` or `RUNNING`
    while the flag stands at `CLEAR` or `WATCH`: the day moves to
    `WEATHER_HOLD`, the flag becomes `WATCH`, and — when the day had been
    `RUNNING` — every `GREEN` session drops to `RED`."

    Design: Difficulty/combinatorial_formula/trackday_posture_multibranch_threshold
    """
    env = setup_suspended_day_via_noise("2026-08-22",
                                        breach_dbs=(91, 92, 93))
    tid, tdid, sid = (env["track"]["id"], env["day"]["id"],
                      env["session"]["id"])
    assert env["day"]["posture"] == "SUSPENDED"
    # A LOW incident cannot lower the posture below SUSPENDED.
    validate_success(api.report_incident(
        tid, tdid, {"session_id": sid, "severity": "LOW",
                    "reported_by_user_id": "ops1"}, OPS), 201)
    day = get_day(tid, tdid)
    assert day["posture"] == "SUSPENDED"
    assert day["open_incident_count"] == 1
    # Weather hold moves the day but the breach count keeps posture SUSPENDED.
    day = validate_success(api.weather_hold(tid, tdid, OPS))
    assert day["status"] == "WEATHER_HOLD"
    assert day["weather_flag"] == "WATCH"
    assert day["posture"] == "SUSPENDED", "the breach branch still dominates"


def test_suspended_day_assign_coach_reports_track_suspended(api):
    """PRD §2.9: "When several checks could reject the same request, they are
    evaluated in the following fixed order, and the first failure wins:" with
    "Posture — the day's `posture` is not `SUSPENDED`, on booking approve,
    session start, garage assignment create, and coach assign:
    `ERR_TRACK_SUSPENDED` (409)." evaluated before "Coach certificate
    sufficiency, on coach assign: `ERR_COACH_CERT_INSUFFICIENT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/posture_vs_business_referential_pair
    """
    env = setup_suspended_day_via_noise("2026-08-30",
                                        breach_dbs=(95, 96, 97))
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    coach = make_coach(tid, cert_level="BASIC", full_name="Bob")
    booking = make_booking(tid, tdid, rbid, "org9", run_group_class="RACE")
    # Both violations are present (suspended day AND under-certified coach);
    # the posture gate must fire first.
    resp = api.assign_coach(tid, tdid, rbid, booking["id"],
                            {"coach_id": coach["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_TRACK_SUSPENDED)
    coach_after = validate_success(api.get_coach(tid, coach["id"], OPS))
    assert booking["id"] not in coach_after["assigned_booking_ids"]


def test_suspended_day_assign_coach_gates_even_certified_coach(api):
    """PRD §2.7: "Posture gates forward progress: while a day's `posture` is
    `SUSPENDED`, booking approvals, session starts, garage assignment
    creation, and coach assignments are rejected with `ERR_TRACK_SUSPENDED`
    (409)." PRD §3.3: "It is refused on a `SUSPENDED` day with
    `ERR_TRACK_SUSPENDED` (409), refused for an under-certified coach with
    `ERR_COACH_CERT_INSUFFICIENT` (422), and refused when the coach already
    serves three bookings on the day with `ERR_COACH_OVERLOADED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/posture_vs_business_referential_pair
    """
    env = setup_suspended_day_via_noise("2026-08-30",
                                        breach_dbs=(95, 96, 97))
    tid, tdid, rbid = env["track"]["id"], env["day"]["id"], env["block"]["id"]
    coach = make_coach(tid, cert_level="RACE", full_name="Pro")
    booking = make_booking(tid, tdid, rbid, "org9", run_group_class="RACE")
    resp = api.assign_coach(tid, tdid, rbid, booking["id"],
                            {"coach_id": coach["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_TRACK_SUSPENDED)

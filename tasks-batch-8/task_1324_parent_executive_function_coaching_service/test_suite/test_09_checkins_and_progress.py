"""Check-in timing/streaks and progress measurement variants (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_progress_snapshot,
    create_checkin,
    get_success_data,
    make_coach_headers,
    make_family_headers,
    run_sweep,
    set_clock,
    setup_active_plan_scenario,
    submit_checkin,
    take_snapshot,
    validate_error,
    validate_success,
)


def test_checkin_submit_exactly_at_due_at_is_on_time(api, admin_headers):
    """PRD §3.7: "Submitting at or before `due_at` — the boundary is inclusive —
    moves the check-in to `SUBMITTED_ON_TIME`, stamps `submitted_at`, and
    increments the client's `checkin_streak` by one."

    Design: Corner/calculations/checkin_submit_exactly_at_due_at_is_on_time
    """
    ctx = setup_active_plan_scenario(account_name="Fam OT", primary_email="ot@example.com")
    plan, coach, client = ctx["plans"][0], ctx["coach"], ctx["clients"][0]
    checkin = create_checkin(plan["id"], coach["id"], "2026-08-05T12:00:00Z")
    set_clock("2026-08-05T12:00:00Z")  # now == due_at exactly
    submitted = validate_success(
        api.submit_checkin(checkin["id"], make_family_headers(ctx["family"]["id"]))
    )
    assert submitted["status"] == "SUBMITTED_ON_TIME"
    client_after = validate_success(api.get_client(client["id"], admin_headers))
    assert client_after["checkin_streak"] == 1


def test_checkin_missed_by_sweep_after_grace(api, admin_headers):
    """PRD §2.4: "second, every check-in still `PENDING` whose grace window has
    fully elapsed is moved to `MISSED` and the owning client's streak is reset"
    PRD §3.7: "Once more than 72 hours have elapsed since `due_at`, submission
    is rejected with `ERR_CHECKIN_EXPIRED`, and the daily sweep will already
    have moved such a check-in to `MISSED`, likewise resetting the streak to
    zero."

    Design: Corner/calculations/checkin_missed_by_sweep_after_grace
    """
    ctx = setup_active_plan_scenario(account_name="Fam MS", primary_email="ms@example.com")
    family, plan, coach, client = (
        ctx["family"], ctx["plans"][0], ctx["coach"], ctx["clients"][0],
    )
    c1 = create_checkin(plan["id"], coach["id"], "2026-08-02T00:00:00Z")
    c2 = create_checkin(plan["id"], coach["id"], "2026-08-04T00:00:00Z")
    # c1 submitted on time at the startup clock => streak 1.
    submit_checkin(c1["id"], family["id"])

    # c2's grace ends 2026-08-07T00:00:00Z; the sweep at 2026-08-08 lapses it.
    set_clock("2026-08-08T00:00:00Z")
    summary = run_sweep()
    assert summary["checkins_missed"] == 1

    checkins = validate_success(api.list_checkins(plan["id"], admin_headers))
    by_id = {c["id"]: c for c in checkins}
    assert by_id[c2["id"]]["status"] == "MISSED"
    assert by_id[c1["id"]]["status"] == "SUBMITTED_ON_TIME"

    client_after = validate_success(api.get_client(client["id"], admin_headers))
    assert client_after["checkin_streak"] == 0, "the MISS wipes the streak from c1"


def test_checkin_acknowledge_twice_rejected(api):
    """PRD §3.7: "A coach may acknowledge a submitted check-in — from either
    `SUBMITTED_ON_TIME` or `SUBMITTED_LATE` into the terminal `ACKNOWLEDGED`
    state — provided the acting coach is the owning plan's `coach_id`, else
    `ERR_FORBIDDEN_SCOPE`. `MISSED` and `ACKNOWLEDGED` are terminal."
    PRD §2.8: "a state transition requested for a from-state the machine does
    not permit — including any write against a terminal state — is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/checkin_acknowledge_twice_rejected
    """
    ctx = setup_active_plan_scenario(account_name="Fam CK", primary_email="ck@example.com")
    family, plan, coach = ctx["family"], ctx["plans"][0], ctx["coach"]
    checkin = create_checkin(plan["id"], coach["id"], "2026-08-05T00:00:00Z")
    submitted = submit_checkin(checkin["id"], family["id"])
    assert submitted["status"] == "SUBMITTED_ON_TIME"

    coach_h = make_coach_headers(coach["id"])
    acked = validate_success(api.acknowledge_checkin(checkin["id"], coach_h))
    assert acked["status"] == "ACKNOWLEDGED"
    resp = api.acknowledge_checkin(checkin["id"], coach_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_progress_snapshot_null_indices_when_no_data(api):
    """PRD §3.8: "The goal rate is `goals_achieved` divided by
    `goals_considered`; the check-in rate is `checkins_on_time` divided by
    `checkins_considered`. When both denominators are zero the index is null"

    Design: Corner/entities/progress_snapshot_null_indices_when_no_data
    """
    ctx = setup_active_plan_scenario(account_name="Fam NI", primary_email="ni@example.com")
    client, coach = ctx["clients"][0], ctx["coach"]
    # The only goal is still SET (non-terminal); no check-ins exist.
    snapshot = take_snapshot(client["id"], coach["id"])
    assert_progress_snapshot(snapshot)
    assert snapshot["goals_considered"] == 0
    assert snapshot["checkins_considered"] == 0
    assert snapshot["rolling_index"] is None
    assert snapshot["cumulative_index"] is None


def test_revision_recommended_after_two_low_rolling_snapshots(api, admin_headers):
    """PRD §3.8: "After the snapshot is stored, a side rule runs: when the two
    most recent snapshots of the client, ordered by creation ascending, both
    hold a non-null `rolling_index` strictly below 40, the `ACTIVE` plan's
    `revision_recommended` flag is set to true — two consecutive low readings
    are the practice's signal to revise the plan."
    PRD §3.3: "The plan's `revision_recommended` flag starts false and is set
    by progress measurement (§3.6)."

    Design: Corner/calculations/revision_recommended_after_two_low_rolling_snapshots
    """
    ctx = setup_active_plan_scenario(account_name="Fam RR", primary_email="rr@example.com")
    plan, coach, goal, client = (
        ctx["plans"][0], ctx["coach"], ctx["goals"][0], ctx["clients"][0],
    )
    coach_h = make_coach_headers(coach["id"])
    # Drop the only goal: goal rate 0/1 => rolling index 0 (< 40).
    get_success_data(api.transition_goal(goal["id"], "DROPPED", coach_h))

    snap1 = take_snapshot(client["id"], coach["id"])
    assert snap1["rolling_index"] == 0
    plan_mid = validate_success(api.get_plan(plan["id"], admin_headers))
    assert plan_mid["revision_recommended"] is False, "one low snapshot is not enough"

    snap2 = take_snapshot(client["id"], coach["id"])
    assert snap2["rolling_index"] == 0
    plan_end = validate_success(api.get_plan(plan["id"], admin_headers))
    assert plan_end["revision_recommended"] is True, (
        "two consecutive readings below 40 set the flag"
    )


def _setup_two_variant_progress(api):
    """Plan activated at the default clock; gB DROPPED and c2 resolved late
    outside a 2026-09-05 snapshot's rolling window; gA ACHIEVED and c1 on time
    inside it."""
    ctx = setup_active_plan_scenario(account_name="Fam PI", primary_email="pi@example.com")
    family, plan, coach, client = (
        ctx["family"], ctx["plans"][0], ctx["coach"], ctx["clients"][0],
    )
    coach_h = make_coach_headers(coach["id"])
    fam_h = make_family_headers(family["id"])
    ga = ctx["goals"][0]
    gb = get_success_data(
        api.create_goal(plan["id"], {"title": "Goal B", "target_date": "2026-09-01"},
                        coach_h)
    )
    # Outside the rolling window of a 2026-09-05 snapshot ([2026-08-08, ...]).
    get_success_data(api.transition_goal(gb["id"], "DROPPED", coach_h))
    c2 = create_checkin(plan["id"], coach["id"], "2026-08-02T00:00:00Z")
    set_clock("2026-08-03T00:00:00Z")
    submitted_c2 = validate_success(api.submit_checkin(c2["id"], fam_h))
    assert submitted_c2["status"] == "SUBMITTED_LATE"

    # Inside the rolling window.
    set_clock("2026-08-20T00:00:00Z")
    get_success_data(api.transition_goal(ga["id"], "ACHIEVED", coach_h))
    c1 = create_checkin(plan["id"], coach["id"], "2026-08-25T00:00:00Z")
    set_clock("2026-08-24T00:00:00Z")
    submitted_c1 = validate_success(api.submit_checkin(c1["id"], fam_h))
    assert submitted_c1["status"] == "SUBMITTED_ON_TIME"

    set_clock("2026-09-05T00:00:00Z")
    return ctx


def test_progress_rolling_window_counts_only_in_window_events(api):
    """PRD §3.8: "The snapshot's rolling variant covers a 28-day window ending
    at the snapshot instant: `window_end` is the snapshot time and
    `window_start` is exactly 28 days earlier, both ends inclusive. Within that
    window, `goals_considered` counts the client's terminal goals whose
    `resolved_at` falls in the window, and `goals_achieved` counts the subset
    in `ACHIEVED`; `checkins_considered` counts check-ins that left `PENDING` —
    submitted, or resolved `MISSED` — with their resolution timestamp in the
    window, and `checkins_on_time` counts the subset whose status is
    `SUBMITTED_ON_TIME` or `ACKNOWLEDGED` and whose `submitted_at` is at or
    before the check-in's `due_at`."

    Design: Difficulty/dual_variant_calc/progress_index_rolling_vs_cumulative
    """
    ctx = _setup_two_variant_progress(api)
    client, coach = ctx["clients"][0], ctx["coach"]
    snapshot = take_snapshot(client["id"], coach["id"])
    assert_progress_snapshot(snapshot)
    assert snapshot["goals_considered"] == 1, "only gA resolved inside the window"
    assert snapshot["checkins_considered"] == 1, "only c1 resolved inside the window"
    # goal rate 1/1, check-in rate 1/1 => 100 x (0.6 + 0.4) = 100.
    assert snapshot["rolling_index"] == 100


def test_progress_cumulative_differs_from_rolling(api, admin_headers):
    """PRD §3.8: "The same underlying rows feed a second variant,
    `cumulative_index`, computed over all goals and check-ins of the client's
    current `ACTIVE` plan regardless of timestamp, with the same weights,
    null-handling, and rounding; it is null when the client has no active plan
    or no data, and it is copied onto the client as `cumulative_progress_index`.
    Because the variants share components, the two numbers differ exactly when
    some event lies outside the rolling window."

    Design: Difficulty/dual_variant_calc/progress_index_rolling_vs_cumulative
    """
    ctx = _setup_two_variant_progress(api)
    client, coach = ctx["clients"][0], ctx["coach"]
    snapshot = take_snapshot(client["id"], coach["id"])
    # All events of the ACTIVE plan: goals 1/2 achieved, check-ins 1/2 on time
    # => 100 x (0.6 x 0.5 + 0.4 x 0.5) = 50.
    assert snapshot["cumulative_index"] == 50
    assert snapshot["rolling_index"] == 100
    assert snapshot["rolling_index"] != snapshot["cumulative_index"]

    client_after = validate_success(api.get_client(client["id"], admin_headers))
    assert client_after["rolling_progress_index"] == 100
    assert client_after["cumulative_progress_index"] == 50

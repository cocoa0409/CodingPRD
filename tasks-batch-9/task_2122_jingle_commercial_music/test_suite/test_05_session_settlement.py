"""Committing, wrapping and cancelling a session, and the AFM wage report."""
from test_helpers import (
    ApiErrorId,
    assert_ledger,
    assert_session_call,
    cancel_session_call,
    complete_session_call,
    confirm_session_call,
    create_studio_room,
    get_booking,
    get_project,
    get_session_call,
    make_afm_steward_headers,
    make_producer_headers,
    schedule_session_call,
    set_clock,
    setup_booked_call,
    setup_engagement_in_production,
    setup_engagement_with_confirmed_call,
    setup_two_same_day_completed_calls,
    validate_error,
    validate_success,
)


def test_afm_report_session_basis_pays_every_call_separately(api):
    """PRD §3.9: "The contributing rows are every booking line sitting on a session call
    of this engagement whose status is `WAGE_ACCRUED` or `PENALTY_ACCRUED` — wages owed
    for a session cancelled inside the AFM window are just as real as wages for a
    session that happened — iterated in `created_at` ascending order."
    PRD §3.9: "`booking_count` is the number of contributing rows, and `session_count`
    is the number of distinct session calls those rows belong to."
    PRD §3.5: "Because the three-hour minimum is applied per call, a player who works
    two calls on the same day is paid two minimum calls."
    PRD §3.9: "Its `basis` parameter defaults to `SESSION` when omitted and also
    accepts `DAY`, and the value used is echoed back as `basis` alongside
    `wage_total_cents`, `pension_health_cents`, `session_count` and `booking_count`."

    Design: Difficulty/dual_variant_calc/afm_wage_session_basis_vs_consolidated_day_basis
    """
    env = setup_two_same_day_completed_calls(budget_cents=4_000_000, demo_fee_cents=150_000,
                                             players=3, scale_hourly_cents=6251)
    report = validate_success(api.get_afm_report(
        env["project"]["id"], make_afm_steward_headers(), params={"basis": "SESSION"}))

    assert report["basis"] == "SESSION", f"Expected basis SESSION, got {report['basis']}"
    assert report["wage_total_cents"] == 168_777, (
        "Three players priced per call give 3 * (25004 + 31255) = 168777; "
        f"got {report['wage_total_cents']}")
    assert report["pension_health_cents"] == 20_253, (
        f"Expected 3 * (3000 + 3751) = 20253, got {report['pension_health_cents']}")
    assert report["session_count"] == 2, f"Expected session_count 2, got {report['session_count']}"
    assert report["booking_count"] == 6, f"Expected booking_count 6, got {report['booking_count']}"


def test_afm_report_day_basis_applies_the_eight_hour_cap(api):
    """PRD §3.9: "Within a group, the day's hours are the sum of the `billed_hours` of
    the group's calls; the billable hours are that sum clamped to the eight-hour day cap
    and then raised to the three-hour minimum if lower — that is, the greater of three
    hours and the lesser of eight hours and the day's hours."
    PRD §3.9: "`wage_total_cents` is the sum of the day wages; `pension_health_cents` is
    the sum of each day wage multiplied by 12 percent and rounded half-up;
    `booking_count` counts the booking lines in `WAGE_ACCRUED` that fed the groups; and
    `session_count` counts the engagement's `COMPLETED` session calls."
    PRD §3.9: "Because only completed calls are grouped, lines in `PENALTY_ACCRUED`
    never contribute on this basis, and because of the eight-hour cap the day total is
    strictly lower than the session total whenever a player's day exceeds eight hours."
    PRD §3.9: "Its `basis` parameter defaults to `SESSION` when omitted and also
    accepts `DAY`, and the value used is echoed back as `basis` alongside
    `wage_total_cents`, `pension_health_cents`, `session_count` and `booking_count`."

    Design: Difficulty/dual_variant_calc/afm_wage_session_basis_vs_consolidated_day_basis
    """
    env = setup_two_same_day_completed_calls(budget_cents=4_000_000, demo_fee_cents=150_000,
                                             players=3, scale_hourly_cents=6251)
    session_report = validate_success(api.get_afm_report(
        env["project"]["id"], make_afm_steward_headers(), params={"basis": "SESSION"}))
    day_report = validate_success(api.get_afm_report(
        env["project"]["id"], make_afm_steward_headers(), params={"basis": "DAY"}))

    assert day_report["basis"] == "DAY", f"Expected basis DAY, got {day_report['basis']}"
    assert day_report["wage_total_cents"] == 150_024, (
        "Nine worked hours clamp to the eight-hour cap: 3 * round(6251 * 8) = 150024; "
        f"got {day_report['wage_total_cents']}")
    assert day_report["pension_health_cents"] == 18_003, (
        f"Expected 3 * round(50008 * 0.12) = 18003, got {day_report['pension_health_cents']}")
    assert day_report["session_count"] == 2, (
        f"Expected session_count 2, got {day_report['session_count']}")
    assert day_report["booking_count"] == 6, (
        f"Expected booking_count 6, got {day_report['booking_count']}")
    assert (session_report["wage_total_cents"] - day_report["wage_total_cents"]) == 18_753, (
        "The day cap must make the DAY total strictly lower than the SESSION total by "
        f"18753; got {session_report['wage_total_cents'] - day_report['wage_total_cents']}")


def test_pension_and_health_is_rounded_on_each_booking_line(api):
    """PRD §3.5: "The line's `line_wage_cents` is the leader part plus the doubling
    part, and its `pension_health_cents` is `line_wage_cents` multiplied by 12 percent
    and rounded half-up."
    PRD §3.5: "The base is the player's `scale_hourly_cents` multiplied by those
    billable hours, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/pension_health_rounded_per_line_then_summed_not_summed_then_rounded
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=4_000_000, demo_fee_cents=150_000,
                                         submitted_length_seconds=60)
    booked = setup_booked_call(env, players=3, scale_hourly_cents=6251)
    confirm_session_call(booked["call"]["id"])
    complete_session_call(booked["call"]["id"], "2026-09-10T13:00:00Z")

    line = get_booking(booked["bookings"][0]["id"])
    assert line["line_wage_cents"] == 25_004, (
        f"round(6251 * 4) = 25004; got {line['line_wage_cents']}")
    assert line["pension_health_cents"] == 3_000, (
        "round(25004 * 0.12) = 3000 on this single line; "
        f"got {line['pension_health_cents']}")
    call = get_session_call(booked["call"]["id"])
    assert call["wage_total_cents"] == 75_012, (
        f"Three identical lines sum to 75012; got {call['wage_total_cents']}")


def test_afm_report_sums_rounded_lines_rather_than_rounding_the_total(api):
    """PRD §3.9: "**On both bases the rounding order is pinned: every line is rounded
    first and the rounded lines are then summed.**"
    PRD §3.9: "Multiplying an already-summed wage total by the pension-and-health
    percentage produces a different number of cents and is not the rule."
    PRD §3.9: "`pension_health_cents` is the sum, over those same rows, of each row's
    `line_wage_cents` multiplied by 12 percent and rounded half-up."

    Design: Difficulty/combinatorial_formula/pension_health_rounded_per_line_then_summed_not_summed_then_rounded
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=4_000_000, demo_fee_cents=150_000,
                                         submitted_length_seconds=60)
    booked = setup_booked_call(env, players=3, scale_hourly_cents=6251)
    confirm_session_call(booked["call"]["id"])
    complete_session_call(booked["call"]["id"], "2026-09-10T13:00:00Z")

    report = validate_success(api.get_afm_report(
        env["project"]["id"], make_afm_steward_headers(), params={"basis": "SESSION"}))
    assert report["wage_total_cents"] == 75_012, (
        f"Expected wage_total_cents 75012, got {report['wage_total_cents']}")
    assert report["pension_health_cents"] == 9_000, (
        "Rounding each 25004-cent line first gives 3 * 3000 = 9000; rounding the 75012 "
        f"total once would give 9001. Got {report['pension_health_cents']}")
    assert report["pension_health_cents"] != 9_001, (
        "9001 is the forbidden round-the-total-once answer")


def test_session_completion_settles_billed_hours_and_accrues_every_line(api):
    """PRD §3.5: "First, `actual_end_utc` is recorded, `billed_hours` is recomputed as
    the elapsed hours from `scheduled_start_utc` to `actual_end_utc` to four decimal
    places, and the call's `studio_cost_cents` and `wage_total_cents` are re-evaluated
    at that new hours basis, with `settled_total_cents` set to their sum."
    PRD §3.5: "Second, because the call now carries settled wage lines, every booking
    line on it still in `BOOKED` moves `BOOKED → WAGE_ACCRUED` with its
    `line_wage_cents` and `pension_health_cents` written at the billed-hours basis,
    processed in `created_at` ascending order."
    PRD §3.5: "The call's `committed_cents` is the sum of `studio_cost_cents` and
    `wage_estimate_cents`, and it is **frozen** at confirmation: it is never re-derived
    afterwards, and it is the exact figure that sits inside the engagement's
    `committed_cents` for as long as the call remains `CONFIRMED`."

    Design: Difficulty/transitive_cascade/session_completion_overrun_cascade_suspends_a_sibling_scheduled_call
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=650_000, demo_fee_cents=150_000,
                                         submitted_length_seconds=60)
    booked = setup_booked_call(env, players=3, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000, room_name="Room A")
    confirm_session_call(booked["call"]["id"])

    settled = complete_session_call(booked["call"]["id"], "2026-09-10T15:00:00Z")
    assert_session_call(settled)
    assert settled["status"] == "COMPLETED", f"Expected COMPLETED, got {settled['status']}"
    assert settled["billed_hours"] == 6, (
        f"09:00 to 15:00 is 6 billed hours; got {settled['billed_hours']}")
    assert settled["committed_cents"] == 235_012, (
        "The commitment stays frozen at the four-hour estimate 160000 + 75012; "
        f"got {settled['committed_cents']}")
    assert settled["wage_total_cents"] == 112_518, (
        f"Three lines of round(6251 * 6) = 37506 sum to 112518; "
        f"got {settled['wage_total_cents']}")
    assert settled["settled_total_cents"] == 352_518, (
        f"240000 of room plus 112518 of wages is 352518; got {settled['settled_total_cents']}")

    line = get_booking(booked["bookings"][0]["id"])
    assert line["status"] == "WAGE_ACCRUED", f"Expected WAGE_ACCRUED, got {line['status']}"
    assert line["line_wage_cents"] == 37_506, (
        f"Expected line_wage_cents 37506, got {line['line_wage_cents']}")
    assert line["pension_health_cents"] == 4_501, (
        f"round(37506 * 0.12) = 4501; got {line['pension_health_cents']}")


def test_completion_overrun_drops_the_posture_and_suspends_the_sibling_call(api):
    """PRD §3.5: "Third, because those lines accrued, the engagement's ledger moves:
    `committed_cents` falls by the call's frozen `committed_cents`, `spent_cents` rises
    by the call's `settled_total_cents`, and `available_cents` absorbs the difference
    between the frozen commitment and the settled total — which is negative when the
    session ran long, so a long session eats into free budget."
    PRD §3.5: "Fifth, because the posture may have changed, the sweep runs: every
    `SCHEDULED` call of the engagement becomes `SUSPENDED_BUDGET` if the posture left
    `HEALTHY`, and every `SUSPENDED_BUDGET` call returns to `SCHEDULED` if the posture
    became `HEALTHY`."

    Design: Difficulty/transitive_cascade/session_completion_overrun_cascade_suspends_a_sibling_scheduled_call
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=650_000, demo_fee_cents=150_000,
                                         submitted_length_seconds=60)
    booked = setup_booked_call(env, players=3, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000, room_name="Room A")
    quiet_room = create_studio_room(name="Room B", hourly_rate_cents=30_000)
    sibling = schedule_session_call(env["project"]["id"], quiet_room["id"],
                                    start="2026-09-11T09:00:00Z", end="2026-09-11T12:00:00Z")
    confirm_session_call(booked["call"]["id"])

    before = get_project(env["project"]["id"])
    assert_ledger(before, committed=235_012, available=264_988, spent=150_000)
    assert before["budget_posture"] == "HEALTHY"
    assert get_session_call(sibling["id"])["status"] == "SCHEDULED"

    complete_session_call(booked["call"]["id"], "2026-09-10T15:00:00Z")

    after = get_project(env["project"]["id"])
    assert_ledger(after, committed=0, available=147_482, spent=502_518)
    assert after["budget_posture"] == "CONSTRAINED", (
        "147482 * 100 is strictly below 25 * 650000, so the posture must fall to "
        f"CONSTRAINED; got {after['budget_posture']}")
    swept = get_session_call(sibling["id"])
    assert swept["status"] == "SUSPENDED_BUDGET", (
        f"The untouched SCHEDULED sibling must be swept to SUSPENDED_BUDGET; "
        f"got {swept['status']}")


def test_outside_window_cancel_restores_the_pre_confirmation_ledger(api):
    """PRD §2.7: "Cancelling a confirmed call at or outside the window withdraws the
    frozen amount from `committed_cents` and returns all of it to `available_cents`,
    leaving `spent_cents` untouched — this last movement is the exact compensating
    action of confirmation, and the pair of confirming and then cancelling outside the
    window must leave all three buckets at the values they held before the confirmation."
    PRD §2.7: "**These three buckets must sum to exactly `budget_cents` after every
    single request, with no drift.**"

    Design: Difficulty/compensating_invariant/confirm_then_outside_window_cancel_conserves_every_budget_cent
    """
    env = setup_engagement_with_confirmed_call(
        budget_cents=4_000_000, demo_fee_cents=150_000, players=3,
        clock="2026-09-01T00:00:00Z", scale_hourly_cents=6251, hourly_rate_cents=40_000,
        submitted_length_seconds=60)
    confirmed = get_project(env["project"]["id"])
    assert_ledger(confirmed, committed=235_012, available=3_614_988, spent=150_000)

    cancelled = validate_success(api.cancel_session_call(
        env["call"]["id"], {"reason": "client postponed the shoot"}, make_producer_headers()))
    assert cancelled["status"] == "CANCELLED_OUTSIDE_WINDOW", (
        "216 hours of notice is at or outside the 24-hour window; "
        f"got {cancelled['status']}")
    assert cancelled["committed_cents"] == 235_012, (
        f"The frozen commitment figure is not erased; got {cancelled['committed_cents']}")

    after = get_project(env["project"]["id"])
    assert_ledger(after, committed=0, available=3_850_000, spent=150_000)
    assert after["budget_posture"] == "HEALTHY", (
        f"Expected HEALTHY, got {after['budget_posture']}")


def test_outside_window_cancel_releases_every_line_without_wages(api):
    """PRD §3.5: "A `CONFIRMED` call cancelled at or outside the window moves
    `CONFIRMED → CANCELLED_OUTSIDE_WINDOW` and is the exact compensating action of
    confirmation: `wage_liability_cents` and `settled_total_cents` are both zero, every
    booking line still in `BOOKED` moves `BOOKED → RELEASED` with `line_wage_cents` and
    `pension_health_cents` at zero, the engagement's `committed_cents` falls by the
    call's frozen `committed_cents` and its `available_cents` rises by exactly the same
    amount, and `spent_cents` is untouched — leaving the ledger byte-for-byte where it
    stood before the confirmation."

    Design: Difficulty/compensating_invariant/confirm_then_outside_window_cancel_conserves_every_budget_cent
    """
    env = setup_engagement_with_confirmed_call(
        budget_cents=4_000_000, demo_fee_cents=150_000, players=3,
        clock="2026-09-01T00:00:00Z", scale_hourly_cents=6251, hourly_rate_cents=40_000,
        submitted_length_seconds=60)

    cancelled = cancel_session_call(env["call"]["id"], reason="client postponed the shoot")
    assert cancelled["wage_liability_cents"] == 0, (
        f"Expected wage_liability_cents 0, got {cancelled['wage_liability_cents']}")
    assert cancelled["settled_total_cents"] == 0, (
        f"Expected settled_total_cents 0, got {cancelled['settled_total_cents']}")

    for booking in env["bookings"]:
        line = get_booking(booking["id"])
        assert line["status"] == "RELEASED", (
            f"Every BOOKED line must be RELEASED; got {line['status']}")
        assert line["line_wage_cents"] == 0, (
            f"A released line owes no wage; got {line['line_wage_cents']}")
        assert line["pension_health_cents"] == 0, (
            f"A released line owes no pension and health; got {line['pension_health_cents']}")


def test_leader_multiplier_and_two_doublings_on_one_wage_line(api):
    """PRD §3.5: "The leader part is that base multiplied by the leader factor and
    rounded half-up, where the leader factor is 2 when the line's `is_leader` is true
    and 1 otherwise."
    PRD §3.5: "The doubling part is that same base multiplied by 20 percent and then by
    the line's `doubles_count`, rounded half-up."
    PRD §3.5: "The room component, `studio_cost_cents`, is the room's
    `hourly_rate_cents` multiplied by that hours basis, rounded half-up to whole cents."

    Design: Corner/calculations/corner_leader_multiplier_and_two_doublings_on_one_wage_line
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=4_000_000, demo_fee_cents=100_000)
    booked = setup_booked_call(env, players=1, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000, is_leader=True, doubles_count=2)
    confirm_session_call(booked["call"]["id"])
    complete_session_call(booked["call"]["id"], "2026-09-10T13:00:00Z")

    line = get_booking(booked["bookings"][0]["id"])
    assert line["line_wage_cents"] == 60_010, (
        "Base 25004, leader part 50008, two doublings round(25004 * 0.20 * 2) = 10002; "
        f"got {line['line_wage_cents']}")
    assert line["pension_health_cents"] == 7_201, (
        f"round(60010 * 0.12) = 7201; got {line['pension_health_cents']}")
    call = get_session_call(booked["call"]["id"])
    assert call["wage_total_cents"] == 60_010
    assert call["studio_cost_cents"] == 160_000, (
        f"40000 cents an hour over 4 hours is 160000; got {call['studio_cost_cents']}")
    assert call["settled_total_cents"] == 220_010
    assert call["committed_cents"] == 220_010
    project = get_project(env["project"]["id"])
    assert project["spent_cents"] == 320_010, (
        f"100000 of demo plus 220010 of session is 320010; got {project['spent_cents']}")


def test_three_hour_minimum_call_lifts_a_two_hour_session(api):
    """PRD §3.5: "The billable hours are the greater of that basis and the three-hour
    AFM minimum call, so a ninety-minute date still pays three hours."
    PRD §3.5: "The room component, `studio_cost_cents`, is the room's
    `hourly_rate_cents` multiplied by that hours basis, rounded half-up to whole cents."

    Design: Corner/calculations/corner_minimum_call_of_three_hours_lifts_a_two_hour_session
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=4_000_000, demo_fee_cents=100_000)
    booked = setup_booked_call(env, players=1, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000,
                               start="2026-09-10T09:00:00Z", end="2026-09-10T11:00:00Z")

    confirmed = validate_success(api.confirm_session_call(
        booked["call"]["id"], make_producer_headers()))
    assert confirmed["scheduled_hours"] == 2, (
        f"09:00 to 11:00 is 2 scheduled hours; got {confirmed['scheduled_hours']}")
    assert confirmed["studio_cost_cents"] == 80_000, (
        f"The room bills the 2 hours actually used; got {confirmed['studio_cost_cents']}")
    assert confirmed["wage_estimate_cents"] == 18_753, (
        "The player is lifted to the three-hour minimum: round(6251 * 3) = 18753; "
        f"got {confirmed['wage_estimate_cents']}")
    assert confirmed["committed_cents"] == 98_753, (
        f"80000 + 18753 = 98753; got {confirmed['committed_cents']}")

    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=98_753, available=3_801_247, spent=100_000)


def test_cancel_inside_the_window_books_the_full_wage_liability(api):
    """PRD §3.5: "The distance measured is the signed number of hours from the logical
    clock to the call's `scheduled_start_utc`, and the boundary is strict: strictly less
    than 24 hours of notice is **inside** the window, exactly 24 hours or more is
    **outside** it."
    PRD §3.5: "A `CONFIRMED` call cancelled inside the window moves
    `CONFIRMED → CANCELLED_INSIDE_WINDOW`; its `wage_liability_cents` is set to the
    call's `wage_estimate_cents` and its `settled_total_cents` is set to that same value
    — the players are owed their wages, but the room is not billed."
    PRD §3.5: "The engagement's `committed_cents` falls by the call's frozen
    `committed_cents`, its `spent_cents` rises by `wage_liability_cents`, and
    `available_cents` rises by the difference between the two."

    Design: Corner/endpoints/corner_cancel_inside_the_window_books_the_full_wage_liability
    """
    env = setup_engagement_with_confirmed_call(
        budget_cents=4_000_000, demo_fee_cents=150_000, players=3,
        clock="2026-09-01T00:00:00Z", scale_hourly_cents=6251, hourly_rate_cents=40_000)
    set_clock("2026-09-09T09:00:01Z")

    cancelled = validate_success(api.cancel_session_call(
        env["call"]["id"], {"reason": "talent illness"}, make_producer_headers()))
    assert cancelled["status"] == "CANCELLED_INSIDE_WINDOW", (
        "One second inside the 24-hour window takes the penalty branch; "
        f"got {cancelled['status']}")
    assert cancelled["wage_liability_cents"] == 75_012, (
        f"Expected the full 75012-cent estimate, got {cancelled['wage_liability_cents']}")
    assert cancelled["settled_total_cents"] == 75_012, (
        f"The room is not billed; got {cancelled['settled_total_cents']}")

    line = get_booking(env["bookings"][0]["id"])
    assert line["status"] == "PENALTY_ACCRUED", (
        f"Expected PENALTY_ACCRUED, got {line['status']}")
    assert line["line_wage_cents"] == 25_004, (
        f"round(6251 * 4) at the scheduled-hours basis; got {line['line_wage_cents']}")
    assert line["pension_health_cents"] == 3_000

    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=0, available=3_774_988, spent=225_012)


def test_cancel_at_exactly_twenty_four_hours_is_outside_the_window(api):
    """PRD §3.5: "The distance measured is the signed number of hours from the logical
    clock to the call's `scheduled_start_utc`, and the boundary is strict: strictly less
    than 24 hours of notice is **inside** the window, exactly 24 hours or more is
    **outside** it."
    PRD §2.5: "**Target state.** On every state-changing operation, the resource named
    in the path is in a status from which the requested transition is defined —
    otherwise `ERR_PROJECT_NOT_IN_BRIEFING`, `ERR_PROJECT_NOT_IN_DEMO`,
    `ERR_PROJECT_NOT_HOLDABLE`, `ERR_PROJECT_NOT_ON_HOLD`, `ERR_BRIEF_NOT_DRAFT`,
    `ERR_DEMO_INVALID_STATE`, `ERR_SESSION_CALL_INVALID_STATE`,
    `ERR_LICENSE_DEAL_INVALID_STATE`, `ERR_LICENSE_NOT_ACTIVE`,
    `ERR_LICENSE_NOT_RENEWABLE`, `ERR_DELIVERABLE_INVALID_STATE` or
    `ERR_CUE_ENTRY_ALREADY_VOIDED` (409)."

    Design: Corner/endpoints/corner_cancel_at_exactly_twenty_four_hours_is_outside_the_window
    """
    env = setup_engagement_with_confirmed_call(
        budget_cents=4_000_000, demo_fee_cents=150_000, players=3,
        clock="2026-09-01T00:00:00Z", scale_hourly_cents=6251, hourly_rate_cents=40_000)
    set_clock("2026-09-09T09:00:00Z")

    cancelled = validate_success(api.cancel_session_call(
        env["call"]["id"], {"reason": "schedule slipped"}, make_producer_headers()))
    assert cancelled["status"] == "CANCELLED_OUTSIDE_WINDOW", (
        "Exactly 24 hours of notice is outside the window; "
        f"got {cancelled['status']}")
    assert cancelled["wage_liability_cents"] == 0, (
        f"Expected wage_liability_cents 0, got {cancelled['wage_liability_cents']}")
    assert get_booking(env["bookings"][0]["id"])["status"] == "RELEASED"

    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=0, available=3_850_000, spent=150_000)

    validate_error(
        api.cancel_session_call(env["call"]["id"], {"reason": "duplicate request"},
                                make_producer_headers()),
        ApiErrorId.ERR_SESSION_CALL_INVALID_STATE.value, 409)


def test_afm_report_defaults_to_the_session_basis(api):
    """PRD §3.9: "Its `basis` parameter defaults to `SESSION` when omitted and also
    accepts `DAY`, and the value used is echoed back as `basis` alongside
    `wage_total_cents`, `pension_health_cents`, `session_count` and `booking_count`."
    PRD §3.9: "`wage_total_cents` is the sum of those rows' `line_wage_cents`."

    Design: Corner/endpoints/corner_afm_report_defaults_to_session_basis_when_basis_is_omitted
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=4_000_000, demo_fee_cents=100_000)
    booked = setup_booked_call(env, players=1, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000,
                               start="2026-09-10T09:00:00Z", end="2026-09-10T12:00:00Z")
    confirm_session_call(booked["call"]["id"])
    complete_session_call(booked["call"]["id"], "2026-09-10T12:00:00Z")

    report = validate_success(api.get_afm_report(env["project"]["id"], make_producer_headers()))
    assert report["basis"] == "SESSION", (
        f"An omitted basis must echo SESSION; got {report['basis']}")
    assert report["wage_total_cents"] == 18_753, (
        f"round(6251 * 3) = 18753; got {report['wage_total_cents']}")
    assert report["pension_health_cents"] == 2_250, (
        f"round(18753 * 0.12) = 2250; got {report['pension_health_cents']}")
    assert report["session_count"] == 1, f"Expected session_count 1, got {report['session_count']}"
    assert report["booking_count"] == 1, f"Expected booking_count 1, got {report['booking_count']}"


def test_confirming_a_constrained_engagement_is_rejected(api):
    """PRD §3.5: "A producer confirms a call that is `SCHEDULED`, moving it
    `SCHEDULED → CONFIRMED`; the engagement must be `IN_PRODUCTION`, its
    `budget_posture` must be `HEALTHY` — a `CONSTRAINED` or `FROZEN` engagement is
    refused with `ERR_PROJECT_BUDGET_CONSTRAINED` — and the call must carry at least one
    booking line still in `BOOKED`."
    PRD §2.5: "**Budget posture gate.** On session-call confirmation, the engagement's
    `budget_posture` is `HEALTHY` — otherwise `ERR_PROJECT_BUDGET_CONSTRAINED` (409)."

    Design: Corner/validations/corner_confirm_while_posture_constrained_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=500_000, demo_fee_cents=400_000)
    constrained = get_project(env["project"]["id"])
    assert constrained["budget_posture"] == "CONSTRAINED", (
        f"Expected CONSTRAINED before the trigger, got {constrained['budget_posture']}")
    booked = setup_booked_call(env, players=1, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000)
    assert booked["call"]["status"] == "SCHEDULED", (
        "A call created after the posture already fell starts SCHEDULED; "
        f"got {booked['call']['status']}")

    error = validate_error(
        api.confirm_session_call(booked["call"]["id"], make_producer_headers()),
        ApiErrorId.ERR_PROJECT_BUDGET_CONSTRAINED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_PROJECT_BUDGET_EXCEEDED.value, (
        "The posture gate is judged before the funds check")

    call = get_session_call(booked["call"]["id"])
    assert call["status"] == "SCHEDULED", f"Expected SCHEDULED, got {call['status']}"
    assert call["committed_cents"] == 0
    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=0, available=100_000, spent=400_000)


def test_confirm_response_already_carries_the_frozen_commitment(api):
    """PRD §3.5: "The call's `committed_cents` is the sum of `studio_cost_cents` and
    `wage_estimate_cents`, and it is **frozen** at confirmation: it is never re-derived
    afterwards, and it is the exact figure that sits inside the engagement's
    `committed_cents` for as long as the call remains `CONFIRMED`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/corner_confirm_response_already_carries_the_frozen_commitment
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(budget_cents=4_000_000, demo_fee_cents=100_000)
    booked = setup_booked_call(env, players=1, scale_hourly_cents=6251,
                               hourly_rate_cents=40_000)

    confirmed = validate_success(api.confirm_session_call(
        booked["call"]["id"], make_producer_headers()))
    assert confirmed["status"] == "CONFIRMED", f"Expected CONFIRMED, got {confirmed['status']}"
    assert confirmed["studio_cost_cents"] == 160_000
    assert confirmed["wage_estimate_cents"] == 25_004
    assert confirmed["committed_cents"] == 185_004, (
        f"160000 + 25004 = 185004; got {confirmed['committed_cents']}")

    reread = validate_success(api.get_session_call(booked["call"]["id"], make_producer_headers()))
    for field in ("status", "studio_cost_cents", "wage_estimate_cents", "committed_cents"):
        assert reread[field] == confirmed[field], (
            f"A follow-up read must return the same {field}: "
            f"{reread[field]} against {confirmed[field]}")

    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=185_004, available=3_714_996, spent=100_000)

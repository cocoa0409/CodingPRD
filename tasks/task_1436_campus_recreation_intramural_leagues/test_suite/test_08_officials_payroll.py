"""Officials: assignment gates, travel buffer, dual-variant pay, settlement
ledger moves, and role/ownership denials (PRD §2.1, §2.8, §3.6)."""
from test_helpers import (
    COORDINATOR,
    NON_EXISTENT_UUID,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    assign_official,
    create_facility,
    create_instructor,
    create_official,
    create_score_report_payload,
    declare_forfeit,
    finalize_game,
    game_with_accepted_official,
    make_member_headers,
    make_staff_headers,
    respond_assignment,
    schedule_game,
    season_context,
    season_game_context,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_official_provisional_pay_and_forfeit_marks_worked():
    """PRD §3.6: "Its `provisional_pay_cents` is estimated at creation: the
    game's `duration_minutes` multiplied by the official's
    `base_hourly_rate_cents` and by a certification multiplier — 1.0 at level
    1, 1.25 at level 2, 1.5 at level 3 — divided by 60, rounded half-up to
    whole cents."
    PRD §3.4: "Officials handling differs sharply by trigger: on a *manual*
    declare-forfeit, `ACCEPTED` assignments move to `WORKED` — leaving them
    eligible for the flat forfeit fee at settlement — while `ASSIGNED`
    assignments are `CANCELLED` with provisional pay reversed; on a *system*
    cascade-forfeit (suspension or withdrawal, below), every non-terminal
    assignment is `CANCELLED` with provisional pay reversed and nobody becomes
    `WORKED`."

    Design: Difficulty/dual_variant_calc/official_provisional_vs_final_pay
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = game_with_accepted_official(cert=2, rate=2000)
    assignment = validate_success(api_client.get_officiating_assignment(
        ctx["assignment"]["id"], REC_ADMIN))
    assert assignment["status"] == "ACCEPTED"
    assert assignment["provisional_pay_cents"] == 3750  # 90 * 2000 * 1.25 / 60

    set_clock("2026-09-08T19:45:00Z")
    game = declare_forfeit(ctx["game"]["id"], ctx["teams"][1]["id"])
    assert game["status"] == "FORFEITED"
    assignment = validate_success(api_client.get_officiating_assignment(
        ctx["assignment"]["id"], REC_ADMIN))
    assert assignment["status"] == "WORKED", (
        "a manual forfeit keeps ACCEPTED officials WORKED"
    )


def test_official_settle_forfeited_game_pays_flat_base_hour():
    """PRD §3.6: "Settlement requires `WORKED` status (otherwise
    `ERR_INVALID_STATE`) and computes `final_pay_cents`: if the game is
    `FINAL`, the billable minutes are the game's `actual_duration_minutes`
    when recorded, otherwise its `duration_minutes`, multiplied by the base
    rate and certification multiplier, divided by 60, and rounded half-up; if
    the game is `FORFEITED`, the official is paid a flat one hour at the base
    rate with *no* certification multiplier and duration ignored — so the same
    assignment can settle for less than its provisional. Settlement moves the
    assignment `WORKED → PAID`, subtracts `provisional_pay_cents` from
    `payroll_pending_cents`, and adds `final_pay_cents` to
    `payroll_paid_cents`."
    PRD §3.4: "The forfeiting team's `losses` increments by 1, its
    `forfeit_count` increments by 1, and it receives an automatic
    sportsmanship 1: `sportsmanship_points_total` up by 1 and
    `sportsmanship_rating_count` up by 1."

    Design: Difficulty/dual_variant_calc/official_provisional_vs_final_pay
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = game_with_accepted_official(cert=2, rate=2000)
    set_clock("2026-09-08T19:45:00Z")
    declare_forfeit(ctx["game"]["id"], ctx["teams"][1]["id"])
    settled = validate_success(api_client.settle_assignment(
        ctx["assignment"]["id"], COORDINATOR))
    assert settled["status"] == "PAID"
    assert settled["final_pay_cents"] == 2000, (
        "FORFEITED pays a flat one hour at base rate; the 1.25 multiplier "
        "and the 90 scheduled minutes are ignored"
    )
    staff = validate_success(api_client.get_staff(
        ctx["official"]["id"], REC_ADMIN))
    assert staff["payroll_pending_cents"] == 0
    assert staff["payroll_paid_cents"] == 2000
    beta = validate_success(api_client.get_team(
        ctx["teams"][1]["id"], REC_ADMIN))
    assert beta["forfeit_count"] == 1
    assert beta["sportsmanship_points_total"] == 1
    assert beta["sportsmanship_rating_count"] == 1


def _disputed_then_finalized_game_with_official():
    """Game whose captains file mismatched reports (DISPUTED), resolved by a
    RecAdmin finalize at 2-1 with actual_duration_minutes 85; an L3 official
    (rate 2000) is ACCEPTED on it and becomes WORKED at finalize."""
    set_clock("2026-08-24T00:00:00Z")
    ctx = game_with_accepted_official(cert=3, rate=2000)
    set_clock("2026-09-08T19:45:00Z")
    validate_success(api_client.submit_score_report(
        ctx["game"]["id"], create_score_report_payload("HOME", 2, 1, 4),
        make_member_headers(ctx["captains"][0]["id"]),
    ), 201)
    disputed = validate_success(api_client.submit_score_report(
        ctx["game"]["id"], create_score_report_payload("AWAY", 2, 2, 5),
        make_member_headers(ctx["captains"][1]["id"]),
    ), 201)
    assert disputed["status"] == "DISPUTED"
    return ctx


def test_finalize_actual_duration_drives_final_pay():
    """PRD §3.6: "if the game is `FINAL`, the billable minutes are the game's
    `actual_duration_minutes` when recorded, otherwise its `duration_minutes`,
    multiplied by the base rate and certification multiplier, divided by 60,
    and rounded half-up"."

    Design: Difficulty/combinatorial_formula/official_pay_multi_input_branching
    """
    ctx = _disputed_then_finalized_game_with_official()
    final = finalize_game(ctx["game"]["id"], 2, 1, 4, 5, 85)
    assert final["status"] == "FINAL"
    assert final["final_home_score"] == 2
    assert final["final_away_score"] == 1
    settled = validate_success(api_client.settle_assignment(
        ctx["assignment"]["id"], COORDINATOR))
    # actual 85 minutes overrides the scheduled 90: 85 * 2000 * 1.5 / 60.
    assert settled["final_pay_cents"] == 4250


def test_provisional_uses_scheduled_duration_and_cert_multiplier():
    """PRD §3.6: "Its `provisional_pay_cents` is estimated at creation: the
    game's `duration_minutes` multiplied by the official's
    `base_hourly_rate_cents` and by a certification multiplier — 1.0 at level
    1, 1.25 at level 2, 1.5 at level 3 — divided by 60, rounded half-up to
    whole cents."
    PRD §3.6: "so the same assignment can settle for less than its
    provisional."

    Design: Difficulty/combinatorial_formula/official_pay_multi_input_branching
    """
    ctx = _disputed_then_finalized_game_with_official()
    assignment = validate_success(api_client.get_officiating_assignment(
        ctx["assignment"]["id"], REC_ADMIN))
    assert assignment["provisional_pay_cents"] == 4500  # 90 * 2000 * 1.5 / 60
    finalize_game(ctx["game"]["id"], 2, 1, 4, 5, 85)
    settled = validate_success(api_client.settle_assignment(
        ctx["assignment"]["id"], COORDINATOR))
    assert settled["final_pay_cents"] == 4250
    assert settled["final_pay_cents"] != 4500, (
        "the three pay branches (provisional 4500, FINAL-actual 4250, "
        "FORFEITED flat 2000) must diverge on the same inputs"
    )


def test_travel_buffer_zero_gap_rejected():
    """PRD §3.6: "The candidate is also checked against the official's travel
    buffer: considering each of the official's other assignments in
    `ASSIGNED`, `ACCEPTED`, or `WORKED` whose game is `SCHEDULED`,
    `PLAYED_PENDING_CONFIRM`, `DISPUTED`, `FINAL`, or `FORFEITED`, the
    candidate conflicts unless the gap between the candidate and that game's
    interval is at least 30 minutes in one direction or the other; a gap of
    exactly 30 minutes is allowed, while 29 is rejected with
    `ERR_OFFICIAL_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/official_travel_buffer_gap
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=4, min_teams=4)
    g1 = schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                       ctx["teams"][1]["id"], ctx["facility"]["id"],
                       "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    g2 = schedule_game(ctx["league"]["id"], ctx["teams"][2]["id"],
                       ctx["teams"][3]["id"], ctx["facility"]["id"],
                       "2026-09-08T19:30:00Z", "2026-09-08T20:30:00Z")
    official = create_official(rate=2000, cert=1)
    assignment = assign_official(g1["id"], official["id"])
    respond_assignment(assignment, "ACCEPT")
    # g2 starts 0 minutes after g1 ends: inside the 30-minute buffer.
    resp = api_client.create_officiating_assignment(
        g2["id"], {"staff_id": official["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_DOUBLE_BOOKED)


def test_travel_buffer_exactly_thirty_minutes_allowed():
    """PRD §3.6: "The candidate is also checked against the official's travel
    buffer: considering each of the official's other assignments in
    `ASSIGNED`, `ACCEPTED`, or `WORKED` whose game is `SCHEDULED`,
    `PLAYED_PENDING_CONFIRM`, `DISPUTED`, `FINAL`, or `FORFEITED`, the
    candidate conflicts unless the gap between the candidate and that game's
    interval is at least 30 minutes in one direction or the other; a gap of
    exactly 30 minutes is allowed, while 29 is rejected with
    `ERR_OFFICIAL_DOUBLE_BOOKED` (HTTP 409)."
    PRD §3.6: "The provisional amount is added to the official's
    `payroll_pending_cents`, which aggregates the provisional pay of all the
    official's assignments in `ASSIGNED`, `ACCEPTED`, or `WORKED` status."

    Design: Difficulty/resource_temporal_overlap/official_travel_buffer_gap
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=4, min_teams=4)
    other_facility = create_facility(name="Court 2")
    g1 = schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                       ctx["teams"][1]["id"], ctx["facility"]["id"],
                       "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    # g3 at a second facility (a 20:00 start at the same facility would
    # overlap the 19:30-20:30 booking there); the travel buffer applies to
    # the official's games regardless of facility.
    g3 = schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                       ctx["teams"][1]["id"], other_facility["id"],
                       "2026-09-08T20:00:00Z", "2026-09-08T21:00:00Z")
    official = create_official(rate=2000, cert=1)
    assignment = assign_official(g1["id"], official["id"])
    respond_assignment(assignment, "ACCEPT")
    # Gap from g1's 19:30 end to g3's 20:00 start is exactly 30 minutes.
    data = validate_success(api_client.create_officiating_assignment(
        g3["id"], {"staff_id": official["id"]}, COORDINATOR), 201)
    assert data["provisional_pay_cents"] == 2000  # 60 * 2000 * 1.0 / 60
    staff = validate_success(api_client.get_staff(
        official["id"], REC_ADMIN))
    assert staff["payroll_pending_cents"] == 5000  # 3000 (g1) + 2000 (g3)


def test_assignment_decline_reverses_pending_and_double_respond():
    """PRD §3.6: "The assigned official responds to an assignment, addressed
    by its `officiating_assignment_id`, with `response` `ACCEPT` or `DECLINE`;
    only the assignee may respond (`ERR_FORBIDDEN` otherwise) and only while
    the assignment is `ASSIGNED` (`ERR_INVALID_STATE` otherwise). Accepting
    moves the assignment `ASSIGNED → ACCEPTED`. Declining moves it to
    `DECLINED` and subtracts its provisional pay back out of
    `payroll_pending_cents`."

    Design: Corner/state_machines/assignment_decline_reverses_pending_and_double_respond
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    official = create_official(rate=2000, cert=3)
    assignment = assign_official(ctx["game"]["id"], official["id"])
    assert assignment["provisional_pay_cents"] == 4500  # 90 * 2000 * 1.5 / 60
    declined = respond_assignment(assignment, "DECLINE")
    assert declined["status"] == "DECLINED"
    staff = validate_success(api_client.get_staff(
        official["id"], REC_ADMIN))
    assert staff["payroll_pending_cents"] == 0, (
        "the 4500 provisional is fully reversed on DECLINE"
    )
    resp = api_client.respond_assignment(
        assignment["id"], {"response": "ACCEPT"},
        make_staff_headers(official["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_assignment_settle_before_worked_returns_invalid_state():
    """PRD §3.6: "Settlement requires `WORKED` status (otherwise
    `ERR_INVALID_STATE`) and computes `final_pay_cents`"."

    Design: Corner/state_machines/assignment_settle_before_worked_returns_invalid_state
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = game_with_accepted_official(cert=2, rate=2000)
    resp = api_client.settle_assignment(ctx["assignment"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assignment = validate_success(api_client.get_officiating_assignment(
        ctx["assignment"]["id"], REC_ADMIN))
    assert assignment["status"] == "ACCEPTED"
    staff = validate_success(api_client.get_staff(
        ctx["official"]["id"], REC_ADMIN))
    assert staff["payroll_paid_cents"] == 0


def test_non_assigned_official_cannot_respond():
    """PRD §3.6: "The assigned official responds to an assignment, addressed
    by its `officiating_assignment_id`, with `response` `ACCEPT` or `DECLINE`;
    only the assignee may respond (`ERR_FORBIDDEN` otherwise) and only while
    the assignment is `ASSIGNED` (`ERR_INVALID_STATE` otherwise)."

    Design: Corner/validations/non_assigned_official_cannot_respond
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    official_1 = create_official(rate=2000, cert=1, name="Ref One")
    official_2 = create_official(rate=2000, cert=1, name="Ref Two")
    assignment = assign_official(ctx["game"]["id"], official_1["id"])
    resp = api_client.respond_assignment(
        assignment["id"], {"response": "ACCEPT"},
        make_staff_headers(official_2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_error_assignment_limit_two():
    """PRD §3.6: "A game may carry at most 2 non-terminal assignments —
    `ASSIGNED`, `ACCEPTED`, or `WORKED` (otherwise
    `ERR_ASSIGNMENT_LIMIT_REACHED`)."

    Design: Corner/errors/error_assignment_limit_two
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    officials = [create_official(rate=2000, cert=1, name=f"Ref {i}")
                 for i in range(3)]
    assign_official(ctx["game"]["id"], officials[0]["id"])
    assign_official(ctx["game"]["id"], officials[1]["id"])
    resp = api_client.create_officiating_assignment(
        ctx["game"]["id"], {"staff_id": officials[2]["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_LIMIT_REACHED)
    _, meta = validate_paginated(api_client.list_officiating_assignments(
        COORDINATOR, params={"game_id": ctx["game"]["id"]}))
    assert meta["total_count"] == 2


def test_error_staff_role_mismatch_on_assignment_and_class():
    """PRD §3.6: "The target must be an `OFFICIAL` (otherwise
    `ERR_STAFF_NOT_OFFICIAL`, HTTP 422)."
    PRD §3.8: "The instructor must be an `INSTRUCTOR` (otherwise
    `ERR_STAFF_NOT_INSTRUCTOR`) whose `certified_class_types` include the
    class's `class_type` (otherwise `ERR_INSTRUCTOR_NOT_CERTIFIED`)."

    Design: Corner/errors/error_staff_role_mismatch_on_assignment_and_class
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    instructor = create_instructor(rate=3000, class_types=("YOGA",))
    official = create_official(rate=2000, cert=2)
    resp1 = api_client.create_officiating_assignment(
        ctx["game"]["id"], {"staff_id": instructor["id"]}, COORDINATOR)
    validate_error(resp1, ApiErrorId.ERR_STAFF_NOT_OFFICIAL)
    resp2 = api_client.create_fitness_class(
        {"title": "Bad", "class_type": "YOGA",
         "instructor_staff_id": official["id"],
         "facility_id": ctx["facility"]["id"],
         "start_at": "2026-09-15T18:00:00Z",
         "end_at": "2026-09-15T19:00:00Z", "capacity": 5},
        REC_ADMIN,
    )
    validate_error(resp2, ApiErrorId.ERR_STAFF_NOT_INSTRUCTOR)


def test_staff_role_cannot_settle_assignment():
    """PRD §2.1: "If the role is valid but not permitted for the endpoint — or
    an entity-backed ownership check fails — the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.8: "When a request fails multiple checks, the error returned is
    determined by a fixed priority order — lower priority number wins."

    Design: Corner/rbac/staff_role_cannot_settle_assignment
    """
    official = create_official(rate=2000, cert=1)
    # Settle is a LeagueCoordinator operation; the role check (priority 2)
    # fires before the existence check (priority 3) even on a made-up id.
    resp = api_client.settle_assignment(
        NON_EXISTENT_UUID, make_staff_headers(official["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

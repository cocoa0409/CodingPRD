"""Running the session: attendance, the no-show ladder, contract billing and the void."""
from test_helpers import (
    complete_session,
    create_active_contract,
    deliver_session,
    create_compliant_coach,
    enroll_athlete,
    fetch_athlete,
    fetch_enrollment,
    fetch_group_session,
    fetch_membership_package,
    fetch_team_contract,
    link_athlete_to_contract,
    lock_session_roster,
    register_athlete,
    run_movement_screen,
    sell_package,
    setup_athlete_with_two_strikes,
    setup_cleared_athlete,
    setup_session_with_coach,
    start_session_at_start_at,
    validate_error,
    validate_success,
)

CONTRACT_WINDOWS = (("2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z"),
                    ("2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z"),
                    ("2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z"))


def _build_contract_scenario(organization_name, rosters):
    """One ACTIVE contract, two linked athletes, and one contract-funded session per
    entry of `rosters` (each entry naming which athletes are booked).  Every roster is
    locked while the clock is still before the first start_at.
    Returns (contract, athletes, sessions, enrollments, coach_headers)."""
    coach, _cert, coach_headers = create_compliant_coach(full_name="Grace Kim")
    contract = create_active_contract(
        organization_name=organization_name, organization_type="SCHOOL",
        contracted_sessions=8, base_rate_cents=18000, offsite_allowance=0,
        term_start="2026-01-01", term_end="2026-12-31")

    athletes = []
    for name in ("Amara Bell", "Bo Nguyen"):
        athlete = register_athlete(full_name=name, date_of_birth="2010-01-15")
        run_movement_screen(athlete["id"], coach_headers)
        link_athlete_to_contract(contract["id"], athlete["id"])
        athletes.append(athlete)

    sessions, enrollments = [], []
    for index, roster in enumerate(rosters):
        start_at, end_at = CONTRACT_WINDOWS[index]
        session = setup_session_with_coach(
            coach["id"], start_at=start_at, end_at=end_at, station_count=3,
            max_athletes=10, team_contract_id=contract["id"])
        booked = [enroll_athlete(athletes[slot]["id"], session["id"])
                  for slot in roster]
        lock_session_roster(session["id"])
        sessions.append(fetch_group_session(session["id"]))
        enrollments.append(booked)
    return contract, athletes, sessions, enrollments, coach_headers


def _deliver(session, coach_headers, enrollment_ids):
    """Start the already-locked session at its own start_at, attend every named row,
    then complete it."""
    return deliver_session(session, coach_headers,
                           attend_enrollment_ids=enrollment_ids, lock_first=False)


def test_01_the_first_completion_prices_both_slots_at_the_lowest_tier(api):
    """With nothing delivered yet the tier is TIER_1 and the base rate applies unscaled.

    "The tier is chosen from that snapshot alone: `TIER_1` when the delivered-before
    figure is under 2, `TIER_2` when it is at least 2 and under 5, and `TIER_3`
    otherwise."

    Design: Difficulty/combinatorial_formula/contract_rate_tier_read_before_delivered_counter_increment
    """
    contract, _athletes, sessions, enrollments, coach_headers = _build_contract_scenario(
        "Northside HS", rosters=[(0, 1)])
    assert enrollments[0][0]["funding_source"] == "TEAM_CONTRACT"
    assert enrollments[0][0]["charge_cents"] == 0
    before = fetch_team_contract(contract["id"])
    assert before["sessions_delivered"] == 0
    assert before["sessions_reserved"] == 2

    completed = _deliver(sessions[0], coach_headers,
                         [row["id"] for row in enrollments[0]])

    assert completed["session_status"] == "COMPLETED"
    assert completed["rate_tier_applied"] == "TIER_1"
    assert completed["billed_rate_cents"] == 18000
    assert completed["delivered_slots_at_completion"] == 2

    after = fetch_team_contract(contract["id"])
    assert after["sessions_delivered"] == 2
    assert after["sessions_reserved"] == 0
    assert after["sessions_available"] == 6
    assert after["billed_amount_cents"] == 36000
    assert after["status"] == "ACTIVE"


def test_02_the_second_completion_reads_the_counter_before_incrementing_it(api):
    """The tier comes from the delivered figure as it stood before this completion.

    "The contract's `sessions_delivered` is read **once, before any increment**."

    "One rate is computed for the whole completion — it is emphatically **not**
    re-tiered slot by slot."

    Design: Difficulty/combinatorial_formula/contract_rate_tier_read_before_delivered_counter_increment
    """
    contract, _athletes, sessions, enrollments, coach_headers = _build_contract_scenario(
        "Northside HS", rosters=[(0, 1), (0, 1)])

    first = _deliver(sessions[0], coach_headers, [row["id"] for row in enrollments[0]])
    assert first["rate_tier_applied"] == "TIER_1"

    second = _deliver(sessions[1], coach_headers, [row["id"] for row in enrollments[1]])

    assert second["rate_tier_applied"] == "TIER_2"
    assert second["billed_rate_cents"] == 16560
    assert second["delivered_slots_at_completion"] == 2

    after = fetch_team_contract(contract["id"])
    assert after["sessions_delivered"] == 4
    assert after["sessions_reserved"] == 0
    assert after["sessions_available"] == 4
    assert after["billed_amount_cents"] == 69120, \
        "36000 at the first tier plus twice 16560 at the second"
    assert after["status"] == "ACTIVE"
    assert enrollments[1][0]["funding_source"] == "TEAM_CONTRACT"
    assert enrollments[1][0]["charge_cents"] == 0


def test_03_the_third_strike_carries_the_raised_multiplier_and_suspends_the_athlete(api):
    """The post-increment strike index of three sets both the fee and the suspension.

    "The list price of a session is 4,500 cents and the no-show fee is 27.5 per cent
    of it, scaled by a strike multiplier read from the post-increment strike index: a
    first or second strike carries a multiplier of 1.0, a third strike carries 1.5,
    and a fourth or any subsequent strike carries 2.0."

    Design: Difficulty/transitive_cascade/third_no_show_strike_cascades_suspension_refund_and_waitlist_promotion
    """
    athlete, staff, coach_headers, earlier = setup_athlete_with_two_strikes(
        athlete_overrides={"full_name": "Ade Balogun", "date_of_birth": "2010-01-15"})
    assert athlete["no_show_strikes"] == 2
    assert [row["no_show_fee_cents"] for row in earlier] == [1238, 1238]

    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-12T10:00:00Z", end_at="2026-08-12T11:00:00Z",
        station_count=3, max_athletes=10)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    lock_session_roster(session["id"])
    start_session_at_start_at(fetch_group_session(session["id"]), coach_headers)

    third = validate_success(api.no_show_enrollment(enrollment["id"], coach_headers))

    assert third["status"] == "NO_SHOW"
    assert third["strike_index_at_no_show"] == 3
    assert third["no_show_fee_cents"] == 1856, \
        "4500 times 0.275 times 1.5 is 1237.5 times 1.5, rounded half up"
    reread_athlete = fetch_athlete(athlete["id"])
    assert reread_athlete["no_show_strikes"] == 3
    assert reread_athlete["no_show_count"] == 3
    assert reread_athlete["membership_status"] == "SUSPENDED"


def test_04_the_suspension_refunds_a_credit_and_promotes_a_stranger(api):
    """One no-show reaches an unrelated athlete on an unrelated session two hops away.

    "Then, when the strike counter reaches 3, the athlete's membership machine fires."

    "A single no-show can therefore promote a stranger onto a different session two
    steps away."

    Design: Difficulty/transitive_cascade/third_no_show_strike_cascades_suspension_refund_and_waitlist_promotion
    """
    athlete, staff, coach_headers, _earlier = setup_athlete_with_two_strikes(
        athlete_overrides={"full_name": "Ade Balogun", "date_of_birth": "2010-01-15"})
    package = sell_package(athlete["id"], sessions_purchased=1, price_cents=9000,
                          expires_on="2026-12-31")

    later_session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=1)
    package_funded = enroll_athlete(athlete["id"], later_session["id"])
    assert package_funded["funding_source"] == "MEMBERSHIP_PACKAGE"
    assert fetch_membership_package(package["id"])["status"] == "DEPLETED"

    stranger = register_athlete(full_name="Bea Toma", date_of_birth="2010-01-15")
    run_movement_screen(stranger["id"], coach_headers)
    waitlisted = enroll_athlete(stranger["id"], later_session["id"],
                                request_waitlist=True)
    assert waitlisted["status"] == "WAITLISTED"

    third_session = setup_session_with_coach(
        staff["id"], start_at="2026-08-12T10:00:00Z", end_at="2026-08-12T11:00:00Z",
        station_count=3, max_athletes=10)
    doomed = enroll_athlete(athlete["id"], third_session["id"])
    lock_session_roster(third_session["id"])
    start_session_at_start_at(fetch_group_session(third_session["id"]), coach_headers)

    validate_success(api.no_show_enrollment(doomed["id"], coach_headers))

    assert fetch_athlete(athlete["id"])["membership_status"] == "SUSPENDED"
    canceled = fetch_enrollment(package_funded["id"])
    assert canceled["status"] == "CANCELED"
    assert canceled["cancel_reason"] == "ATHLETE_SUSPENDED"
    refunded = fetch_membership_package(package["id"])
    assert refunded["status"] == "ACTIVE"
    assert refunded["sessions_remaining"] == 1
    assert refunded["sessions_reserved"] == 0

    promoted = fetch_enrollment(waitlisted["id"])
    assert promoted["status"] == "RESERVED"
    assert promoted["promoted_from_waitlist"] is True
    assert promoted["funding_source"] == "DROP_IN"
    assert promoted["charge_cents"] == 4500
    reread = fetch_group_session(later_session["id"])
    assert reread["reserved_count"] == 1
    assert reread["waitlisted_count"] == 0


def test_05_the_void_reverses_the_money_from_the_stored_snapshots(
        api, performance_director_headers):
    """Voiding the middle completion returns twice the persisted rate, not a fresh one.

    "The contract reversal **must use the stored snapshots** and never a recomputed
    rate: `billed_amount_cents` is reduced by the persisted `billed_rate_cents`
    multiplied by the persisted `delivered_slots_at_completion`, `sessions_delivered`
    is reduced by `delivered_slots_at_completion`, and `sessions_reserved` is
    increased by the same amount."

    Design: Difficulty/compensating_invariant/contract_slot_and_money_ledger_reversed_from_snapshots_on_void_completion
    """
    contract, _athletes, sessions, enrollments, coach_headers = _build_contract_scenario(
        "Riverside Club", rosters=[(0, 1), (0, 1), (0,)])
    for session, booked in zip(sessions, enrollments):
        _deliver(session, coach_headers, [row["id"] for row in booked])

    before = fetch_team_contract(contract["id"])
    assert before["sessions_delivered"] == 5
    assert before["billed_amount_cents"] == 85680

    voided = validate_success(api.void_completion(
        sessions[1]["id"], {"void_reason": "Attendance captured against the wrong roster"},
        performance_director_headers))
    assert voided["session_status"] == "IN_PROGRESS"

    after = fetch_team_contract(contract["id"])
    assert after["billed_amount_cents"] == 52560
    assert after["billed_amount_cents"] != 55080, \
        "re-deriving the rate at the later tier is explicitly not the contract"
    assert after["sessions_delivered"] == 3
    assert after["sessions_reserved"] == 2
    assert after["sessions_available"] == 3
    assert (after["sessions_available"] + after["sessions_reserved"]
            + after["sessions_delivered"]) == after["contracted_sessions"]
    assert after["status"] == "ACTIVE"


def test_06_the_void_clears_its_own_snapshots_and_reverts_the_attendance(
        api, performance_director_headers):
    """Only the voided session is unwound; its neighbours keep their pinned rates.

    "On success `session_status` moves `COMPLETED → IN_PROGRESS`, and every
    `ATTENDED` enrollment reverts to `RESERVED` with the athlete's `attended_count`
    reduced by one for each and each package-funded row moving a credit from
    `sessions_consumed` back to `sessions_reserved`."

    "Finally `billed_rate_cents`, `rate_tier_applied` and
    `delivered_slots_at_completion` are all cleared to null, and the session's
    `version` increments."

    Design: Difficulty/compensating_invariant/contract_slot_and_money_ledger_reversed_from_snapshots_on_void_completion
    """
    _contract, athletes, sessions, enrollments, coach_headers = _build_contract_scenario(
        "Riverside Club", rosters=[(0, 1), (0, 1), (0,)])
    completed = [_deliver(session, coach_headers, [row["id"] for row in booked])
                 for session, booked in zip(sessions, enrollments)]
    version_before = completed[1]["version"]

    validate_success(api.void_completion(
        sessions[1]["id"], {"void_reason": "Attendance captured against the wrong roster"},
        performance_director_headers))

    reread = fetch_group_session(sessions[1]["id"])
    assert reread["session_status"] == "IN_PROGRESS"
    assert reread["billed_rate_cents"] is None
    assert reread["rate_tier_applied"] is None
    assert reread["delivered_slots_at_completion"] is None
    assert reread["version"] == version_before + 1
    for row in enrollments[1]:
        assert fetch_enrollment(row["id"])["status"] == "RESERVED"

    untouched_first = fetch_group_session(sessions[0]["id"])
    assert untouched_first["billed_rate_cents"] == 18000
    assert untouched_first["rate_tier_applied"] == "TIER_1"
    untouched_last = fetch_group_session(sessions[2]["id"])
    assert untouched_last["billed_rate_cents"] == 16560
    assert untouched_last["rate_tier_applied"] == "TIER_2"

    assert fetch_athlete(athletes[0]["id"])["attended_count"] == 2
    assert fetch_athlete(athletes[1]["id"])["attended_count"] == 1


def test_07_attendance_cannot_be_marked_before_the_session_is_running(api):
    """The enrollment is RESERVED but the session has not started, so the state is wrong.

    "A `Coach` marks a `RESERVED` enrollment as attended while the session is
    `IN_PROGRESS`."

    Design: Corner/state_machines/enrollment_attend_precondition_requires_session_in_progress
    """
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides={"full_name": "Early Attend Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach Early")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=8)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    assert fetch_group_session(session["id"])["session_status"] == "SCHEDULED"

    validate_error(api.attend_enrollment(enrollment["id"], coach_headers),
                   "ERR_INVALID_STATE", expected_status=409)

    assert fetch_enrollment(enrollment["id"])["status"] == "RESERVED"
    assert fetch_athlete(athlete["id"])["attended_count"] == 0


def test_08_completion_sweeps_the_remaining_reserved_row_to_a_no_show(api):
    """Nobody was marked present, so the completion charges the absentee itself.

    "Every enrollment still `RESERVED` is swept to `NO_SHOW` in ascending
    `created_at` order, each one running the full no-show cascade above, fee and
    strike and possible suspension included."

    Design: Corner/state_machines/group_session_completion_side_effects_sweep_reserved_rows_to_no_show
    """
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides={"full_name": "Sweep Athlete", "date_of_birth": "2009-02-02"},
        coach_name="Coach Sweep")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=8)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    lock_session_roster(session["id"])
    start_session_at_start_at(fetch_group_session(session["id"]), coach_headers)

    completed = complete_session(session["id"], coach_headers)

    assert completed["session_status"] == "COMPLETED"
    assert completed["no_show_count"] == 1
    assert completed["attended_count"] == 0
    swept = fetch_enrollment(enrollment["id"])
    assert swept["status"] == "NO_SHOW"
    assert swept["strike_index_at_no_show"] == 1
    assert swept["no_show_fee_cents"] == 1238, "4500 times 0.275 times 1.0, rounded half up"
    reread_athlete = fetch_athlete(athlete["id"])
    assert reread_athlete["no_show_count"] == 1
    assert reread_athlete["no_show_strikes"] == 1
    assert reread_athlete["membership_status"] == "ACTIVE"


def test_09_a_completion_carrying_a_no_show_can_never_be_voided(
        api, performance_director_headers):
    """One absentee is enough to freeze the completion permanently.

    "The session must be `COMPLETED`, and the reversal is refused outright when
    **any** enrollment on the session was marked `NO_SHOW`, because the strike
    counters and the assessed fees against those athletes cannot be unwound; that
    refusal is `ERR_VOID_BLOCKED_BY_NO_SHOW`."

    Design: Corner/endpoints/void_completion_blocked_when_any_enrollment_was_marked_no_show
    """
    athlete, staff, coach_headers = setup_cleared_athlete(
        athlete_overrides={"full_name": "Void Block Athlete",
                           "date_of_birth": "2009-02-02"},
        coach_name="Coach VoidBlock")
    session = setup_session_with_coach(
        staff["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=8)
    enrollment = enroll_athlete(athlete["id"], session["id"])
    lock_session_roster(session["id"])
    start_session_at_start_at(fetch_group_session(session["id"]), coach_headers)
    marked = validate_success(api.no_show_enrollment(enrollment["id"], coach_headers))
    assert marked["status"] == "NO_SHOW"
    completed = complete_session(session["id"], coach_headers)
    assert completed["session_status"] == "COMPLETED"

    validate_error(
        api.void_completion(session["id"],
                            {"void_reason": "Coach recorded attendance on the wrong session"},
                            performance_director_headers),
        "ERR_VOID_BLOCKED_BY_NO_SHOW", expected_status=409)

    reread = fetch_group_session(session["id"])
    assert reread["session_status"] == "COMPLETED"
    assert reread["no_show_count"] == 1
    intact = fetch_enrollment(enrollment["id"])
    assert intact["status"] == "NO_SHOW"
    assert intact["no_show_fee_cents"] == 1238


def test_10_the_coach_who_completes_a_session_may_not_void_it(api):
    """The reversal is the director's alone, and the role check runs before the state check.

    "Only the `PerformanceDirector` may reverse an erroneous completion, supplying a
    `void_reason`."

    Design: Corner/rbac/coach_cannot_void_completion_of_a_group_session
    """
    coach, _cert, coach_headers = create_compliant_coach(
        full_name="Coach Unauthorised")
    session = setup_session_with_coach(
        coach["id"], start_at="2026-08-20T16:00:00Z", end_at="2026-08-20T17:00:00Z",
        station_count=3, max_athletes=8)

    validate_error(
        api.void_completion(session["id"],
                            {"void_reason": "Coach attempting an unauthorised reversal"},
                            coach_headers),
        "ERR_UNAUTHORIZED", expected_status=403)

    assert fetch_group_session(session["id"])["session_status"] == "SCHEDULED", \
        "the still-scheduled session never reported a state error"

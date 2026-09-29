"""Offering games to officials, the stipend, confirmation, and postponement."""
from test_helpers import (
    ApiErrorId,
    assert_official_assignment,
    assert_same_instant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def test_postponing_a_confirmed_contest_drops_it_back_and_withdraws_its_officials(
    api, admin_headers
):
    """PRD §3.9: "The association may move a `CONFIRMED` contest to a new date,
    supplying `new_starts_at`, `new_ends_at`, and optionally a `postpone_note`."
    PRD §3.9: "A postponement rewrites the contest's `starts_at` and `ends_at` from
    the two supplied instants, drops it `CONFIRMED → SCHEDULED` with `hold_reason`
    set to `ADMIN_POSTPONE` and `accepted_official_count` reset to 0, moves every
    assignment on it standing at `OFFERED` or `ACCEPTED` to `WITHDRAWN` while
    decrementing the relevant official's `accepted_assignment_count` by 1 for each
    formerly accepted one, and cancels every trip on it standing at `REQUESTED` or
    `APPROVED` with `cancelled_reason` `CONTEST_HOLD_CASCADE`, returning each
    formerly approved trip's `release_minutes` to its school's
    `release_minutes_used`."

    Design: Difficulty/non_linear_state_machine/contest_confirm_then_postpone_returns_to_scheduled_and_reopens_staffing
    """
    ctx = fx.setup_confirmed_contest(required_officials=2)
    assert ctx["contest"]["status"] == "CONFIRMED"

    postponed = validate_success(
        api.postpone_contest(
            ctx["contest"]["id"],
            {"new_starts_at": "2026-10-10T18:00:00Z",
             "new_ends_at": "2026-10-10T20:00:00Z",
             "postpone_note": "field unplayable"},
            admin_headers,
        ),
        200,
    )

    assert postponed["status"] == "SCHEDULED"
    assert postponed["hold_reason"] == "ADMIN_POSTPONE"
    assert postponed["accepted_official_count"] == 0
    assert_same_instant(postponed["starts_at"], "2026-10-10T18:00:00Z", "starts_at")
    assert_same_instant(postponed["ends_at"], "2026-10-10T20:00:00Z", "ends_at")
    for assignment in ctx["assignments"]:
        assert fx.read_assignment(assignment["id"])["status"] == "WITHDRAWN"


def test_postponed_contest_reopens_staffing_and_relocks_a_stipend(api, admin_headers):
    """PRD §3.9: "The whole slate of officials and buses is therefore rebuilt from
    scratch after a postponement."
    PRD §3.7: "An `ACCEPT` moves it `OFFERED → ACCEPTED`, stamps `responded_at`,
    locks the travel stipend into `stipend_cents`, increments the contest's
    `accepted_official_count` by 1 and the official's `accepted_assignment_count` by
    1, and — when that count reaches the season's `required_officials` — promotes the
    contest `SCHEDULED → OFFICIALS_ASSIGNED` and clears its `hold_reason` back to
    null."
    PRD §3.7: "The certification base is 4000 cents for a `LEVEL_1` official, 6000
    for `LEVEL_2`, and 8500 for `LEVEL_3`."

    Design: Difficulty/non_linear_state_machine/contest_confirm_then_postpone_returns_to_scheduled_and_reopens_staffing
    """
    ctx = fx.setup_confirmed_contest(required_officials=2)
    fx.get_success_data(
        api.postpone_contest(
            ctx["contest"]["id"],
            {"new_starts_at": "2026-10-10T18:00:00Z",
             "new_ends_at": "2026-10-10T20:00:00Z"},
            admin_headers,
        )
    )
    official = ctx["officials"][0]

    reoffered = fx.offer_official(ctx["contest"]["id"], official["id"])
    accepted = validate_success(
        api.respond_to_assignment(reoffered["id"], {"response": "ACCEPT"},
                                  fx.make_official_headers(official["id"])),
        200,
    )

    assert_official_assignment(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["stipend_cents"] == 9980, (
        "LEVEL_2 base 6000 at the TIER_A multiplier plus 40 miles at 62 cents"
    )
    contest = fx.read_contest(ctx["contest"]["id"])
    assert contest["accepted_official_count"] == 1
    assert contest["status"] == "SCHEDULED", (
        "one acceptance is short of the two-official quorum"
    )


def test_suspended_home_school_blocks_confirmation_before_the_quorum_check(api):
    """PRD §3.7: "Three conditions apply. The governing season must stand at
    `REGULAR_SEASON` or `PLAYOFFS`, or the answer is `ERR_SEASON_NOT_OPEN`. The home
    school's `sanction_status` must not be `SUSPENDED`, or the answer is
    `ERR_SCHOOL_SANCTIONED`. And `accepted_official_count` must have reached the
    season's `required_officials`, or the answer is `ERR_OFFICIALS_INCOMPLETE`."
    PRD §3.9: "the school's sanction posture is re-derived — a `forfeit_count` that
    has reached 2 while still below 4 moves the school `GOOD_STANDING → PROBATION`,
    and a `forfeit_count` that has reached 4 moves it `PROBATION → SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_sanction_gate_outranks_the_officials_completeness_gate
    """
    ctx = fx.setup_school_with_forfeits(4)
    day = ctx["next_contest_date"]
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                f"{day}T18:00:00Z", f"{day}T20:00:00Z")
    assert contest["accepted_official_count"] == 0

    response = api.confirm_contest(contest["id"],
                                   fx.make_director_headers(ctx["home"]["id"]))

    validate_error(response, ApiErrorId.ERR_SCHOOL_SANCTIONED.value, 409)


def test_confirmation_sanction_gate_pre_empts_the_officials_completeness_gate(api):
    """PRD §2.6: "Checks are evaluated in the following fixed order, and the first
    failing check determines the response."
    PRD §2.6: "The governing school's `sanction_status` is not `SUSPENDED` —
    otherwise `ERR_SCHOOL_SANCTIONED` (409)."
    PRD §2.6: "`accepted_official_count` has reached the season's
    `required_officials` — otherwise `ERR_OFFICIALS_INCOMPLETE` (409)."
    PRD §3.7: "Confirmation is declared from `SCHEDULED` as well as from
    `OFFICIALS_ASSIGNED`, and that is intentional: it means an understaffed contest
    reaches the substantive quorum check rather than being turned away by a generic
    state error."

    Design: Difficulty/priority_pair_validation_conflict/confirm_sanction_gate_outranks_the_officials_completeness_gate
    """
    ctx = fx.setup_school_with_forfeits(4)
    day = ctx["next_contest_date"]
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                f"{day}T18:00:00Z", f"{day}T20:00:00Z")

    response = api.confirm_contest(contest["id"],
                                   fx.make_director_headers(ctx["home"]["id"]))

    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_OFFICIALS_INCOMPLETE.value
    school = fx.read_school(ctx["home"]["id"])
    assert school["forfeit_count"] == 4
    assert school["sanction_status"] == "SUSPENDED"
    after = fx.read_contest(contest["id"])
    assert after["status"] == "SCHEDULED"
    assert after["accepted_official_count"] == 0


def _contest_under_a_practice_open_season():
    set_clock("2026-09-10T09:00:00Z")
    home = fx.create_school(name="North High")
    away = fx.create_school(name="South High", region_code="R-SOUTH")
    season = fx.create_season(required_officials=1)
    fx.advance_season(season["id"], "PRACTICE_OPEN")
    official = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_1")
    contest = fx.create_contest(season["id"], home["id"], away["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    return {"home": home, "away": away, "season": season,
            "official": official, "contest": contest}


def test_officiating_offer_is_refused_while_the_season_is_only_practice_open(
    api, coordinator_headers
):
    """PRD §3.7: "Offers are admitted only while the governing season stands at
    `REGULAR_SEASON` or `PLAYOFFS`, and otherwise draw `ERR_SEASON_NOT_OPEN`."
    PRD §3.1: "Contest confirmation and officiating offers are admitted only while
    it stands at `REGULAR_SEASON` or `PLAYOFFS`."

    Design: Difficulty/cross_entity_state_dependency/officiating_offer_is_gated_on_the_parent_season_status
    """
    ctx = _contest_under_a_practice_open_season()
    assert ctx["contest"]["status"] == "SCHEDULED"

    response = api.offer_official(
        ctx["contest"]["id"],
        {"official_id": ctx["official"]["id"],
         "expected_contest_version": ctx["contest"]["version"]},
        coordinator_headers,
    )

    validate_error(response, ApiErrorId.ERR_SEASON_NOT_OPEN.value, 409)
    rows, _meta = validate_paginated(
        api.list_official_assignments(coordinator_headers,
                                      {"contest_id": ctx["contest"]["id"]})
    )
    assert rows == [], "a refused offer must not mint an assignment"


def test_the_same_offer_succeeds_once_the_season_reaches_regular_season(
    api, coordinator_headers
):
    """PRD §3.1: "From `PRACTICE_OPEN` it may move to `REGULAR_SEASON`, but only
    once the clock's UTC date has reached or passed `first_contest_date`."
    PRD §3.7: "An accepted offer opens at `OFFERED` with `stipend_cents` and
    `responded_at` both null, and the parent contest's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/officiating_offer_is_gated_on_the_parent_season_status
    """
    ctx = _contest_under_a_practice_open_season()
    payload = {"official_id": ctx["official"]["id"],
               "expected_contest_version": ctx["contest"]["version"]}
    api.offer_official(ctx["contest"]["id"], payload, coordinator_headers)

    fx.advance_season(ctx["season"]["id"], "REGULAR_SEASON")
    response = api.offer_official(ctx["contest"]["id"], payload, coordinator_headers)

    assignment = validate_success(response, 201)
    assert assignment["status"] == "OFFERED"
    assert assignment["stipend_cents"] is None
    assert assignment["responded_at"] is None
    assert fx.read_season(ctx["season"]["id"])["status"] == "REGULAR_SEASON"


def _three_venues_and_one_official():
    set_clock("2026-09-10T09:00:00Z")
    north = fx.create_school(name="North High")
    south = fx.create_school(name="South High", region_code="R-SOUTH")
    east = fx.create_school(name="East High", region_code="R-EAST")
    season = fx.create_season(required_officials=2)
    fx.open_season_to_regular(season["id"])
    official = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_2")
    # P is the booked game: buffered 16:30Z to 21:30Z.
    contest_p = fx.create_contest(season["id"], north["id"], south["id"],
                                  "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    # Q's buffered window opens exactly at 21:30Z.
    contest_q = fx.create_contest(season["id"], south["id"], east["id"],
                                  "2026-09-20T23:00:00Z", "2026-09-21T01:00:00Z",
                                  headers=fx.make_director_headers(south["id"]))
    # R's buffered window opens at 21:29Z, one minute inside P's.
    contest_r = fx.create_contest(season["id"], east["id"], north["id"],
                                  "2026-09-20T22:59:00Z", "2026-09-21T00:59:00Z",
                                  headers=fx.make_director_headers(east["id"]))
    fx.offer_official(contest_p["id"], official["id"])
    return {"official": official, "p": contest_p, "q": contest_q, "r": contest_r}


def test_officials_buffered_windows_that_merely_touch_are_admitted(api, coordinator_headers):
    """PRD §3.7: "Each contest an official is committed to is widened by a
    ninety-minute travel buffer on **both** ends, and the resulting window is
    half-open — the lower bound counts, the upper bound does not."
    PRD §3.7: "Because the comparison is strict on both sides, a second contest
    whose buffered window begins exactly when the first buffered window ends is
    admitted — the opposite outcome from the touching case in the bus-fleet rule of
    §3.8."

    Design: Difficulty/resource_temporal_overlap/official_half_open_buffered_window_admits_touching_but_rejects_one_minute_of_overlap
    """
    ctx = _three_venues_and_one_official()

    response = api.offer_official(
        ctx["q"]["id"],
        {"official_id": ctx["official"]["id"],
         "expected_contest_version": fx.contest_version(ctx["q"]["id"])},
        coordinator_headers,
    )

    assignment = validate_success(response, 201)
    assert assignment["status"] == "OFFERED"
    rows, _meta = validate_paginated(
        api.list_official_assignments(coordinator_headers,
                                      {"official_id": ctx["official"]["id"],
                                       "limit": 100})
    )
    assert len(rows) == 2


def test_one_minute_of_positive_overlap_double_books_the_official(api, coordinator_headers):
    """PRD §3.7: "Two buffered windows collide only when they overlap with positive
    measure, meaning each one's start falls strictly before the other's end. A
    collision is refused with `ERR_OFFICIAL_DOUBLE_BOOKED`."
    PRD §3.7: "The official's commitments are every assignment of theirs standing at
    `OFFERED` or `ACCEPTED`, across every season; assignments that have been
    `DECLINED` or `WITHDRAWN` free the time back up."

    Design: Difficulty/resource_temporal_overlap/official_half_open_buffered_window_admits_touching_but_rejects_one_minute_of_overlap
    """
    ctx = _three_venues_and_one_official()
    fx.offer_official(ctx["q"]["id"], ctx["official"]["id"])

    response = api.offer_official(
        ctx["r"]["id"],
        {"official_id": ctx["official"]["id"],
         "expected_contest_version": fx.contest_version(ctx["r"]["id"])},
        coordinator_headers,
    )

    validate_error(response, ApiErrorId.ERR_OFFICIAL_DOUBLE_BOOKED.value, 409)
    rows, _meta = validate_paginated(
        api.list_official_assignments(coordinator_headers,
                                      {"official_id": ctx["official"]["id"],
                                       "limit": 100})
    )
    assert len(rows) == 2, "the refused offer must not mint a third assignment"


def test_answering_the_same_offer_twice_is_already_responded(api):
    """PRD §3.7: "An assignment that has already been answered — anything other
    than `OFFERED` — draws `ERR_ALREADY_RESPONDED`, and an assignment whose contest
    has moved out of `SCHEDULED` or `OFFICIALS_ASSIGNED` draws
    `ERR_CONTEST_NOT_STAFFABLE`."
    PRD §3.7: "An `ACCEPT` moves it `OFFERED → ACCEPTED`, stamps `responded_at`,
    locks the travel stipend into `stipend_cents`, increments the contest's
    `accepted_official_count` by 1 and the official's `accepted_assignment_count` by
    1, and — when that count reaches the season's `required_officials` — promotes the
    contest `SCHEDULED → OFFICIALS_ASSIGNED` and clears its `hold_reason` back to
    null."

    Design: Corner/state_machines/responding_twice_to_the_same_offer_returns_already_responded
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z", season_overrides={"required_officials": 2}
    )
    official = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_2")
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    assignment = fx.offer_official(contest["id"], official["id"])
    fx.respond_to_offer(assignment["id"], official["id"], "ACCEPT")

    response = api.respond_to_assignment(
        assignment["id"], {"response": "ACCEPT"}, fx.make_official_headers(official["id"])
    )

    validate_error(response, ApiErrorId.ERR_ALREADY_RESPONDED.value, 409)
    stored = fx.read_assignment(assignment["id"])
    assert stored["status"] == "ACCEPTED"
    assert stored["stipend_cents"] == 9980
    after = fx.read_contest(contest["id"])
    assert after["accepted_official_count"] == 1, "a refused answer must not double-count"
    assert after["status"] == "SCHEDULED"


def test_stipend_stacks_the_tier_mileage_night_and_playoff_addends(api):
    """PRD §3.7: "The stipend has four addends, each rounded to whole cents on its
    own before they are added together."
    PRD §3.7: "That base is multiplied by the season's tier multiplier — 1.25 for
    `TIER_A`, 1.00 for `TIER_B`, 0.85 for `TIER_C` — and the product rounded half up
    to whole cents; this rounding happens **before** anything else is added."
    PRD §3.7: "A night addend of a flat 1500 cents applies when the UTC hour of the
    contest's `starts_at` is 23 or later, and is 0 otherwise."
    PRD §3.7: "A playoff addend applies only when `is_playoff` is true, and it is
    the larger of 2500 cents and twenty percent of the certification base rounded
    half up; since twenty percent of the three declared bases comes to 800, 1200, and
    1700 cents respectively, every certification level in practice takes the
    2500-cent floor — the floor, not the percentage, is what makes this branch
    non-proportional."

    Design: Corner/calculations/officials_stipend_stacks_tier_mileage_night_and_playoff_terms
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z", season_overrides={"required_officials": 1}
    )
    official = fx.create_official(full_name="Umi Tanaka", certification_level="LEVEL_3")
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T23:30:00Z", "2026-09-21T01:30:00Z",
                                travel_miles=150, is_playoff=True)
    assignment = fx.offer_official(contest["id"], official["id"])

    accepted = validate_success(
        api.respond_to_assignment(assignment["id"], {"response": "ACCEPT"},
                                  fx.make_official_headers(official["id"])),
        200,
    )

    assert accepted["status"] == "ACCEPTED"
    assert accepted["stipend_cents"] == 22065, (
        "10625 tier-adjusted base + 7440 capped mileage + 1500 night + 2500 playoff"
    )
    assert_same_instant(accepted["responded_at"], "2026-09-10T09:00:00Z", "responded_at")
    assert fx.read_contest(contest["id"])["status"] == "OFFICIALS_ASSIGNED"


def test_stipend_mileage_is_capped_at_one_hundred_twenty_miles(api):
    """PRD §3.7: "The mileage addend takes the contest's `travel_miles` capped at
    120 miles, multiplies the capped figure by 62 cents per mile, and rounds half
    up."
    PRD §3.7: "The certification base is 4000 cents for a `LEVEL_1` official, 6000
    for `LEVEL_2`, and 8500 for `LEVEL_3`."

    Design: Corner/calculations/officials_stipend_mileage_is_capped_at_one_hundred_twenty_miles
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "West High", "classification": "C2A",
                        "region_code": "R-WEST"},
        away_overrides={"name": "East High", "classification": "C2A",
                        "region_code": "R-EAST"},
        season_overrides={"sport": "TRACK", "classification": "C2A",
                          "sport_tier": "TIER_C", "required_officials": 1},
    )
    official = fx.create_official(full_name="Vic Alonso", certification_level="LEVEL_1",
                                  home_region_code="R-WEST")
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z",
                                travel_miles=150)
    assignment = fx.offer_official(contest["id"], official["id"])

    accepted = validate_success(
        api.respond_to_assignment(assignment["id"], {"response": "ACCEPT"},
                                  fx.make_official_headers(official["id"])),
        200,
    )

    assert accepted["stipend_cents"] == 10840, (
        "3400 tier-adjusted base plus 120 capped miles at 62 cents, not 150 miles"
    )


def test_assignment_listing_scopes_by_contest_and_by_official(api, coordinator_headers):
    """PRD §3.7: "Contests can be listed and filtered by `sport_season_id`, by
    `home_school_id`, by `away_school_id`, by `forfeiting_school_id`, and by
    `status`; officiating assignments can be listed and filtered by `contest_id`, by
    `official_id`, and by `status`."
    PRD §3.7: "An accepted offer opens at `OFFERED` with `stipend_cents` and
    `responded_at` both null, and the parent contest's `version` increments by 1."

    Design: Corner/endpoints/official_assignment_filtered_list_scopes_by_contest_and_by_official
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "Alpha High"},
        away_overrides={"name": "Beta High", "region_code": "R-SOUTH"},
        season_overrides={"required_officials": 2},
    )
    first = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_2")
    second = fx.create_official(full_name="Pia Sandoval", certification_level="LEVEL_1",
                                home_region_code="R-SOUTH")
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    asg_one = fx.offer_official(contest["id"], first["id"])
    asg_two = fx.offer_official(contest["id"], second["id"])

    by_official, _meta = validate_paginated(
        api.list_official_assignments(coordinator_headers, {"official_id": second["id"]})
    )
    by_contest, _meta2 = validate_paginated(
        api.list_official_assignments(coordinator_headers,
                                      {"contest_id": contest["id"], "limit": 100})
    )
    single = validate_success(
        api.get_official_assignment(asg_one["id"], coordinator_headers), 200
    )

    assert len(by_official) == 1
    assert by_official[0]["id"] == asg_two["id"]
    assert by_official[0]["status"] == "OFFERED"
    assert {row["id"] for row in by_contest} == {asg_one["id"], asg_two["id"]}
    assert single["stipend_cents"] is None


def test_replaying_a_stale_contest_version_on_an_offer_is_refused_with_412(
    api, coordinator_headers
):
    """PRD §2.7: "Offering a game to an official requires `expected_contest_version`
    as a mandatory body field carrying the client's last observed `version` of the
    target `Contest`. If that value does not equal the contest's current `version` —
    because another offer has been minted or an acceptance has moved
    `accepted_official_count` — the offer is rejected with `ERR_STALE_CONTEST_VERSION`
    and HTTP 412."

    Design: Corner/cross_cutting_layers/officiating_offer_with_a_stale_contest_version_returns_412
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "Alpha High"},
        away_overrides={"name": "Beta High", "region_code": "R-SOUTH"},
        season_overrides={"required_officials": 2},
    )
    first = fx.create_official(full_name="Ola Nkemdi", certification_level="LEVEL_2")
    second = fx.create_official(full_name="Pia Sandoval", certification_level="LEVEL_1",
                                home_region_code="R-SOUTH")
    contest = fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                                "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z")
    stale_version = contest["version"]

    accepted = api.offer_official(
        contest["id"],
        {"official_id": first["id"], "expected_contest_version": stale_version},
        coordinator_headers,
    )
    first_assignment = validate_success(accepted, 201)

    replayed = api.offer_official(
        contest["id"],
        {"official_id": second["id"], "expected_contest_version": stale_version},
        coordinator_headers,
    )

    assert first_assignment["status"] == "OFFERED"
    validate_error(replayed, ApiErrorId.ERR_STALE_CONTEST_VERSION.value, 412)
    rows, _meta = validate_paginated(
        api.list_official_assignments(coordinator_headers,
                                      {"contest_id": contest["id"], "limit": 100})
    )
    assert len(rows) == 1
    assert fx.read_contest(contest["id"])["accepted_official_count"] == 0

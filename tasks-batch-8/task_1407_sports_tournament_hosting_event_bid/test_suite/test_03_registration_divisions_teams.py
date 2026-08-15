"""Registration, division seeding, bracket topology, and team workflow tests."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_event, create_verified_bid, award_event_bid, create_contracted_venue,
    create_hotel_block, advance_posture, create_division, create_team,
    make_team_eligible, get_event, get_division, list_division_matches,
    setup_event_in_registration_open, setup_published_bracket,
    make_teamrep_headers, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]


def _get_team(api, team_id):
    return get_success_data(api.get_team(team_id, ANY))


# ===========================================================================
# Corner / state_machines (posture gate, lock guard)
# ===========================================================================

def test_registration_forbidden_in_planning_rejected(api):
    """PRD §2.5: "Team registration requires `REGISTRATION_OPEN`."
    PRD §2.5: "Any operation attempted in a posture that does not permit it is
    rejected with `ERR_EVENT_POSTURE_FORBIDS` (HTTP 409)..."

    Design: Corner/state_machines/registration_forbidden_in_planning_rejected
    """
    ev = create_event()
    award_event_bid(ev["id"])
    create_contracted_venue(ev["id"])
    create_hotel_block(ev["id"], contracted=True)
    advance_posture(ev["id"], "PLANNING")
    div = create_division(ev["id"])
    resp = api.create_team(div["id"], {"name": "Tigers", "contact_email": "t@x.com",
                                       "strength_rating": 90}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_POSTURE_FORBIDS)


def test_lock_seeding_below_min_teams_rejected(api):
    """PRD §3.5: "Locking requires the event to be in `REGISTRATION_OPEN`
    (otherwise `ERR_EVENT_POSTURE_FORBIDS`) and the division's
    `eligible_team_count` to meet or exceed its `min_teams` (otherwise
    `ERR_DIVISION_BELOW_MIN_TEAMS`, HTTP 409), and the division itself must
    still be `OPEN` (otherwise `ERR_DIVISION_NOT_OPEN`)."

    Design: Corner/state_machines/lock_seeding_below_min_teams_rejected
    """
    ctx = setup_event_in_registration_open()
    make_team_eligible(ctx["division"]["id"], name="Tigers", contact_email="t@x.com",
                       strength_rating=90)
    resp = api.lock_seeding(ctx["division"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DIVISION_BELOW_MIN_TEAMS)
    assert get_division(ctx["division"]["id"])["status"] == "OPEN"


# ===========================================================================
# Queue A: boundary_precision_check / division_cap_waitlist_boundary
# ===========================================================================

def test_division_cap_waitlist_boundary(api):
    """PRD §3.4: "The cap decides the new team's initial `status`: while
    `entered_team_count` is below `team_cap` the team enters as `ENTERED`; once
    the cap is reached, overflow teams become `WAITLISTED`."

    Design: Difficulty/boundary_precision_check/division_cap_waitlist_boundary
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 2, "min_teams": 2})
    d1 = ctx["division"]["id"]
    t1 = validate_success(api.create_team(d1, {"name": "Tigers", "contact_email": "t@x.com",
                                               "strength_rating": 90}, ADMIN), expected_status=201)
    t2 = validate_success(api.create_team(d1, {"name": "Sharks", "contact_email": "s@x.com",
                                               "strength_rating": 70}, ADMIN), expected_status=201)
    t3 = validate_success(api.create_team(d1, {"name": "Wolves", "contact_email": "w@x.com",
                                               "strength_rating": 85}, ADMIN), expected_status=201)
    assert t1["status"] == "ENTERED"      # pre-create count 0 < cap 2
    assert t2["status"] == "ENTERED"      # pre-create count 1 < cap 2
    assert t3["status"] == "WAITLISTED"   # pre-create count 2 >= cap 2
    assert get_division(d1)["entered_team_count"] == 2


def test_division_cap_boundary_waitlisted_not_counted(api):
    """PRD §3.4: "`entered_team_count` counts its teams in `ENTERED`,
    `ROSTER_SUBMITTED`, `ELIGIBLE`, `CHECKED_IN`, `ELIMINATED`, `FINISHED`,
    `CHAMPION`, or `DISQUALIFIED`; `eligible_team_count` counts the narrower set
    `ELIGIBLE`, `CHECKED_IN`, `ELIMINATED`, `FINISHED`, and `CHAMPION`."

    Design: Difficulty/boundary_precision_check/division_cap_waitlist_boundary
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 2, "min_teams": 2})
    d1 = ctx["division"]["id"]
    create_team(d1, name="Tigers", contact_email="t@x.com", strength_rating=90)
    create_team(d1, name="Sharks", contact_email="s@x.com", strength_rating=70)
    # The third team overflows to WAITLISTED and is not counted.
    create_team(d1, name="Wolves", contact_email="w@x.com", strength_rating=85)
    div = get_division(d1)
    assert div["entered_team_count"] == 2
    assert div["eligible_team_count"] == 0


# ===========================================================================
# Queue A: compensating_invariant /
#          division_entered_count_withdraw_promote_invariant
# ===========================================================================

def test_division_entered_count_withdraw_promote_invariant(api):
    """PRD §3.4: "When an `ENTERED` or `ELIGIBLE` team withdraws while the
    division is `OPEN` and a waitlist exists, the oldest `WAITLISTED` team by
    `created_at` ascending is promoted to `ENTERED` automatically (its `version`
    increments and `entered_team_count` is recomputed); no waitlisted team can
    exist past seeding lock, so the promotion is a registration-window
    mechanism."

    Design: Difficulty/compensating_invariant/division_entered_count_withdraw_promote_invariant
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 2, "min_teams": 2})
    d1 = ctx["division"]["id"]
    # Clock-stagger creation so created_at ordering is unambiguous.
    set_clock("2026-08-01T00:00:01Z")
    t1 = create_team(d1, name="Tigers", contact_email="t@x.com", strength_rating=90)
    set_clock("2026-08-01T00:00:02Z")
    t2 = create_team(d1, name="Sharks", contact_email="s@x.com", strength_rating=70)
    set_clock("2026-08-01T00:00:03Z")
    t3 = create_team(d1, name="Wolves", contact_email="w@x.com", strength_rating=85)
    assert _get_team(api, t3["id"])["status"] == "WAITLISTED"
    validate_success(api.withdraw_team(t1["id"], make_teamrep_headers(t1["id"])))
    assert _get_team(api, t1["id"])["status"] == "WITHDRAWN"
    # The oldest WAITLISTED team (t3) is promoted; the count is conserved.
    assert _get_team(api, t3["id"])["status"] == "ENTERED"
    assert get_division(d1)["entered_team_count"] == 2


def test_division_withdraw_promotion_prefers_oldest_waitlisted(api):
    """PRD §3.4: "When an `ENTERED` or `ELIGIBLE` team withdraws while the
    division is `OPEN` and a waitlist exists, the oldest `WAITLISTED` team by
    `created_at` ascending is promoted to `ENTERED` automatically (its `version`
    increments and `entered_team_count` is recomputed); no waitlisted team can
    exist past seeding lock, so the promotion is a registration-window
    mechanism."

    Design: Difficulty/compensating_invariant/division_entered_count_withdraw_promote_invariant
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 2, "min_teams": 2})
    d1 = ctx["division"]["id"]
    set_clock("2026-08-01T00:00:01Z")
    t1 = create_team(d1, name="Tigers", contact_email="t@x.com", strength_rating=90)
    set_clock("2026-08-01T00:00:02Z")
    t2 = create_team(d1, name="Sharks", contact_email="s@x.com", strength_rating=70)
    set_clock("2026-08-01T00:00:03Z")
    t3 = create_team(d1, name="Wolves", contact_email="w@x.com", strength_rating=85)
    set_clock("2026-08-01T00:00:04Z")
    t4 = create_team(d1, name="Bears", contact_email="b@x.com", strength_rating=65)
    # Two waitlisted; the older one (t3) wins promotion when t1 withdraws.
    validate_success(api.withdraw_team(t1["id"], make_teamrep_headers(t1["id"])))
    assert _get_team(api, t3["id"])["status"] == "ENTERED"
    assert _get_team(api, t4["id"])["status"] == "WAITLISTED"
    assert get_division(d1)["entered_team_count"] == 2


# ===========================================================================
# Corner / calculations (seeding tie-break, five-team bracket topology)
# ===========================================================================

def test_seeding_rating_tie_created_at_tiebreak(api):
    """PRD §3.5: "Locking moves the division to `SEEDING_LOCKED` and performs
    the seeding: the division's `ELIGIBLE` teams are ordered by
    `strength_rating` descending, ties broken by `created_at` ascending — the
    earlier-registered team seeds higher, with three-fractional-digit timestamp
    precision — and `seed_number` values 1 through N are assigned in that order."

    Design: Corner/calculations/seeding_rating_tie_created_at_tiebreak
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 6, "min_teams": 2})
    d1 = ctx["division"]["id"]
    set_clock("2026-08-01T00:00:01Z")
    t1 = make_team_eligible(d1, name="Tigers", contact_email="t@x.com", strength_rating=80)
    set_clock("2026-08-01T00:00:02Z")
    t2 = make_team_eligible(d1, name="Sharks", contact_email="s@x.com", strength_rating=80)
    set_clock("2026-08-01T00:00:03Z")
    t3 = make_team_eligible(d1, name="Wolves", contact_email="w@x.com", strength_rating=50)
    validate_success(api.lock_seeding(d1, ADMIN))
    assert _get_team(api, t1["id"])["seed_number"] == 1
    assert _get_team(api, t2["id"])["seed_number"] == 2
    assert _get_team(api, t3["id"])["seed_number"] == 3


def test_bracket_topology_five_team_byes(api):
    """PRD §3.5: "The `bracket_size` is the smallest power of two that is
    greater than or equal to the seeded team count, and never smaller than two;
    `total_rounds` is the base-2 logarithm of the bracket size, so `round_number`
    1 is the first round and `round_number` equal to `total_rounds` is the
    final. The number of byes is the bracket size minus the seeded count, and
    byes go to seeds 1 through the bye count in order. Each first-round real
    match pairs seed s with the seed whose number is the bracket size plus one
    minus s, for every seed s in the lower half of the seeding list that did not
    receive a bye; the total number of matches created is the bracket size minus
    one minus the number of byes. Every match records its `division_id`,
    `round_number`, and one-based `bracket_slot` within the round, and knows its
    successor through `winner_advances_to_match_id`: the winner of the match in
    round r at slot k advances to the match in round r+1 at the slot given by k
    divided by two rounded up, filling that successor's `home_team_id` when k is
    odd and its `away_team_id` when k is even. The final has no successor, so
    its `winner_advances_to_match_id` is null. Seeds holding byes are placed
    directly into their round-two match slots at publish time."

    Design: Corner/calculations/bracket_topology_five_team_byes
    """
    ctx = setup_published_bracket(
        team_ratings=[95, 85, 75, 65, 55],
        division_overrides={"team_cap": 6, "min_teams": 2})
    div = get_division(ctx["division"]["id"])
    assert div["bracket_size"] == 8
    assert div["total_rounds"] == 3
    matches = list_division_matches(div["id"])
    assert len(matches) == 4  # bracket_size 8 - 1 - 3 byes
    t1, t2, t3, t4, t5 = ctx["team_ids"]
    # Find matches by (round, slot); the list sorts round ASC then slot ASC.
    by_pos = {(m["round_number"], m["bracket_slot"]): m for m in matches}
    r1s2 = by_pos[(1, 2)]
    assert r1s2["home_team_id"] == t4  # seed 4
    assert r1s2["away_team_id"] == t5  # seed 5
    sf1 = by_pos[(2, 1)]
    assert r1s2["winner_advances_to_match_id"] == sf1["id"]
    assert sf1["home_team_id"] == t1   # seed 1 bye placed directly
    assert sf1["away_team_id"] is None
    sf2 = by_pos[(2, 2)]
    assert sf2["home_team_id"] == t3   # seed 3
    assert sf2["away_team_id"] == t2   # seed 2
    fin = by_pos[(3, 1)]
    assert fin["home_team_id"] is None
    assert fin["away_team_id"] is None
    assert fin["winner_advances_to_match_id"] is None


# ===========================================================================
# Corner / state_machines (advancement side effects, division completion)
# ===========================================================================

def test_finalize_advances_winner_to_final_slot(api):
    """PRD §3.6: "The higher scorer becomes `winner_team_id` and the match
    becomes `FINAL`. Advancement then fires: if the match has a successor, the
    winner is written into the successor's home slot when the finished match's
    `bracket_slot` is odd, or its away slot when even, incrementing the
    successor match's `version`. Elimination follows the round: the loser, if
    `ELIGIBLE` or `CHECKED_IN`, becomes `ELIMINATED` after a non-final round or
    `FINISHED` after the final, while the final's winner becomes `CHAMPION`."

    Design: Corner/state_machines/finalize_advances_winner_to_final_slot
    """
    ctx = setup_published_bracket(team_ratings=[90, 85, 70, 65], advance_to_live=True)
    t1, t3, t2, t4 = ctx["team_ids"]  # seeds: t1=1 (90), t3=2 (85), t2=3 (70), t4=4 (65)
    matches = ctx["matches"]
    by_pos = {(m["round_number"], m["bracket_slot"]): m for m in matches}
    r1m1 = by_pos[(1, 1)]  # seed 1 vs seed 4
    fin = by_pos[(2, 1)]
    validate_success(api.schedule_match(
        r1m1["id"], {"field_id": ctx["field"]["id"],
                     "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.start_match(r1m1["id"], ADMIN))
    finished = validate_success(api.finalize_match(
        r1m1["id"], {"home_score": 2, "away_score": 0}, ADMIN))
    assert finished["winner_team_id"] == t1
    fin_after = get_success_data(api.get_match(fin["id"], ANY))
    assert fin_after["home_team_id"] == t1  # odd bracket_slot advances to home
    assert _get_team(api, t4)["status"] == "ELIMINATED"


def test_division_completes_when_all_matches_terminal(api):
    """PRD §3.4: "the division completes to `COMPLETED` automatically once every
    one of its matches has reached `FINAL`, `FORFEITED`, or `CANCELLED`."
    PRD §3.6: "When the last unresolved match of a division finishes, the
    division completes to `COMPLETED`."

    Design: Corner/state_machines/division_completes_when_all_matches_terminal
    """
    ctx = setup_published_bracket(team_ratings=[90, 70], advance_to_live=True)
    t1, t2 = ctx["team_ids"]
    final = ctx["matches"][-1]
    validate_success(api.schedule_match(
        final["id"], {"field_id": ctx["field"]["id"],
                      "scheduled_start": "2026-10-10T14:00:00Z"}, ADMIN))
    validate_success(api.start_match(final["id"], ADMIN))
    validate_success(api.finalize_match(final["id"], {"home_score": 3, "away_score": 1}, ADMIN))
    assert get_division(ctx["division"]["id"])["status"] == "COMPLETED"
    assert _get_team(api, t1)["status"] == "CHAMPION"
    assert _get_team(api, t2)["status"] == "FINISHED"


# ===========================================================================
# Corner / rbac (entity-backed ownership, allow)
# ===========================================================================

def test_teamrep_roster_own_team_allowed(api):
    """PRD §2.1: "When `X-User-Role` is `TeamRep`, `X-User-ID` is the `id` of
    the acting Team; ownership checks on any resource that references a Team
    compare the resource's team field to `X-User-ID` (a team representative may
    act only on their own team and their own team's bookings)."
    PRD §3.4: "From `ENTERED`, the team's own `TeamRep` submits its roster,
    supplying `roster_player_count` and optional `roster_notes`."

    Design: Corner/rbac/teamrep_roster_own_team_allowed
    """
    ctx = setup_event_in_registration_open()
    t1 = create_team(ctx["division"]["id"], name="Tigers", contact_email="t@x.com",
                     strength_rating=90)
    resp = api.submit_roster(t1["id"], {"roster_player_count": 12},
                             make_teamrep_headers(t1["id"]))
    team = validate_success(resp)
    assert team["status"] == "ROSTER_SUBMITTED"
    # A TeamRep naming a different team id is denied by the ownership scope.
    foreign = {"X-User-ID": "00000000-0000-0000-0000-000000000001",
               "X-User-Role": "TeamRep"}
    resp = api.submit_roster(t1["id"], {"roster_player_count": 12}, foreign)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# Corner / endpoints (team listing pagination and sort)
# ===========================================================================

def test_teams_listing_pagination_and_sort(api):
    """PRD §3.4: "Teams list by `seed_number` ascending with unseeded teams
    last, then `strength_rating` descending, then `created_at` ascending."
    PRD §2.3: "`limit` caps the number of returned items: it defaults to 10,
    with a minimum of 1 and a maximum of 100. `offset` skips a number of items
    and defaults to 0. Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/teams_listing_pagination_and_sort
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 6, "min_teams": 2})
    d1 = ctx["division"]["id"]
    t1 = create_team(d1, name="Tigers", contact_email="t@x.com", strength_rating=90)
    t2 = create_team(d1, name="Sharks", contact_email="s@x.com", strength_rating=70)
    t3 = create_team(d1, name="Wolves", contact_email="w@x.com", strength_rating=85)
    page1, meta1 = validate_paginated(api.list_division_teams(
        d1, ANY, params={"limit": 2, "offset": 0}))
    # Unseeded teams: seed_number nulls last, so strength_rating DESC governs.
    assert [t["id"] for t in page1] == [t1["id"], t3["id"]]
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    page2, meta2 = validate_paginated(api.list_division_teams(
        d1, ANY, params={"limit": 2, "offset": 2}))
    assert [t["id"] for t in page2] == [t2["id"]]
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 3


def test_matches_filtered_by_status(api):
    """PRD §3.5: "a division's matches list by `round_number` ascending then
    `bracket_slot` ascending, filterable by `status` or `round_number`."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/matches_filtered_by_status
    """
    ctx = setup_published_bracket(team_ratings=[90, 70])
    d1 = ctx["division"]["id"]
    data, meta = validate_paginated(api.list_matches(
        ANY, params={"division_id": d1, "status": "PENDING_TEAMS"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == ctx["matches"][0]["id"]
    data2, meta2 = validate_paginated(api.list_matches(
        ANY, params={"division_id": d1, "status": "FINAL"}))
    assert meta2["total_count"] == 0
    assert data2 == []


def test_event_summary_computed_read(api):
    """PRD §3.1: "A computed operational summary view per event reports its
    `posture`, `registered_team_count`, `finalized_match_count`,
    `active_bid_id`, plus two rollup figures used by stakeholders during
    planning and settlement: `total_final_rebate_cents`, the sum of final
    rebates across the event's hotel blocks, and `picked_up_room_nights_total`,
    the sum of picked-up room-nights across those blocks."

    Design: Corner/endpoints/event_summary_computed_read
    """
    ctx = setup_event_in_registration_open(
        division_overrides={"team_cap": 6, "min_teams": 2})
    d1 = ctx["division"]["id"]
    create_team(d1, name="Tigers", contact_email="t@x.com", strength_rating=90)
    create_team(d1, name="Sharks", contact_email="s@x.com", strength_rating=70)
    create_team(d1, name="Wolves", contact_email="w@x.com", strength_rating=85)
    summary = validate_success(api.get_event_summary(ctx["event"]["id"], ANY))
    assert summary["registered_team_count"] == 3
    assert summary["finalized_match_count"] == 0
    assert summary["active_bid_id"] == ctx["bid"]["id"]
    assert summary["total_final_rebate_cents"] == 0
    assert summary["picked_up_room_nights_total"] == 0

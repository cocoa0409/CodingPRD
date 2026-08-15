"""Relay declarations, leg management, lock/scratch windows, and the relay
scratch cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_event,
    add_relay_leg,
    add_swimmer,
    add_team,
    assert_relay_leg,
    create_open_meet,
    declare_relay,
    declare_relay_with_legs,
    get_success_data,
    lane_for_entry,
    make_team_coach_headers,
    seed_meet,
    setup_deck_coverage,
    start_event,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


def _relay_scenario(api, meet_name="RL"):
    """Meet ENTRIES_OPEN + team + relay event + four swimmers."""
    meet = create_open_meet(meet_name=meet_name)
    team = add_team(meet["id"])
    swimmers = [add_swimmer(team["id"], full_name=f"L{i}",
                            birth_date=f"2014-01-0{i}")
                for i in range(1, 5)]
    event = add_event(meet["id"], event_number=7, stroke="FREESTYLE_RELAY",
                      distance_meters=200, is_relay=True,
                      scheduled_start_minute=600, scheduled_end_minute=630)
    return meet, team, swimmers, event


def _seeded_locked_relay(api, meet_name="TC2", with_coverage=False,
                         start_the_event=False):
    """Meet SEEDED with one LEGS_LOCKED relay whose entry is SEEDED.

    Returns (meet, team, relay, lane). With start_the_event=True the relay
    event is IN_PROGRESS on return.
    """
    meet, team, swimmers, event = _relay_scenario(api, meet_name=meet_name)
    relay = declare_relay_with_legs(
        team["id"], event["id"], [s["id"] for s in swimmers],
        seed_time_cs=9500, lock=True)
    if with_coverage or start_the_event:
        setup_deck_coverage(event["id"], meet["id"])
    seed_meet(meet["id"])
    lane = lane_for_entry(relay["entry_id"])
    if start_the_event:
        start_event(event["id"])
    return meet, team, relay, lane, event


class TestRelayLegShape:
    def test_leg_is_thin_record_and_repost_replaces(self, api):
        """PRD §2.5: "One deliberate exception exists: a relay leg is a thin
        join record carrying only `id` and `created_at`; `updated_at` and
        `version` are absent from it entirely."
        PRD §3.4: "The coach posts a `leg_number` from one through four
        together with a `swimmer_id`; posting a `leg_number` that already
        exists replaces that leg's swimmer."

        Design: Corner/entities/relay_leg_immutability_and_replace
        """
        _meet, team, swimmers, event = _relay_scenario(api, meet_name="LegM")
        sub = add_swimmer(team["id"], full_name="L Sub", birth_date="2014-02-02")
        relay = declare_relay(team["id"], event["id"], seed_time_cs=9500)
        coach = make_team_coach_headers(team["id"])
        first = validate_success(api.add_relay_leg(
            relay["id"], {"leg_number": 1, "swimmer_id": swimmers[0]["id"]},
            coach), expected_status=201)
        assert_relay_leg(first)  # id + created_at only; no updated_at/version
        validate_success(api.add_relay_leg(
            relay["id"], {"leg_number": 1, "swimmer_id": sub["id"]},
            coach), expected_status=201)
        legs = get_success_data(api.list_relay_team_legs(relay["id"], DIRECTOR))
        leg_one = [leg for leg in legs if leg["leg_number"] == 1]
        assert len(leg_one) == 1, "replace semantics: exactly one row for leg 1"
        assert leg_one[0]["swimmer_id"] == sub["id"]


class TestRelayLock:
    def test_lock_with_incomplete_legs_rejected(self, api):
        """PRD §3.4: "A `DECLARED` relay locks to `LEGS_LOCKED` only when
        exactly four legs exist (`ERR_RELAY_LEG_COUNT_INCOMPLETE` otherwise)".

        Design: Corner/errors/relay_lock_incomplete_legs_rejected
        """
        _meet, team, swimmers, event = _relay_scenario(api, meet_name="RL1")
        relay = declare_relay(team["id"], event["id"], seed_time_cs=9500)
        verify_entry(relay["entry_id"])  # isolate the leg-count failure
        for i, swimmer in enumerate(swimmers[:3], start=1):
            add_relay_leg(relay["id"], team["id"], i, swimmer["id"])
        resp = api.lock_relay_team(relay["id"],
                                   make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_RELAY_LEG_COUNT_INCOMPLETE)

    def test_lock_window_closed_once_event_underway(self, api):
        """PRD §3.4: "and while the relay's event still stands in `PENDING` or
        `SEEDED` — once the event is underway the lock window has closed
        (`ERR_RELAY_LOCK_WINDOW_CLOSED`)."

        Design: Corner/errors/relay_lock_window_closed_after_event_start
        """
        meet, team, swimmers, event = _relay_scenario(api, meet_name="RL5")
        relay = declare_relay(team["id"], event["id"], seed_time_cs=9500)
        verify_entry(relay["entry_id"])
        for i, swimmer in enumerate(swimmers, start=1):
            add_relay_leg(relay["id"], team["id"], i, swimmer["id"])
        setup_deck_coverage(event["id"], meet["id"])
        seed_meet(meet["id"])
        start_event(event["id"])
        resp = api.lock_relay_team(relay["id"],
                                   make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_RELAY_LOCK_WINDOW_CLOSED)


class TestRelayLegEligibility:
    def test_duplicate_swimmer_rejected(self, api):
        """PRD §3.4: "may appear on at most one leg of the relay, duplicates
        being rejected as `ERR_RELAY_SWIMMER_DUPLICATE`."

        Design: Corner/errors/relay_duplicate_swimmer_leg_rejected
        """
        _meet, team, swimmers, event = _relay_scenario(api, meet_name="RL2")
        relay = declare_relay(team["id"], event["id"], seed_time_cs=9500)
        coach = make_team_coach_headers(team["id"])
        add_relay_leg(relay["id"], team["id"], 1, swimmers[0]["id"])
        resp = api.add_relay_leg(relay["id"],
                                 {"leg_number": 2,
                                  "swimmer_id": swimmers[0]["id"]}, coach)
        validate_error(resp, ApiErrorId.ERR_RELAY_SWIMMER_DUPLICATE)

    def test_leg_swimmer_from_other_team_rejected(self, api):
        """PRD §3.4: "Each leg's swimmer must be an `ACTIVE` member of the
        relay's own team — a swimmer from another club is refused with
        `ERR_RELAY_SWIMMER_TEAM_MISMATCH`".

        Design: Corner/errors/relay_leg_team_mismatch_rejected
        """
        meet = create_open_meet(meet_name="RL3")
        team_a = add_team(meet["id"], team_code="AAA", team_name="Aquatics")
        team_b = add_team(meet["id"], team_code="BBB", team_name="Barracudas")
        swimmer_b = add_swimmer(team_b["id"], full_name="Ring In",
                                birth_date="2014-01-01")
        event = add_event(meet["id"], event_number=7, stroke="FREESTYLE_RELAY",
                          distance_meters=200, is_relay=True,
                          scheduled_start_minute=600, scheduled_end_minute=630)
        relay = declare_relay(team_a["id"], event["id"], seed_time_cs=9500)
        resp = api.add_relay_leg(
            relay["id"], {"leg_number": 1, "swimmer_id": swimmer_b["id"]},
            make_team_coach_headers(team_a["id"]))
        validate_error(resp, ApiErrorId.ERR_RELAY_SWIMMER_TEAM_MISMATCH)

    def test_leg_write_blocked_once_locked(self, api):
        """PRD §3.4: "Once the relay is `LEGS_LOCKED` or `SCRATCHED`, leg
        writes fail with `ERR_RELAY_LEGS_LOCKED`."

        Design: Corner/errors/relay_legs_locked_blocks_edit
        """
        _meet, team, swimmers, event = _relay_scenario(api, meet_name="RL4")
        spare = add_swimmer(team["id"], full_name="L5", birth_date="2014-01-05")
        relay = declare_relay_with_legs(
            team["id"], event["id"], [s["id"] for s in swimmers],
            seed_time_cs=9500, lock=True)
        resp = api.add_relay_leg(
            relay["id"], {"leg_number": 1, "swimmer_id": spare["id"]},
            make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_RELAY_LEGS_LOCKED)


class TestRelayScratch:
    def test_locked_relay_scratch_blocked_once_event_underway(self, api):
        """PRD §3.4: "From `LEGS_LOCKED`, scratching remains possible only
        while the relay's event stands in `PENDING` or `SEEDED`; once the
        event is `IN_PROGRESS` or beyond, the attempt fails with
        `ERR_RELAY_NOT_SCRATCHABLE`."

        Design: Corner/errors/relay_scratch_blocked_after_event_start
        """
        _meet, team, relay, _lane, _event = _seeded_locked_relay(
            api, meet_name="RL6", start_the_event=True)
        resp = api.scratch_relay_team(relay["id"],
                                      make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_RELAY_NOT_SCRATCHABLE)

    def test_relay_scratch_cascades_to_entry(self, api):
        """PRD §3.4: "Either scratch cascades: the relay's entry, if `ENTERED`
        or `SEEDED`, becomes `SCRATCHED`; if that entry was seeded, its lane
        assignment is `VOIDED`; and the team's `active_entry_count` is
        recomputed."

        Design: Difficulty/transitive_cascade/relay_scratch_cascade
        """
        _meet, team, relay, lane, _event = _seeded_locked_relay(
            api, meet_name="TC2")
        assert lane["lane_status"] == "ACTIVE", "precondition: lane ACTIVE"
        resp = api.scratch_relay_team(relay["id"],
                                      make_team_coach_headers(team["id"]))
        scratched = validate_success(resp)
        assert scratched["status"] == "SCRATCHED"
        entry_after = get_success_data(
            api.get_entry(relay["entry_id"], DIRECTOR))
        assert entry_after["status"] == "SCRATCHED", \
            "hop 2: the relay's seeded entry is scratched"

    def test_relay_scratch_voids_lane_and_zeroes_count(self, api):
        """PRD §3.4: "if that entry was seeded, its lane assignment is
        `VOIDED`; and the team's `active_entry_count` is recomputed."
        PRD §3.1: "it counts the team's entries standing in `ENTERED`,
        `SEEDED`, `FINISHED`, `DQ`, or `NO_SHOW`, and excludes anything
        `SCRATCHED`."

        Design: Difficulty/transitive_cascade/relay_scratch_cascade
        """
        _meet, team, relay, lane, _event = _seeded_locked_relay(
            api, meet_name="TC2b")
        validate_success(api.scratch_relay_team(
            relay["id"], make_team_coach_headers(team["id"])))
        lane_after = get_success_data(
            api.get_lane_assignment(lane["id"], DIRECTOR))
        assert lane_after["lane_status"] == "VOIDED", \
            "hop 3: the seeded entry's lane is voided"
        team_after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert team_after["active_entry_count"] == 0

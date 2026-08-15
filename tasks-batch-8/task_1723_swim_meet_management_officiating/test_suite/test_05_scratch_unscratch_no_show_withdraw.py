"""Entry scratch/unscratch round trips, no-shows, ownership denial, and the
team-withdrawal cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_entry,
    add_event,
    add_relay_leg,
    add_swimmer,
    add_team,
    create_open_meet,
    declare_relay,
    get_success_data,
    lane_for_entry,
    lanes_for_event,
    make_meet_referee_headers,
    make_team_coach_headers,
    seed_meet,
    setup_deck_coverage,
    setup_in_progress_event,
    start_event,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


def _seeded_meet_with_entry(api, meet_name="CI1", num_swimmers=2):
    """Meet SEEDED with one event and num_swimmers verified entries on one team."""
    meet = create_open_meet(meet_name=meet_name)
    team = add_team(meet["id"])
    swimmers = [add_swimmer(team["id"], full_name=f"Sw {c}",
                            birth_date=f"2014-0{i + 3}-1{i}")
                for i, c in enumerate("ABCDEF"[:num_swimmers])]
    event = add_event(meet["id"], qualifying_time_cs=3000)
    entries = []
    for i, swimmer in enumerate(swimmers):
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900 + i * 10)
        verify_entry(entry["id"])
        entries.append(entry)
    seed_meet(meet["id"])
    return meet, team, swimmers, event, entries


class TestScratchGateByEventState:
    """Difficulty pair: EventEntry x SwimEvent — the same scratch call is
    lawful at event SEEDED and forbidden once the event is IN_PROGRESS."""

    def test_scratch_and_restore_while_event_seeded(self, api):
        """PRD §3.3: "a `SEEDED` entry scratches while its event stands in
        `SEEDED`". PRD §3.3: "After seeding, a `SCRATCHED` entry returns
        directly to `SEEDED` — but only while both the meet and its event stand
        in `SEEDED` and its `VOIDED` lane assignment still exists, in which
        case that lane is restored to `ACTIVE` with its original `heat_number`
        and `lane_number`."

        Design: Difficulty/cross_entity_state_dependency/entry_scratch_gated_by_event_state
        """
        meet, team, _swimmers, event, entries = _seeded_meet_with_entry(
            api, meet_name="XD1", num_swimmers=1)
        setup_deck_coverage(event["id"], meet["id"])
        coach = make_team_coach_headers(team["id"])
        scratched = validate_success(api.scratch_entry(entries[0]["id"], coach))
        assert scratched["status"] == "SCRATCHED", \
            "scratch is allowed while the entry's event stands in SEEDED"
        restored = validate_success(api.unscratch_entry(entries[0]["id"], coach))
        assert restored["status"] == "SEEDED", \
            "unscratch restores the entry directly to SEEDED post-seeding"

    def test_scratch_rejected_once_event_in_progress(self, api):
        """PRD §3.3: "from any other configuration the attempt fails with
        `ERR_ENTRY_NOT_SCRATCHABLE`, including an entry whose event has reached
        `IN_PROGRESS`, `COMPLETED`, `OFFICIAL`, or `CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/entry_scratch_gated_by_event_state
        """
        meet, team, _swimmers, event, entries = _seeded_meet_with_entry(
            api, meet_name="XD1b", num_swimmers=1)
        setup_deck_coverage(event["id"], meet["id"])
        started = start_event(event["id"])
        assert started["status"] == "IN_PROGRESS"
        resp = api.scratch_entry(entries[0]["id"],
                                 make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_SCRATCHABLE)


class TestScratchUnscratchOccupancyInvariant:
    """Difficulty pair: the scratch/unscratch round trip conserves per-event
    ACTIVE lane occupancy, lane identity, and the team's active_entry_count."""

    def test_scratch_voids_then_unscratch_restores_same_lane(self, api):
        """PRD §3.3: "Scratching a seeded entry voids its lane assignment — the
        lane's `lane_status` becomes `VOIDED`" and "that lane is restored to
        `ACTIVE` with its original `heat_number` and `lane_number`."

        Design: Difficulty/compensating_invariant/scratch_unscratch_lane_occupancy_invariant
        """
        _meet, team, _swimmers, event, entries = _seeded_meet_with_entry(
            api, meet_name="CI1", num_swimmers=2)
        coach = make_team_coach_headers(team["id"])
        lane_before = lane_for_entry(entries[1]["id"])
        validate_success(api.scratch_entry(entries[1]["id"], coach))
        active_mid = [lane for lane in lanes_for_event(event["id"])
                      if lane["lane_status"] == "ACTIVE"]
        assert len(active_mid) == 1, \
            "scratch drops ACTIVE lane occupancy from 2 to 1"
        restored = validate_success(api.unscratch_entry(entries[1]["id"], coach))
        assert restored["status"] == "SEEDED"
        lane_after = get_success_data(
            api.get_lane_assignment(lane_before["id"], DIRECTOR))
        assert lane_after["lane_status"] == "ACTIVE"
        assert lane_after["lane_number"] == lane_before["lane_number"], \
            "the same physical lane is restored, not a new assignment"
        assert lane_after["heat_number"] == lane_before["heat_number"]

    def test_active_entry_count_conserved_across_round_trip(self, api):
        """PRD §3.1: "A team's `active_entry_count` tracks its live commitment
        load: it counts the team's entries standing in `ENTERED`, `SEEDED`,
        `FINISHED`, `DQ`, or `NO_SHOW`, and excludes anything `SCRATCHED`."

        Design: Difficulty/compensating_invariant/scratch_unscratch_lane_occupancy_invariant
        """
        _meet, team, _swimmers, _event, entries = _seeded_meet_with_entry(
            api, meet_name="CI1c", num_swimmers=2)
        coach = make_team_coach_headers(team["id"])
        before = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert before["active_entry_count"] == 2
        validate_success(api.scratch_entry(entries[1]["id"], coach))
        mid = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert mid["active_entry_count"] == 1
        validate_success(api.unscratch_entry(entries[1]["id"], coach))
        after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert after["active_entry_count"] == 2, \
            "the compensating round trip conserves the counter exactly"


class TestUnscratchGuards:
    def test_unscratch_non_scratched_entry_rejected(self, api):
        """PRD §3.3: "Any other configuration fails with
        `ERR_ENTRY_NOT_UNSCRATCHABLE`, and both flavors of restore recompute
        `active_entry_count`."

        Design: Corner/errors/unscratch_non_scratched_entry_rejected
        """
        meet = create_open_meet(meet_name="RE9")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        resp = api.unscratch_entry(entry["id"],
                                   make_team_coach_headers(team["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_UNSCRATCHABLE)


class TestNoShow:
    def test_no_show_marks_entry_and_voids_lane(self, api):
        """PRD §3.7: "the `MeetReferee` may mark a seeded entry as a no-show,
        moving it from `SEEDED` to the unconditionally terminal `NO_SHOW`; the
        entry's lane is `VOIDED` and the team's `active_entry_count`
        recomputed."

        Design: Corner/state_machines/no_show_marks_entry_and_voids_lane
        """
        workspace = setup_in_progress_event(meet_name="NS1")
        entry = workspace["entries"][0]
        lane = workspace["lanes"][0]
        referee_id = workspace["coverage"]["referee"]["id"]
        resp = api.mark_no_show(entry["id"],
                                make_meet_referee_headers(referee_id))
        marked = validate_success(resp)
        assert marked["status"] == "NO_SHOW"
        lane_after = get_success_data(api.get_lane_assignment(lane["id"], DIRECTOR))
        assert lane_after["lane_status"] == "VOIDED"


class TestImmediateConsistency:
    def test_scratch_response_reflects_mutation_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "An `ENTERED` entry scratches while the meet stands in
        `ENTRIES_OPEN` or `ENTRIES_CLOSED`".

        Design: Corner/consistency_model/scratch_response_reflects_mutation_immediately
        """
        meet = create_open_meet(meet_name="IM1")
        team = add_team(meet["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        coach = make_team_coach_headers(team["id"])
        resp = api.scratch_entry(entry["id"], coach)
        scratched = validate_success(resp)
        assert scratched["status"] == "SCRATCHED"
        reread = get_success_data(api.get_entry(entry["id"], DIRECTOR))
        assert reread["status"] == "SCRATCHED", \
            "a same-instant re-GET agrees with the mutation response"


class TestCoachOwnership:
    def test_coach_cannot_touch_other_teams_entry(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a Team —
        swimmers, entries, relay teams and their legs, protested
        disqualifications — compare the resource's team field to `X-User-ID`,
        and a coach acting on another club's resource fails the check."

        Design: Corner/rbac/coach_cannot_touch_other_teams_entry
        """
        meet = create_open_meet(meet_name="RB3")
        team_a = add_team(meet["id"], team_code="AAA", team_name="Aquatics")
        team_b = add_team(meet["id"], team_code="BBB", team_name="Barracudas")
        swimmer_b = add_swimmer(team_b["id"], full_name="Sw B")
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entry_b = add_entry(event["id"], swimmer_b["id"], team_b["id"],
                            seed_time_cs=2900)
        resp = api.scratch_entry(entry_b["id"],
                                 make_team_coach_headers(team_a["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestTeamWithdrawCascade:
    def test_withdraw_cascades_to_swimmers_entries_relays(self, api):
        """PRD §3.1: "The withdrawal cascade is total: every swimmer of the
        team becomes `INACTIVE`; every entry of the team standing in `ENTERED`
        or `SEEDED` becomes `SCRATCHED`, and each such seeded entry's lane
        assignment flips to `VOIDED`; every relay team standing in `DECLARED`
        or `LEGS_LOCKED` becomes `SCRATCHED`, its entry and lane cascading in
        the same way; and the team's `active_entry_count` is recomputed,
        landing at zero."

        Design: Corner/state_machines/team_withdraw_cascade
        """
        meet = create_open_meet(meet_name="WD1")
        team = add_team(meet["id"])
        coach = make_team_coach_headers(team["id"])
        swimmer = add_swimmer(team["id"], full_name="Sw A",
                              birth_date="2014-03-10")
        leg_swimmers = [add_swimmer(team["id"], full_name=f"L{i}",
                                    birth_date=f"2014-01-0{i}")
                        for i in range(1, 5)]
        event = add_event(meet["id"], event_number=1, qualifying_time_cs=3000)
        relay_event = add_event(meet["id"], event_number=7,
                                stroke="FREESTYLE_RELAY", distance_meters=200,
                                is_relay=True, scheduled_start_minute=600,
                                scheduled_end_minute=630)
        entry = add_entry(event["id"], swimmer["id"], team["id"],
                          seed_time_cs=2900)
        verify_entry(entry["id"])
        relay = declare_relay(team["id"], relay_event["id"], seed_time_cs=9500)
        verify_entry(relay["entry_id"])
        for i, leg_swimmer in enumerate(leg_swimmers, start=1):
            add_relay_leg(relay["id"], team["id"], i, leg_swimmer["id"])
        validate_success(api.lock_relay_team(relay["id"], coach))
        seed_meet(meet["id"])

        lane_entry = lane_for_entry(entry["id"])
        lane_relay = lane_for_entry(relay["entry_id"])

        resp = api.withdraw_team(team["id"], DIRECTOR)
        withdrawn = validate_success(resp)
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["active_entry_count"] == 0

        swimmer_after = get_success_data(api.get_swimmer(swimmer["id"], DIRECTOR))
        assert swimmer_after["status"] == "INACTIVE"
        entry_after = get_success_data(api.get_entry(entry["id"], DIRECTOR))
        relay_entry_after = get_success_data(
            api.get_entry(relay["entry_id"], DIRECTOR))
        assert entry_after["status"] == "SCRATCHED"
        assert relay_entry_after["status"] == "SCRATCHED"
        relay_after = get_success_data(api.get_relay_team(relay["id"], DIRECTOR))
        assert relay_after["status"] == "SCRATCHED"
        lane_entry_after = get_success_data(
            api.get_lane_assignment(lane_entry["id"], DIRECTOR))
        lane_relay_after = get_success_data(
            api.get_lane_assignment(lane_relay["id"], DIRECTOR))
        assert lane_entry_after["lane_status"] == "VOIDED"
        assert lane_relay_after["lane_status"] == "VOIDED"

"""Scoring: competition ranking, SPLIT vs TOP tie policies, relay multiplier
and table depth, provisional/official reconciliation, complete/reopen
compensation, and the completion/publication gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_entry,
    add_event,
    add_swimmer,
    add_team,
    assert_points_precision,
    complete_event_with_times,
    create_open_meet,
    declare_relay,
    get_success_data,
    lane_for_entry,
    make_meet_referee_headers,
    seed_meet,
    setup_deck_coverage,
    setup_in_progress_event,
    start_event,
    submit_clean_readings,
    validate_error,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


def _completed_tie_meet(api, meet_name, scoring_tie_policy):
    """Four swimmers finish 2490/2500/2500/2510 (tie at second) under the
    default points table; returns (workspace, completed_event)."""
    workspace = setup_in_progress_event(
        meet_name=meet_name,
        meet_overrides={"scoring_tie_policy": scoring_tie_policy},
        seed_times=(2400, 2450, 2460, 2470))
    completed = complete_event_with_times(workspace, [2490, 2500, 2500, 2510])
    assert completed["status"] == "COMPLETED"
    return workspace


def _result_for(api, entry):
    results = get_success_data(api.get_entry_result(entry["id"], DIRECTOR))
    assert len(results) == 1, "each scored entry has exactly one Result"
    return results[0]


class TestTiePolicySplitVsTop:
    """Difficulty pair (dual variants, scoring domain): identical race data
    pays 6.50 per tied swimmer under SPLIT but 7.00 under TOP."""

    def test_split_policy_pools_tied_points(self, api):
        """PRD §3.9: "Under `SPLIT`, each member of a tied group of size k at
        place p receives the sum of the base points across the k places the
        tie covers, divided by k, rounded half-up to two decimal places — a
        two-way tie at second under the default table splits seven and six,
        yielding 6.50 points each."
        PRD §3.9: "equal times share the same place, and the place awarded to
        the next distinct time advances by the size of the tie — two swimmers
        tied for second are both placed second, and the next distinct finisher
        is placed fourth."

        Design: Difficulty/dual_variant_calc/tie_policy_split_vs_top_points
        """
        workspace = _completed_tie_meet(api, "MS", "SPLIT")
        entries = workspace["entries"]
        res_a = _result_for(api, entries[0])  # 2490 -> place 1
        res_b = _result_for(api, entries[1])  # 2500 -> tie at 2
        res_c = _result_for(api, entries[2])  # 2500 -> tie at 2
        res_d = _result_for(api, entries[3])  # 2510 -> place 4
        assert (res_a["place"], res_a["points"]) == (1, 9.0)
        assert (res_b["place"], res_b["points"]) == (2, 6.5)
        assert (res_c["place"], res_c["points"]) == (2, 6.5)
        assert (res_d["place"], res_d["points"]) == (4, 5.0), \
            "competition ranking 1224: the place after the tie advances by two"
        team = get_success_data(
            api.get_team(workspace["teams"]["AAA"]["id"], DIRECTOR))
        assert team["provisional_points"] == 27.0  # 9.00 + 6.50 + 6.50 + 5.00

    def test_top_policy_pays_the_higher_place(self, api):
        """PRD §3.9: "Under `TOP`, each tied result receives the base points of
        the place at which the tie occurred — the same tie pays 7.00 each —
        while the following place still advances by the size of the tie."

        Design: Difficulty/dual_variant_calc/tie_policy_split_vs_top_points
        """
        workspace = _completed_tie_meet(api, "MT", "TOP")
        entries = workspace["entries"]
        res_b = _result_for(api, entries[1])
        res_c = _result_for(api, entries[2])
        res_d = _result_for(api, entries[3])
        assert (res_b["place"], res_b["points"]) == (2, 7.0)
        assert (res_c["place"], res_c["points"]) == (2, 7.0)
        assert (res_d["place"], res_d["points"]) == (4, 5.0)
        team = get_success_data(
            api.get_team(workspace["teams"]["AAA"]["id"], DIRECTOR))
        assert team["provisional_points"] == 28.0  # 9.00 + 7.00 + 7.00 + 5.00


class TestRelayMultiplierAndTableDepth:
    """Difficulty pair (multi-input non-linear interaction): a relay tie at
    first pays the pooled average times the relay multiplier; a place beyond
    the table depth pays zero."""

    def _setup(self, api):
        meet = create_open_meet(meet_name="CF1", points_table=[9, 7, 6],
                                relay_points_multiplier=2)
        team = add_team(meet["id"], team_code="RLY", team_name="Relayville")
        event = add_event(meet["id"], event_number=7, stroke="FREESTYLE_RELAY",
                          distance_meters=200, is_relay=True,
                          scheduled_start_minute=600, scheduled_end_minute=630)
        relays = {}
        for name, seed in (("A", 9500), ("B", 9600), ("C", 9700),
                           ("D", 9800)):
            relay = declare_relay(team["id"], event["id"], relay_name=name,
                                  seed_time_cs=seed)
            verify_entry(relay["entry_id"])
            relays[name] = relay
        setup_deck_coverage(event["id"], meet["id"])
        seed_meet(meet["id"])
        started = start_event(event["id"])
        lanes = {name: lane_for_entry(relay["entry_id"])
                 for name, relay in relays.items()}
        for name, pad in (("A", 8000), ("B", 8000), ("C", 8100), ("D", 8200)):
            submit_clean_readings(lanes[name]["id"], pad)
        completed = validate_success(api.complete_event(
            event["id"], started["version"], DIRECTOR))
        assert completed["status"] == "COMPLETED"
        return meet, team, event, relays

    def test_relay_tie_at_first_pools_then_multiplies(self, api):
        """PRD §3.9: "Under `SPLIT`, each member of a tied group of size k at
        place p receives the sum of the base points across the k places the
        tie covers, divided by k, rounded half-up to two decimal places".
        PRD §3.9: "For relay events, the result's points are multiplied by the
        meet's `relay_points_multiplier` after tie handling, with the product
        rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/relay_tie_multiplier_depth_interaction
        """
        _meet, _team, _event, relays = self._setup(api)
        res_a = _result_for(api, {"id": relays["A"]["entry_id"]})
        res_b = _result_for(api, {"id": relays["B"]["entry_id"]})
        res_c = _result_for(api, {"id": relays["C"]["entry_id"]})
        assert (res_a["place"], res_a["points"]) == (1, 16.0), \
            "pooled (9+7)/2 = 8.00, then x2 relay multiplier"
        assert (res_b["place"], res_b["points"]) == (1, 16.0)
        assert (res_c["place"], res_c["points"]) == (3, 12.0), \
            "the place after the tie advances by two; 6.00 x2"

    def test_place_beyond_table_depth_earns_zero(self, api):
        """PRD §3.9: "The base points for a place come from the meet's
        `points_table`, counting its first element as first place; places
        deeper than the table's length earn zero."
        PRD §3.9: "A team's `provisional_points` are the sum of `points`
        across **all** of its Result rows — `UNOFFICIAL` and `OFFICIAL` alike,
        with `DQ_EXCLUDED` rows contributing 0.00 — rounded half-up to two
        decimal places".

        Design: Difficulty/combinatorial_formula/relay_tie_multiplier_depth_interaction
        """
        _meet, team, _event, relays = self._setup(api)
        res_d = _result_for(api, {"id": relays["D"]["entry_id"]})
        assert (res_d["place"], res_d["points"]) == (4, 0.0), \
            "place 4 is beyond the depth-3 table"
        team_after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert team_after["provisional_points"] == 44.0
        assert_points_precision(team_after["provisional_points"],
                                context="provisional_points")


class TestProvisionalVsOfficialReconciliation:
    def test_provisional_leads_until_publish(self, api):
        """PRD §3.9: "A team's `provisional_points` are the sum of `points`
        across **all** of its Result rows — `UNOFFICIAL` and `OFFICIAL` alike,
        with `DQ_EXCLUDED` rows contributing 0.00 — rounded half-up to two
        decimal places; its `official_points` are the same sum restricted to
        `OFFICIAL` rows only."
        PRD §3.9: "Publication promotes every `UNOFFICIAL` Result to
        `OFFICIAL`, recomputes `official_points` for every team holding
        official results in the event".

        Design: Corner/calculations/provisional_vs_official_points_reconciliation
        """
        workspace = setup_in_progress_event(meet_name="PO1")
        complete_event_with_times(workspace, [2490])
        team_id = workspace["teams"]["AAA"]["id"]
        mid = get_success_data(api.get_team(team_id, DIRECTOR))
        assert mid["provisional_points"] == 9.0, \
            "UNOFFICIAL results count provisionally"
        assert mid["official_points"] == 0.0, "nothing is OFFICIAL yet"
        validate_success(api.publish_event(workspace["event"]["id"], DIRECTOR))
        results = get_success_data(
            api.get_entry_result(workspace["entries"][0]["id"], DIRECTOR))
        assert results[0]["status"] == "OFFICIAL"
        end = get_success_data(api.get_team(team_id, DIRECTOR))
        assert end["provisional_points"] == 9.0
        assert end["official_points"] == 9.0, "reconciled at publish"


class TestCompleteReopenCompensation:
    """Difficulty pair: complete -> reopen -> complete conserves the team's
    provisional_points exactly (9.00 -> 0.00 -> 9.00)."""

    def test_reopen_withdraws_distributed_points(self, api):
        """PRD §3.9: "The referee's reopen runs the other way: from `COMPLETED`
        back to `IN_PROGRESS`, hard-deleting all of the event's Result rows,
        returning `FINISHED` entries to `SEEDED` while `DQ` entries stay
        disqualified, recomputing the affected teams' `provisional_points`, and
        incrementing the event's `version`."

        Design: Difficulty/compensating_invariant/complete_reopen_recomplete_points_invariant
        """
        workspace = setup_in_progress_event(meet_name="CI2")
        complete_event_with_times(workspace, [2490])
        team_id = workspace["teams"]["AAA"]["id"]
        after_complete = get_success_data(api.get_team(team_id, DIRECTOR))
        assert after_complete["provisional_points"] == 9.0, \
            "the forward action distributes"
        referee_id = workspace["coverage"]["referee"]["id"]
        validate_success(api.reopen_event(
            workspace["event"]["id"], make_meet_referee_headers(referee_id)))
        after_reopen = get_success_data(api.get_team(team_id, DIRECTOR))
        assert after_reopen["provisional_points"] == 0.0, \
            "the compensation withdraws completely"
        entry = get_success_data(
            api.get_entry(workspace["entries"][0]["id"], DIRECTOR))
        assert entry["status"] == "SEEDED"
        results = get_success_data(
            api.get_entry_result(workspace["entries"][0]["id"], DIRECTOR))
        assert results == [], "the event's Result rows are hard-deleted"

    def test_recomplete_restores_points_exactly(self, api):
        """PRD §3.9: "The referee's reopen runs the other way: from `COMPLETED`
        back to `IN_PROGRESS`, hard-deleting all of the event's Result rows,
        returning `FINISHED` entries to `SEEDED` while `DQ` entries stay
        disqualified, recomputing the affected teams' `provisional_points`,
        and incrementing the event's `version`." PRD §3.9: "A non-tied,
        non-relay result simply earns its place's base points rendered at two
        decimal places."

        Design: Difficulty/compensating_invariant/complete_reopen_recomplete_points_invariant
        """
        workspace = setup_in_progress_event(meet_name="CI2b")
        complete_event_with_times(workspace, [2490])
        referee_id = workspace["coverage"]["referee"]["id"]
        reopened = validate_success(api.reopen_event(
            workspace["event"]["id"], make_meet_referee_headers(referee_id)))
        # Re-complete with the version the reopen advanced to; the reconciled
        # times are unchanged (lanes remain AUTO_CONFIRMED).
        recompleted = validate_success(api.complete_event(
            workspace["event"]["id"], reopened["version"], DIRECTOR))
        assert recompleted["status"] == "COMPLETED"
        team_id = workspace["teams"]["AAA"]["id"]
        after = get_success_data(api.get_team(team_id, DIRECTOR))
        assert after["provisional_points"] == 9.0, \
            "the round trip conserves the points sum exactly"
        results = get_success_data(
            api.get_entry_result(workspace["entries"][0]["id"], DIRECTOR))
        assert results[0]["place"] == 1


class TestCompletionGates:
    def test_complete_blocked_by_unresolved_lanes(self, api):
        """PRD §3.9: "every lane assignment whose `lane_status` is `ACTIVE`
        must have reached `AUTO_CONFIRMED` or `RESOLVED` — a single
        unreconciled lane blocks completion with `ERR_UNRESOLVED_LANES_EXIST`."

        Design: Corner/validations/complete_blocked_by_unresolved_lanes
        """
        workspace = setup_in_progress_event(meet_name="UL1")
        resp = api.complete_event(workspace["event"]["id"],
                                  workspace["event_version"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_LANES_EXIST)

    def test_publish_requires_completed_event(self, api):
        """PRD §3.9: "The director publishes a `COMPLETED` event — the
        requirement failing with `ERR_EVENT_NOT_COMPLETED` from any other
        posture".

        Design: Corner/state_machines/publish_requires_completed_event
        """
        workspace = setup_in_progress_event(meet_name="PB1")
        resp = api.publish_event(workspace["event"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_COMPLETED)

    def test_meet_complete_blocked_by_unofficial_events(self, api):
        """PRD §3.9: "Completing the meet moves it from `SEEDED` to `COMPLETED`
        and requires every event of the meet to stand in `OFFICIAL` or
        `CANCELLED`; anything short fails with `ERR_EVENTS_NOT_OFFICIAL`."

        Design: Corner/validations/meet_complete_blocked_by_unofficial_events
        """
        workspace = setup_in_progress_event(meet_name="MC1")
        complete_event_with_times(workspace, [2490])  # COMPLETED, not OFFICIAL
        resp = api.complete_meet(workspace["meet"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EVENTS_NOT_OFFICIAL)

    def test_event_complete_with_stale_version_rejected(self, api):
        """PRD §2.7: "If the event's current `version` has advanced since —
        typically an intervening referee reopen or a disqualification-driven
        rescore — the completion is rejected with `ERR_STALE_VERSION`
        (HTTP 412), again ahead of the state checks, because the client's view
        of which lanes are reconciled is stale."

        Design: Corner/complexity_layers/occ_event_complete_stale_version
        """
        workspace = setup_in_progress_event(meet_name="OC2")
        stale_version = workspace["event_version"]
        complete_event_with_times(workspace, [2490])
        referee_id = workspace["coverage"]["referee"]["id"]
        validate_success(api.reopen_event(
            workspace["event"]["id"], make_meet_referee_headers(referee_id)))
        resp = api.complete_event(workspace["event"]["id"], stale_version,
                                  DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

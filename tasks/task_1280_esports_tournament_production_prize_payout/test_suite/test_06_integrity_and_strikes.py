"""Integrity cases, strike decay, the ban threshold, and the DQ cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_integrity_case,
    create_player,
    create_server,
    get_integrity_case,
    get_match,
    get_player,
    get_registration,
    get_roster_slot,
    get_server,
    issue_violation_strike,
    make_anti_cheat_investigator_headers,
    resolve_case,
    schedule_match,
    set_clock,
    setup_in_progress_2team,
    setup_seeded_tournament,
    validate_error,
)

AC = TEST_USERS["anti_cheat_investigator_headers"]


class TestStrikeBanCascade:

    def test_third_strike_cascades_to_match_forfeit(self):
        """PRD §3.9: "If the recomputed count reaches 3 — at exactly 3 the
        ban triggers, at 2 it does not — the player's `eligibility_status`
        moves to `BANNED`, which is terminal within a tournament season with
        no unban path."
        PRD §3.9: "The ban then cascades: every `ACTIVE` `RosterSlot` for the
        player whose registration's tournament is in `REGISTRATION_LOCKED`,
        `SEEDED`, `IN_PROGRESS`, or `COMPLETED` moves to `INELIGIBLE`."
        PRD §3.9: "For each affected registration, if the count of `ACTIVE`
        `STARTER` slots has dropped below the tournament's `roster_size`, the
        registration moves `LOCKED → FORFEITED`."
        PRD §3.9: "For each forfeited registration, every non-terminal match
        where the registration is a participant moves to `FORFEIT` with
        walkover propagation, and the affected servers' `booked_minutes` are
        recomputed."

        Design: Difficulty/transitive_cascade/strike_ban_cascade_to_walkover
        """
        ctx = setup_in_progress_2team("Cascade Cup")
        r1, r2 = ctx["registrations"]
        p2 = ctx["players"][1]
        slot2 = ctx["slots"][1]
        match_id = ctx["match"]["id"]
        server_id = ctx["server"]["id"]

        issue_violation_strike(p2["id"], "sig 1")
        issue_violation_strike(p2["id"], "sig 2")
        player = get_player(p2["id"])
        assert player["active_strike_count"] == 2
        assert player["eligibility_status"] == "ELIGIBLE", \
            "at 2 active strikes the ban does not trigger"

        issue_violation_strike(p2["id"], "sig 3")
        player = get_player(p2["id"])
        assert player["active_strike_count"] == 3
        assert player["eligibility_status"] == "BANNED"

        assert get_roster_slot(slot2["id"])["status"] == "INELIGIBLE"
        assert get_registration(r2["id"])["status"] == "FORFEITED", \
            "ACTIVE starters drop to 0, below roster_size 1"
        match = get_match(match_id)
        assert match["status"] == "FORFEIT"
        assert match["winner_registration_id"] == r1["id"], \
            "walkover to the non-forfeiting side"
        assert get_server(server_id)["booked_minutes"] == 0, \
            "FORFEIT releases the 75-minute booking"
        assert get_registration(r1["id"])["status"] == "LOCKED", \
            "the unaffected team stays LOCKED"

    def test_two_strikes_do_not_ban(self):
        """PRD §3.9: "If the recomputed count reaches 3 — at exactly 3 the
        ban triggers, at 2 it does not — the player's `eligibility_status`
        moves to `BANNED`, which is terminal within a tournament season with
        no unban path."
        PRD §3.9: "The active strike count is the number of events in
        `ac_strike_events` whose `issued_at` is strictly after (now minus 365
        days); a strike exactly 365 days old is expired."

        Design: Difficulty/transitive_cascade/strike_ban_cascade_to_walkover
        """
        ctx = setup_in_progress_2team("TwoStrike Cup")
        r2 = ctx["registrations"][1]
        p2 = ctx["players"][1]
        slot2 = ctx["slots"][1]

        issue_violation_strike(p2["id"], "sig 1")
        issue_violation_strike(p2["id"], "sig 2")

        player = get_player(p2["id"])
        assert player["active_strike_count"] == 2
        assert player["eligibility_status"] == "ELIGIBLE"
        assert get_roster_slot(slot2["id"])["status"] == "ACTIVE"
        assert get_registration(r2["id"])["status"] == "LOCKED"
        assert get_match(ctx["match"]["id"])["status"] == "SCHEDULED"
        assert get_server(ctx["server"]["id"])["booked_minutes"] == 75


class TestStrikeWindow:

    def test_strike_window_expiry_boundary(self):
        """PRD §3.9: "The active strike count is the number of events in
        `ac_strike_events` whose `issued_at` is strictly after (now minus 365
        days); a strike exactly 365 days old is expired."
        PRD §2.5: "Reads of the clock for rule evaluation always see the most
        recently set value."

        Design: Corner/calculations/strike_window_expiry_boundary
        """
        player = create_player("p1", "2000-01-01", "NA")
        set_clock("2026-08-10T00:00:00Z")
        issue_violation_strike(player["id"], "sig 1")
        issue_violation_strike(player["id"], "sig 2")

        set_clock("2027-08-09T23:59:59Z")
        before = get_player(player["id"])
        assert before["active_strike_count"] == 2, \
            "one second before expiry both strikes are still active"

        set_clock("2027-08-10T00:00:00Z")
        after = get_player(player["id"])
        assert after["active_strike_count"] == 0, \
            "a strike exactly 365 days old is expired (strictly-greater window)"
        assert after["eligibility_status"] == "ELIGIBLE"


class TestCaseMachine:

    def test_error_invalid_case_status_on_double_resolve(self):
        """PRD §3.9: "`RESOLVE` is valid only from `INVESTIGATING` and takes
        an `outcome` of `CLEARED` or `VIOLATION`."
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/errors/error_invalid_case_status_on_double_resolve
        """
        player = create_player("p1", "2000-01-01", "NA")
        case = issue_violation_strike(player["id"], "sig 1")
        assert case["status"] == "RESOLVED_VIOLATION"
        assert case["strike_issued"] is True

        resp = api_client.resolve_integrity_case(
            case["id"], {"action": "RESOLVE", "outcome": "CLEARED"},
            make_anti_cheat_investigator_headers("ac-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATUS)
        after = get_integrity_case(case["id"])
        assert after["status"] == "RESOLVED_VIOLATION"
        assert after["strike_issued"] is True

    def test_sod_referee_cannot_resolve_own_match_case(self):
        """PRD §2.10: "An integrity case cannot be resolved by the
        investigator whose `X-User-ID` equals the `assigned_referee_id` of
        the match referenced by the case (the check applies only when
        `match_id` is non-null)."
        PRD §2.10: "Violations are rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 422)."
        PRD §3.9: "A `CLEARED` outcome records `resolved_by_user_id` and
        `resolved_at` and moves the case to `RESOLVED_CLEARED`."

        Design: Corner/rbac/sod_referee_cannot_resolve_own_match_case
        """
        ctx = setup_seeded_tournament("SoD3 Cup")
        tournament_id = ctx["tournament"]["id"]
        server = create_server(tournament_id, "S1", "NA")
        match = ctx["matches"][0]
        schedule_match(match["id"], server["id"], "2026-08-11T10:00:00Z",
                       60, "ref-9")
        p1 = ctx["players"][0]
        case = create_integrity_case(p1["id"], "wallhack clip round 3",
                                     match_id=match["id"])
        resolve_case(case["id"], {"action": "BEGIN_INVESTIGATION"})

        resp = api_client.resolve_integrity_case(
            case["id"], {"action": "RESOLVE", "outcome": "CLEARED"},
            make_anti_cheat_investigator_headers("ref-9"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        resolved = resolve_case(case["id"],
                                {"action": "RESOLVE", "outcome": "CLEARED"},
                                investigator_id="ac-2")
        assert resolved["status"] == "RESOLVED_CLEARED"
        assert resolved["resolved_by_user_id"] == "ac-2"
        assert resolved["strike_issued"] is False

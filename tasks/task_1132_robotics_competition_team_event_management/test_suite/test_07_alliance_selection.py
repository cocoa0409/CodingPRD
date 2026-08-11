"""Alliance selection: captain seeding, pick eligibility, and the OCC guard
on picks (PRD §3.6, §2.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_team_lead_headers,
    ranked_confirmed_teams,
    setup_alliance_selection,
    validate_error,
    validate_success,
    api_client,
)

ED = TEST_USERS["event_director_headers"]


def _captain_mentor(ctx, captain_team_id):
    for entry in ctx["teams"]:
        if entry["team"]["id"] == captain_team_id:
            return entry["mentor"]
    raise AssertionError("captain team not found in fixture teams")


def _eligible_pick_target(ctx, captain_ids):
    for entry in sorted(ctx["teams"], key=lambda e: e["team"]["team_number"]):
        if entry["team"]["id"] not in captain_ids:
            return entry["team"]["id"]
    raise AssertionError("no eligible team left to pick")


class TestCaptainSeeding:
    def test_eight_captains_seeded_in_ranking_order(self):
        """PRD §3.6: "The first 8 teams of that sorted list become captains;
        for each, an `Alliance` row is created with `seed` equal to the
        1-based position in the sorted list, `captain_team_id` equal to the
        team's id, and `status` equal to `FORMING`." — the sort being
        "`ranking_score` descending, then `ranking_tie_break` descending,
        then `team_number` ascending, then `created_at` ascending".

        Design: Corner/calculations/alliance_captain_seeding_uses_ranking
        """
        ctx = setup_alliance_selection(num_teams=24)
        alliances = ctx["alliances"]
        assert len(alliances) == 8
        by_seed = {a["seed"]: a for a in alliances}
        assert sorted(by_seed) == [1, 2, 3, 4, 5, 6, 7, 8]
        for a in alliances:
            assert a["status"] == "FORMING"
        expected_order = [t["id"] for t in ranked_confirmed_teams(ctx["event"]["id"])[:8]]
        for seed in range(1, 9):
            assert by_seed[seed]["captain_team_id"] == expected_order[seed - 1], (
                f"seed {seed} must be the #{seed} team by the pinned ranking sort"
            )
        round1 = [r for r in ctx["rounds"] if r["round_index"] == 1][0]
        assert round1["status"] == "OPEN"


class TestPickEligibility:
    def test_picking_a_captain_is_ineligible(self):
        """PRD §3.6: "The team being picked must satisfy three eligibility
        conditions simultaneously: their `registration_status` is `CONFIRMED`,
        they are not themselves a captain (`is_alliance_captain` is false),
        and they are not already on another alliance ... Picking an
        ineligible team is rejected with `ERR_PICK_INELIGIBLE` (HTTP 422)."

        Design: Corner/errors/err_pick_ineligible_triggerable
        """
        ctx = setup_alliance_selection(num_teams=24)
        event_id = ctx["event"]["id"]
        round1 = [r for r in ctx["rounds"] if r["round_index"] == 1][0]
        round1 = validate_success(api_client.get_selection_round(event_id, round1["id"], ED))
        current_captain = round1["current_captain_team_id"]
        mentor = _captain_mentor(ctx, current_captain)
        other_captain = next(
            a["captain_team_id"] for a in ctx["alliances"]
            if a["captain_team_id"] != current_captain
        )
        resp = api_client.submit_pick(
            event_id, round1["id"], other_captain, round1["version"],
            make_team_lead_headers(mentor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PICK_INELIGIBLE)

    def test_pick_with_stale_round_version_rejected(self):
        """PRD §2.4: "Submitting an alliance pick requires
        `expected_round_version` matching the current
        `AllianceSelectionRound.version`; a stale round view — for example,
        one whose `current_captain_team_id` no longer reflects the latest
        pick — is likewise rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting/occ_alliance_pick_stale_version
        """
        ctx = setup_alliance_selection(num_teams=24)
        event_id = ctx["event"]["id"]
        round1 = [r for r in ctx["rounds"] if r["round_index"] == 1][0]
        round1 = validate_success(api_client.get_selection_round(event_id, round1["id"], ED))
        current_captain = round1["current_captain_team_id"]
        mentor = _captain_mentor(ctx, current_captain)
        captain_ids = {a["captain_team_id"] for a in ctx["alliances"]}
        target = _eligible_pick_target(ctx, captain_ids)
        # Every other gate passes (turn, eligibility); only the OCC version
        # is stale.
        resp = api_client.submit_pick(
            event_id, round1["id"], target, round1["version"] + 100,
            make_team_lead_headers(mentor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

"""Championship qualification waterfall: bucket ordering and the CHAIRMANS
decide cascade (PRD §3.7, §3.8)."""
from test_helpers import (
    TEST_USERS,
    list_all_teams,
    ranked_confirmed_teams,
    setup_closed_event_with_chairmans,
    setup_qualified_team,
    validate_success,
    api_client,
)

ED = TEST_USERS["event_director_headers"]


class TestChampionshipWaterfall:
    def test_chairmans_winner_consumes_bucket1_not_double_counted(self):
        """PRD §3.8: "Bucket 1: the `CHAIRMANS` award winner — if that award
        is `PRESENTED` and has a non-null `winner_team_id`, that team takes
        one slot." and "Bucket 4: every remaining `CONFIRMED` team not yet
        awarded, sorted by `ranking_score` descending, `ranking_tie_break`
        descending, `team_number` ascending, `created_at` ascending, taking
        slots in order until none remain." and "Teams that already had
        `qualified_for_championship` set to true by an earlier cascade — a
        `CHAIRMANS` decide, a `CHAMPION` alliance — still consume a slot in
        the waterfall so the slot counts remain honest."

        With championship_slots=2 the qualifiers must be exactly {chairmans
        winner, best-ranked other CONFIRMED team}; a reversed bucket order
        would hand the slots to the top two ranked teams instead.

        Design: Difficulty/combinatorial_formula/championship_qualification_mode_c_circular_dependency_pinned
        """
        ctx, chairmans_entry, award = setup_closed_event_with_chairmans()
        event_id = ctx["event"]["id"]
        assert ctx["event"]["status"] == "CLOSED"
        assert award["winner_team_id"] == chairmans_entry["team"]["id"]

        teams = list_all_teams(event_id)
        by_id = {t["id"]: t for t in teams}
        a_id = chairmans_entry["team"]["id"]
        # Expected bucket-4 recipient: best-ranked CONFIRMED team that is not
        # the CHAIRMANS winner (pinned sort from PRD §3.8).
        remaining = [t for t in ranked_confirmed_teams(event_id) if t["id"] != a_id]
        b_id = remaining[0]["id"]
        c_id = remaining[1]["id"]

        assert by_id[a_id]["qualified_for_championship"] is True
        assert by_id[b_id]["qualified_for_championship"] is True
        assert by_id[c_id]["qualified_for_championship"] is False
        qualified = {t["id"] for t in teams if t["qualified_for_championship"] is True}
        assert qualified == {a_id, b_id}

    def test_chairmans_decide_flips_qualified_immediately(self):
        """PRD §3.7: "If the `award_kind` is `CHAIRMANS`, the winning team's
        `qualified_for_championship` immediately flips to true as a cascade —
        the chairmans winner does not wait for the championship waterfall."

        Design: Difficulty/combinatorial_formula/championship_qualification_mode_c_circular_dependency_pinned
        """
        ctx, target, award = setup_qualified_team()
        # The event is still in MATCHES_RUNNING — no waterfall has run.
        assert ctx["event"]["status"] == "MATCHES_RUNNING"
        assert award["status"] == "DECIDED"
        assert award["winner_team_id"] == target["team"]["id"]
        team = validate_success(api_client.get_team(ctx["event"]["id"], target["team"]["id"], ED))
        assert team["qualified_for_championship"] is True

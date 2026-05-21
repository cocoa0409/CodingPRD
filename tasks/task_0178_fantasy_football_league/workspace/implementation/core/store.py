"""In-memory data store for all Fantasy Football League entities."""
from __future__ import annotations

from typing import Dict, List


class _Store:
    """Process-wide singleton holding every entity collection."""

    def __init__(self) -> None:
        self.leagues: Dict[str, dict] = {}
        self.teams: Dict[str, dict] = {}
        self.players: Dict[str, dict] = {}
        self.draft_picks: Dict[str, dict] = {}
        self.roster_slots: Dict[str, dict] = {}
        self.waiver_claims: Dict[str, dict] = {}
        self.trade_proposals: Dict[str, dict] = {}
        self.trade_votes: Dict[str, dict] = {}
        self.matchup_weeks: Dict[str, dict] = {}
        self.keeper_designations: Dict[str, dict] = {}

        # Tracks drop events per league: {league_id: [(player_id, dropped_at_ts), ...]}
        self.drop_history: Dict[str, List[tuple]] = {}

        # Tracks scoring snapshots: {(league_id, week_number): {team_id: [slot_ids]}}
        self.lock_snapshots: Dict[tuple, dict] = {}

    # Helpers
    def teams_in_league(self, league_id: str) -> List[dict]:
        return [t for t in self.teams.values() if t["league_id"] == league_id]

    def roster_slots_for_team(self, team_id: str) -> List[dict]:
        return [r for r in self.roster_slots.values() if r["team_id"] == team_id]

    def players_on_team(self, team_id: str) -> List[str]:
        return [r["player_id"] for r in self.roster_slots_for_team(team_id)]

    def player_team_in_league(self, league_id: str, player_id: str):
        """Return the team that owns this player in this league, if any."""
        league_team_ids = {t["id"] for t in self.teams_in_league(league_id)}
        for rs in self.roster_slots.values():
            if rs["team_id"] in league_team_ids and rs["player_id"] == player_id:
                return rs
        return None

    def draft_picks_in_league(self, league_id: str) -> List[dict]:
        return [d for d in self.draft_picks.values() if d["league_id"] == league_id]

    def keepers_for_team(self, team_id: str) -> List[dict]:
        return [k for k in self.keeper_designations.values() if k["team_id"] == team_id]

    def matchups_in_league(self, league_id: str) -> List[dict]:
        return [m for m in self.matchup_weeks.values() if m["league_id"] == league_id]

    def waiver_claims_in_league(self, league_id: str) -> List[dict]:
        return [w for w in self.waiver_claims.values() if w["league_id"] == league_id]

    def trades_in_league(self, league_id: str) -> List[dict]:
        return [t for t in self.trade_proposals.values() if t["league_id"] == league_id]

    def votes_for_trade(self, trade_id: str) -> List[dict]:
        return [v for v in self.trade_votes.values() if v["trade_proposal_id"] == trade_id]

    def reset(self) -> None:
        self.__init__()


store = _Store()

"""Aggregate recomputation helpers — recalc derived fields on entities and stamp updates."""
from __future__ import annotations

from decimal import Decimal

from .. import calculations as calc
from ..store import Store, stamp_update


def recompute_team_roster(store: Store, team: dict) -> None:
    roster, tier_a = calc.team_roster_aggregates(store.players.values(), team["id"])
    team["roster_count"] = roster
    team["tier_a_count"] = tier_a
    stamp_update(team)


def recompute_team_record(store: Store, team: dict) -> None:
    wins, losses = calc.team_record(team["id"], store.games.values())
    team["wins"] = wins
    team["losses"] = losses
    stamp_update(team)


def recompute_guardian_volunteer(store: Store, guardian: dict, season_id: str | None = None) -> None:
    if season_id is None:
        # Active season heuristic: most recent non-CLOSED season.
        from .lookup import active_season

        s = active_season(store)
        if s is None:
            guardian["volunteer_hours_logged"] = Decimal("0.00")
            guardian["volunteer_status"] = "DEFICIENT"
            stamp_update(guardian)
            return
        season_id = s["id"]
        required = Decimal(str(s["volunteer_hours_required_per_family"]))
    else:
        season = store.seasons.get(season_id)
        required = Decimal(str(season["volunteer_hours_required_per_family"])) if season else Decimal("0")
    logged = calc.guardian_volunteer_hours(guardian["id"], season_id, store.shifts.values())
    guardian["volunteer_hours_logged"] = logged
    guardian["volunteer_status"] = calc.volunteer_status_classification(logged, required)
    stamp_update(guardian)

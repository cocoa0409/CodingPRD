"""Existence lookups that raise the right error when an id does not resolve."""
from __future__ import annotations

from ..errors import raise_error
from ..store import Store


def get_season(store: Store, season_id: str) -> dict:
    s = store.seasons.get(season_id)
    if s is None:
        raise_error("ERR_SEASON_NOT_FOUND")
    return s


def get_team(store: Store, team_id: str) -> dict:
    t = store.teams.get(team_id)
    if t is None:
        raise_error("ERR_TEAM_NOT_FOUND")
    return t


def get_player(store: Store, player_id: str) -> dict:
    p = store.players.get(player_id)
    if p is None:
        raise_error("ERR_PLAYER_NOT_FOUND")
    return p


def get_game(store: Store, game_id: str) -> dict:
    g = store.games.get(game_id)
    if g is None:
        raise_error("ERR_GAME_NOT_FOUND")
    return g


def get_shift(store: Store, shift_id: str) -> dict:
    s = store.shifts.get(shift_id)
    if s is None:
        raise_error("ERR_SHIFT_NOT_FOUND")
    return s


def get_guardian(store: Store, guardian_id: str) -> dict:
    g = store.guardians.get(guardian_id)
    if g is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Guardian not found.")
    return g


def get_coach(store: Store, coach_id: str) -> dict:
    c = store.coaches.get(coach_id)
    if c is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Coach not found.")
    return c


def get_referee(store: Store, referee_id: str) -> dict:
    r = store.referees.get(referee_id)
    if r is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Referee not found.")
    return r


def active_season(store: Store) -> dict | None:
    """Most recent (by created_at) Season whose status != CLOSED, used by volunteer aggregation."""
    candidates = [s for s in store.seasons.values() if s.get("status") != "CLOSED"]
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["created_at"], reverse=True)
    return candidates[0]

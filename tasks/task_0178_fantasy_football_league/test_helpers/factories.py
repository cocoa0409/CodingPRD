"""Payload factories — one per endpoint that accepts a body, input
fields only.

PRD §4 endpoint table is the authoritative source for input fields.
Each factory emits exactly the fields PRD describes as input; computed
fields (e.g., status, current_week, faab_balance_dollars on Team,
priority_seed, review_deadline_ts, assigned_round, home_points) are
NEVER emitted from a factory — they are computed by the server.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def iso_utc(dt: datetime) -> str:
    """Format a datetime as PRD §2.4 ISO 8601 UTC with three fractional
    digits, ending in Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_offset(base: datetime, **delta) -> str:
    return iso_utc(base + timedelta(**delta))


def utc(year: int, month: int, day: int,
        hour: int = 0, minute: int = 0, second: int = 0, ms: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, ms * 1000, tzinfo=timezone.utc)


def manager_uid(label: str = "") -> str:
    """Build a unique manager_user_id. Tests subsequently mint
    Manager headers via make_manager_headers(this_id)."""
    return f"mgr-{label or _suffix()}"


# A stable anchor far enough in the future to allow tests to step
# forward and backward without colliding with a real clock.
DEFAULT_BASE_CLOCK = utc(2026, 8, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# League (PRD §3.1)
# ---------------------------------------------------------------------------
def create_league_payload(
    *,
    name: Optional[str] = None,
    season_year: int = 2026,
    draft_mode: str = "SNAKE",
    scoring_mode: str = "STANDARD",
    team_count: int = 4,
    roster_size: int = 12,
    starter_count: int = 7,
    ir_slots: int = 1,
    faab_budget_dollars: int = 100,
    auction_budget_dollars: Optional[int] = None,
    keeper_mode: str = "NONE",
    keeper_cap: Optional[int] = None,
    veto_quorum_pct: Optional[int] = None,
    trade_review_hours: Optional[int] = None,
    waiver_period_hours: Optional[int] = None,
    playoff_team_count: int = 2,
    regular_season_weeks: int = 10,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"League-{_suffix()}",
        "season_year": season_year,
        "draft_mode": draft_mode,
        "scoring_mode": scoring_mode,
        "team_count": team_count,
        "roster_size": roster_size,
        "starter_count": starter_count,
        "ir_slots": ir_slots,
        "faab_budget_dollars": faab_budget_dollars,
        "keeper_mode": keeper_mode,
        "playoff_team_count": playoff_team_count,
        "regular_season_weeks": regular_season_weeks,
    }
    if auction_budget_dollars is not None:
        payload["auction_budget_dollars"] = auction_budget_dollars
    if keeper_cap is not None:
        payload["keeper_cap"] = keeper_cap
    if veto_quorum_pct is not None:
        payload["veto_quorum_pct"] = veto_quorum_pct
    if trade_review_hours is not None:
        payload["trade_review_hours"] = trade_review_hours
    if waiver_period_hours is not None:
        payload["waiver_period_hours"] = waiver_period_hours
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Team (PRD §3.1)
# ---------------------------------------------------------------------------
def create_team_payload(
    *,
    manager_user_id: str,
    name: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Team-{_suffix()}",
        "manager_user_id": manager_user_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Player (PRD §3.1)
# ---------------------------------------------------------------------------
def create_player_payload(
    *,
    full_name: Optional[str] = None,
    nfl_team: str = "KC",
    position: str = "RB",
    weekly_proj_points: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Player-{_suffix()}",
        "nfl_team": nfl_team,
        "position": position,
    }
    if weekly_proj_points is not None:
        payload["weekly_proj_points"] = weekly_proj_points
    payload.update(overrides)
    return payload


def player_status_payload(
    *,
    status_tag: str,
    weekly_proj_points: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status_tag": status_tag}
    if weekly_proj_points is not None:
        payload["weekly_proj_points"] = weekly_proj_points
    return payload


# ---------------------------------------------------------------------------
# DraftPick (PRD §3.3)
# ---------------------------------------------------------------------------
def create_draft_pick_payload(
    *,
    team_id: str,
    player_id: str,
    price_dollars: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "player_id": player_id,
    }
    if price_dollars is not None:
        payload["price_dollars"] = price_dollars
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Keeper (PRD §3.2)
# ---------------------------------------------------------------------------
def create_keeper_payload(
    *,
    player_id: str,
    season_year: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "player_id": player_id,
        "season_year": season_year,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Waiver (PRD §3.6)
# ---------------------------------------------------------------------------
def create_waiver_payload(
    *,
    team_id: str,
    add_player_id: str,
    bid_dollars: int,
    settle_ts: str,
    drop_player_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "add_player_id": add_player_id,
        "bid_dollars": bid_dollars,
        "settle_ts": settle_ts,
    }
    if drop_player_id is not None:
        payload["drop_player_id"] = drop_player_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Trade (PRD §3.7)
# ---------------------------------------------------------------------------
def create_trade_payload(
    *,
    proposing_team_id: str,
    counterparty_team_id: str,
    send_player_ids: List[str],
    receive_player_ids: List[str],
    send_faab_dollars: Optional[int] = None,
    receive_faab_dollars: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "proposing_team_id": proposing_team_id,
        "counterparty_team_id": counterparty_team_id,
        "send_player_ids": list(send_player_ids),
        "receive_player_ids": list(receive_player_ids),
    }
    if send_faab_dollars is not None:
        payload["send_faab_dollars"] = send_faab_dollars
    if receive_faab_dollars is not None:
        payload["receive_faab_dollars"] = receive_faab_dollars
    payload.update(overrides)
    return payload


def trade_vote_payload(
    *,
    voting_team_id: str,
    vote: str,
) -> Dict[str, Any]:
    return {"voting_team_id": voting_team_id, "vote": vote}


# ---------------------------------------------------------------------------
# RosterSlot patch (PRD §3.4)
# ---------------------------------------------------------------------------
def patch_roster_slot_payload(
    *,
    slot_type: Optional[str] = None,
    position_label: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if slot_type is not None:
        payload["slot_type"] = slot_type
    if position_label is not None:
        payload["position_label"] = position_label
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# Matchup score (PRD §3.5)
# ---------------------------------------------------------------------------
def score_entry(
    *,
    player_id: str,
    actual_points: float,
    receptions_credited: Optional[int] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "player_id": player_id,
        "actual_points": actual_points,
    }
    if receptions_credited is not None:
        entry["receptions_credited"] = receptions_credited
    return entry


def score_payload(scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"scores": scores}


__all__ = [
    "iso_utc",
    "iso_offset",
    "utc",
    "manager_uid",
    "DEFAULT_BASE_CLOCK",
    "create_league_payload",
    "create_team_payload",
    "create_player_payload",
    "player_status_payload",
    "create_draft_pick_payload",
    "create_keeper_payload",
    "create_waiver_payload",
    "create_trade_payload",
    "trade_vote_payload",
    "patch_roster_slot_payload",
    "score_entry",
    "score_payload",
]

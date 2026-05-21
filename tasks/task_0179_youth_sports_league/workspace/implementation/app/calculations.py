"""Calculation rules from SCAFFOLD.yaml §1.3.

Each function here implements one named calc. Care is taken with rounding and
boundary semantics — see PRD §2.10 (Precision, Rounding, and Time).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from math import ceil, log2
from typing import Iterable

# ---------------------------------------------------------------------------
# tier_classification
# ---------------------------------------------------------------------------
TIER_A_MIN = Decimal("85.0")
TIER_B_MIN = Decimal("70.0")
TIER_C_MIN = Decimal("50.0")


def tier_classification(score: float) -> str:
    s = Decimal(str(score))
    if s >= TIER_A_MIN:
        return "TIER_A"
    if s >= TIER_B_MIN:
        return "TIER_B"
    if s >= TIER_C_MIN:
        return "TIER_C"
    return "TIER_D"


# ---------------------------------------------------------------------------
# team_roster_aggregates
# ---------------------------------------------------------------------------
TIER_A_CAP = 3


def team_roster_aggregates(players: Iterable[dict], team_id: str) -> tuple[int, int]:
    roster = 0
    tier_a = 0
    for p in players:
        if p.get("team_id") == team_id and p.get("status") == "DRAFTED":
            roster += 1
            if p.get("evaluation_tier") == "TIER_A":
                tier_a += 1
    return roster, tier_a


# ---------------------------------------------------------------------------
# draft_seat_resolver
# ---------------------------------------------------------------------------
def draft_seat_resolver(season_id: str, teams: list[dict], players: Iterable[dict]) -> int:
    season_teams = [t for t in teams if t.get("season_id") == season_id]
    N = len(season_teams)
    if N == 0:
        return 0
    picks_so_far = sum(
        1 for p in players if p.get("season_id") == season_id and p.get("status") == "DRAFTED"
    )
    round_index = picks_so_far // N
    seat_in_round = picks_so_far % N
    if round_index % 2 == 0:
        return seat_in_round + 1
    return N - seat_in_round


# ---------------------------------------------------------------------------
# Interval helpers
# ---------------------------------------------------------------------------
GAME_DURATION = timedelta(minutes=90)
REF_BUFFER = timedelta(minutes=30)


def half_open_overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """[a_start, a_end) overlaps [b_start, b_end) iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# field_overlap_check
# ---------------------------------------------------------------------------
def field_overlap_check(
    new_start: datetime,
    new_end: datetime,
    field_id: str,
    games: Iterable[dict],
    exclude_game_id: str | None = None,
) -> bool:
    """Return True if a collision exists; False if the slot is free.

    Considered games: same field_id, status in {SCHEDULED, COMPLETED, FORFEITED},
    excluding the game being edited (if id provided)."""
    for g in games:
        if g.get("id") == exclude_game_id:
            continue
        if g.get("field_id") != field_id:
            continue
        if g.get("status") not in ("SCHEDULED", "COMPLETED", "FORFEITED"):
            continue
        from .time_utils import parse_iso

        g_start = parse_iso(g["scheduled_start"])
        g_end = parse_iso(g["scheduled_end"])
        if half_open_overlaps(new_start, new_end, g_start, g_end):
            return True
    return False


# ---------------------------------------------------------------------------
# referee_overlap_check
# ---------------------------------------------------------------------------
def referee_overlap_check(
    target_start: datetime,
    target_end: datetime,
    referee_id: str,
    games: Iterable[dict],
    exclude_game_id: str | None = None,
) -> bool:
    """Return True if a buffered overlap exists for this referee."""
    from .time_utils import parse_iso

    for g in games:
        if g.get("id") == exclude_game_id:
            continue
        if g.get("referee_id") != referee_id:
            continue
        if g.get("status") not in ("SCHEDULED", "COMPLETED"):
            continue
        g_start = parse_iso(g["scheduled_start"])
        g_end = parse_iso(g["scheduled_end"])
        # target.start < g.end + buffer AND g.start - buffer < target.end
        if target_start < (g_end + REF_BUFFER) and (g_start - REF_BUFFER) < target_end:
            return True
    return False


def referee_weekly_count(
    referee_id: str,
    target_start: datetime,
    games: Iterable[dict],
    exclude_game_id: str | None = None,
) -> int:
    """Count of this referee's non-CANCELLED games in the same ISO week (UTC Monday..Sunday)
    as target_start, excluding the target itself.
    """
    from .time_utils import parse_iso

    week_start, week_end = iso_week_bounds(target_start)
    count = 0
    for g in games:
        if g.get("id") == exclude_game_id:
            continue
        if g.get("referee_id") != referee_id:
            continue
        if g.get("status") == "CANCELLED":
            continue
        g_start = parse_iso(g["scheduled_start"])
        if week_start <= g_start <= week_end:
            count += 1
    return count


def iso_week_bounds(dt: datetime) -> tuple[datetime, datetime]:
    """Return Monday 00:00:00.000 UTC and Sunday 23:59:59.999 UTC bounding dt's ISO week."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    weekday = dt.isoweekday()  # Monday=1
    monday = (dt - timedelta(days=weekday - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59, milliseconds=999)
    return monday, sunday


# ---------------------------------------------------------------------------
# team_record
# ---------------------------------------------------------------------------
def team_record(team_id: str, games: Iterable[dict]) -> tuple[int, int]:
    wins = 0
    losses = 0
    for g in games:
        status = g.get("status")
        home = g.get("home_team_id")
        away = g.get("away_team_id")
        if team_id not in (home, away):
            continue
        if status == "COMPLETED":
            hs = g.get("home_score") or 0
            as_ = g.get("away_score") or 0
            if home == team_id:
                if hs > as_:
                    wins += 1
                elif hs < as_:
                    losses += 1
            else:
                if as_ > hs:
                    wins += 1
                elif as_ < hs:
                    losses += 1
        elif status == "FORFEITED":
            forfeit = g.get("forfeiting_team_id")
            if forfeit == team_id:
                losses += 1
            else:
                wins += 1
    return wins, losses


# ---------------------------------------------------------------------------
# playoff_seeding
# ---------------------------------------------------------------------------
PLAYOFF_BRACKET_SIZE = 4


def _win_pct(wins: int, losses: int) -> Decimal:
    total = wins + losses
    if total == 0:
        return Decimal("0.0000")
    p = Decimal(wins) / Decimal(total)
    return p.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _run_differential(team_id: str, games: Iterable[dict]) -> int:
    diff = 0
    for g in games:
        if g.get("status") != "COMPLETED":
            continue
        home = g.get("home_team_id")
        away = g.get("away_team_id")
        hs = g.get("home_score") or 0
        as_ = g.get("away_score") or 0
        if home == team_id:
            diff += hs - as_
        elif away == team_id:
            diff += as_ - hs
    return diff


def _head_to_head_wins(team_id: str, tied_team_ids: set[str], games: Iterable[dict]) -> int:
    h2h = 0
    for g in games:
        if g.get("status") != "COMPLETED":
            continue
        home = g.get("home_team_id")
        away = g.get("away_team_id")
        if home == team_id and away in tied_team_ids and (g.get("home_score") or 0) > (g.get("away_score") or 0):
            h2h += 1
        elif away == team_id and home in tied_team_ids and (g.get("away_score") or 0) > (g.get("home_score") or 0):
            h2h += 1
    return h2h


def playoff_seeding(teams: list[dict], games: list[dict]) -> list[dict]:
    """Return teams sorted per PRD §3.6. Top 4 are seeded; rest eliminated.
    Tie-breaks: win_pct DESC, head_to_head_wins among tied DESC, run differential DESC, name ASC.
    """
    # Step 1: compute win_pct.
    enriched: list[dict] = []
    for t in teams:
        wins, losses = team_record(t["id"], games)
        enriched.append(
            {
                "team": t,
                "win_pct": _win_pct(wins, losses),
                "run_diff": _run_differential(t["id"], games),
                "name": t.get("name", ""),
            }
        )

    # Step 2: group by win_pct (the primary sort key); within each group apply head-to-head.
    enriched.sort(key=lambda e: (-e["win_pct"], -e["run_diff"], e["name"]))

    # Re-sort within tie groups, computing head-to-head wins relative to other tied teams.
    grouped: list[list[dict]] = []
    cur_key = None
    cur: list[dict] = []
    for e in enriched:
        k = e["win_pct"]
        if k != cur_key:
            if cur:
                grouped.append(cur)
            cur = [e]
            cur_key = k
        else:
            cur.append(e)
    if cur:
        grouped.append(cur)

    final: list[dict] = []
    for grp in grouped:
        if len(grp) <= 1:
            final.extend(grp)
            continue
        tied_ids = {g["team"]["id"] for g in grp}
        for g in grp:
            g["h2h"] = _head_to_head_wins(g["team"]["id"], tied_ids - {g["team"]["id"]}, games)
        grp.sort(key=lambda e: (-e["h2h"], -e["run_diff"], e["name"]))
        final.extend(grp)

    return [e["team"] for e in final]


def playoff_final_round(qualified_count: int) -> int:
    if qualified_count <= 1:
        return 1
    return int(ceil(log2(qualified_count)))


# ---------------------------------------------------------------------------
# guardian_volunteer_hours
# ---------------------------------------------------------------------------
def guardian_volunteer_hours(guardian_id: str, season_id: str, shifts: Iterable[dict]) -> Decimal:
    total = Decimal("0")
    for s in shifts:
        if s.get("guardian_id") != guardian_id:
            continue
        if s.get("season_id") != season_id:
            continue
        if s.get("status") != "APPROVED":
            continue
        total += Decimal(str(s.get("hours_credited") or 0))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# volunteer_status_classification
# ---------------------------------------------------------------------------
def volunteer_status_classification(logged: Decimal, required: Decimal) -> str:
    half = required * Decimal("0.5")
    if logged >= required:
        return "FULFILLED"
    if logged >= half:
        return "ON_TRACK"
    return "DEFICIENT"


# ---------------------------------------------------------------------------
# shift_hours
# ---------------------------------------------------------------------------
def shift_hours(start: datetime, end: datetime) -> Decimal:
    delta_seconds = (end - start).total_seconds()
    hours = Decimal(str(delta_seconds)) / Decimal("3600")
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

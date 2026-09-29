"""Domain assertions for the tennis league API."""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import MATCH_WIN_POINTS


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the four common fields of a mutable entity (PRD 2.4)."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be ISO-8601, got {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be ISO-8601, got {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entity: Dict[str, Any]):
    """A CommitteeVote carries only ``id`` and ``created_at`` (PRD 2.4)."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert "updated_at" not in entity, "CommitteeVote must not carry updated_at"
    assert "version" not in entity, "CommitteeVote must not carry version"


def assert_envelope_meta(body: Dict[str, Any]):
    """Assert the envelope meta block (PRD 2.2)."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    ts = meta["api_request_timestamp"]
    assert ts.endswith("Z"), f"api_request_timestamp must end with Z, got {ts!r}"
    assert len(ts.split(".")[-1]) == 4, (
        f"api_request_timestamp must carry exactly 3 fractional digits, got {ts!r}"
    )


def _instant(value: Any) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating any fractional-second rendering."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 instant, got {value!r}"
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str):
    """Assert two ISO-8601 UTC instants denote the same instant.

    PRD 2.5 pins every stored instant as "an ISO 8601 UTC instant" and fixes a
    three-fractional-digit rendering only for ``created_at`` and ``updated_at``
    (PRD 2.4), so the instant is the contract here and its rendering is not.
    """
    assert _instant(actual) == _instant(expected), f"expected instant {expected}, got {actual}"


def q3(value: Any) -> Optional[Decimal]:
    """Quantize to 3 decimals with round-half-up (PRD 2.6)."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def assert_rating_equals(actual: Any, expected: str):
    """Compare a 3-decimal dynamic rating against an exact decimal literal."""
    assert actual is not None, f"expected {expected}, got null"
    assert q3(actual) == Decimal(expected), f"expected {expected}, got {actual}"


def assert_standings_points(team: Dict[str, Any]):
    """standings_points == 3 * matches_won + lines_won (PRD 3.6)."""
    expected = MATCH_WIN_POINTS * team["matches_won"] + team["lines_won"]
    assert team["standings_points"] == expected, (
        f"standings_points {team['standings_points']} != "
        f"3*{team['matches_won']} + {team['lines_won']} = {expected}"
    )


def assert_league_ledger_invariants(
    home: Dict[str, Any], away: Dict[str, Any], decided_match_count: int
):
    """The four exact league-result-ledger equalities of PRD 2.11."""
    # A — every decided match contributes exactly one win and one loss
    assert home["matches_won"] + away["matches_won"] + home["matches_lost"] + away[
        "matches_lost"
    ] == 2 * decided_match_count, "ledger invariant A violated"
    # B — lines won across the league equal lines lost across the league
    assert home["lines_won"] + away["lines_won"] == home["lines_lost"] + away[
        "lines_lost"
    ], "ledger invariant B violated"
    # C — sets and games won equal sets and games lost
    assert home["sets_won"] + away["sets_won"] == home["sets_lost"] + away["sets_lost"], (
        "ledger invariant C violated for sets"
    )
    assert home["games_won"] + away["games_won"] == home["games_lost"] + away[
        "games_lost"
    ], "ledger invariant C violated for games"
    # D — standings points reconcile to 3 * decided matches + total lines won
    assert home["standings_points"] + away["standings_points"] == (
        MATCH_WIN_POINTS * decided_match_count + home["lines_won"] + away["lines_won"]
    ), "ledger invariant D violated"


def assert_strike_ledger(player: Dict[str, Any], active_strikes: Iterable[Dict[str, Any]]):
    """Player.strike_count == sum of the weights of its ACTIVE strikes (PRD 3.7)."""
    expected = sum(s["weight"] for s in active_strikes)
    assert player["strike_count"] == expected, (
        f"strike_count {player['strike_count']} != sum of ACTIVE weights {expected}"
    )


def assert_no_write(before: Dict[str, Any], after: Dict[str, Any], *fields: str):
    """Assert a rejected call left the row untouched, version included."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on a rejected call"
    )
    assert after["updated_at"] == before["updated_at"], (
        "updated_at moved on a rejected call"
    )
    for field in fields:
        assert after[field] == before[field], (
            f"{field} moved from {before[field]!r} to {after[field]!r} "
            "on a rejected call"
        )


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ordered_by_created_at(rows: List[Dict[str, Any]]):
    """Default listing order is ``created_at`` ascending (PRD 2.3)."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


def line_by_number(match_or_card: Dict[str, Any], key: str, line_number: int):
    for line in match_or_card[key]:
        if line["line_number"] == line_number:
            return line
    raise AssertionError(f"no entry with line_number {line_number} in {key}")


def standings_row_team_id(row: Dict[str, Any]) -> str:
    """Team identity of a standings row (PRD 3.6 does not fix the key name)."""
    for key in ("team_id", "id"):
        if row.get(key):
            return row[key]
    raise AssertionError(f"standings row identifies no team: {row}")


def standings_by_team(
    api, league_id: str, headers: Dict[str, str], basis: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """Standings rows of a league keyed by team id, on the requested basis."""
    params: Dict[str, Any] = {"limit": 100, "offset": 0}
    if basis is not None:
        params["basis"] = basis
    rows, _meta = validate_paginated(api.get_standings(league_id, headers, params))
    return {standings_row_team_id(row): row for row in rows}

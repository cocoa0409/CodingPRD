"""Shared helpers: common-fields, pagination, OCC, listing utilities."""
from __future__ import annotations

from flask import request

from db import new_id, now_iso, store
from errors import (
    ERR_INVALID_STATE,
    ERR_STALE_TRADE_VERSION,
    ERR_STALE_WAIVER_VERSION,
    APIError,
    err_invalid_request,
    err_not_found,
)


# ---------------- Common fields ----------------

def new_common_fields(seq: int) -> dict:
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": seq,
    }


def bump(row: dict, *, refresh_ts: bool = True) -> None:
    row["version"] = row.get("version", 1) + 1
    if refresh_ts:
        row["updated_at"] = now_iso()


# ---------------- OCC ----------------

def check_occ(row: dict, expected_field_name: str, body: dict, *,
              stale_error_id: str | None = None, stale_http: int = 412):
    """Optimistic-concurrency check.

    If `expected_field_name` is present in body, compare against
    `row['version']`. On mismatch:
      - If `stale_error_id` is given, raise that with given http status.
      - Otherwise raise ERR_INVALID_STATE (per PRD §2.5).
    If the field is absent, the PRD's wording says the field is "required";
    however the OCC spec also says "When the OCC field is provided, compare".
    To be safe, we treat absence as ERR_INVALID_REQUEST when the endpoint
    explicitly requires it (callers pass `required=True`).
    """
    if expected_field_name not in body or body[expected_field_name] is None:
        # PRD: endpoints with OCC declare expected_<entity>_version in input.
        raise err_invalid_request(f"{expected_field_name} is required.")
    expected = body[expected_field_name]
    if not isinstance(expected, int):
        raise err_invalid_request(f"{expected_field_name} must be an integer.")
    if expected != row.get("version"):
        if stale_error_id:
            raise APIError(stale_error_id, stale_http,
                           f"{expected_field_name} stale.")
        raise APIError(ERR_INVALID_STATE, 409,
                       f"{expected_field_name} mismatch.")


def check_trade_finalize_occ(trade: dict, body: dict):
    check_occ(trade, "expected_trade_version", body,
              stale_error_id=ERR_STALE_TRADE_VERSION, stale_http=412)


def check_waiver_cancel_occ(claim: dict, body: dict):
    check_occ(claim, "expected_waiverclaim_version", body,
              stale_error_id=ERR_STALE_WAIVER_VERSION, stale_http=412)


def check_league_occ(league: dict, body: dict):
    check_occ(league, "expected_league_version", body)


def check_team_occ(team: dict, body: dict):
    check_occ(team, "expected_team_version", body)


def check_player_occ(player: dict, body: dict):
    check_occ(player, "expected_player_version", body)


def check_matchup_occ(matchup: dict, body: dict):
    check_occ(matchup, "expected_playoffmatchup_version", body)


# ---------------- Pagination ----------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(s, name, *, minv=None, maxv=None):
    try:
        v = int(s)
    except (TypeError, ValueError):
        raise err_invalid_request(f"{name} must be an integer.")
    if minv is not None and v < minv:
        raise err_invalid_request(f"{name} below minimum.")
    if maxv is not None and v > maxv:
        raise err_invalid_request(f"{name} above maximum.")
    return v


def parse_pagination():
    args = request.args
    limit_str = args.get("limit")
    offset_str = args.get("offset")
    limit = DEFAULT_LIMIT if limit_str is None else _parse_int(
        limit_str, "limit", minv=MIN_LIMIT, maxv=MAX_LIMIT)
    offset = DEFAULT_OFFSET if offset_str is None else _parse_int(
        offset_str, "offset", minv=0)
    return limit, offset


def sort_by_created_at(items):
    """Sort by created_at ASC, ties by _seq (insertion order)."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


# ---------------- Existence fetch ----------------

def get_league(league_id):
    if not isinstance(league_id, str) or league_id not in store().leagues:
        raise err_not_found(f"League {league_id} not found.")
    return store().leagues[league_id]


def get_team(team_id):
    if not isinstance(team_id, str) or team_id not in store().teams:
        raise err_not_found(f"Team {team_id} not found.")
    return store().teams[team_id]


def get_player(player_id):
    if not isinstance(player_id, str) or player_id not in store().players:
        raise err_not_found(f"Player {player_id} not found.")
    return store().players[player_id]


def get_trade(trade_id):
    if not isinstance(trade_id, str) or trade_id not in store().trades:
        raise err_not_found(f"Trade {trade_id} not found.")
    return store().trades[trade_id]


def get_waiver_claim(claim_id):
    if not isinstance(claim_id, str) or claim_id not in store().waiver_claims:
        raise err_not_found(f"WaiverClaim {claim_id} not found.")
    return store().waiver_claims[claim_id]


def get_matchup(matchup_id):
    if not isinstance(matchup_id, str) or matchup_id not in store().matchups:
        raise err_not_found(f"Matchup {matchup_id} not found.")
    return store().matchups[matchup_id]


def get_draft_pick(pick_id):
    if not isinstance(pick_id, str) or pick_id not in store().draft_picks:
        raise err_not_found(f"DraftPick {pick_id} not found.")
    return store().draft_picks[pick_id]


def get_veto_vote(vote_id):
    if not isinstance(vote_id, str) or vote_id not in store().veto_votes:
        raise err_not_found(f"VetoVote {vote_id} not found.")
    return store().veto_votes[vote_id]


def get_roster_slot(slot_id):
    if not isinstance(slot_id, str) or slot_id not in store().roster_slots:
        raise err_not_found(f"RosterSlot {slot_id} not found.")
    return store().roster_slots[slot_id]


# ---------------- Serialization ----------------

def strip_private(row: dict) -> dict:
    """Remove private fields (those starting with `_`) before serialization."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize(row: dict | None) -> dict | None:
    if row is None:
        return None
    return strip_private(row)


def serialize_list(rows):
    return [serialize(r) for r in rows]

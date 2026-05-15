"""Match service — draft flow, result reporting, forfeit, referee assignment."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from ..auth import current_actor
from ..clock import CLOCK, format_iso, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, common_fields_append_only, get_store
from .referees import VALID_LEVELS, referee_by_user_id
from .serializers import serialize_match


TERMINAL_MATCH_STATES = {"COMPLETED", "FORFEITED", "DISQUALIFIED"}


def _require_match(mid: str) -> dict[str, Any]:
    m = get_store().matches.get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", f"Match {mid} not found.")
    return m


def get_match(mid: str) -> dict[str, Any]:
    return serialize_match(_require_match(mid))


def list_matches(tid: str, round_num: Optional[int], status: Optional[str]) -> list[dict[str, Any]]:
    store = get_store()
    if tid not in store.tournaments:
        raise ApiError("ERR_NOT_FOUND", f"Tournament {tid} not found.")
    rows = [m for m in store.matches.values() if m["tournament_id"] == tid]
    if round_num is not None:
        rows = [m for m in rows if int(m["round_number"]) == round_num]
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    rows.sort(key=lambda m: (m["created_at"], m["id"]))
    return [serialize_match(m) for m in rows]


def patch_match(mid: str, body: dict[str, Any]) -> dict[str, Any]:
    m = _require_match(mid)
    if m["status"] == "LIVE":
        raise ApiError("ERR_INVALID_STATE", "Cannot adjust schedule of a LIVE match.")
    if "version" in body:
        if int(body["version"]) != int(m["version"]):
            raise ApiError("ERR_VERSION_CONFLICT",
                           f"Version mismatch: provided {body['version']}, current {m['version']}.")
    new_start = body.get("scheduled_start", m["scheduled_start"])
    new_end = body.get("scheduled_end", m["scheduled_end"])
    parse_iso(new_start)
    parse_iso(new_end)
    # Overlap check
    _check_match_time_overlap(m, new_start, new_end)
    m["scheduled_start"] = new_start
    m["scheduled_end"] = new_end
    bump_version(m)
    return serialize_match(m)


def _check_match_time_overlap(m: dict[str, Any], start: str, end: str) -> None:
    s_dt = parse_iso(start)
    e_dt = parse_iso(end)
    team_a, team_b = m.get("team_a_id"), m.get("team_b_id")
    teams = set(filter(None, [team_a, team_b]))
    for other in get_store().matches.values():
        if other["id"] == m["id"]:
            continue
        if other["tournament_id"] != m["tournament_id"]:
            continue
        if other["status"] == "FORFEITED":
            continue
        other_teams = set(filter(None, [other.get("team_a_id"), other.get("team_b_id")]))
        if not (teams & other_teams):
            continue
        o_s = parse_iso(other["scheduled_start"])
        o_e = parse_iso(other["scheduled_end"])
        if s_dt < o_e and o_s < e_dt:
            raise ApiError("ERR_MATCH_TIME_CONFLICT",
                           f"Schedule overlaps match {other['id']}.")


def assign_referee(mid: str, body: dict[str, Any]) -> dict[str, Any]:
    m = _require_match(mid)
    if "referee_user_id" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing referee_user_id.")
    ref = referee_by_user_id(body["referee_user_id"])
    if ref is None:
        raise ApiError("ERR_NOT_FOUND", f"Referee with user_id {body['referee_user_id']} not found.")

    # Check certification level vs tournament requirement
    t = get_store().tournaments.get(m["tournament_id"])
    if t is not None:
        required_level = t.get("required_referee_level", "L1")
        if VALID_LEVELS.get(ref["certification_level"], 0) < VALID_LEVELS.get(required_level, 0):
            raise ApiError("ERR_FORBIDDEN",
                           f"Referee level {ref['certification_level']} < required {required_level}.")

    # Double-booking with 15-minute buffer
    s_dt = parse_iso(m["scheduled_start"])
    e_dt = parse_iso(m["scheduled_end"])
    buffer = timedelta(minutes=15)
    buf_start = s_dt - buffer
    buf_end = e_dt + buffer
    for other in get_store().matches.values():
        if other["id"] == m["id"]:
            continue
        if other.get("assigned_referee_id") != ref["id"]:
            continue
        if other["status"] == "FORFEITED":
            continue
        o_s = parse_iso(other["scheduled_start"]) - buffer
        o_e = parse_iso(other["scheduled_end"]) + buffer
        if buf_start < o_e and o_s < buf_end:
            raise ApiError("ERR_REFEREE_DOUBLE_BOOKED",
                           f"Referee {ref['id']} is double-booked.")
    m["assigned_referee_id"] = ref["id"]
    bump_version(m)
    return serialize_match(m)


def _ensure_active_certified_referee_caller(m: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    ref = referee_by_user_id(user_id)
    if ref is None:
        raise ApiError("ERR_FORBIDDEN", "Caller is not a registered Referee.")
    if ref["status"] != "ACTIVE":
        raise ApiError("ERR_REFEREE_CERT_EXPIRED", "Referee is SUSPENDED.")
    expiry = parse_iso(ref["certification_expiry"])
    if CLOCK.now >= expiry:
        raise ApiError("ERR_REFEREE_CERT_EXPIRED", "Referee certification expired.")
    if m.get("assigned_referee_id") and m["assigned_referee_id"] != ref["id"]:
        raise ApiError("ERR_FORBIDDEN", "Caller is not the assigned referee for this match.")
    return ref


def start_draft(mid: str) -> dict[str, Any]:
    m = _require_match(mid)
    if m["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", f"Match in {m['status']}, expected SCHEDULED.")
    _ensure_active_certified_referee_caller(m)
    # Match must be in [scheduled_start, scheduled_end)
    s = parse_iso(m["scheduled_start"])
    e = parse_iso(m["scheduled_end"])
    if not (s <= CLOCK.now < e):
        raise ApiError("ERR_MATCH_NOT_IN_WINDOW",
                       "Clock.now is not within [scheduled_start, scheduled_end).")
    if m.get("team_a_id") is None or m.get("team_b_id") is None:
        raise ApiError("ERR_INVALID_STATE", "Bye matches cannot start a draft.")
    m["status"] = "DRAFT_IN_PROGRESS"
    bump_version(m)
    return serialize_match(m)


def append_draft_event(mid: str, body: dict[str, Any]) -> dict[str, Any]:
    m = _require_match(mid)
    if m["status"] != "DRAFT_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", f"Match in {m['status']}, expected DRAFT_IN_PROGRESS.")
    ref = _ensure_active_certified_referee_caller(m)

    for k in ("step_index", "action", "side", "target_type", "target_name"):
        if k not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {k}")
    if body["action"] not in {"BAN", "PICK"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid action: {body['action']}")
    if body["side"] not in {"A", "B"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid side: {body['side']}")
    if body["target_type"] not in {"MAP", "CHARACTER"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid target_type: {body['target_type']}")

    store = get_store()
    anomaly = body.get("anomaly_type")
    if anomaly is not None and anomaly not in {"DISCONNECT", "MISCLICK"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid anomaly_type: {anomaly}")

    submitted_step = int(body["step_index"])
    events = [e for e in store.draft_events.values() if e["match_id"] == m["id"]]
    # Effective step = number of non-anomaly + non-voided events
    voided_ids = set()
    for e in events:
        for vid in e.get("_voids", []) or []:
            voided_ids.add(vid)
    effective_count = sum(
        1 for e in events
        if e["id"] not in voided_ids
        and e.get("anomaly_type") is None
    )
    next_expected = effective_count + 1

    if anomaly == "MISCLICK":
        # Must claim step_index = next_expected - 1; void the previous event at step_index-1 by same side
        if submitted_step != next_expected - 1:
            raise ApiError("ERR_DRAFT_STEP_OUT_OF_ORDER",
                           f"MISCLICK must use step_index = next_expected - 1 = {next_expected - 1}.")
        # Find previous event at step_index-1 same side
        candidate = None
        for e in sorted(events, key=lambda x: x["created_at"], reverse=True):
            if int(e.get("step_index", -1)) == submitted_step and e.get("side") == body["side"] \
                    and e["id"] not in voided_ids:
                candidate = e
                break
        if candidate is None:
            raise ApiError("ERR_DRAFT_STEP_OUT_OF_ORDER",
                           "No prior DraftEvent at that step by the same side to void.")
    elif anomaly == "DISCONNECT":
        # Step still counts (acts like a normal step); grace 60s applied to scheduled_end
        if submitted_step != next_expected:
            raise ApiError("ERR_DRAFT_STEP_OUT_OF_ORDER",
                           f"step_index {submitted_step} != next_expected {next_expected}.")
    else:
        if submitted_step != next_expected:
            raise ApiError("ERR_DRAFT_STEP_OUT_OF_ORDER",
                           f"step_index {submitted_step} != next_expected {next_expected}.")

    # Uniqueness check on (match_id, step_index) for non-anomaly events at the same index
    uniq_key = (m["id"], submitted_step)
    existing = store.draft_step_uniq.get(uniq_key)
    if anomaly is None and existing:
        raise ApiError("ERR_DRAFT_STEP_TAKEN",
                       f"Step {submitted_step} is already claimed.")

    row = common_fields_append_only()
    row.update({
        "match_id": m["id"],
        "step_index": submitted_step,
        "action": body["action"],
        "side": body["side"],
        "target_type": body["target_type"],
        "target_name": body["target_name"],
        "anomaly_type": anomaly,
        "recorded_by_user_id": ref["user_id"],
        "_voids": [],
    })
    if anomaly == "MISCLICK" and candidate is not None:
        # Void the previous event
        row["_voids"] = [candidate["id"]]
        # Mark candidate as voided to make accounting consistent
        candidate.setdefault("_voided", True)
    if anomaly is None:
        store.draft_step_uniq[uniq_key] = row["id"]

    store.draft_events[row["id"]] = row

    if anomaly == "DISCONNECT":
        # Extend scheduled_end by 60 seconds
        end_dt = parse_iso(m["scheduled_end"])
        m["scheduled_end"] = format_iso(end_dt + timedelta(seconds=60))
        bump_version(m)

    return dict(row)


def list_draft_events(mid: str) -> list[dict[str, Any]]:
    m = _require_match(mid)
    rows = [e for e in get_store().draft_events.values() if e["match_id"] == m["id"]]
    rows.sort(key=lambda e: (e["created_at"], e["id"]))
    return [dict(e) for e in rows]


def complete_draft(mid: str) -> dict[str, Any]:
    m = _require_match(mid)
    if m["status"] != "DRAFT_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", f"Match in {m['status']}, expected DRAFT_IN_PROGRESS.")
    _ensure_active_certified_referee_caller(m)
    t = get_store().tournaments.get(m["tournament_id"])
    if t is None:
        raise ApiError("ERR_NOT_FOUND", "Parent tournament missing.")
    events = [e for e in get_store().draft_events.values() if e["match_id"] == m["id"]
              and e.get("anomaly_type") is None and not e.get("_voided")]
    required_count = len(t.get("ban_pick_sequence", []))
    if len(events) != required_count:
        raise ApiError("ERR_INVALID_STATE",
                       f"Draft event count {len(events)} != required {required_count}.")
    m["status"] = "LIVE"
    bump_version(m)
    return serialize_match(m)


def report_result(mid: str, body: dict[str, Any]) -> dict[str, Any]:
    m = _require_match(mid)
    if m["status"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE", f"Match in {m['status']}, expected LIVE.")
    _ensure_active_certified_referee_caller(m)
    if "winner_team_id" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing winner_team_id.")
    winner = body["winner_team_id"]
    if winner not in (m.get("team_a_id"), m.get("team_b_id")):
        raise ApiError("ERR_BAD_REQUEST", "winner_team_id must equal team_a_id or team_b_id.")
    m["winner_team_id"] = winner
    m["status"] = "COMPLETED"
    bump_version(m)
    return serialize_match(m)


def forfeit_match(mid: str, body: dict[str, Any]) -> dict[str, Any]:
    m = _require_match(mid)
    _, role = current_actor()
    if role == "Referee":
        _ensure_active_certified_referee_caller(m)
    if m["status"] in {"COMPLETED", "FORFEITED", "DISQUALIFIED"}:
        raise ApiError("ERR_INVALID_STATE", f"Match already terminal: {m['status']}.")
    if "forfeit_reason" not in body or "winner_team_id" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing forfeit_reason or winner_team_id.")
    winner = body["winner_team_id"]
    if winner not in (m.get("team_a_id"), m.get("team_b_id")):
        raise ApiError("ERR_BAD_REQUEST", "winner_team_id must equal team_a_id or team_b_id.")
    m["forfeit_reason"] = body["forfeit_reason"]
    m["winner_team_id"] = winner
    m["status"] = "FORFEITED"
    bump_version(m)
    return serialize_match(m)

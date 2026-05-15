"""MatchIncident service: filing, assignment, ruling, appeals, cascade reversal."""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any, Optional

from ..audit import log_event
from ..auth import current_actor
from ..calculations import (
    apply_contagion_decay,
    compute_contagion_delta,
    half_up_int,
)
from ..clock import CLOCK, parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso
from .referees import referee_by_user_id


VALID_SUBJECT_TYPES = {"PLAYER", "TEAM", "MATCH"}
VALID_CLASSIFICATION = {"LATENCY", "CHEATING_SUSPICION", "UNSPORTSMANLIKE_CONDUCT", "RULE_VIOLATION"}
VALID_PENALTY = {"NONE", "WARNING", "FORFEIT", "DISQUALIFICATION", "FINE"}
APPEAL_WINDOW_HOURS = 72
MAX_APPEALS = 1


def _require_incident(iid: str) -> dict[str, Any]:
    i = get_store().match_incidents.get(iid)
    if i is None:
        raise ApiError("ERR_NOT_FOUND", f"MatchIncident {iid} not found.")
    return i


def file_incident(body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    for k in ("match_id", "subject_type", "subject_id", "classification", "evidence", "referee_id"):
        if k not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {k}")
    if body["subject_type"] not in VALID_SUBJECT_TYPES:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid subject_type: {body['subject_type']}")
    if body["classification"] not in VALID_CLASSIFICATION:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid classification: {body['classification']}")
    if body["referee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN", "referee_id must equal X-User-ID.")
    ref = referee_by_user_id(user_id)
    if ref is None:
        raise ApiError("ERR_FORBIDDEN", "Caller is not a registered Referee.")
    if ref["status"] != "ACTIVE":
        raise ApiError("ERR_REFEREE_CERT_EXPIRED", "Referee is SUSPENDED.")
    expiry = parse_iso(ref["certification_expiry"])
    if CLOCK.now >= expiry:
        raise ApiError("ERR_REFEREE_CERT_EXPIRED", "Referee certification expired.")

    store = get_store()
    if body["match_id"] not in store.matches:
        raise ApiError("ERR_NOT_FOUND", f"Match {body['match_id']} not found.")
    # Validate subject_id exists
    st = body["subject_type"]
    sid = body["subject_id"]
    if st == "PLAYER" and sid not in {c["player_id"] for c in store.player_contracts.values()}:
        raise ApiError("ERR_NOT_FOUND", f"Player {sid} not found.")
    if st == "TEAM" and sid not in store.team_registrations:
        raise ApiError("ERR_NOT_FOUND", f"Team {sid} not found.")
    if st == "MATCH" and sid not in store.matches:
        raise ApiError("ERR_NOT_FOUND", f"Match {sid} not found.")

    # Uniqueness
    uniq_key = (body["match_id"], sid, body["classification"])
    if uniq_key in store.incident_uniq:
        raise ApiError("ERR_DUPLICATE_INCIDENT",
                       "An incident already exists for this (match, subject, classification).")

    incident = common_fields_create()
    incident.update({
        "match_id": body["match_id"],
        "subject_type": st,
        "subject_id": sid,
        "classification": body["classification"],
        "evidence": list(body["evidence"]),
        "referee_id": user_id,
        "ruling": "PENDING",
        "penalty_type": "NONE",
        "fine_amount_cents": None,
        "appeal_count": 0,
        "status": "FILED",
    })
    store.match_incidents[incident["id"]] = incident
    store.incident_uniq[uniq_key] = incident["id"]

    log_event("MATCH_INCIDENT", incident["id"], user_id, "Referee", "FILE",
              {"before": None, "after": copy.deepcopy(incident)})
    return dict(incident)


def get_incident(iid: str) -> dict[str, Any]:
    return dict(_require_incident(iid))


def assign_incident(iid: str) -> dict[str, Any]:
    user_id, _ = current_actor()
    i = _require_incident(iid)
    if i["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", f"Incident in {i['status']}, expected FILED.")
    # Re-validate filing referee certification at this moment (per scaffold).
    ref = referee_by_user_id(i["referee_id"])
    if ref is None or ref["status"] != "ACTIVE":
        raise ApiError("ERR_REFEREE_CERT_EXPIRED", "Filing referee not active.")
    expiry = parse_iso(ref["certification_expiry"])
    if CLOCK.now >= expiry:
        raise ApiError("ERR_REFEREE_CERT_EXPIRED", "Filing referee certification expired.")
    before = copy.deepcopy(i)
    i["status"] = "UNDER_REVIEW"
    bump_version(i)
    log_event("MATCH_INCIDENT", i["id"], user_id, "LeagueAdmin", "ASSIGN_REVIEW",
              {"before": before, "after": copy.deepcopy(i)})
    return dict(i)


def rule_incident(iid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    i = _require_incident(iid)
    if i["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", f"Incident in {i['status']}, expected UNDER_REVIEW.")
    if "ruling" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing ruling.")
    ruling = body["ruling"]
    if ruling not in {"UPHELD", "DISMISSED"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid ruling: {ruling}")
    penalty = body.get("penalty_type", "NONE")
    if ruling == "UPHELD":
        if penalty == "NONE":
            raise ApiError("ERR_BAD_REQUEST", "penalty_type required when ruling=UPHELD.")
        if penalty not in VALID_PENALTY:
            raise ApiError("ERR_BAD_REQUEST", f"Invalid penalty_type: {penalty}")
        if penalty == "FINE":
            fine_amt = body.get("fine_amount_cents", 0)
            if fine_amt is None or int(fine_amt) <= 0:
                raise ApiError("ERR_FINE_AMOUNT_REQUIRED",
                               "fine_amount_cents must be > 0 when penalty_type=FINE.")
            i["fine_amount_cents"] = int(fine_amt)
    else:
        penalty = "NONE"

    before = copy.deepcopy(i)
    i["ruling"] = ruling
    i["penalty_type"] = penalty
    i["status"] = "RULED"
    bump_version(i)
    get_store().ruled_at[i["id"]] = CLOCK.now

    log_event("MATCH_INCIDENT", i["id"], user_id, "LeagueAdmin", f"RULE_{ruling}",
              {"before": before, "after": copy.deepcopy(i)})

    if ruling == "UPHELD":
        # Apply contagion risk update if subject_type=TEAM
        if i["subject_type"] == "TEAM":
            _apply_contagion_risk(i, sign=+1)
        # Disqualification cascade
        if penalty == "DISQUALIFICATION" and i["subject_type"] == "TEAM":
            _apply_disqualification_cascade(i)
    return dict(i)


def _apply_contagion_risk(incident: dict[str, Any], sign: int) -> None:
    """Apply +1 or -1 sign delta to team's accumulated risk."""
    store = get_store()
    team_id = incident["subject_id"]
    entry = store.team_risk.setdefault(team_id, {"risk": 0, "last_decay_at": CLOCK.now})

    if sign > 0:
        decayed = apply_contagion_decay(int(entry["risk"]), entry["last_decay_at"], CLOCK.now)
        delta = compute_contagion_delta(incident["penalty_type"], incident["classification"])
        new_risk = half_up_int(decayed + delta)
        entry["risk"] = new_risk
        entry["last_decay_at"] = CLOCK.now
        # Record delta for reversal
        store.cascade_history.setdefault(incident["id"], {})["risk_delta"] = float(delta)
    else:
        # Reversal: subtract exact delta (no re-decay)
        cascade = store.cascade_history.get(incident["id"], {})
        delta = cascade.get("risk_delta", 0.0)
        new_risk = max(0, int(entry["risk"]) - int(delta))
        entry["risk"] = new_risk


def _apply_disqualification_cascade(incident: dict[str, Any]) -> None:
    """Hop 1: TeamRegistration → DISQUALIFIED.
       Hop 2: every non-terminal Match → FORFEITED with winner = other side.
       Hop 3: any PROVISIONAL PrizePayout for this team → CLAWED_BACK, gross=0.
    Snapshots are stored for compensating reversal."""
    store = get_store()
    team_id = incident["subject_id"]
    team = store.team_registrations.get(team_id)
    if team is None:
        return
    snapshot: dict[str, Any] = {
        "registration_prev_status": team["status"],
        "matches": [],
        "payouts": [],
    }

    # Hop 1
    if team["status"] == "REGISTERED":
        team["status"] = "DISQUALIFIED"
        bump_version(team)

    # Hop 2
    for m in store.matches.values():
        if m["tournament_id"] != team["tournament_id"]:
            continue
        if m["status"] in {"COMPLETED", "FORFEITED", "DISQUALIFIED"}:
            continue
        if m.get("team_a_id") != team_id and m.get("team_b_id") != team_id:
            continue
        snapshot["matches"].append({
            "match_id": m["id"],
            "prev_status": m["status"],
            "prev_winner": m.get("winner_team_id"),
            "prev_reason": m.get("forfeit_reason"),
        })
        other = m["team_b_id"] if m.get("team_a_id") == team_id else m.get("team_a_id")
        m["winner_team_id"] = other
        m["forfeit_reason"] = f"Team disqualified by incident {incident['id']}"
        m["status"] = "FORFEITED"
        bump_version(m)

    # Hop 3
    for p in store.prize_payouts.values():
        if p["tournament_id"] != team["tournament_id"]:
            continue
        if p["status"] != "PROVISIONAL":
            continue
        if p.get("team_id") != team_id:
            continue
        snapshot["payouts"].append({
            "payout_id": p["id"],
            "prev_status": p["status"],
            "prev_gross": p["gross_amount_cents"],
        })
        p["gross_amount_cents"] = 0
        p["status"] = "CLAWED_BACK"
        bump_version(p)

    store.cascade_history.setdefault(incident["id"], {}).update(snapshot)


def _reverse_disqualification_cascade(incident: dict[str, Any]) -> None:
    store = get_store()
    snapshot = store.cascade_history.get(incident["id"], {})
    # Reverse Hop 1
    team = store.team_registrations.get(incident["subject_id"])
    if team is not None and "registration_prev_status" in snapshot:
        team["status"] = snapshot["registration_prev_status"]
        bump_version(team)
    # Reverse Hop 2
    for entry in snapshot.get("matches", []):
        m = store.matches.get(entry["match_id"])
        if m is None:
            continue
        m["status"] = entry["prev_status"]
        m["winner_team_id"] = entry["prev_winner"]
        m["forfeit_reason"] = entry["prev_reason"]
        bump_version(m)
    # Reverse Hop 3
    for entry in snapshot.get("payouts", []):
        p = store.prize_payouts.get(entry["payout_id"])
        if p is None:
            continue
        p["status"] = entry["prev_status"]
        p["gross_amount_cents"] = entry["prev_gross"]
        bump_version(p)


def appeal_incident(iid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    i = _require_incident(iid)
    if i["status"] != "RULED":
        raise ApiError("ERR_INVALID_STATE", f"Incident in {i['status']}, expected RULED.")
    if int(i.get("appeal_count", 0)) >= MAX_APPEALS:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED",
                       f"appeal_count {i['appeal_count']} >= MAX_APPEALS {MAX_APPEALS}.")
    ruled_at = get_store().ruled_at.get(i["id"])
    if ruled_at is not None:
        deadline = ruled_at + timedelta(hours=APPEAL_WINDOW_HOURS)
        if CLOCK.now >= deadline:
            raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "Appeal window has closed (72h).")
    if "grounds" not in body:
        raise ApiError("ERR_BAD_REQUEST", "Missing grounds.")
    # Ownership: TeamManager must own the team that's the subject (when subject_type=TEAM)
    if i["subject_type"] == "TEAM":
        team = get_store().team_registrations.get(i["subject_id"])
        if team is None or team["manager_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "Caller does not own the subject team.")

    before = copy.deepcopy(i)
    i["status"] = "APPEALED"
    i["appeal_count"] = int(i["appeal_count"]) + 1
    i["appeal_grounds"] = body["grounds"]
    bump_version(i)
    log_event("MATCH_INCIDENT", i["id"], user_id, "TeamManager", "APPEAL",
              {"before": before, "after": copy.deepcopy(i)})
    return dict(i)


def decide_appeal(iid: str, body: dict[str, Any]) -> dict[str, Any]:
    user_id, _ = current_actor()
    i = _require_incident(iid)
    if i["status"] != "APPEALED":
        raise ApiError("ERR_INVALID_STATE", f"Incident in {i['status']}, expected APPEALED.")
    if "decision" not in body:
        raise ApiError("ERR_APPEAL_DECISION_REQUIRED", "Missing decision.")
    decision = body["decision"]
    # PRD §3.5 names "overturn" as the reversal branch. The non-overturn
    # branch is unnamed in PRD; accept both AFFIRM and UPHOLD as synonyms.
    if decision not in {"UPHOLD", "AFFIRM", "OVERTURN"}:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid decision: {decision}")
    before = copy.deepcopy(i)
    if decision == "OVERTURN":
        new_ruling = body.get("new_ruling", "OVERTURNED")
        new_penalty = body.get("new_penalty_type", "NONE")
        # Reverse cascade if there was a UPHELD-DISQUALIFICATION on a TEAM
        if i["ruling"] == "UPHELD" and i.get("penalty_type") == "DISQUALIFICATION" \
                and i["subject_type"] == "TEAM":
            _reverse_disqualification_cascade(i)
        # Reverse contagion risk
        if i["ruling"] == "UPHELD" and i["subject_type"] == "TEAM":
            _apply_contagion_risk(i, sign=-1)
        i["ruling"] = "OVERTURNED"
        i["penalty_type"] = "NONE"
        i["fine_amount_cents"] = None
        log_label = "APPEAL_OVERTURNED"
    else:
        # Uphold the prior ruling
        log_label = "APPEAL_UPHELD"
    i["status"] = "RULED"
    bump_version(i)
    get_store().ruled_at[i["id"]] = CLOCK.now
    log_event("MATCH_INCIDENT", i["id"], user_id, "LeagueAdmin", log_label,
              {"before": before, "after": copy.deepcopy(i)})
    return dict(i)


def close_incident(iid: str) -> dict[str, Any]:
    user_id, _ = current_actor()
    i = _require_incident(iid)
    if i["status"] != "RULED":
        raise ApiError("ERR_INVALID_STATE", f"Incident in {i['status']}, expected RULED.")
    ruled_at = get_store().ruled_at.get(i["id"])
    appeal_count = int(i.get("appeal_count", 0))
    ok = appeal_count >= 1
    if not ok and ruled_at is not None:
        if CLOCK.now >= ruled_at + timedelta(hours=APPEAL_WINDOW_HOURS):
            ok = True
    if not ok:
        raise ApiError("ERR_INVALID_STATE",
                       "Cannot close: appeal_count < 1 and window still open.")
    before = copy.deepcopy(i)
    i["status"] = "CLOSED"
    bump_version(i)
    log_event("MATCH_INCIDENT", i["id"], user_id, "LeagueAdmin", "CLOSE",
              {"before": before, "after": copy.deepcopy(i)})
    return dict(i)

"""Match list, results, disputes endpoints."""
from flask import Blueprint, request, g

import db
from clock import now, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import match_results
from services.audit import write_audit
from services.ranking import recompute_rankings
from services.validation import (
    get_body, require_field, require_str, require_int, require_bool, check_version,
)


bp = Blueprint("matches", __name__)


@bp.route("/events/<event_id>/matches", methods=["GET"])
@require_auth(roles={"Organizer", "Referee", "Participant", "DisciplinaryOfficer"})
def list_matches(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")
    limit, offset = get_pagination()
    status = request.args.get("status")
    round_index = request.args.get("round_index")
    rows = [m for m in db.matches.values() if m["event_id"] == event_id]
    if status:
        rows = [m for m in rows if m["status"] == status]
    if round_index:
        try:
            ri = int(round_index)
        except ValueError:
            raise err("ERR_VALIDATION", "round_index must be integer")
        rows = [m for m in rows if m["round_index"] == ri]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total, 200)


@bp.route("/matches/<match_id>/results", methods=["POST"])
@require_auth(roles={"Referee"})
def post_result(match_id):
    body = get_body()
    re_row = match_results.submit_result(match_id, body, g.user_id, g.user_role)
    return success(db.public(re_row), 201)


@bp.route("/matches/<match_id>/disputes", methods=["POST"])
@require_auth(roles={"Participant"})
def post_dispute(match_id):
    m = db.matches.get(match_id)
    if not m:
        raise err("ERR_NOT_FOUND", "match not found")
    body = get_body()
    require_field(body, "filed_by_participant_id")
    pid = body["filed_by_participant_id"]
    if not isinstance(pid, str):
        raise err("ERR_VALIDATION", "filed_by_participant_id must be a string")
    reason_text = require_str(body, "reason_text", min_len=1, max_len=1000)

    p = db.participants.get(pid)
    if not p:
        raise err("ERR_REFERENCE_NOT_FOUND", "participant not found")

    if m["status"] not in ("RESULT_PENDING", "LOCKED"):
        raise err("ERR_INVALID_STATE", "match not in RESULT_PENDING or LOCKED")

    # Ownership: filed_by_participant_id must equal X-User-ID
    if pid != g.user_id:
        raise err("ERR_FORBIDDEN", "filed_by_participant_id != X-User-ID")

    d = {
        "match_id": match_id,
        "filed_by_participant_id": pid,
        "reason_text": reason_text,
        "status": "OPEN",
        "corrected_result_entry_id": None,
        # snapshot for restore on reject
        "_snapshot": {
            "match_was_locked": m["status"] == "LOCKED",
            "locked_home_score": m.get("locked_home_score"),
            "locked_away_score": m.get("locked_away_score"),
            "locked_home_sets_won": m.get("locked_home_sets_won"),
            "locked_away_sets_won": m.get("locked_away_sets_won"),
            "winner_participant_id": m.get("winner_participant_id"),
            "match_status": m["status"],
        },
    }
    db.stamp_create(d, common_fields=True)
    db.disputes[d["id"]] = d

    if m["status"] == "LOCKED":
        m["status"] = "DISPUTED"
        db.stamp_update(m)
    return success(db.public(d), 201)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
@require_auth(roles={"DisciplinaryOfficer"})
def resolve_dispute(dispute_id):
    d = db.disputes.get(dispute_id)
    if not d:
        raise err("ERR_NOT_FOUND", "dispute not found")
    body = get_body()
    if d["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "dispute not OPEN")
    uphold = require_bool(body, "uphold")
    check_version(d, body)
    m = db.matches.get(d["match_id"])
    if not m:
        raise err("ERR_NOT_FOUND", "match not found")
    ev = db.events.get(m["event_id"])

    if not uphold:
        d["status"] = "REJECTED"
        db.stamp_update(d)
        # Restore match
        snap = d.get("_snapshot", {})
        if snap.get("match_was_locked"):
            m["status"] = "LOCKED"
            m["locked_home_score"] = snap["locked_home_score"]
            m["locked_away_score"] = snap["locked_away_score"]
            m["locked_home_sets_won"] = snap["locked_home_sets_won"]
            m["locked_away_sets_won"] = snap["locked_away_sets_won"]
            m["winner_participant_id"] = snap["winner_participant_id"]
            db.stamp_update(m)
        else:
            # Match was RESULT_PENDING -> stays RESULT_PENDING (per state machine,
            # PRD says match transition DISPUTED -> LOCKED only when there had been a LOCK).
            # If we never moved to DISPUTED, no restore needed.
            pass
        return success(db.public(d), 200)

    # Uphold path — corrected scores required
    chs = body.get("corrected_home_score")
    cas = body.get("corrected_away_score")
    chsw = body.get("corrected_home_sets_won")
    casw = body.get("corrected_away_sets_won")
    if chs is None or cas is None:
        raise err("ERR_VALIDATION", "corrected_home_score and corrected_away_score required")
    if isinstance(chs, bool) or not isinstance(chs, int) or chs < 0:
        raise err("ERR_VALIDATION", "corrected_home_score must be non-negative integer")
    if isinstance(cas, bool) or not isinstance(cas, int) or cas < 0:
        raise err("ERR_VALIDATION", "corrected_away_score must be non-negative integer")
    if chsw is not None and (isinstance(chsw, bool) or not isinstance(chsw, int)):
        raise err("ERR_VALIDATION", "corrected_home_sets_won must be int or null")
    if casw is not None and (isinstance(casw, bool) or not isinstance(casw, int)):
        raise err("ERR_VALIDATION", "corrected_away_sets_won must be int or null")
    # Score validity
    match_results._check_score_validity(ev["event_type"], chs, cas, chsw, casw)

    # Snapshot before
    before = {
        "locked_home_score": m.get("locked_home_score"),
        "locked_away_score": m.get("locked_away_score"),
        "locked_home_sets_won": m.get("locked_home_sets_won"),
        "locked_away_sets_won": m.get("locked_away_sets_won"),
        "winner_participant_id": m.get("winner_participant_id"),
    }

    # Pick the assignment id from any existing REFEREE_SUBMISSION row to attach to CORRECTION
    sba_id = None
    older = [e for e in db.result_entries.values()
             if e["match_id"] == m["id"] and e["kind"] == "REFEREE_SUBMISSION"
             and not e.get("superseded_by_id")]
    if older:
        sba_id = older[0]["submitted_by_assignment_id"]

    new_entry = match_results._persist_entry(m["id"], sba_id, chs, cas, chsw, casw, "CORRECTION")
    for old in older:
        old["superseded_by_id"] = new_entry["id"]

    # Update match
    m["locked_home_score"] = chs
    m["locked_away_score"] = cas
    if ev["event_type"] == "SETS_MATCH":
        m["locked_home_sets_won"] = chsw
        m["locked_away_sets_won"] = casw
    m["winner_participant_id"] = match_results._winner_pid(m, ev["event_type"], chs, cas, chsw, casw)
    m["status"] = "LOCKED"
    db.stamp_update(m)

    after = {
        "locked_home_score": m.get("locked_home_score"),
        "locked_away_score": m.get("locked_away_score"),
        "locked_home_sets_won": m.get("locked_home_sets_won"),
        "locked_away_sets_won": m.get("locked_away_sets_won"),
        "winner_participant_id": m.get("winner_participant_id"),
    }
    write_audit(kind="RESULT_CHANGE", subject_kind="MATCH", subject_id=m["id"],
                actor_user_id=g.user_id, actor_role=g.user_role,
                from_value=before, to_value=after)

    # Toggle states if winner flipped
    if before["winner_participant_id"] != after["winner_participant_id"]:
        # Previous winner becomes ELIMINATED (if was ACTIVE), previous loser ACTIVE (if was ELIMINATED)
        prev_winner = db.participants.get(before["winner_participant_id"]) if before["winner_participant_id"] else None
        new_winner = db.participants.get(after["winner_participant_id"]) if after["winner_participant_id"] else None
        if prev_winner and prev_winner["status"] == "ACTIVE":
            prev_winner["status"] = "ELIMINATED"
            db.stamp_update(prev_winner)
        if new_winner and new_winner["status"] == "ELIMINATED":
            new_winner["status"] = "ACTIVE"
            db.stamp_update(new_winner)
        recompute_rankings(m["event_id"], finalize=False)
    else:
        recompute_rankings(m["event_id"], finalize=False)

    d["status"] = "UPHELD"
    d["corrected_result_entry_id"] = new_entry["id"]
    db.stamp_update(d)
    return success(db.public(d), 200)

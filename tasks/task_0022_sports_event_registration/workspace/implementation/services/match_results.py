"""Match result submission and locking."""
import db
from clock import now, parse_iso
from errors import err
from services import ranking
from services.audit import write_audit


def _entries_for_match(match_id):
    return [e for e in db.result_entries.values()
            if e["match_id"] == match_id and e.get("kind") == "REFEREE_SUBMISSION"
            and not e.get("superseded_by_id")]


def submit_result(match_id: str, body: dict, actor_id: str, actor_role: str):
    m = db.matches.get(match_id)
    if not m:
        raise err("ERR_NOT_FOUND", "match not found")
    ev = db.events.get(m["event_id"])
    if not ev:
        raise err("ERR_NOT_FOUND", "event not found")

    # Body fields
    if "submitted_by_assignment_id" not in body:
        raise err("ERR_VALIDATION", "submitted_by_assignment_id required")
    sba_id = body["submitted_by_assignment_id"]
    if not isinstance(sba_id, str):
        raise err("ERR_VALIDATION", "submitted_by_assignment_id must be a string")
    if "home_score" not in body or "away_score" not in body:
        raise err("ERR_VALIDATION", "home_score and away_score required")
    hs = body["home_score"]
    as_ = body["away_score"]
    if isinstance(hs, bool) or not isinstance(hs, int) or hs < 0:
        raise err("ERR_VALIDATION", "home_score must be a non-negative integer")
    if isinstance(as_, bool) or not isinstance(as_, int) or as_ < 0:
        raise err("ERR_VALIDATION", "away_score must be a non-negative integer")
    home_sets_won = body.get("home_sets_won")
    away_sets_won = body.get("away_sets_won")
    if home_sets_won is not None and (isinstance(home_sets_won, bool) or not isinstance(home_sets_won, int)):
        raise err("ERR_VALIDATION", "home_sets_won must be int or null")
    if away_sets_won is not None and (isinstance(away_sets_won, bool) or not isinstance(away_sets_won, int)):
        raise err("ERR_VALIDATION", "away_sets_won must be int or null")

    # FK existence (assignment)
    assn = db.referee_assignments.get(sba_id)
    if not assn:
        raise err("ERR_REFERENCE_NOT_FOUND", "submitted_by_assignment_id not found")

    # State validity: match must be in SCHEDULED or RESULT_PENDING
    if m["status"] not in ("SCHEDULED", "RESULT_PENDING"):
        raise err("ERR_INVALID_STATE", "match not in SCHEDULED/RESULT_PENDING")

    # Posture gate
    if ev.get("posture") == "FROZEN":
        raise err("ERR_EVENT_FROZEN", "event posture is FROZEN")

    # Assignment must be on this match, role HEAD/ASSISTANT.
    # PRD §3.3 + §3.4: the assignment is auto-activated upon the first result
    # entry (when the match transitions to RESULT_PENDING). So at submission
    # time the assignment may be either ASSIGNED (will be auto-activated as a
    # side-effect of the first valid submission) or ACTIVATED (already activated
    # for the second cross-verifying submission).
    if assn["match_id"] != match_id:
        raise err("ERR_INVALID_STATE", "assignment not on this match")
    if assn["status"] not in ("ASSIGNED", "ACTIVATED"):
        raise err("ERR_INVALID_STATE", "assignment not ASSIGNED or ACTIVATED")
    if assn["role"] not in ("HEAD", "ASSISTANT"):
        raise err("ERR_INVALID_STATE", "assignment role not HEAD or ASSISTANT")

    # Match.scheduled_end_at <= now()
    if now() < parse_iso(m["scheduled_end_at"]):
        raise err("ERR_INVALID_STATE", "now() < scheduled_end_at")

    # Referee identity must match X-User-ID
    if assn["referee_id"] != actor_id:
        raise err("ERR_FORBIDDEN", "referee identity mismatch with X-User-ID")

    existing = _entries_for_match(match_id)

    # If this is a second submission:
    # Per PRD §2.12 + scaffold priority: score validity (18) -> duplicate-referee (19) -> disagreement (20).
    if existing:
        # Score validity first (priority 18)
        _check_score_validity(ev["event_type"], hs, as_, home_sets_won, away_sets_won)
        first = existing[0]
        first_assn = db.referee_assignments.get(first["submitted_by_assignment_id"])
        # Cross-verifier identity check (priority 19) — explicitly before disagreement
        if first_assn and first_assn["referee_id"] == assn["referee_id"]:
            raise err("ERR_DUPLICATE_REFEREE_ENTRY", "same referee submitting twice")
        # Disagreement check (priority 20)
        if (first["home_score"] != hs or first["away_score"] != as_):
            raise err("ERR_RESULT_DISAGREEMENT", "scores disagree with first submission")
        if ev["event_type"] == "SETS_MATCH":
            if first.get("home_sets_won") != home_sets_won or first.get("away_sets_won") != away_sets_won:
                raise err("ERR_RESULT_DISAGREEMENT", "sets_won disagree with first submission")
        # Persist second entry
        re_row = _persist_entry(match_id, sba_id, hs, as_, home_sets_won, away_sets_won, "REFEREE_SUBMISSION")
        # Lock the match
        m["locked_home_score"] = hs
        m["locked_away_score"] = as_
        if ev["event_type"] == "SETS_MATCH":
            m["locked_home_sets_won"] = home_sets_won
            m["locked_away_sets_won"] = away_sets_won
        m["winner_participant_id"] = _winner_pid(m, ev["event_type"], hs, as_, home_sets_won, away_sets_won)
        m["status"] = "LOCKED"
        db.stamp_update(m)
        # Cascades
        _cascade_on_lock(m, ev)
        return re_row

    # First submission path
    _check_score_validity(ev["event_type"], hs, as_, home_sets_won, away_sets_won)
    re_row = _persist_entry(match_id, sba_id, hs, as_, home_sets_won, away_sets_won, "REFEREE_SUBMISSION")
    m["status"] = "RESULT_PENDING"
    db.stamp_update(m)
    # Auto-activate ASSIGNED HEAD/ASSISTANT assignments on this match
    for a in db.referee_assignments.values():
        if a["match_id"] == match_id and a["status"] == "ASSIGNED" \
                and a["role"] in ("HEAD", "ASSISTANT"):
            a["status"] = "ACTIVATED"
            db.stamp_update(a)
    return re_row


def _check_score_validity(event_type, hs, as_, hsw, asw):
    if event_type == "SINGLE_ELIM":
        if hs == as_:
            raise err("ERR_INVALID_SCORE", "SINGLE_ELIM: scores must differ")
    elif event_type == "ROUND_ROBIN":
        # draws allowed
        pass
    elif event_type == "SETS_MATCH":
        if hsw is None or asw is None:
            raise err("ERR_INVALID_SCORE", "SETS_MATCH: sets_won fields required")
        if hsw == asw:
            raise err("ERR_INVALID_SCORE", "SETS_MATCH: sets_won must differ")


def _winner_pid(m, event_type, hs, as_, hsw, asw):
    if event_type == "SETS_MATCH":
        if hsw > asw:
            return m["home_participant_id"]
        if asw > hsw:
            return m["away_participant_id"]
        return None
    if hs > as_:
        return m["home_participant_id"]
    if as_ > hs:
        return m["away_participant_id"]
    return None  # draw in ROUND_ROBIN


def _persist_entry(match_id, sba_id, hs, as_, hsw, asw, kind):
    re_row = {
        "match_id": match_id,
        "submitted_by_assignment_id": sba_id,
        "home_score": hs,
        "away_score": as_,
        "home_sets_won": hsw,
        "away_sets_won": asw,
        "kind": kind,
        "superseded_by_id": None,
    }
    db.stamp_create(re_row, common_fields=False)
    db.result_entries[re_row["id"]] = re_row
    return re_row


def _cascade_on_lock(m: dict, ev: dict):
    # Loser participant ACTIVE -> ELIMINATED
    if m.get("winner_participant_id"):
        loser_id = m["away_participant_id"] if m["winner_participant_id"] == m["home_participant_id"] else m["home_participant_id"]
        loser = db.participants.get(loser_id) if loser_id else None
        if loser and loser["status"] == "ACTIVE":
            loser["status"] = "ELIMINATED"
            db.stamp_update(loser)
    # Recompute rankings (provisional)
    ranking.recompute_rankings(m["event_id"], finalize=False)
    # Set next-round seat
    next_round = m["round_index"] + 1
    next_pos = (m["bracket_position"] + 1) // 2
    next_match = next((nm for nm in db.matches.values()
                       if nm["event_id"] == m["event_id"]
                       and nm["round_index"] == next_round
                       and nm["bracket_position"] == next_pos), None)
    if next_match and m.get("winner_participant_id"):
        if m["bracket_position"] % 2 == 1:
            if next_match.get("home_participant_id") is None:
                next_match["home_participant_id"] = m["winner_participant_id"]
                db.stamp_update(next_match)
        else:
            if next_match.get("away_participant_id") is None:
                next_match["away_participant_id"] = m["winner_participant_id"]
                db.stamp_update(next_match)
        # Winner SEEDED/ACTIVE for next round
        winner = db.participants.get(m["winner_participant_id"])
        if winner and winner["status"] in ("SEEDED", "ACTIVE"):
            if winner["status"] == "SEEDED":
                winner["status"] = "ACTIVE"
                db.stamp_update(winner)

"""Photo-to-student match scorer (SCAFFOLD §1.3 match_confidence_score, PRD §3.3).

Candidate set: students with status == ENROLLED in the photo's session.
score(s) = round_half_up(100 * (W_NAME*name + W_GRADE*grade + W_HOMEROOM*homeroom))
where each *_match is 1 when the normalized field equals the photo's slate field.
Ranking: score DESC, tie-break created_at ASC (never id). Threshold inclusive 80.
"""
import db
from common import (
    MATCH_AUTO_THRESHOLD,
    W_GRADE,
    W_HOMEROOM,
    W_NAME,
    round_half_up,
)
from errors import err


def _normalize(s):
    if s is None:
        return ""
    return str(s).strip().lower()


def _score(student, photo):
    name_match = 1 if _normalize(student["full_name"]) == _normalize(photo["candidate_name"]) else 0
    grade_match = 1 if _normalize(student["grade"]) == _normalize(photo["candidate_grade"]) else 0
    homeroom_match = 1 if _normalize(student["homeroom"]) == _normalize(photo["candidate_homeroom"]) else 0
    weighted = W_NAME * name_match + W_GRADE * grade_match + W_HOMEROOM * homeroom_match
    return round_half_up(100 * weighted)


def best_match(photo):
    """Return (winning_student, score) or raise ERR_NO_MATCH_CANDIDATE.

    Candidates are ranked by score DESC then created_at (creation order) ASC.
    The winner must score >= MATCH_AUTO_THRESHOLD (inclusive)."""
    session_id = photo["picture_day_session_id"]
    candidates = [
        s for s in db.students.values()
        if s["picture_day_session_id"] == session_id and s["status"] == "ENROLLED"
    ]
    if not candidates:
        raise err("ERR_NO_MATCH_CANDIDATE", "No ENROLLED candidate student to match")

    # Sort: highest score first; on ties, earliest-created (smaller _seq) first.
    ranked = sorted(
        candidates,
        key=lambda s: (-_score(s, photo), s["_seq"]),
    )
    winner = ranked[0]
    winner_score = _score(winner, photo)
    if winner_score < MATCH_AUTO_THRESHOLD:
        raise err("ERR_NO_MATCH_CANDIDATE", "Best candidate score below match threshold")
    return winner, winner_score

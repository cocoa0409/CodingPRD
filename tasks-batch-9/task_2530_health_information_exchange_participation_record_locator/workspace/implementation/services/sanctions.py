"""Break-glass sanction accounting (PRD 3.8)."""
from db import clock, commit, db, parse_iso, plus_days, plus_minutes, snapshot
from services import cascades, repo

POINTS_BY_CATEGORY = {
    "LIFE_THREATENING": 6,
    "UNCONSCIOUS_PATIENT": 4,
    "DISASTER": 3,
}
SENSITIVE_DISCLOSURE_SURCHARGE = 2
SANCTION_DECAY_DAYS = 180
SANCTION_SUSPENSION_THRESHOLD = 12
BREAK_GLASS_SESSION_MINUTES = 240
BREAK_GLASS_COOLDOWN_MINUTES = 60
BREAK_GLASS_JUSTIFICATION_MIN_CHARS = 40


def award_for(session):
    points = POINTS_BY_CATEGORY[session["emergency_category"]]
    if int(session["disclosed_sensitive_count"] or 0) > 0:
        points += SENSITIVE_DISCLOSURE_SURCHARGE
    return points


def active_points(participant_id):
    """Sum of unjustified awards decided inside the one hundred eighty day window."""
    horizon = plus_days(clock(), -SANCTION_DECAY_DAYS)
    total = 0
    for session in db.break_glass.values():
        if session["invoking_participant_id"] != participant_id:
            continue
        if session["review_status"] != "UNJUSTIFIED":
            continue
        decided = parse_iso(session["decided_at"]) if session["decided_at"] else None
        if decided is None or decided <= horizon:
            continue
        total += int(session["sanction_points_awarded"] or 0)
    return total


def recompute(participant):
    participant["sanction_points_active"] = active_points(participant["id"])
    return participant["sanction_points_active"]


def refresh_and_maybe_suspend(participant):
    """Recompute the sum and fire the automatic suspension cascade when due."""
    before = snapshot(participant)
    recompute(participant)
    if (
        participant["sanction_points_active"] >= SANCTION_SUSPENSION_THRESHOLD
        and participant["onboarding_status"] == "CERTIFIED"
    ):
        cascades.suspend_participant(
            participant, cascades.AUTOMATIC_SANCTION_THRESHOLD
        )
    commit(participant, before)


def expire_if_due(session):
    """Lazy expiry: an OPEN session whose expires_at is strictly earlier than the
    logical clock reads EXPIRED on the next read or write touching the row."""
    if session["session_status"] != "OPEN":
        return session
    expires = parse_iso(session["expires_at"])
    if expires is not None and expires < clock():
        before = snapshot(session)
        session["session_status"] = "EXPIRED"
        commit(session, before)
    return session


def cooldown_blocked(cluster_id, clinician_user_id):
    """Each prior session occupies the closed interval [opened_at, expires_at+60m]."""
    moment = clock()
    for session in db.break_glass.values():
        if session["cluster_id"] != cluster_id:
            continue
        if session["invoking_clinician_user_id"] != clinician_user_id:
            continue
        opened = parse_iso(session["opened_at"])
        expires = parse_iso(session["expires_at"])
        if opened is None or expires is None:
            continue
        upper = plus_minutes(expires, BREAK_GLASS_COOLDOWN_MINUTES)
        if opened <= moment <= upper:
            return True
    return False


def recompute_session_disclosures(session):
    disclosed = 0
    sensitive = 0
    for query in repo.queries_citing(session["id"]):
        disclosed += int(query["disclosed_record_count"] or 0)
        for entry in repo.audit_for_query(query["id"]):
            if entry["action"] != "BREAK_GLASS_DISCLOSED":
                continue
            if entry["sensitive_category_hit"]:
                sensitive += 1
    session["disclosed_record_count"] = disclosed
    session["disclosed_sensitive_count"] = sensitive
    return disclosed, sensitive


def mark_audit_reviewed(session):
    for query in repo.queries_citing(session["id"]):
        for entry in repo.audit_for_query(query["id"]):
            entry["reviewed"] = True

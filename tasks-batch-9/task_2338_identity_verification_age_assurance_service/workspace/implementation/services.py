"""Domain services: scoring, state transitions, cascades and the operations sweep."""
import calc
import clock
import db
import derived
from errors import fail

# --- audit trail ------------------------------------------------------------

SYSTEM_ACTOR_ROLE = "system"


def append_event(session, event_type, caller, payload_summary):
    """Append one immutable audit event to a session's trail (PRD 2.10)."""
    record = {
        "session_id": session["id"],
        "event_type": event_type,
        "actor_role": caller.role if caller is not None else SYSTEM_ACTOR_ROLE,
        "actor_user_id": caller.user_id if caller is not None else None,
        "payload_summary": payload_summary,
        "occurred_at": clock.now(),
    }
    return db.insert(db.AUDIT_EVENTS, record, versioned=False)


# --- scoring ----------------------------------------------------------------

def recompute_provisional(session):
    """PROVISIONAL variant: sum SCORED and ACCEPTED contributions, capped at 100."""
    total = 0
    for attempt in derived.attempts_of_session(session["id"]):
        if attempt["state"] in ("SCORED", "ACCEPTED") and attempt["contribution_points"] is not None:
            total += attempt["contribution_points"]
    session["assurance_score_provisional"] = min(calc.SCORE_CAP, total)
    db.touch(session)
    return session["assurance_score_provisional"]


def write_final_score(session):
    """FINAL variant: ACCEPTED attempts only, bias haircut, then both caps."""
    total = 0
    for attempt in derived.attempts_of_session(session["id"]):
        if attempt["state"] != "ACCEPTED" or attempt["contribution_points"] is None:
            continue
        points = attempt["contribution_points"]
        profile = db.get(db.METHOD_PROFILES, attempt["method_profile_id"])
        if profile is not None and profile["bias_state"] == "RESTRICTED":
            points = calc.floor_div(points * calc.RESTRICTED_MULTIPLIER_BPS, 10000)
        total += points
    session["assurance_score_final"] = min(session["assurance_ceiling"], min(calc.SCORE_CAP, total))
    db.touch(session)
    return session["assurance_score_final"]


# --- manual review cases ----------------------------------------------------

def create_review_case(session, trigger_reason):
    record = {
        "session_id": session["id"],
        "trigger_reason": trigger_reason,
        "state": "QUEUED",
        "assigned_by_user_id": None,
        "assigned_reviewer_user_id": None,
        "decision": None,
        "decided_by_user_id": None,
        "decided_at": None,
    }
    db.insert(db.REVIEW_CASES, record)
    record["sla_due_at"] = clock.plus_hours(record["created_at"], calc.REVIEW_SLA_HOURS)
    return record


# --- biometric retention ----------------------------------------------------

def apply_retention(session, caller):
    """Resolve custody of every STORED template of a terminal session (PRD 3.10).

    Returns the number of templates deleted immediately.
    """
    client = db.get(db.CLIENTS, session["client_id"])
    deleted = 0
    for template in derived.templates_of_session(session["id"]):
        if template["state"] != "STORED":
            continue
        reason = None
        if session["resolved_age_band"] in calc.MINOR_BANDS:
            reason = "MINOR_PROTECTION"
        elif client is not None and client["biometric_retention_mode"] == "DELETE_ON_COMPLETE":
            reason = "POLICY_IMMEDIATE"
        elif (client is not None
              and client["biometric_retention_mode"] == "RETAIN_WITH_CONSENT"
              and not session["biometric_consent"]):
            reason = "CONSENT_ABSENT"
        if reason is not None:
            template["state"] = "DELETED"
            template["deleted_at"] = clock.now()
            template["deletion_reason"] = reason
            db.touch(template)
            append_event(session, "TEMPLATE_DELETED", caller,
                         "state, deleted_at, deletion_reason")
            deleted += 1
        else:
            template["state"] = "PURGE_SCHEDULED"
            template["retention_expires_at"] = clock.plus_days(
                session["completed_at"], calc.RETENTION_DAYS)
            db.touch(template)
    return deleted


# --- policy pinning and quota ----------------------------------------------

def pin_policy(client_id):
    """Highest policy_version among PUBLISHED policies, created_at ascending on ties."""
    candidates = [p for p in db.POLICIES.values()
                  if p["client_id"] == client_id and p["state"] == "PUBLISHED"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (-p["policy_version"], p["created_at"], p["_seq"]))
    return candidates[0]


def rolling_window_usage(client_id):
    """Sessions created inside the 24h window ending now, inclusive at both ends."""
    now = clock.now()
    window_start = clock.plus_hours(now, -calc.QUOTA_WINDOW_HOURS)
    return sum(1 for s in db.SESSIONS.values()
               if s["client_id"] == client_id
               and window_start <= s["created_at"] <= now)


def prior_rejected_count(client_id, external_subject_ref):
    return sum(1 for s in db.SESSIONS.values()
               if s["client_id"] == client_id
               and s["external_subject_ref"] == external_subject_ref
               and s["identity_state"] == "REJECTED")


# --- method selection -------------------------------------------------------

def select_ladder_profile(session, policy):
    """LADDER variant of the candidate selector."""
    admitted = set(policy["allowed_method_codes"])
    accepted_codes = {a["method_code"] for a in derived.attempts_of_session(session["id"])
                      if a["state"] == "ACCEPTED"}
    candidates = []
    for profile in db.METHOD_PROFILES.values():
        if profile["method_code"] not in admitted:
            continue
        if profile["bias_state"] == "RESTRICTED":
            continue
        if session["risk_level"] == "HIGH" and not profile["strong_evidence"]:
            continue
        if profile["method_code"] in accepted_codes:
            continue
        candidates.append(profile)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (-p["assurance_weight"], p["cost_cents"],
                                   p["created_at"], p["_seq"]))
    return candidates[0]


def select_pathway_profile():
    """PATHWAY_GRANT variant: cheapest unrestricted VOUCHING_ATTESTATION profile."""
    candidates = [p for p in db.METHOD_PROFILES.values()
                  if p["method_code"] == "VOUCHING_ATTESTATION"
                  and p["bias_state"] != "RESTRICTED"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["cost_cents"], p["created_at"], p["_seq"]))
    return candidates[0]


# --- attempt construction ---------------------------------------------------

def create_attempt(session, profile, selection_mode):
    same_code = sum(1 for a in derived.attempts_of_session(session["id"])
                    if a["method_code"] == profile["method_code"])
    record = {
        "session_id": session["id"],
        "method_profile_id": profile["id"],
        "method_code": profile["method_code"],
        "selection_mode": selection_mode,
        "retry_index": same_code,
        "state": "AWAITING_EVIDENCE",
        "evidence_quality_bps": None,
        "match_score_bps": None,
        "contribution_points": None,
        "tamper_flag": False,
        "rejection_reason": None,
        "finalized_at": None,
        "_has_evidence": False,
    }
    return db.insert(db.ATTEMPTS, record)


def score_attempt(attempt, profile, evidence_quality_bps):
    attempt["evidence_quality_bps"] = evidence_quality_bps
    attempt["contribution_points"] = calc.contribution_points(
        profile["assurance_weight"], evidence_quality_bps)
    attempt["state"] = "SCORED"
    attempt["_has_evidence"] = True
    db.touch(attempt)


# --- terminal session transitions ------------------------------------------

def terminate_session(session, caller, identity_state, disposition_reason,
                      manual_override=False, write_final=True, event_type="SESSION_TERMINAL",
                      payload_summary=None):
    session["identity_state"] = identity_state
    session["disposition_reason"] = disposition_reason
    session["completed_at"] = clock.now()
    if manual_override:
        session["manual_override_flag"] = True
    db.touch(session)
    if write_final:
        write_final_score(session)
    deleted = apply_retention(session, caller)
    append_event(session, event_type, caller,
                 payload_summary or "identity_state, disposition_reason, completed_at, assurance_score_final")
    return deleted


# --- bias restriction cascade ----------------------------------------------

def apply_restriction_cascade(profile, caller):
    """Restrict a profile and cascade transitively (PRD 3.9)."""
    profile["bias_state"] = "RESTRICTED"
    profile["restricted_at"] = clock.now()
    db.touch(profile)

    affected_sessions = []
    for attempt in db.all_of(db.ATTEMPTS):
        if attempt["method_profile_id"] != profile["id"]:
            continue
        if attempt["state"] not in ("AWAITING_EVIDENCE", "SCORED", "REQUIRES_RESCORE"):
            continue
        attempt["state"] = "REQUIRES_RESCORE"
        attempt["contribution_points"] = None
        db.touch(attempt)
        session = db.get(db.SESSIONS, attempt["session_id"])
        if session is not None and session not in affected_sessions:
            affected_sessions.append(session)

    for session in affected_sessions:
        if session["identity_state"] == "IN_PROGRESS":
            session["identity_state"] = "AWAITING_EVIDENCE"
            db.touch(session)
        recompute_provisional(session)
        # degraded_flag is derived from the live profile postures on every read
        # (PRD 3.1), so the cascade needs no explicit policy write.
        append_event(session, "METHOD_RESTRICTION_APPLIED", caller,
                     "identity_state, assurance_score_provisional")


def apply_remediation_cascade(profile, caller):
    """Lift the restriction and close out rescore-blocked attempts (PRD 3.9)."""
    profile["bias_state"] = "MONITORED"
    profile["restricted_at"] = None
    db.touch(profile)

    touched_sessions = []
    for attempt in db.all_of(db.ATTEMPTS):
        if attempt["method_profile_id"] != profile["id"]:
            continue
        if attempt["state"] != "REQUIRES_RESCORE":
            continue
        attempt["state"] = "REJECTED"
        attempt["rejection_reason"] = "METHOD_RESTRICTED"
        attempt["contribution_points"] = 0
        attempt["finalized_at"] = clock.now()
        db.touch(attempt)
        session = db.get(db.SESSIONS, attempt["session_id"])
        if session is not None and session not in touched_sessions:
            touched_sessions.append(session)
    for session in touched_sessions:
        recompute_provisional(session)


# --- operations sweep -------------------------------------------------------

def run_sweep(caller):
    now = clock.now()
    expired_session_count = 0
    withdrawn_case_count = 0
    deleted_template_count = 0

    # 1. lapse overdue sessions
    for session in db.all_of(db.SESSIONS):
        if session["identity_state"] not in ("IN_PROGRESS", "AWAITING_EVIDENCE"):
            continue
        if not now > session["expires_at"]:
            continue
        for attempt in derived.attempts_of_session(session["id"]):
            if attempt["state"] in ("AWAITING_EVIDENCE", "SCORED", "REQUIRES_RESCORE"):
                attempt["state"] = "EXPIRED"
                attempt["rejection_reason"] = "EXPIRED_WINDOW"
                attempt["finalized_at"] = now
                db.touch(attempt)
        for pathway in derived.pathways_of_session(session["id"]):
            if pathway["state"] in ("VOUCH_PENDING", "ATTESTATION_PENDING"):
                pathway["state"] = "WITHDRAWN"
                pathway["decided_at"] = now
                db.touch(pathway)
        session["identity_state"] = "EXPIRED"
        session["disposition_reason"] = "EXPIRED_TTL"
        session["completed_at"] = now
        db.touch(session)
        deleted_template_count += apply_retention(session, caller)
        append_event(session, "SESSION_TERMINAL", caller,
                     "identity_state, disposition_reason, completed_at")
        expired_session_count += 1

    # 2. withdraw review cases past their service level
    for case in db.all_of(db.REVIEW_CASES):
        if case["state"] not in ("QUEUED", "ASSIGNED"):
            continue
        if not now >= case["sla_due_at"]:
            continue
        case["state"] = "WITHDRAWN"
        case["decided_at"] = now
        db.touch(case)
        withdrawn_case_count += 1
        session = db.get(db.SESSIONS, case["session_id"])
        if session is None or session["identity_state"] != "MANUAL_REVIEW":
            continue
        session["identity_state"] = "REJECTED"
        session["disposition_reason"] = "REVIEW_LAPSED"
        session["completed_at"] = now
        db.touch(session)
        write_final_score(session)
        deleted_template_count += apply_retention(session, caller)
        append_event(session, "SESSION_TERMINAL", caller,
                     "identity_state, disposition_reason, completed_at, assurance_score_final")

    # 3. purge deferred templates
    for template in db.all_of(db.BIOMETRIC_TEMPLATES):
        if template["state"] != "PURGE_SCHEDULED":
            continue
        if template["retention_expires_at"] is None or not now >= template["retention_expires_at"]:
            continue
        template["state"] = "DELETED"
        template["deleted_at"] = now
        template["deletion_reason"] = "RETENTION_EXPIRED"
        db.touch(template)
        deleted_template_count += 1
        session = db.get(db.SESSIONS, template["session_id"])
        if session is not None:
            append_event(session, "TEMPLATE_DELETED", caller,
                         "state, deleted_at, deletion_reason")

    return {
        "expired_session_count": expired_session_count,
        "withdrawn_case_count": withdrawn_case_count,
        "deleted_template_count": deleted_template_count,
        "swept_at": clock.to_iso(now),
    }


# --- shared guards ----------------------------------------------------------

def session_or_404(session_id):
    session = db.get(db.SESSIONS, session_id)
    if session is None:
        fail("ERR_SESSION_NOT_FOUND")
    return session


def attempt_or_404(attempt_id):
    attempt = db.get(db.ATTEMPTS, attempt_id)
    if attempt is None:
        fail("ERR_ATTEMPT_NOT_FOUND")
    return attempt


def client_of_session(session):
    return db.get(db.CLIENTS, session["client_id"])


def policy_of_session(session):
    return db.get(db.POLICIES, session["policy_id"])


def require_not_lapsed(session):
    if clock.now() > session["expires_at"]:
        fail("ERR_SESSION_EXPIRED")

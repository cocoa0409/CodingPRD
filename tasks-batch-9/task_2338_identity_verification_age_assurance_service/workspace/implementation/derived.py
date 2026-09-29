"""Server-derived counters and flags (PRD 2.8, 3.1).

These are never accepted as input and are always recomputed from the live store, which
is what makes the invariants of PRD 2.8 hold by construction.
"""
import db


def sessions_of_client(client_id):
    return [s for s in db.SESSIONS.values() if s["client_id"] == client_id]


def review_cases_of_client(client_id):
    out = []
    for case in db.REVIEW_CASES.values():
        session = db.SESSIONS.get(case["session_id"])
        if session is not None and session["client_id"] == client_id:
            out.append(case)
    return out


def templates_of_client(client_id):
    out = []
    for template in db.BIOMETRIC_TEMPLATES.values():
        session = db.SESSIONS.get(template["session_id"])
        if session is not None and session["client_id"] == client_id:
            out.append(template)
    return out


def reserved_review_credits(client):
    return sum(1 for c in review_cases_of_client(client["id"]) if c["state"] == "ASSIGNED")


def available_review_credits(client):
    return client["granted_review_credits"] - reserved_review_credits(client)


def stored_template_count(client):
    return sum(1 for t in templates_of_client(client["id"]) if t["state"] == "STORED")


def pending_stepup_count(client):
    return sum(1 for s in sessions_of_client(client["id"]) if s["identity_state"] == "AWAITING_EVIDENCE")


def consumed_review_count(client):
    return sum(1 for c in review_cases_of_client(client["id"]) if c["state"] == "DECIDED")


def attempts_of_session(session_id):
    return db.ordered([a for a in db.ATTEMPTS.values() if a["session_id"] == session_id])


def fraud_signal_count(session):
    return sum(1 for a in attempts_of_session(session["id"]) if a.get("tamper_flag"))


def pathways_of_session(session_id):
    return db.ordered([p for p in db.PATHWAYS.values() if p["session_id"] == session_id])


def templates_of_session(session_id):
    return db.ordered([t for t in db.BIOMETRIC_TEMPLATES.values() if t["session_id"] == session_id])


def age_results_of_session(session_id):
    return db.ordered([r for r in db.AGE_RESULTS.values() if r["session_id"] == session_id])


def review_cases_of_session(session_id):
    return db.ordered([c for c in db.REVIEW_CASES.values() if c["session_id"] == session_id])


def audit_events_of_session(session_id):
    events = [e for e in db.AUDIT_EVENTS.values() if e["session_id"] == session_id]
    return sorted(events, key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))


def cohort_metrics_of_audit(audit_id):
    return db.ordered([c for c in db.COHORT_METRICS.values() if c["bias_audit_id"] == audit_id])


def bias_audits_of_profile(profile_id):
    return db.ordered([a for a in db.BIAS_AUDITS.values() if a["method_profile_id"] == profile_id])


def captures_of_attempt(attempt_id):
    return db.ordered([c for c in db.DOCUMENT_CAPTURES.values() if c["attempt_id"] == attempt_id])


def liveness_checks_of_attempt(attempt_id):
    return db.ordered([c for c in db.LIVENESS_CHECKS.values() if c["attempt_id"] == attempt_id])


def policy_degraded_flag(policy):
    """True when at least one profile whose method_code the policy admits is RESTRICTED."""
    admitted = set(policy["allowed_method_codes"])
    for profile in db.METHOD_PROFILES.values():
        if profile["method_code"] in admitted and profile["bias_state"] == "RESTRICTED":
            return True
    return False

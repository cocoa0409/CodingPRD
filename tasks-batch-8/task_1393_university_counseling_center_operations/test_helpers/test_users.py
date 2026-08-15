"""Pre-built role headers for every role in the PRD (PRD section 2.1).

Identity models:
- Student, Counselor, TriageScreener, ClinicalDirector are entity-backed:
  X-User-ID must equal the id of the acting Student/Counselor record whenever
  the call is ownership-gated. Use the make_*_headers builders with the real
  entity id for those calls.
- FrontDesk, ReferralCoordinator, Registrar are opaque: X-User-ID is never
  compared to any entity id, so the shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "front_desk_headers": build_user_headers("front-desk-1", "FrontDesk"),
    "referral_coordinator_headers": build_user_headers(
        "referral-coordinator-1", "ReferralCoordinator"),
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    # Entity-backed roles — shared constants are a fallback for calls that
    # are not ownership-gated (e.g. bootstrap creation of the first
    # counselor, clock advances, policy lifecycle).
    "clinical_director_headers": build_user_headers(
        "director-bootstrap-1", "ClinicalDirector"),
    "counselor_headers": build_user_headers("counselor-unbound-1", "Counselor"),
    "triage_screener_headers": build_user_headers(
        "screener-unbound-1", "TriageScreener"),
    "student_headers": build_user_headers("student-unbound-1", "Student"),
}


def make_student_headers(user_id: str) -> dict:
    """Student is entity_backed: pass the real Student.id for ownership-gated
    calls (dropping one's own group enrollment)."""
    return build_user_headers(user_id, "Student")


def make_counselor_headers(user_id: str) -> dict:
    """Counselor is entity_backed: pass the real Counselor.id whenever the
    call is ownership-gated (complete/mark-no-show/close/reopen/room/etc)."""
    return build_user_headers(user_id, "Counselor")


def make_triage_screener_headers(user_id: str) -> dict:
    """TriageScreener is entity_backed: pass the acting Counselor.id."""
    return build_user_headers(user_id, "TriageScreener")


def make_clinical_director_headers(user_id: str) -> dict:
    """ClinicalDirector is entity_backed (the director's own Counselor id);
    the director bypasses ownership gates."""
    return build_user_headers(user_id, "ClinicalDirector")


def make_front_desk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_referral_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReferralCoordinator")


def make_registrar_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Registrar")

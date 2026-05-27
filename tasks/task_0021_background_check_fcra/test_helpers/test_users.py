"""Pre-built role headers for every role declared in PRD §2.1.

PRD §2.1 declares the Applicant role as `entity_backed:Applicant` — its
X-User-ID equals the acting Applicant.id and ownership checks compare that
value back to Application.applicant_id (and the applicant chain).
The four other roles (PlatformAdmin, Recruiter, ComplianceOfficer,
VerificationProvider) are opaque operator ids not tied to any entity.

Shared TEST_USERS constants are safe for tests whose success does NOT depend
on the caller owning the subject resource. For ownership-gated calls as
Applicant, use the per-instance builder make_applicant_headers(applicant_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# ─── Shared constants ──────────────────────────────────────────────────

TEST_USERS = {
    # Opaque-id roles — shared constants are canonical.
    "platform_admin_headers": build_user_headers("pa-001", "PlatformAdmin"),
    "recruiter_headers": build_user_headers("rec-001", "Recruiter"),
    "recruiter_b_headers": build_user_headers("rec-002", "Recruiter"),
    "compliance_officer_headers": build_user_headers("co-001", "ComplianceOfficer"),
    "compliance_officer_b_headers": build_user_headers("co-002", "ComplianceOfficer"),
    "verification_provider_headers": build_user_headers("vp-001", "VerificationProvider"),
    # entity_backed:Applicant — fallback only for tests that do NOT exercise
    # ownership (e.g. RBAC denials where the call is rejected regardless of id).
    "applicant_headers": build_user_headers("applicant-fallback", "Applicant"),
}


# ─── Per-instance builders for entity_backed roles ─────────────────────

def make_applicant_headers(applicant_id: str) -> dict:
    """For Applicant (entity_backed:Applicant per PRD §2.1).

    Pass the actual Applicant.id as X-User-ID whenever the call is
    ownership-gated (anything that touches Application / Consent / Order /
    Verification / AdverseAction owned by this applicant).
    """
    return build_user_headers(applicant_id, "Applicant")


def make_recruiter_headers(recruiter_id: str) -> dict:
    """Opaque Recruiter id (PRD §2.1: Recruiter is opaque, not entity-backed).
    Used to thread a specific recruiter X-User-ID through fixtures so that
    segregation-of-duties tests can compare actor identities."""
    return build_user_headers(recruiter_id, "Recruiter")


def make_compliance_officer_headers(officer_id: str) -> dict:
    """Opaque ComplianceOfficer id (PRD §2.1). Used to thread a specific
    officer X-User-ID through fixtures so that segregation-of-duties tests
    can compare actor identities."""
    return build_user_headers(officer_id, "ComplianceOfficer")

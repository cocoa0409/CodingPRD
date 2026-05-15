"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

ENTITY-BACKED role — X-User-ID is the id of a persisted entity:
  - Applicant: "X-User-ID is the id of the acting Applicant entity;
    ownership checks on any resource that references an Applicant
    ... compare the resource's foreign-key chain to X-User-ID."
  Every Applicant-role call that exercises ownership (submit, withdraw,
  enroll, attach essay, request recommendation, accept aid, etc.) MUST
  mint headers via make_applicant_headers(applicant_id) using the real
  Applicant.id. The shared APPLICANT_FALLBACK_ID constant is ONLY safe
  for tests that do not exercise ownership (header-missing, role-mismatch,
  not-found paths, or calls where the role is non-permitted for the
  endpoint).

OPAQUE roles — X-User-ID is an operator identifier not tied to any
persisted entity. Shared constants are canonical for these:
  - PlatformAdmin
  - AdmissionsOfficer
  - FinancialAidOfficer
  - Recommender (PRD §2.1: "X-User-ID is an opaque operator identifier
    not tied to any persisted entity ... A recommender may read or act
    on a RecommendationRequest only when the value of X-User-ID matches
    the recommender_email recorded on the request" — i.e. the opaque
    identifier the recommender uses MUST equal the email the applicant
    invited; for ownership-gated Recommender calls use
    make_recommender_headers(recommender_email).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "platform-admin-001"
PLATFORM_ADMIN_ID_ALT = "platform-admin-002"

ADMISSIONS_OFFICER_ID = "admissions-officer-001"
ADMISSIONS_OFFICER_ID_ALT = "admissions-officer-002"

FINANCIAL_AID_OFFICER_ID = "financial-aid-officer-001"
FINANCIAL_AID_OFFICER_ID_ALT = "financial-aid-officer-002"

# Recommender fallback ids — usable only for tests that do NOT exercise
# the recommender_email-matching ownership check. Ownership-gated
# Recommender calls MUST use make_recommender_headers(email).
RECOMMENDER_FALLBACK_ID = "recommender-fallback@example.com"


# ---------------------------------------------------------------------------
# Entity-backed-role fallback id — DO NOT USE for ownership-gated
# Applicant calls. Use make_applicant_headers(applicant_id) with the
# real Applicant.id instead.
# ---------------------------------------------------------------------------
APPLICANT_FALLBACK_ID = "applicant-fallback-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants canonical (PRD §2.1).
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    "admissions_officer_headers": build_user_headers(
        ADMISSIONS_OFFICER_ID, "AdmissionsOfficer",
    ),
    "admissions_officer_headers_alt": build_user_headers(
        ADMISSIONS_OFFICER_ID_ALT, "AdmissionsOfficer",
    ),
    "financial_aid_officer_headers": build_user_headers(
        FINANCIAL_AID_OFFICER_ID, "FinancialAidOfficer",
    ),
    "financial_aid_officer_headers_alt": build_user_headers(
        FINANCIAL_AID_OFFICER_ID_ALT, "FinancialAidOfficer",
    ),
    "recommender_headers_fallback": build_user_headers(
        RECOMMENDER_FALLBACK_ID, "Recommender",
    ),

    # Entity-backed fallback — ONLY for non-ownership-gated tests.
    "applicant_headers_fallback": build_user_headers(
        APPLICANT_FALLBACK_ID, "Applicant",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# Applicant (entity_backed): mandatory for every ownership-gated call.
# Recommender (opaque but identity-matched-by-email): mandatory for every
#   ownership-gated Recommender call.
# Other opaque roles: convenience builders for tests that need a second
#   distinct id of the same role.
# ---------------------------------------------------------------------------
def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """Mint Applicant headers bound to a real Applicant.id.

    PRD §2.1: "When X-User-Role is Applicant, X-User-ID is the id of
    the acting Applicant entity; ownership checks ... compare the
    resource's foreign-key chain to X-User-ID." Every applicant-side
    mutation (submit, withdraw, enroll, attach essay, request
    recommendation, accept/decline aid, accept waitlist offer) MUST
    use this builder with the actual Applicant.id.
    """
    return build_user_headers(applicant_id, "Applicant")


def make_recommender_headers(recommender_email: str) -> Dict[str, str]:
    """Mint Recommender headers bound to the email the applicant invited.

    PRD §2.1: "A recommender may read or act on a RecommendationRequest
    only when the value of X-User-ID matches the recommender_email
    recorded on the request." Every recommender-side action (accept,
    decline, submit-letter) MUST use this builder with the same email
    that was supplied on POST /applications/{id}/recommendations.
    """
    return build_user_headers(recommender_email, "Recommender")


def make_admissions_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, "AdmissionsOfficer")


def make_financial_aid_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, "FinancialAidOfficer")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "ADMISSIONS_OFFICER_ID",
    "ADMISSIONS_OFFICER_ID_ALT",
    "FINANCIAL_AID_OFFICER_ID",
    "FINANCIAL_AID_OFFICER_ID_ALT",
    "RECOMMENDER_FALLBACK_ID",
    "APPLICANT_FALLBACK_ID",
    "TEST_USERS",
    "make_applicant_headers",
    "make_recommender_headers",
    "make_admissions_officer_headers",
    "make_financial_aid_officer_headers",
    "make_platform_admin_headers",
]

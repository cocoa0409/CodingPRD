"""Pre-built role headers for every role the PRD declares.

Every request carries ``X-User-ID`` and ``X-User-Role``. For the eight opaque
operator roles the shared constants below are the canonical form. For the
``Subgrantee`` role ``X-User-ID`` is the ``id`` of the acting subgrantee, so
ownership-gated calls MUST use :func:`make_subgrantee_headers` with the real
subgrantee id rather than a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used throughout the suite.
ADMIN_1 = "admin-1"
ADMIN_2 = "admin-2"
ANALYST_1 = "analyst-1"
ANALYST_2 = "analyst-2"
REVIEWER_1 = "reviewer-1"
REVIEWER_2 = "reviewer-2"
SCORER_1 = "scorer-1"
SCORER_2 = "scorer-2"
EHP_1 = "ehp-1"
AUDITOR_1 = "auditor-1"
AUDITOR_2 = "auditor-2"
COMMUNITY_1 = "comm-1"
COMMUNITY_9 = "comm-9"
PROVIDER_2 = "prov-2"
PROVIDER_3 = "prov-3"
PROVIDER_9 = "prov-9"


TEST_USERS = {
    # ProgramAdmin — opaque operator identifier.
    "program_admin_headers": build_user_headers(ADMIN_1, "ProgramAdmin"),
    "program_admin_2_headers": build_user_headers(ADMIN_2, "ProgramAdmin"),
    # EligibilityAnalyst — two identities, because the analyst who triaged a
    # challenge may not record its determination.
    "eligibility_analyst_headers": build_user_headers(ANALYST_1, "EligibilityAnalyst"),
    "eligibility_analyst_2_headers": build_user_headers(
        ANALYST_2, "EligibilityAnalyst"
    ),
    # CapabilityReviewer — the reviewer stamped on a subgrantee.
    "capability_reviewer_headers": build_user_headers(REVIEWER_1, "CapabilityReviewer"),
    "capability_reviewer_2_headers": build_user_headers(
        REVIEWER_2, "CapabilityReviewer"
    ),
    # ScoringOfficer.
    "scoring_officer_headers": build_user_headers(SCORER_1, "ScoringOfficer"),
    "scoring_officer_2_headers": build_user_headers(SCORER_2, "ScoringOfficer"),
    # EnvironmentalReviewer.
    "environmental_reviewer_headers": build_user_headers(
        EHP_1, "EnvironmentalReviewer"
    ),
    # AuditOfficer — two identities, because the operator who last verified a
    # milestone may neither record an audit result nor verify remediation.
    "audit_officer_headers": build_user_headers(AUDITOR_1, "AuditOfficer"),
    "audit_officer_2_headers": build_user_headers(AUDITOR_2, "AuditOfficer"),
    # Challenger and Provider — opaque filing identities.
    "challenger_headers": build_user_headers(COMMUNITY_1, "Challenger"),
    "challenger_other_headers": build_user_headers(COMMUNITY_9, "Challenger"),
    "provider_headers": build_user_headers(PROVIDER_2, "Provider"),
    "provider_other_headers": build_user_headers(PROVIDER_3, "Provider"),
    "provider_stranger_headers": build_user_headers(PROVIDER_9, "Provider"),
    # Subgrantee — fallback only, for calls that never touch an ownership check.
    "subgrantee_headers": build_user_headers("test-subgrantee-1", "Subgrantee"),
}


def make_subgrantee_headers(user_id: str) -> dict:
    """Headers for the ``Subgrantee`` role.

    ``X-User-ID`` is the ``id`` of the acting subgrantee, so pass the real
    subgrantee id whenever the call is ownership-gated: an application is owned
    by the subgrantee whose id equals its ``subgrantee_id``.
    """
    return build_user_headers(user_id, "Subgrantee")


def make_program_admin_headers(user_id: str) -> dict:
    """Headers for a specific ``ProgramAdmin`` operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_eligibility_analyst_headers(user_id: str) -> dict:
    """Headers for a specific ``EligibilityAnalyst`` operator identifier."""
    return build_user_headers(user_id, "EligibilityAnalyst")


def make_capability_reviewer_headers(user_id: str) -> dict:
    """Headers for a specific ``CapabilityReviewer`` operator identifier."""
    return build_user_headers(user_id, "CapabilityReviewer")


def make_scoring_officer_headers(user_id: str) -> dict:
    """Headers for a specific ``ScoringOfficer`` operator identifier."""
    return build_user_headers(user_id, "ScoringOfficer")


def make_environmental_reviewer_headers(user_id: str) -> dict:
    """Headers for a specific ``EnvironmentalReviewer`` operator identifier."""
    return build_user_headers(user_id, "EnvironmentalReviewer")


def make_audit_officer_headers(user_id: str) -> dict:
    """Headers for a specific ``AuditOfficer`` operator identifier."""
    return build_user_headers(user_id, "AuditOfficer")


def make_challenger_headers(user_id: str) -> dict:
    """Headers for a specific ``Challenger`` filing identity."""
    return build_user_headers(user_id, "Challenger")


def make_provider_headers(user_id: str) -> dict:
    """Headers for a specific ``Provider`` filing identity."""
    return build_user_headers(user_id, "Provider")


# Bare headers with no acting user, for the authentication rule.
NO_USER_HEADERS = {"X-User-Role": "ProgramAdmin", "Content-Type": "application/json"}

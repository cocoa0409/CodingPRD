"""Pre-built role headers for every role the PRD defines.

Every request must carry ``X-User-ID`` and ``X-User-Role``.  Identity semantics
differ by role: for a ``RiskManager`` the ``X-User-ID`` is the ``id`` of the
acting ``Insured``, so ownership-gated calls MUST use
:func:`make_risk_manager_headers` with the real insured id.  The other three
roles carry opaque operator identifiers.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the three opaque-identity roles, and for
# RiskManager calls that never reach an ownership comparison.
TEST_USERS = {
    "underwriter_headers": build_user_headers("uw-001", "Underwriter"),
    "risk_manager_headers": build_user_headers("rm-unowned-001", "RiskManager"),
    "claims_adjuster_headers": build_user_headers("adj-001", "ClaimsAdjuster"),
    "compliance_officer_headers": build_user_headers("co-001", "ComplianceOfficer"),
}

# A second adjuster identity. The adjuster who recommended a settlement may not
# be the adjuster who funds it, so resolutions need a distinct operator id.
SECOND_ADJUSTER_USER_ID = "adj-002"
FIRST_ADJUSTER_USER_ID = "adj-001"

TEST_USERS["second_claims_adjuster_headers"] = build_user_headers(
    SECOND_ADJUSTER_USER_ID, "ClaimsAdjuster"
)

# Headers carrying no identity at all, for the authentication gate.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_underwriter_headers(user_id: str = "uw-001") -> dict:
    """For an ``Underwriter``: ``X-User-ID`` is an opaque operator identifier
    recorded as ``issued_by_user_id`` on a quote, never compared to an entity id."""
    return build_user_headers(user_id, "Underwriter")


def make_risk_manager_headers(insured_id: str) -> dict:
    """For a ``RiskManager``: ``X-User-ID`` is the ``id`` of the acting
    ``Insured``.  Pass the real insured id whenever the call is ownership-gated."""
    return build_user_headers(insured_id, "RiskManager")


def make_claims_adjuster_headers(user_id: str = FIRST_ADJUSTER_USER_ID) -> dict:
    """For a ``ClaimsAdjuster``: ``X-User-ID`` is an opaque operator identifier
    recorded as ``decided_by_user_id`` and ``recommended_by_user_id``."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_compliance_officer_headers(user_id: str = "co-001") -> dict:
    """For a ``ComplianceOfficer``: ``X-User-ID`` is an opaque operator
    identifier the server neither records nor compares."""
    return build_user_headers(user_id, "ComplianceOfficer")


__all__ = [
    "TEST_USERS", "NO_AUTH_HEADERS",
    "FIRST_ADJUSTER_USER_ID", "SECOND_ADJUSTER_USER_ID",
    "make_underwriter_headers", "make_risk_manager_headers",
    "make_claims_adjuster_headers", "make_compliance_officer_headers",
]

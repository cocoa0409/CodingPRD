"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, six roles are opaque (X-User-ID is an operator identifier the
server never reconciles against any entity): LoanOfficer, Underwriter, Closer,
Appraiser, TitleAgent, ComplianceOfficer.

The seventh role, Applicant, is entity-backed: X-User-ID MUST equal the acting
Applicant.id for ownership-gated calls (POST /disclosures/{id}/acknowledge).
Use `make_applicant_headers(applicant_id)` whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # Opaque roles — shared constant is canonical (PRD §2.1).
    "loan_officer_headers": build_user_headers("lo-001", "LoanOfficer"),
    "loan_officer_alt_headers": build_user_headers("lo-002", "LoanOfficer"),
    "underwriter_headers": build_user_headers("uw-001", "Underwriter"),
    "underwriter_alt_headers": build_user_headers("uw-002", "Underwriter"),
    "closer_headers": build_user_headers("cl-001", "Closer"),
    "appraiser_headers": build_user_headers("appr-001", "Appraiser"),
    "title_agent_headers": build_user_headers("ta-001", "TitleAgent"),
    "compliance_officer_headers": build_user_headers("co-001", "ComplianceOfficer"),
    # Entity-backed Applicant — shared constant is a fallback for non-ownership
    # tests only; ownership-gated calls MUST use make_applicant_headers(applicant_id).
    "applicant_headers": build_user_headers("test-applicant-fallback", "Applicant"),
}


def make_loan_officer_headers(user_id: str) -> dict:
    """LoanOfficer headers with a specific X-User-ID — used when SoD requires
    distinct or identical-by-design X-User-IDs across prequalify and approve."""
    return build_user_headers(user_id, "LoanOfficer")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter headers with a specific X-User-ID — used to align/diverge
    from the originating LoanOfficer's X-User-ID for SoD scenarios."""
    return build_user_headers(user_id, "Underwriter")


def make_applicant_headers(applicant_id: str) -> dict:
    """Applicant headers where X-User-ID equals the acting Applicant.id.

    Required for ownership-gated calls — POST /disclosures/{id}/acknowledge.
    Falling back to the shared constant for entity-backed Applicant calls
    would mismatch every ownership check.
    """
    return build_user_headers(applicant_id, "Applicant")


def make_unauthenticated_headers() -> dict:
    """Headers that deliberately omit X-User-Role / X-User-ID to trigger
    ERR_UNAUTHENTICATED (PRD §2.1)."""
    return {"Content-Type": "application/json"}

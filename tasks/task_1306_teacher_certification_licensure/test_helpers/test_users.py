"""Pre-built role headers for every role in the PRD (section 2.1).

Only `Applicant` is entity-backed: its X-User-ID must equal the acting
Applicant record's id on any ownership-gated call, so tests MUST build
per-instance headers via make_applicant_headers(applicant["id"]). All other
roles are opaque operator identifiers; their shared constants are canonical,
and per-instance builders exist so tests that pin a specific X-User-ID
(e.g. segregation-of-duties scenarios) can do so explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared constants.
    "anonymous_headers": build_user_headers("anon-self-register", "Anonymous"),
    "intake_officer_headers": build_user_headers("intake-1", "IntakeOfficer"),
    "credential_evaluator_headers": build_user_headers("eval-1", "CredentialEvaluator"),
    "background_investigator_headers": build_user_headers("bi-1", "BackgroundInvestigator"),
    "legal_officer_headers": build_user_headers("legal-1", "LegalOfficer"),
    "program_approval_officer_headers": build_user_headers("pao-1", "ProgramApprovalOfficer"),
    "agency_admin_headers": build_user_headers("admin-1", "AgencyAdmin"),
    # Entity-backed role: fallback ONLY for tests that never exercise ownership.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For the entity-backed Applicant role: pass the actual Applicant.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Applicant")


def make_anonymous_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_intake_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_credential_evaluator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CredentialEvaluator")


def make_background_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BackgroundInvestigator")


def make_legal_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalOfficer")


def make_program_approval_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramApprovalOfficer")


def make_agency_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyAdmin")

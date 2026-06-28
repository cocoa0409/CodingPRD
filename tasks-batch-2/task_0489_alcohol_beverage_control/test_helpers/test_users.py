"""Pre-built role headers for every role in the PRD (section 2.1).

Seven roles: Director, LicensingExaminer, ZoningOfficer, AdjudicationOfficer,
Investigator, Applicant, Anonymous.

- Director / LicensingExaminer / ZoningOfficer / AdjudicationOfficer /
  Investigator / Anonymous carry an OPAQUE X-User-ID that the server records as
  an actor footprint but never compares to any entity id; the shared constant is
  the canonical form for these roles.
- Applicant is entity_backed: when X-User-Role is Applicant, X-User-ID is the id
  of the acting Applicant, and ownership checks compare a resource's applicant FK
  to X-User-ID. For any ownership-gated call, use make_applicant_headers(
  applicant_id) with the real Applicant.id — the shared constant is only a
  fallback for non-ownership tests (404 / role-denial / bad-payload).

Separation of duties (PRD section 2.1) is enforced on opaque footprints: the
issuer's X-User-ID must differ from examiner_user_id; the adjudicator's must
differ from investigator_user_id. Distinct opaque ids are provided below.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "director_headers": build_user_headers("dir-1", "Director"),
    "examiner_headers": build_user_headers("exam-1", "LicensingExaminer"),
    "zoning_officer_headers": build_user_headers("zone-1", "ZoningOfficer"),
    "adjudication_officer_headers": build_user_headers("adj-1", "AdjudicationOfficer"),
    "investigator_headers": build_user_headers("inv-1", "Investigator"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # Entity-backed fallback — only safe where ownership is not exercised.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_director_headers(user_id: str = "dir-1") -> dict:
    return build_user_headers(user_id, "Director")


def make_examiner_headers(user_id: str = "exam-1") -> dict:
    """LicensingExaminer footprint recorded as examiner_user_id. Pass a distinct
    user_id from the Director on approve/issue/deny to exercise segregation."""
    return build_user_headers(user_id, "LicensingExaminer")


def make_zoning_officer_headers(user_id: str = "zone-1") -> dict:
    return build_user_headers(user_id, "ZoningOfficer")


def make_adjudication_officer_headers(user_id: str = "adj-1") -> dict:
    """AdjudicationOfficer footprint recorded as officer_user_id / adjudicator_user_id.
    Pass a distinct user_id from the violation's investigator to exercise
    segregation of duties on sustain/dismiss."""
    return build_user_headers(user_id, "AdjudicationOfficer")


def make_investigator_headers(user_id: str = "inv-1") -> dict:
    """Investigator footprint recorded as investigator_user_id."""
    return build_user_headers(user_id, "Investigator")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the actual Applicant.id as
    user_id whenever the call is ownership-gated (submit, pay-fee, withdraw,
    server-permits, activate, renew, pay-fine, contest, compliance-reports,
    transfer-requests)."""
    return build_user_headers(user_id, "Applicant")

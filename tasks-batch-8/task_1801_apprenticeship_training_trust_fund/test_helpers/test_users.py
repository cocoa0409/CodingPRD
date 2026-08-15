"""Pre-built role headers for every role in PRD §2.1.

EmployerRep is entity-backed: its X-User-ID must be the acting Employer's id
whenever the call is ownership-gated (report submit / resubmit / remit).
Use make_employer_rep_headers(employer["id"]) for those calls; the shared
constant is only safe for negative RBAC probes.

Instructor identity is opaque but must equal the class's instructor_user_id
string at pay-claim filing time; use make_instructor_headers with the class's
instructor_user_id for claim creation.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "trust_admin_headers": build_user_headers("admin-1", "TrustAdmin"),
    "trust_admin2_headers": build_user_headers("admin-2", "TrustAdmin"),
    "committee_member_headers": build_user_headers("cm-1", "CommitteeMember"),
    "committee_member2_headers": build_user_headers("cm-2", "CommitteeMember"),
    # entity_backed:Employer — fallback for non-ownership probes only.
    "employer_rep_headers": build_user_headers("rep-orphan-1", "EmployerRep"),
    # opaque, but must match the class's instructor_user_id on claim filing.
    "instructor_headers": build_user_headers("inst-1", "Instructor"),
}

# Requests carrying no X-User-ID / X-User-Role at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_employer_rep_headers(employer_id: str) -> dict:
    """EmployerRep is entity-backed by Employer: pass the acting employer's id
    whenever the call is ownership-gated (submit / resubmit / remit)."""
    return build_user_headers(employer_id, "EmployerRep")


def make_instructor_headers(instructor_user_id: str) -> dict:
    """Instructor identity is opaque but must equal the class's
    instructor_user_id when filing a pay claim."""
    return build_user_headers(instructor_user_id, "Instructor")


def make_trust_admin_headers(user_id: str) -> dict:
    """TrustAdmin identity is opaque but recorded (e.g. proposed_by_user_id)."""
    return build_user_headers(user_id, "TrustAdmin")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember identity is opaque but recorded (e.g. approved_by_user_id)."""
    return build_user_headers(user_id, "CommitteeMember")

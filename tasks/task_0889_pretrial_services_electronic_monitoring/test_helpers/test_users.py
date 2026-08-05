"""Pre-built role headers for every role in the PRD.

Four roles (IntakeOfficer, SupervisingOfficer, JudicialOfficer, ProgramAdmin) carry an
opaque identity — their X-User-ID is an operator id not tied to any entity, so the shared
constant form is canonical for them. Segregation-of-duties tests still need to control the
exact X-User-ID, so per-id builders are provided for each opaque role.

The Defendant role is entity-backed: its X-User-ID must be the acting Defendant's id, so
ownership-gated calls MUST use make_defendant_headers(defendant["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for the opaque roles.
TEST_USERS = {
    "intake_headers": build_user_headers("u_intake", "IntakeOfficer"),
    "supervising_headers": build_user_headers("u_sup", "SupervisingOfficer"),
    "judicial_headers": build_user_headers("u_judge", "JudicialOfficer"),
    "admin_headers": build_user_headers("u_admin", "ProgramAdmin"),
}


# Per-id builders for the opaque roles (needed for SoD, where two actors of the same
# role must carry distinct — or deliberately identical — X-User-ID values).
def make_intake_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_supervising_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupervisingOfficer")


def make_judicial_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "JudicialOfficer")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


# Entity-backed Defendant role: pass the actual Defendant.id.
def make_defendant_headers(defendant_id: str) -> dict:
    """For the Defendant role. Pass the acting Defendant.id as X-User-ID."""
    return build_user_headers(defendant_id, "Defendant")

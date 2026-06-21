"""Pre-built role headers for every role in the PRD (PRD §2.1).

The PRD recognizes exactly three roles, spelled precisely: PlanAdministrator,
ComplianceOfficer, Participant.

- PlanAdministrator and ComplianceOfficer carry an OPAQUE X-User-ID that the server
  never compares to an entity id; shared constants are the canonical form.
- Participant is entity-backed: X-User-ID is the acting Participant's id and ownership
  checks compare it to the resource's participant_id. For ownership-gated calls callers
  MUST use make_participant_headers(participant_id) with the real id; the shared
  constant carries a fake id usable only for non-ownership paths (401/404/etc.).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "plan_admin_headers": build_user_headers("admin1", "PlanAdministrator"),
    # A second distinct admin id, for segregation-of-duties tests where the runner
    # must differ from the certifying officer.
    "plan_admin2_headers": build_user_headers("admin2", "PlanAdministrator"),
    "compliance_officer_headers": build_user_headers("officer1", "ComplianceOfficer"),
    "compliance_officer2_headers": build_user_headers("officer2", "ComplianceOfficer"),
    # Entity-backed role — fake-id fallback for non-ownership tests only.
    "participant_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000ff", "Participant"
    ),
}


def make_participant_headers(participant_id: str) -> dict:
    """Headers for the Participant role bound to a specific Participant.id."""
    return build_user_headers(participant_id, "Participant")


def make_admin_headers(admin_id: str = "admin1") -> dict:
    """Headers for the PlanAdministrator role (opaque id)."""
    return build_user_headers(admin_id, "PlanAdministrator")


def make_officer_headers(officer_id: str = "officer1") -> dict:
    """Headers for the ComplianceOfficer role (opaque id)."""
    return build_user_headers(officer_id, "ComplianceOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)

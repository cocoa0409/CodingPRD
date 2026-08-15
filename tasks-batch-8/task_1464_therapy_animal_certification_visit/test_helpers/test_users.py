"""Pre-built role headers for every role in the PRD (§2.1).

Identity model (PRD §2.1):
- Anonymous / ProgramAdmin / ComplianceOfficer carry an opaque X-User-ID.
- Handler: X-User-ID is the acting Handler record's id (entity-backed).
- Evaluator: X-User-ID is the acting Evaluator record's id (entity-backed).
- FacilityCoordinator: X-User-ID is the coordinator's Facility record id
  (entity-backed).

The shared constants for entity-backed roles are fallbacks for tests whose
success does NOT depend on ownership. Any ownership-gated call MUST use the
make_* builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "anonymous_headers": build_user_headers("anon-caller-1", "Anonymous"),
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    # Entity-backed fallbacks — only for tests that do not exercise ownership.
    "handler_headers": build_user_headers("handler-stub-1", "Handler"),
    "evaluator_headers": build_user_headers("evaluator-stub-1", "Evaluator"),
    "facility_coordinator_headers": build_user_headers("facility-stub-1", "FacilityCoordinator"),
}


def make_handler_headers(user_id: str) -> dict:
    """Handler is entity-backed: pass the real Handler.id for ownership-gated calls."""
    return build_user_headers(user_id, "Handler")


def make_evaluator_headers(user_id: str) -> dict:
    """Evaluator is entity-backed: pass the real Evaluator.id when scoring."""
    return build_user_headers(user_id, "Evaluator")


def make_facility_coordinator_headers(facility_id: str) -> dict:
    """FacilityCoordinator is entity-backed: pass the real Facility.id."""
    return build_user_headers(facility_id, "FacilityCoordinator")


def make_program_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")

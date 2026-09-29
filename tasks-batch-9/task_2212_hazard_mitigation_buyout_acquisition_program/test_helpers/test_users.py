"""Pre-built role headers for every role named in the PRD.

Five of the six roles carry an opaque X-User-ID that the server never compares
against an entity id, so a shared constant is the canonical form for them.
``SubrecipientCoordinator`` is the one project-scoped role: its X-User-ID is the
id of the acting MitigationProject, so every ownership-gated coordinator call
MUST be made with ``make_subrecipient_coordinator_headers(project["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # ProgramAdministrator -- opaque identifier.
    "program_administrator_headers": build_user_headers("pa-1", "ProgramAdministrator"),
    # A second and third administrator, needed because project approval bars the
    # administrator who validated the benefit-cost analysis from approving it.
    "bca_validator_headers": build_user_headers("pa-validator", "ProgramAdministrator"),
    "project_approver_headers": build_user_headers("pa-approver", "ProgramAdministrator"),
    # SubrecipientCoordinator -- shared constant, ownership-safe only for calls
    # that never resolve to a project (e.g. structural-validation failures).
    "subrecipient_coordinator_headers": build_user_headers(
        "test-coordinator-1", "SubrecipientCoordinator"
    ),
    # StaffAppraiser -- opaque identifier recorded as appraiser_user_id.
    "staff_appraiser_headers": build_user_headers("sa-1", "StaffAppraiser"),
    "staff_appraiser_2_headers": build_user_headers("sa-2", "StaffAppraiser"),
    # ReviewAppraiser -- opaque identifier recorded as appraiser_user_id.
    "review_appraiser_headers": build_user_headers("ra-1", "ReviewAppraiser"),
    "review_appraiser_2_headers": build_user_headers("ra-2", "ReviewAppraiser"),
    # RelocationSpecialist -- opaque identifier, never recorded nor compared.
    "relocation_specialist_headers": build_user_headers("rs-1", "RelocationSpecialist"),
    # ComplianceMonitor -- opaque identifier recorded as inspector_user_id.
    "compliance_monitor_headers": build_user_headers("cm-1", "ComplianceMonitor"),
    "compliance_monitor_2_headers": build_user_headers("cm-2", "ComplianceMonitor"),
}


# ─── Per-instance builders ────────────────────────────────────────────────────

def make_subrecipient_coordinator_headers(project_id: str) -> dict:
    """Headers for the coordinator of one specific project.

    X-User-ID must equal the id of the MitigationProject this coordinator
    administers; anything else resolves to a different project and is rejected.
    """
    return build_user_headers(project_id, "SubrecipientCoordinator")


def make_program_administrator_headers(user_id: str) -> dict:
    """Headers for a named administrator, for the approval and cure duty bars."""
    return build_user_headers(user_id, "ProgramAdministrator")


def make_staff_appraiser_headers(user_id: str) -> dict:
    """Headers for a named staff appraiser; the id lands on appraiser_user_id."""
    return build_user_headers(user_id, "StaffAppraiser")


def make_review_appraiser_headers(user_id: str) -> dict:
    """Headers for a named review appraiser; the id lands on appraiser_user_id."""
    return build_user_headers(user_id, "ReviewAppraiser")


def make_relocation_specialist_headers(user_id: str) -> dict:
    """Headers for a named relocation specialist."""
    return build_user_headers(user_id, "RelocationSpecialist")


def make_compliance_monitor_headers(user_id: str) -> dict:
    """Headers for a named monitor; the id lands on inspector_user_id."""
    return build_user_headers(user_id, "ComplianceMonitor")

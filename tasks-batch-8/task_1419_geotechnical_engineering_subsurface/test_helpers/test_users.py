"""Pre-built role headers for every role in the PRD (section 2.1).

Eight roles are opaque: X-User-ID is an operator identifier never compared to
an entity id. Two roles are entity-backed: ClientRep (X-User-ID is a Client
id) and DrillingSub (X-User-ID is a Subcontractor id). For those, the shared
constant is a fallback for non-ownership tests only; ownership-gated calls
MUST use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "firm_admin_headers": build_user_headers("admin-1", "FirmAdmin"),
    # entity_backed:Client — fallback for non-ownership tests only.
    "client_rep_headers": build_user_headers("test-clientrep-1", "ClientRep"),
    "project_manager_headers": build_user_headers("pm-1", "ProjectManager"),
    "staff_engineer_headers": build_user_headers("ste-1", "StaffEngineer"),
    "field_geologist_headers": build_user_headers("fg-1", "FieldGeologist"),
    # entity_backed:Subcontractor — fallback for non-ownership tests only.
    "drilling_sub_headers": build_user_headers("test-drilsub-1", "DrillingSub"),
    "lab_manager_headers": build_user_headers("lm-1", "LabManager"),
    "lab_technician_headers": build_user_headers("lt-1", "LabTechnician"),
    "senior_engineer_headers": build_user_headers("se-1", "SeniorEngineer"),
    "principal_engineer_headers": build_user_headers("pe-9", "PrincipalEngineer"),
}


def make_firm_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FirmAdmin")


def make_client_rep_headers(user_id: str) -> dict:
    """ClientRep is entity-backed: pass the acting Client's id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ClientRep")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_staff_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StaffEngineer")


def make_field_geologist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldGeologist")


def make_drilling_sub_headers(user_id: str) -> dict:
    """DrillingSub is entity-backed: pass the acting Subcontractor's id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "DrillingSub")


def make_lab_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabManager")


def make_lab_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_senior_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SeniorEngineer")


def make_principal_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrincipalEngineer")

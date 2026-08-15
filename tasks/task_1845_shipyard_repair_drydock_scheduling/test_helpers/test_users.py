"""Pre-built role headers for every role in the PRD (§2.1).

For six roles the user id is an opaque operator identifier; for Subcontractor it
is the id of the acting Subcontractor entity, so ownership-gated calls must use
make_subcontractor_headers() with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "yard_admin_headers": build_user_headers("admin_1", "YardAdmin"),
    "project_manager_headers": build_user_headers("pm_1", "ProjectManager"),
    "project_manager_2_headers": build_user_headers("pm_2", "ProjectManager"),
    "commercial_approver_headers": build_user_headers("comm_1", "CommercialApprover"),
    "commercial_approver_2_headers": build_user_headers("comm_2", "CommercialApprover"),
    "shipowner_rep_headers": build_user_headers("owner_9", "ShipownerRep"),
    "shipowner_rep_2_headers": build_user_headers("owner_x", "ShipownerRep"),
    "class_surveyor_headers": build_user_headers("sv_1", "ClassSurveyor"),
    "class_surveyor_2_headers": build_user_headers("sv_2", "ClassSurveyor"),
    "environmental_officer_headers": build_user_headers(
        "eo_1", "EnvironmentalOfficer"
    ),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "subcontractor_headers": build_user_headers("sub_1", "Subcontractor"),
}


def make_subcontractor_headers(subcontractor_id: str) -> dict:
    """For Subcontractor (entity-backed): pass the actual Subcontractor.id whenever
    the call is ownership-gated (start/complete of an assigned work item)."""
    return build_user_headers(subcontractor_id, "Subcontractor")


def make_shipowner_rep_headers(user_id: str) -> dict:
    """ShipownerRep identity is compared against the vessel's owner_user_id for
    owner countersign and warranty filing."""
    return build_user_headers(user_id, "ShipownerRep")

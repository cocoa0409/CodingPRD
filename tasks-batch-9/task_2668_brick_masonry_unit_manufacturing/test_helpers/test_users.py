"""
Auth headers for the eight roles.

Seven of the eight roles are identified by an opaque user id, so a module-level
header dict is enough. `PlantOperator` is different: the PRD scopes an operator
to one plant and identifies the operator by that plant's id, so operator headers
must be built per plant with make_plant_operator_headers(plant_id).

Several PRD rules forbid one person from performing two steps of the same
workflow (the certifier may not be the composer, the approver may not be the
submitter), so each workflow role has a second distinct identity.
"""

from prd_bench_local_runner.testing import build_user_headers

PLANT_ADMIN_ID = "admin-001"
BODY_ENGINEER_ID = "body-001"
BLEND_TECHNICIAN_ID = "blend-001"
BLEND_TECHNICIAN_2_ID = "blend-002"
QUALITY_MANAGER_ID = "qual-001"
QUALITY_MANAGER_2_ID = "qual-002"
ARCHITECT_REVIEWER_ID = "arch-001"
ARCHITECT_REVIEWER_2_ID = "arch-002"
SALES_REP_ID = "sales-001"
LOGISTICS_COORDINATOR_ID = "logi-001"

PLANT_ADMIN = build_user_headers(PLANT_ADMIN_ID, "PlantAdmin")
BODY_ENGINEER = build_user_headers(BODY_ENGINEER_ID, "BodyEngineer")
BLEND_TECHNICIAN = build_user_headers(BLEND_TECHNICIAN_ID, "BlendTechnician")
BLEND_TECHNICIAN_2 = build_user_headers(BLEND_TECHNICIAN_2_ID, "BlendTechnician")
QUALITY_MANAGER = build_user_headers(QUALITY_MANAGER_ID, "QualityManager")
QUALITY_MANAGER_2 = build_user_headers(QUALITY_MANAGER_2_ID, "QualityManager")
ARCHITECT_REVIEWER = build_user_headers(ARCHITECT_REVIEWER_ID, "ArchitectReviewer")
ARCHITECT_REVIEWER_2 = build_user_headers(ARCHITECT_REVIEWER_2_ID, "ArchitectReviewer")
SALES_REP = build_user_headers(SALES_REP_ID, "SalesRep")
LOGISTICS_COORDINATOR = build_user_headers(
    LOGISTICS_COORDINATOR_ID, "LogisticsCoordinator"
)

# An X-User-Role value that is not one of the eight roles the PRD defines.
UNKNOWN_ROLE = build_user_headers("nobody-001", "WarehousePicker")

# No auth headers at all.
NO_AUTH = {"Content-Type": "application/json"}


def make_plant_operator_headers(plant_id: str) -> dict:
    """
    Headers for the PlantOperator of one specific plant.

    The operator's X-User-ID is that plant's id, which is how the PRD decides
    whether a production endpoint is inside the operator's scope.
    """
    return build_user_headers(plant_id, "PlantOperator")


# Every role that can read; the read endpoints are open to all eight roles.
ALL_ROLE_HEADERS = {
    "PlantAdmin": PLANT_ADMIN,
    "BodyEngineer": BODY_ENGINEER,
    "BlendTechnician": BLEND_TECHNICIAN,
    "QualityManager": QUALITY_MANAGER,
    "ArchitectReviewer": ARCHITECT_REVIEWER,
    "SalesRep": SALES_REP,
    "LogisticsCoordinator": LOGISTICS_COORDINATOR,
}

# The seven roles whose identity is opaque (everything except PlantOperator).
OPAQUE_ROLE_HEADERS = dict(ALL_ROLE_HEADERS)

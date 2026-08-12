"""Pre-built role headers for every role in the PRD.

All seven roles are opaque — X-User-ID is an operator id, not an entity id —
so shared constants are the canonical form. Per-user variants are still
provided for workflows that stamp the actor (inspection / certification
segregation of duties), where the user id must differ between operators.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "sales_rep_headers": build_user_headers("sr-1", "SalesRep"),
    "production_planner_headers": build_user_headers("pp-1", "ProductionPlanner"),
    "material_receiver_headers": build_user_headers("mr-1", "MaterialReceiver"),
    "quality_inspector_headers": build_user_headers("qi-1", "QualityInspector"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "shipping_coordinator_headers": build_user_headers("sc-1", "ShippingCoordinator"),
    "plant_admin_headers": build_user_headers("pa-1", "PlantAdmin"),
}


def make_sales_rep_headers(user_id: str) -> dict:
    """SalesRep with a specific operator id."""
    return build_user_headers(user_id, "SalesRep")


def make_production_planner_headers(user_id: str) -> dict:
    """ProductionPlanner with a specific operator id."""
    return build_user_headers(user_id, "ProductionPlanner")


def make_material_receiver_headers(user_id: str) -> dict:
    """MaterialReceiver with a specific operator id."""
    return build_user_headers(user_id, "MaterialReceiver")


def make_quality_inspector_headers(user_id: str) -> dict:
    """QualityInspector with a specific operator id. Use when segregation of
    duties requires distinguishing the lot inspector from the certifier."""
    return build_user_headers(user_id, "QualityInspector")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific operator id. Pass a different id
    than the lot inspector when exercising segregation of duties."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_shipping_coordinator_headers(user_id: str) -> dict:
    """ShippingCoordinator with a specific operator id."""
    return build_user_headers(user_id, "ShippingCoordinator")


def make_plant_admin_headers(user_id: str) -> dict:
    """PlantAdmin with a specific operator id."""
    return build_user_headers(user_id, "PlantAdmin")

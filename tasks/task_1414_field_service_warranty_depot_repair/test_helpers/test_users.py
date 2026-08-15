"""Pre-built role headers for every role in the PRD (§2.1).

The Customer role is entity-backed: when X-User-Role is Customer, X-User-ID is
the id of the acting Customer record, so ownership-gated calls must be built
with make_customer_headers(customer["id"]). The five operator roles
(IntakeAgent, DepotTechnician, DepotManager, WarrantyAdministrator,
EngineeringLead) carry opaque identifiers; distinct operator identities matter
for the segregation-of-duties gates (PRD §2.9), so per-identity builders are
provided for them too.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "intake_agent_headers": build_user_headers("intake-1", "IntakeAgent"),
    "depot_technician_headers": build_user_headers("tech-1", "DepotTechnician"),
    "depot_manager_headers": build_user_headers("mgr-1", "DepotManager"),
    "warranty_admin_headers": build_user_headers("wa-1", "WarrantyAdministrator"),
    "engineering_lead_headers": build_user_headers("eng-1", "EngineeringLead"),
    # Entity-backed Customer role — fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id whenever the
    call is ownership-gated (quote approve/decline, own RMA/unit reads,
    RMA create/cancel on own units)."""
    return build_user_headers(user_id, "Customer")


def make_intake_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeAgent")


def make_depot_technician_headers(user_id: str) -> dict:
    """For DepotTechnician. Distinct identities matter for the four-eyes QA
    gate: the qa-release actor must differ from repair_completed_by."""
    return build_user_headers(user_id, "DepotTechnician")


def make_depot_manager_headers(user_id: str) -> dict:
    """For DepotManager. The override-decision actor must differ from
    diagnosed_by; the scrap actor must differ from warranty_override_by."""
    return build_user_headers(user_id, "DepotManager")


def make_warranty_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarrantyAdministrator")


def make_engineering_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EngineeringLead")

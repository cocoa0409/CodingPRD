"""Pre-built role headers for every role in the PRD (§2.1).

Five roles are opaque (X-User-ID is not tied to a persisted entity). Dealer is
entity-backed by Customer: any ownership-gated call must use
``make_dealer_headers(customer_id)`` with the real customer id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles. Segregation-of-duties scenarios need
# two distinct user ids for the same role, hence the numbered variants.
PLANT_MANAGER = build_user_headers("pm-1", "PlantManager")
PLANT_MANAGER_2 = build_user_headers("pm-2", "PlantManager")
LAB_TECHNICIAN = build_user_headers("lab-1", "LabTechnician")
PRODUCTION_OPERATOR = build_user_headers("op-1", "ProductionOperator")
QC_INSPECTOR = build_user_headers("qc-1", "QCInspector")
QC_INSPECTOR_2 = build_user_headers("qc-2", "QCInspector")
QC_INSPECTOR_9 = build_user_headers("qc-9", "QCInspector")
QC_INSPECTOR_10 = build_user_headers("qc-10", "QCInspector")
REGULATORY_CLERK = build_user_headers("reg-1", "RegulatoryClerk")

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "plant_manager_headers": PLANT_MANAGER,
    "plant_manager_2_headers": PLANT_MANAGER_2,
    "lab_technician_headers": LAB_TECHNICIAN,
    "production_operator_headers": PRODUCTION_OPERATOR,
    "qc_inspector_headers": QC_INSPECTOR,
    "qc_inspector_2_headers": QC_INSPECTOR_2,
    "regulatory_clerk_headers": REGULATORY_CLERK,
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only; never use it where a customer-ownership check applies.
    "dealer_headers": build_user_headers("test-dealer-1", "Dealer"),
}


def make_dealer_headers(customer_id: str) -> dict:
    """Dealer is entity-backed by Customer. Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated (orders, claims, reads)."""
    return build_user_headers(customer_id, "Dealer")


def make_plant_manager_headers(user_id: str) -> dict:
    """Distinct PlantManager identity (claim approver vs settler, etc.)."""
    return build_user_headers(user_id, "PlantManager")


def make_qc_inspector_headers(user_id: str) -> dict:
    """Distinct QCInspector identity (measurer vs approver segregation)."""
    return build_user_headers(user_id, "QCInspector")


def make_lab_technician_headers(user_id: str) -> dict:
    """Distinct LabTechnician identity (measurement entry)."""
    return build_user_headers(user_id, "LabTechnician")

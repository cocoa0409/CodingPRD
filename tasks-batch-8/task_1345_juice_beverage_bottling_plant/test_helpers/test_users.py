"""Pre-built role headers for every role in the PRD RBAC table (§2.1, §4).

All operational roles are opaque: their X-User-ID is not compared to any
entity id. CustomerContact is entity-backed: its X-User-ID must equal the
acting CustomerAccount.id, so ownership-gated calls must use
make_customer_contact_headers(customer["id"]).

Segregation-of-duties markers: keep the blending operator ("op-1") distinct
from the QA inspector ("qa-1"), and the formula submitter ("dev-1") distinct
from the label reviewer ("rev-1").
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identities (opaque roles)
PM_USER = "pm-1"
FIN_USER = "fin-1"
DEV_USER = "dev-1"
REV_USER = "rev-1"
OP_USER = "op-1"
QA_USER = "qa-1"
PLAN_USER = "plan-1"
WH_USER = "wh-1"
CSR_USER = "csr-1"

TEST_USERS = {
    "plant_manager_headers": build_user_headers(PM_USER, "PlantManager"),
    "finance_clerk_headers": build_user_headers(FIN_USER, "FinanceClerk"),
    "product_developer_headers": build_user_headers(DEV_USER, "ProductDeveloper"),
    "label_reviewer_headers": build_user_headers(REV_USER, "LabelComplianceReviewer"),
    "blend_operator_headers": build_user_headers(OP_USER, "BlendOperator"),
    "qa_inspector_headers": build_user_headers(QA_USER, "QAInspector"),
    "production_planner_headers": build_user_headers(PLAN_USER, "ProductionPlanner"),
    "warehouse_lead_headers": build_user_headers(WH_USER, "WarehouseLead"),
    "customer_service_rep_headers": build_user_headers(CSR_USER, "CustomerServiceRep"),
}


def make_plant_manager_headers(user_id: str = PM_USER) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_finance_clerk_headers(user_id: str = FIN_USER) -> dict:
    return build_user_headers(user_id, "FinanceClerk")


def make_product_developer_headers(user_id: str = DEV_USER) -> dict:
    return build_user_headers(user_id, "ProductDeveloper")


def make_label_reviewer_headers(user_id: str = REV_USER) -> dict:
    return build_user_headers(user_id, "LabelComplianceReviewer")


def make_blend_operator_headers(user_id: str = OP_USER) -> dict:
    return build_user_headers(user_id, "BlendOperator")


def make_qa_inspector_headers(user_id: str = QA_USER) -> dict:
    return build_user_headers(user_id, "QAInspector")


def make_production_planner_headers(user_id: str = PLAN_USER) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_warehouse_lead_headers(user_id: str = WH_USER) -> dict:
    return build_user_headers(user_id, "WarehouseLead")


def make_customer_service_rep_headers(user_id: str = CSR_USER) -> dict:
    return build_user_headers(user_id, "CustomerServiceRep")


def make_customer_contact_headers(customer_id: str) -> dict:
    """CustomerContact is entity-backed: pass the real CustomerAccount.id as
    user_id whenever the call is ownership-gated (shipment-order placement)."""
    return build_user_headers(customer_id, "CustomerContact")

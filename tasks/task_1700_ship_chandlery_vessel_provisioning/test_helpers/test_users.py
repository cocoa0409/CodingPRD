"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed and therefore get per-instance builders:
- VesselCateringOfficer: X-User-ID IS the acting VesselCall.id
- ShipAgentClerk: X-User-ID IS the acting ShipAgent.id

For any ownership-gated call (submit/recall a requisition, accept a quotation,
confirm a delivery, file/reopen a complaint; clerk paying an invoice) the
builder MUST be called with the actual entity id. The shared constants are a
fallback for opaque roles and for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "ops_headers": build_user_headers("test-ops-1", "ChandlerOpsManager"),
    "sales_headers": build_user_headers("test-sales-1", "ChandlerSalesRep"),
    "warehouse_headers": build_user_headers("test-warehouse-1", "WarehouseSupervisor"),
    "customs_headers": build_user_headers("test-customs-1", "PortCustomsOfficer"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceController"),
    "qa_headers": build_user_headers("test-qa-1", "QualityAssuranceLead"),
    # Entity-backed roles — fallback ONLY for tests that never pass an
    # ownership gate (e.g. unauthenticated-shape probes).
    "officer_headers": build_user_headers("test-officer-1", "VesselCateringOfficer"),
    "clerk_headers": build_user_headers("test-clerk-1", "ShipAgentClerk"),
}


def make_officer_headers(vessel_call_id: str) -> dict:
    """VesselCateringOfficer headers whose X-User-ID is a real VesselCall.id.

    Mandatory whenever the call is ownership-gated (requisition create /
    submit / recall, quotation accept, delivery confirm, complaint create /
    reopen).
    """
    return build_user_headers(vessel_call_id, "VesselCateringOfficer")


def make_clerk_headers(agent_id: str) -> dict:
    """ShipAgentClerk headers whose X-User-ID is a real ShipAgent.id.

    Mandatory when recording a payment: a clerk may only pay invoices billed
    to their own agent.
    """
    return build_user_headers(agent_id, "ShipAgentClerk")


def make_qa_headers(user_id: str) -> dict:
    """QualityAssuranceLead headers with a chosen operator id (opaque role).

    Used to exercise the four-eyes rule on reopened complaints, where the
    reviewer identity matters relative to last_reviewer_user_id.
    """
    return build_user_headers(user_id, "QualityAssuranceLead")

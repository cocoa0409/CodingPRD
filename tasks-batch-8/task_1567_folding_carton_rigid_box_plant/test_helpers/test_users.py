"""Pre-built role headers for every role in the PRD.

BrandQuality is entity-backed: its X-User-ID must equal the acting Customer's
id. Use make_brand_quality_headers(customer_id) for every ownership-gated call.
The shared TEST_USERS["brand_quality_headers"] constant is only a fallback for
tests that do not exercise ownership (e.g., 400/404 shape checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_admin_headers": build_user_headers("test-plant-admin-1", "PlantAdmin"),
    "structural_designer_headers": build_user_headers(
        "test-structural-designer-1", "StructuralDesigner"
    ),
    "press_operator_headers": build_user_headers(
        "test-press-operator-1", "PressOperator"
    ),
    "finishing_operator_headers": build_user_headers(
        "test-finishing-operator-1", "FinishingOperator"
    ),
    "kitting_lead_headers": build_user_headers("test-kitting-lead-1", "KittingLead"),
    # entity_backed:Customer — fallback only, never use for ownership-gated calls.
    "brand_quality_headers": build_user_headers(
        "test-brand-quality-1", "BrandQuality"
    ),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
}


def make_brand_quality_headers(customer_id: str) -> dict:
    """BrandQuality is entity-backed by Customer: pass the owning Customer.id
    whenever the call is ownership-gated (standard approve, design
    accept/reject, press-approval approve/reject, audit certify/reject)."""
    return build_user_headers(customer_id, "BrandQuality")

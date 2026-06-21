"""Pre-built role headers for every role in the PRD.

Three staff roles (FrameDesigner, FrameProductionTech, FrontDeskClerk) are opaque:
their X-User-ID is an opaque operator id never compared to any entity. The Customer
role is entity_backed: its X-User-ID must equal the addressed Customer's id, so
ownership-gated reads require a per-instance builder."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque staff roles use these directly; the Customer shared
# constant is only valid for tests that do not exercise resource ownership.
TEST_USERS = {
    "frame_designer_headers": build_user_headers("designer-1", "FrameDesigner"),
    "frame_production_tech_headers": build_user_headers("tech-1", "FrameProductionTech"),
    "front_desk_clerk_headers": build_user_headers("clerk-1", "FrontDeskClerk"),
    "customer_headers": build_user_headers("customer-1", "Customer"),
}


# Per-instance builder — required for the entity_backed Customer role. Pass the
# actual Customer.id whenever the read is ownership-gated.
def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the real Customer.id
    so ownership checks (X-User-ID == order.customer_id) pass."""
    return build_user_headers(customer_id, "Customer")

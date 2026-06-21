"""Pre-built role headers for every role in the PRD (Ghost Kitchen Platform).

Identity model (PRD §2.1):
  - PlatformOps        : opaque operator id, never compared to any entity id.
  - AggregatorGateway  : opaque integration id, never compared to any entity id.
  - StallOperator      : entity_backed -> X-User-ID MUST equal the acting Stall.id.
  - BrandOwner         : entity_backed -> X-User-ID MUST equal the acting VirtualBrand.id.

The two opaque roles use the shared constants below. The two entity-backed roles
MUST use the per-instance builders with the real entity id whenever the call is
ownership-gated; the shared StallOperator/BrandOwner constants are only safe for
tests whose outcome does NOT depend on ownership (e.g. 404-on-missing-resource).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
TEST_USERS = {
    # Opaque roles — canonical form.
    "platform_ops_headers": build_user_headers("ops-1", "PlatformOps"),
    "aggregator_gateway_headers": build_user_headers("gateway-1", "AggregatorGateway"),
    # Entity-backed roles — fallback for non-ownership tests only.
    "stall_operator_headers": build_user_headers("stall-operator-fallback", "StallOperator"),
    "brand_owner_headers": build_user_headers("brand-owner-fallback", "BrandOwner"),
}


def make_platform_ops_headers(user_id: str = "ops-1") -> dict:
    """PlatformOps (opaque)."""
    return build_user_headers(user_id, "PlatformOps")


def make_aggregator_gateway_headers(user_id: str = "gateway-1") -> dict:
    """AggregatorGateway (opaque)."""
    return build_user_headers(user_id, "AggregatorGateway")


def make_stall_operator_headers(stall_id: str) -> dict:
    """StallOperator (entity_backed:Stall). Pass the acting Stall.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(stall_id, "StallOperator")


def make_brand_owner_headers(brand_id: str) -> dict:
    """BrandOwner (entity_backed:VirtualBrand). Pass the acting VirtualBrand.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(brand_id, "BrandOwner")

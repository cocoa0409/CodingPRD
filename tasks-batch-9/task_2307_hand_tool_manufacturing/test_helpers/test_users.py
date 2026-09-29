"""Pre-built role headers for every role in the PRD.

Every request carries ``X-User-ID`` and ``X-User-Role``. For the six operator
roles the user identifier is opaque and never compared against any entity's
``id``. For the ``Claimant`` role the identifier IS the ``id`` of the acting
``Claimant`` row, so ownership-gated calls MUST use
``make_claimant_headers(claimant["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque operator roles, and for any test that
# does not exercise claimant ownership.
TEST_USERS = {
    "channel_manager_headers": build_user_headers("cm-1", "ChannelManager"),
    "production_planner_headers": build_user_headers("pp-1", "ProductionPlanner"),
    "quality_engineer_headers": build_user_headers("qe-1", "QualityEngineer"),
    "warranty_administrator_headers": build_user_headers("wa-1", "WarrantyAdministrator"),
    "brand_protection_analyst_headers": build_user_headers("bp-1", "BrandProtectionAnalyst"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallback only: the Claimant role is entity-backed, so ownership-gated
    # calls must use make_claimant_headers() with a real Claimant id.
    "claimant_headers": build_user_headers("claimant-unbound", "Claimant"),
}


def make_claimant_headers(claimant_id: str) -> dict:
    """For the Claimant role, whose X-User-ID is the id of the acting Claimant
    row. Pass the actual Claimant id whenever the call is ownership-gated."""
    return build_user_headers(claimant_id, "Claimant")


def make_channel_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChannelManager")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_quality_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityEngineer")


def make_warranty_administrator_headers(user_id: str) -> dict:
    """The acting X-User-ID is recorded as held_by_user_id on a fraud hold and
    is compared again at clear-hold and at approval, so tests that exercise the
    duty separation must pass distinct identifiers here."""
    return build_user_headers(user_id, "WarrantyAdministrator")


def make_brand_protection_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BrandProtectionAnalyst")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_headers_with_role(user_id: str, role: str) -> dict:
    """Build headers naming an arbitrary role string, including one that is not
    among the seven declared roles."""
    return build_user_headers(user_id, role)


# Headers carrying no X-User-Role at all.
NO_ROLE_HEADERS = {"Content-Type": "application/json"}

"""Pre-built role headers for every role in the PRD (§2.1).

The Grower role is entity-backed: when X-User-Role is Grower, X-User-ID must be
the id of the acting Grower entity. Ownership-gated calls MUST use
make_grower_headers(grower["id"]) with the real entity id — never the shared
fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque (non-entity-backed) roles. Multiple operator
# ids exist per role where segregation-of-duties checks compare identities.
TEST_USERS = {
    # IntegratorAdmin operators (approve vs pay segregation needs two admins).
    "admin_headers": build_user_headers("adm_1", "IntegratorAdmin"),
    "admin2_headers": build_user_headers("adm_2", "IntegratorAdmin"),
    # FieldTech operators (quote vs approve segregation needs two techs).
    "fieldtech_headers": build_user_headers("ft_1", "FieldTech"),
    "fieldtech2_headers": build_user_headers("ft_2", "FieldTech"),
    # FeedMill operator.
    "feedmill_headers": build_user_headers("fm_1", "FeedMill"),
    # TransportCoordinator operator.
    "transport_headers": build_user_headers("tc_1", "TransportCoordinator"),
    # EnvironmentalManager operators (submit identity matters for re-stamp).
    "envmgr_headers": build_user_headers("em_1", "EnvironmentalManager"),
    "envmgr2_headers": build_user_headers("em_2", "EnvironmentalManager"),
    # Grower fallback — ONLY for tests that never exercise ownership
    # (e.g., role-denial checks where any Grower identity is rejected).
    "grower_headers": build_user_headers("grower-placeholder", "Grower"),
}


def make_grower_headers(user_id: str) -> dict:
    """Headers for the entity-backed Grower role. Pass the actual Grower.id
    whenever the call is ownership-gated (mortality reports, barn washes,
    maintenance tickets, settlement disputes, grower-chain reads)."""
    return build_user_headers(user_id, "Grower")


def make_admin_headers(user_id: str) -> dict:
    """IntegratorAdmin headers with an explicit operator id (SoD pairs)."""
    return build_user_headers(user_id, "IntegratorAdmin")


def make_fieldtech_headers(user_id: str) -> dict:
    """FieldTech headers with an explicit operator id (SoD pairs)."""
    return build_user_headers(user_id, "FieldTech")


def make_transport_headers(user_id: str) -> dict:
    """TransportCoordinator headers with an explicit operator id."""
    return build_user_headers(user_id, "TransportCoordinator")


def make_envmgr_headers(user_id: str) -> dict:
    """EnvironmentalManager headers with an explicit operator id."""
    return build_user_headers(user_id, "EnvironmentalManager")

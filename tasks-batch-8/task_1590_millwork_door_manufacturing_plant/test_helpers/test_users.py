"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles are opaque: X-User-ID is never compared to any entity id.
Segregation-of-duties workflows still need distinct user ids per actor
(submitter vs approver, issuer vs applier vs verifier, reporter vs verifier),
so per-instance builders are provided for every role.
"""
from prd_bench_local_runner.testing import build_user_headers


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_architect_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Architect")


def make_production_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionLead")


def make_label_authority_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabelAuthority")


def make_qa_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QAInspector")


def make_shipping_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShippingCoordinator")


def make_any_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Any")


def role_headers(role: str, user_id: str) -> dict:
    """Build auth headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)


# Shared constants — canonical user ids used across the suite.
TEST_USERS = {
    "plant_manager_headers": make_plant_manager_headers("pm-1"),
    "estimator_headers": make_estimator_headers("est-1"),
    "architect_headers": make_architect_headers("arch-1"),
    "production_lead_headers": make_production_lead_headers("pl-1"),
    "label_authority_headers": make_label_authority_headers("la-1"),
    "qa_inspector_headers": make_qa_inspector_headers("qa-1"),
    "shipping_coordinator_headers": make_shipping_coordinator_headers("sc-1"),
    "any_headers": make_any_headers("any-1"),
}

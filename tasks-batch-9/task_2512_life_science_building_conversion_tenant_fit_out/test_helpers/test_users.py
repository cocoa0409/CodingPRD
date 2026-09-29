"""Pre-built request headers for the five roles.

`Tenant` is the one entity-backed role: a tenant caller's `X-User-ID` must be
the `id` of the acting tenant record, so tenant headers are always built from a
tenant id with :func:`make_tenant_headers`. The other four roles carry opaque
operator identifiers, and several distinct operator identities are provided per
role because the separation-of-duties rules compare those identifiers against
each other.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers. Distinct ids within one role exist so that a test
# can author with one operator and act with another.
USER_LANDLORD_ASSET_MANAGER = "u_landlord_asset_mgr"
USER_LANDLORD_NEGOTIATOR = "u_landlord_negotiator"
USER_LANDLORD_SIGNER = "u_landlord_signer"
USER_LANDLORD_OPS = "u_landlord_ops"
USER_ENGINEER_OF_RECORD = "u_engineer_of_record"
USER_ENGINEER_REVIEWER = "u_engineer_reviewer"
USER_AHJ_OFFICER = "u_ahj_officer"
USER_AHJ_OFFICER_ALT = "u_ahj_officer_alt"
USER_CX_AGENT = "u_cx_agent"
USER_CX_TECH = "u_cx_tech"
USER_CX_WITNESS = "u_cx_witness"

LANDLORD_HEADERS = build_user_headers(
    USER_LANDLORD_ASSET_MANAGER, UserRole.LANDLORD_ASSET_MANAGER.value
)
LANDLORD_NEGOTIATOR_HEADERS = build_user_headers(
    USER_LANDLORD_NEGOTIATOR, UserRole.LANDLORD_ASSET_MANAGER.value
)
LANDLORD_SIGNER_HEADERS = build_user_headers(
    USER_LANDLORD_SIGNER, UserRole.LANDLORD_ASSET_MANAGER.value
)
LANDLORD_OPS_HEADERS = build_user_headers(
    USER_LANDLORD_OPS, UserRole.LANDLORD_ASSET_MANAGER.value
)
ENGINEER_HEADERS = build_user_headers(
    USER_ENGINEER_OF_RECORD, UserRole.BASE_BUILDING_ENGINEER.value
)
ENGINEER_REVIEWER_HEADERS = build_user_headers(
    USER_ENGINEER_REVIEWER, UserRole.BASE_BUILDING_ENGINEER.value
)
AHJ_HEADERS = build_user_headers(USER_AHJ_OFFICER, UserRole.AHJ_PERMIT_OFFICER.value)
AHJ_ALT_HEADERS = build_user_headers(
    USER_AHJ_OFFICER_ALT, UserRole.AHJ_PERMIT_OFFICER.value
)
CX_AGENT_HEADERS = build_user_headers(USER_CX_AGENT, UserRole.COMMISSIONING_AGENT.value)
CX_WITNESS_HEADERS = build_user_headers(
    USER_CX_WITNESS, UserRole.COMMISSIONING_AGENT.value
)


def make_tenant_headers(tenant_id: str) -> Dict[str, str]:
    """Headers for the tenant record identified by ``tenant_id``.

    Ownership checks compare a resource's `tenant_id`, reached through the lease
    that owns it, against `X-User-ID`, so the acting tenant's own id must be
    threaded through rather than a shared constant.
    """
    return build_user_headers(tenant_id, UserRole.TENANT.value)


def make_landlord_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary asset-management operator identity."""
    return build_user_headers(user_id, UserRole.LANDLORD_ASSET_MANAGER.value)


def make_engineer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary base-building engineer identity."""
    return build_user_headers(user_id, UserRole.BASE_BUILDING_ENGINEER.value)


def make_ahj_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary permit-officer identity."""
    return build_user_headers(user_id, UserRole.AHJ_PERMIT_OFFICER.value)


def make_commissioning_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary commissioning-agent identity."""
    return build_user_headers(user_id, UserRole.COMMISSIONING_AGENT.value)


TEST_USERS = {
    "landlord_headers": LANDLORD_HEADERS,
    "landlord_negotiator_headers": LANDLORD_NEGOTIATOR_HEADERS,
    "landlord_signer_headers": LANDLORD_SIGNER_HEADERS,
    "landlord_ops_headers": LANDLORD_OPS_HEADERS,
    "engineer_headers": ENGINEER_HEADERS,
    "engineer_reviewer_headers": ENGINEER_REVIEWER_HEADERS,
    "ahj_headers": AHJ_HEADERS,
    "ahj_alt_headers": AHJ_ALT_HEADERS,
    "cx_agent_headers": CX_AGENT_HEADERS,
    "cx_witness_headers": CX_WITNESS_HEADERS,
}

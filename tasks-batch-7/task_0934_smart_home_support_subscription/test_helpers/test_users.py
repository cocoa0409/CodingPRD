"""Pre-built role headers for every role in the PRD.

Four roles are entity-backed. ``Owner``, ``Member`` and ``BillingAdmin`` carry
the id of the acting HouseholdMember row in ``X-User-ID``; ``Technician``
carries the id of the acting Technician row. Every ownership-gated call MUST
use the per-instance builder below with the real row id — the shared constants
are only safe for calls whose outcome does not depend on the caller owning the
subject row (a missing-header test, a 404 probe, or a call by one of the two
opaque operator roles).

``SupportAgent`` and ``PlatformAdmin`` are opaque operator identities: the
server records the identifier but never compares it to any row's id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers, spelled once so assertions can compare them.
AGENT_USER_ID = "agent-1"
SECOND_AGENT_USER_ID = "agent-2"
PLATFORM_ADMIN_USER_ID = "platform-1"
TECH_OPERATOR_USER_ID = "tech-op-1"

# A placeholder id used only where the identity is deliberately unresolvable.
PLACEHOLDER_MEMBER_ID = "00000000-0000-4000-8000-000000000001"

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "support_agent_headers": build_user_headers(AGENT_USER_ID, "SupportAgent"),
    "second_support_agent_headers": build_user_headers(SECOND_AGENT_USER_ID, "SupportAgent"),
    # Entity-backed roles — shared constants are fallbacks for calls that are
    # NOT ownership-gated (e.g. a 404 probe). Never use them for a call whose
    # success depends on the caller owning the target row.
    "owner_headers": build_user_headers(PLACEHOLDER_MEMBER_ID, "Owner"),
    "member_headers": build_user_headers(PLACEHOLDER_MEMBER_ID, "Member"),
    "billing_admin_headers": build_user_headers(PLACEHOLDER_MEMBER_ID, "BillingAdmin"),
    "technician_headers": build_user_headers(PLACEHOLDER_MEMBER_ID, "Technician"),
}

# A request that carries no role header at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_owner_headers(member_id: str) -> dict:
    """Owner is entity_backed on HouseholdMember: pass the real member id."""
    return build_user_headers(member_id, "Owner")


def make_member_headers(member_id: str) -> dict:
    """Member is entity_backed on HouseholdMember: pass the real member id."""
    return build_user_headers(member_id, "Member")


def make_billing_admin_headers(member_id: str) -> dict:
    """BillingAdmin is entity_backed on HouseholdMember: pass the real member id."""
    return build_user_headers(member_id, "BillingAdmin")


def make_technician_headers(technician_id: str) -> dict:
    """Technician is entity_backed on Technician: pass the real technician id."""
    return build_user_headers(technician_id, "Technician")


def make_support_agent_headers(user_id: str = AGENT_USER_ID) -> dict:
    """SupportAgent acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "SupportAgent")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    """PlatformAdmin acting under a specific opaque operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")

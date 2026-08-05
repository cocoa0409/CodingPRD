"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin, CommunityManager, ComplianceOfficer, FinanceAdmin are `opaque`
roles: X-User-ID is a free operator string never compared to any entity id, so
their shared constants (and per-id builders) are the canonical form.

Host and Member are `entity_backed`: X-User-ID must equal the acting entity's
id on every ownership-gated write, so tests MUST thread the real entity id
through make_host_headers()/make_member_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


# ---- opaque-role builders (X-User-ID is an operator string) --------------
def admin_headers(user_id: str = "platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def manager_headers(user_id: str = "cm-1") -> dict:
    return build_user_headers(user_id, "CommunityManager")


def compliance_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def finance_headers(user_id: str = "fa-1") -> dict:
    return build_user_headers(user_id, "FinanceAdmin")


# ---- entity_backed-role builders (X-User-ID is the entity id) ------------
def make_host_headers(user_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id as user_id."""
    return build_user_headers(user_id, "Host")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id."""
    return build_user_headers(user_id, "Member")


# ---- shared constants (non-ownership tests / opaque roles) ---------------
TEST_USERS = {
    "admin_headers": admin_headers(),
    "manager_headers": manager_headers(),
    "compliance_headers": compliance_headers(),
    "compliance2_headers": compliance_headers("co-2"),
    "finance_headers": finance_headers(),
    "finance2_headers": finance_headers("fa-2"),
    # entity_backed shared constants: fallback only for tests that do NOT
    # exercise ownership (e.g. 404-on-missing-resource).
    "host_headers": build_user_headers("host-shared-1", "Host"),
    "member_headers": build_user_headers("member-shared-1", "Member"),
}

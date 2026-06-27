"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use an opaque identity model: X-User-ID is never compared to an entity id
for ownership. The single exception is the service-ticket owner check, where the FieldTech's
X-User-ID is recorded as assigned_tech_id and later resolve/reopen are gated on the acting
tech matching that recorded value. For that reason FieldTech gets per-id builders so a test
can act as two distinct techs (the owner vs a non-owner).
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable per-tech ids used by ticket-ownership scenarios.
TECH_T1 = "tech-T1"
TECH_T2 = "tech-T2"

# Shared constants — the canonical form for all five opaque roles. Safe everywhere except
# where a ticket-ownership check distinguishes two field techs (use make_field_tech_headers).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "vault_controller_headers": build_user_headers("vault-1", "VaultController"),
    "field_tech_headers": build_user_headers(TECH_T1, "FieldTech"),
    "settlement_officer_headers": build_user_headers("settle-1", "SettlementOfficer"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # Anonymous (no role) is represented by empty headers for the unauthenticated test.
    "anonymous_headers": {},
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_vault_controller_headers(user_id: str = "vault-1") -> dict:
    return build_user_headers(user_id, "VaultController")


def make_field_tech_headers(user_id: str = TECH_T1) -> dict:
    """For the FieldTech role. Pass an explicit tech id (e.g. TECH_T1 / TECH_T2) when a
    service-ticket ownership check must distinguish the acknowledging tech from another."""
    return build_user_headers(user_id, "FieldTech")


def make_settlement_officer_headers(user_id: str = "settle-1") -> dict:
    return build_user_headers(user_id, "SettlementOfficer")


def make_compliance_officer_headers(user_id: str = "compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")

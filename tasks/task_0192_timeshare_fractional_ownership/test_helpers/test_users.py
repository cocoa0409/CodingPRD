"""Pre-built role headers for every role in the PRD.

The PRD (§2.1) recognizes exactly five roles. Four of them (ResortManager,
ResaleAgent, ComplianceOfficer, System) carry an opaque X-User-ID not matched
against any entity, so a shared constant is the canonical form. Owner is
entity-backed: an Owner may act only on resources resolving to a contract whose
owner_id equals the caller's X-User-ID, so ownership-gated Owner calls MUST use
make_owner_headers(owner_id) with the real Owner.id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "resort_manager_headers": build_user_headers("test-resort-manager-1", "ResortManager"),
    "resale_agent_headers": build_user_headers("test-resale-agent-1", "ResaleAgent"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "system_headers": build_user_headers("test-system-1", "System"),
    # Owner is entity_backed: this shared constant is a fallback for tests that
    # do NOT exercise ownership (e.g. 403-forbidden-role probes). Ownership-gated
    # Owner calls must use make_owner_headers(owner_id) instead.
    "owner_headers": build_user_headers("test-owner-fallback-1", "Owner"),
}


def make_owner_headers(user_id: str) -> dict:
    """For the Owner role (entity_backed:Owner). Pass the actual Owner.id as
    user_id whenever the call is ownership-gated (reservation create/confirm/
    cancel/deposit-exchange, contract rescind, exchange redeem/recall, resale
    rescind, contract payment)."""
    return build_user_headers(user_id, "Owner")


def make_resort_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ResortManager")


def make_resale_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ResaleAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")

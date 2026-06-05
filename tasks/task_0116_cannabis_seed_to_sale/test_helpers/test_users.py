"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, all seven roles carry an OPAQUE identity: X-User-ID is an
operator identifier that is never compared against any persisted entity's id.
The shared constants below are therefore the canonical form for every role.

Two segregation-of-duties checks (PRD §2.6) compare the acting X-User-ID
against a previously recorded one (the QALabUser who recorded a PASS result,
the InventoryAuditor who placed a hold). Tests that exercise those checks must
control the exact X-User-ID, so a builder `make_headers(role, user_id)` is
provided to mint headers with a specific operator id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque-role headers, the canonical form for every role.
TEST_USERS = {
    "state_regulator_headers": build_user_headers("reg-1", "StateRegulator"),
    "cultivator_headers": build_user_headers("cult-1", "Cultivator"),
    "qa_lab_headers": build_user_headers("qa-1", "QALabUser"),
    "compliance_manager_headers": build_user_headers("cm-1", "ComplianceManager"),
    "distribution_agent_headers": build_user_headers("dist-1", "DistributionAgent"),
    "budtender_headers": build_user_headers("bud-1", "Budtender"),
    "inventory_auditor_headers": build_user_headers("audit-1", "InventoryAuditor"),
}


def make_headers(role: str, user_id: str) -> dict:
    """Mint request headers for `role` with an explicit opaque X-User-ID.

    Use whenever a test must pin the acting operator id — e.g. to make the
    releasing ComplianceManager share (or differ from) the QALabUser id that
    recorded a PASS result, or the auditor id that placed a hold.
    """
    return build_user_headers(user_id, role)

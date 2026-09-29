"""Pre-built role headers for the six roles of PRD §2.1.

`NetworkPlanner` and `PartnerCarrier` are entity-backed: their `X-User-ID` is
the `id` of the acting `Carrier`, so any ownership-gated call must use the
per-instance builder with that carrier's real id. The other four roles carry an
opaque operator identifier that is never compared to an entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
SLOT_COORDINATOR_USER_ID = "usr-coord-1"
COMPLIANCE_OFFICER_USER_ID = "usr-comp-1"
FILING_AGENT_USER_ID = "usr-file-1"
SYSTEM_ADMIN_USER_ID = "usr-admin-1"

# A second filing agent, for the segregation-of-duties pairing.
SECOND_FILING_AGENT_USER_ID = "usr-file-2"
SECOND_SLOT_COORDINATOR_USER_ID = "usr-coord-2"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "slot_coordinator_headers": build_user_headers(
        SLOT_COORDINATOR_USER_ID, "SlotCoordinator"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "filing_agent_headers": build_user_headers(FILING_AGENT_USER_ID, "FilingAgent"),
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_USER_ID, "SystemAdmin"),
    "second_filing_agent_headers": build_user_headers(
        SECOND_FILING_AGENT_USER_ID, "FilingAgent"
    ),
    "second_slot_coordinator_headers": build_user_headers(
        SECOND_SLOT_COORDINATOR_USER_ID, "SlotCoordinator"
    ),
    # Entity-backed roles — these fallbacks are only safe for calls that never
    # reach an ownership check (unauthenticated probes, role-admission probes,
    # 404 probes on ids that do not resolve).
    "network_planner_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000aa", "NetworkPlanner"
    ),
    "partner_carrier_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000bb", "PartnerCarrier"
    ),
}


def make_network_planner_headers(carrier_id: str) -> dict:
    """For `NetworkPlanner` (entity-backed on Carrier). Pass the acting
    carrier's own `id`."""
    return build_user_headers(carrier_id, "NetworkPlanner")


def make_partner_carrier_headers(carrier_id: str) -> dict:
    """For `PartnerCarrier` (entity-backed on Carrier). Pass the counterparty
    carrier's own `id`."""
    return build_user_headers(carrier_id, "PartnerCarrier")


def make_slot_coordinator_headers(user_id: str = SLOT_COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "SlotCoordinator")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_filing_agent_headers(user_id: str = FILING_AGENT_USER_ID) -> dict:
    return build_user_headers(user_id, "FilingAgent")


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity/role pair, for role-admission and identity probes."""
    return build_user_headers(user_id, role)

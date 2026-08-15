"""Pre-built role headers for every role in the PRD (§2.1).

OperationsManager and BillingClerk are opaque identities: X-User-ID is not
tied to any persisted entity. EntrySupervisor, Attendant, RescueTeamLead, and
SafetyOfficer are entity-backed by Personnel: X-User-ID is the acting
Personnel row's id, and the row must be ACTIVE and hold the role's required
qualification. Ownership/identity-gated calls MUST use the per-instance
builders with the real Personnel id; the shared constants are fallbacks only
for tests that do not exercise identity resolution (malformed-payload 400s,
wrong-role 403s, 404s).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed identity resolution.
TEST_USERS = {
    "operations_manager_headers": build_user_headers(
        "test-ops-manager-1", "OperationsManager"),
    "billing_clerk_headers": build_user_headers(
        "test-billing-clerk-1", "BillingClerk"),
    # entity_backed roles: shared constants are fallbacks for non-identity
    # tests only — a bare string id never resolves to an ACTIVE Personnel row.
    "entry_supervisor_headers": build_user_headers(
        "test-supervisor-1", "EntrySupervisor"),
    "attendant_headers": build_user_headers("test-attendant-1", "Attendant"),
    "rescue_team_lead_headers": build_user_headers(
        "test-rescue-lead-1", "RescueTeamLead"),
    "safety_officer_headers": build_user_headers(
        "test-safety-officer-1", "SafetyOfficer"),
}


def make_operations_manager_headers(user_id: str = "test-ops-manager-1") -> dict:
    """OperationsManager is opaque; any identifier works."""
    return build_user_headers(user_id, "OperationsManager")


def make_billing_clerk_headers(user_id: str = "test-billing-clerk-1") -> dict:
    """BillingClerk is opaque; any identifier works."""
    return build_user_headers(user_id, "BillingClerk")


def make_entry_supervisor_headers(personnel_id: str) -> dict:
    """For EntrySupervisor (entity_backed:Personnel). Pass the acting
    Personnel.id — the row must be ACTIVE and hold ENTRY_SUPERVISOR."""
    return build_user_headers(personnel_id, "EntrySupervisor")


def make_attendant_headers(personnel_id: str) -> dict:
    """For Attendant (entity_backed:Personnel). Pass the acting Personnel.id —
    the row must be ACTIVE and hold ATTENDANT."""
    return build_user_headers(personnel_id, "Attendant")


def make_rescue_team_lead_headers(personnel_id: str) -> dict:
    """For RescueTeamLead (entity_backed:Personnel). Pass the acting
    Personnel.id — the row must be ACTIVE and hold RESCUE_LEAD."""
    return build_user_headers(personnel_id, "RescueTeamLead")


def make_safety_officer_headers(personnel_id: str) -> dict:
    """For SafetyOfficer (entity_backed:Personnel). Pass the acting
    Personnel.id — the row must be ACTIVE and hold SAFETY_OFFICER."""
    return build_user_headers(personnel_id, "SafetyOfficer")

"""Pre-built role headers for every role in the PRD (§2.1).

Five roles: Resident, ParkingClerk, PermitSupervisor, EnforcementOfficer,
Anonymous.

Only Resident is entity-backed: its X-User-ID must equal the acting Household's
id, and ownership checks compare that id against a resource's owning household.
Every ownership-gated Resident call MUST use make_resident_headers(household_id)
with the real household id.

ParkingClerk, PermitSupervisor and Anonymous are opaque (X-User-ID never
compared to an entity id), so shared constants suffice. EnforcementOfficer is
also opaque, but its recorded X-User-ID matters for the segregation-of-duties
rule on citation adjudication (issuing officer != adjudicating officer), so
make_officer_headers(user_id) is provided to distinguish two officers.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constants are the canonical form.
    "parking_clerk_headers": build_user_headers("test-clerk-1", "ParkingClerk"),
    "permit_supervisor_headers": build_user_headers("test-supervisor-1", "PermitSupervisor"),
    "enforcement_officer_headers": build_user_headers("officer-1", "EnforcementOfficer"),
    "enforcement_officer_2_headers": build_user_headers("officer-2", "EnforcementOfficer"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed Resident: shared constant is a fallback for non-ownership
    # tests only (e.g. RBAC-denied calls that never reach an ownership check).
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
}


def make_resident_headers(household_id: str) -> dict:
    """For Resident (entity_backed:Household). Pass the real Household.id as the
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(household_id, "Resident")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """For EnforcementOfficer. The X-User-ID is recorded as issuing_officer_id /
    adjudicator_id and drives the segregation-of-duties comparison."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "ParkingClerk")


def make_supervisor_headers(user_id: str = "test-supervisor-1") -> dict:
    return build_user_headers(user_id, "PermitSupervisor")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")

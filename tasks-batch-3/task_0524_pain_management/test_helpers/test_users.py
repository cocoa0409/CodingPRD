"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (Prescriber, ComplianceOfficer): their X-User-ID must be
the id of the acting Provider. For those roles, ownership-gated calls MUST use the
per-instance builders below with the actual Provider.id. The three opaque roles
(ClinicAdmin, IntakeCoordinator, PriorAuthClerk) use shared-constant identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership tests of entity-backed roles.
TEST_USERS = {
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "prior_auth_clerk_headers": build_user_headers("test-pa-clerk-1", "PriorAuthClerk"),
    # Entity-backed roles: these shared constants are fallbacks for non-ownership tests only
    # (e.g. permission-denied checks). Ownership-gated calls must use the builders below.
    "prescriber_headers": build_user_headers("test-prescriber-1", "Prescriber"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
}


# Per-instance builders — required for the entity-backed roles.
def make_prescriber_headers(provider_id: str) -> dict:
    """For Prescriber (entity_backed:Provider). Pass the acting Provider.id whose
    role_kind is PRESCRIBER, so ownership checks (e.g. agreement counter-sign) resolve."""
    return build_user_headers(provider_id, "Prescriber")


def make_compliance_officer_headers(provider_id: str) -> dict:
    """For ComplianceOfficer (entity_backed:Provider). Pass the acting Provider.id whose
    role_kind is COMPLIANCE_OFFICER, so segregation-of-duties identity resolves."""
    return build_user_headers(provider_id, "ComplianceOfficer")


def make_clinic_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ClinicAdmin")


def make_intake_coordinator_headers(user_id: str = "test-intake-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_prior_auth_clerk_headers(user_id: str = "test-pa-clerk-1") -> dict:
    return build_user_headers(user_id, "PriorAuthClerk")

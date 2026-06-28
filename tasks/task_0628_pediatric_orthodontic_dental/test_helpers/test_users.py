"""Pre-built role headers for every role in the PRD.

Two roles are entity_backed and therefore need per-instance builders:
  - Orthodontist (entity_backed:Provider) - X-User-ID is the Provider's
    provider_user_id; ownership checks compare resources' provider FK to it.
  - Guardian (entity_backed:FamilyAccount) - X-User-ID is the guardian_user_id
    stamped on the owning FamilyAccount.

FrontDesk, BillingSpecialist and ClinicAdmin are opaque operator roles, so the
shared constants below are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants - safe for opaque roles, and for tests that do not exercise
# entity ownership of the acting role.
TEST_USERS = {
    "frontdesk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "billing_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
    # Fallbacks for entity_backed roles - only for non-ownership tests.
    "orthodontist_headers": build_user_headers("test-ortho-1", "Orthodontist"),
    "guardian_headers": build_user_headers("test-guardian-1", "Guardian"),
}


def make_orthodontist_headers(provider_user_id: str) -> dict:
    """For Orthodontist (entity_backed:Provider). Pass the Provider's
    provider_user_id whenever the call is ownership-gated."""
    return build_user_headers(provider_user_id, "Orthodontist")


def make_guardian_headers(guardian_user_id: str) -> dict:
    """For Guardian (entity_backed:FamilyAccount). Pass the owning
    FamilyAccount's guardian_user_id whenever the call is ownership-gated."""
    return build_user_headers(guardian_user_id, "Guardian")


def make_frontdesk_headers(user_id: str = "test-frontdesk-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ClinicAdmin")

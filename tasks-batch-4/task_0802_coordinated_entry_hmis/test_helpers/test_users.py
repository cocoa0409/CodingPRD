"""Pre-built role headers for every role in the PRD.

Identity model (PRD §2.1):
  - IntakeSpecialist -> X-User-ID is an opaque operator id, not tied to any entity.
  - ShelterManager   -> X-User-ID is an opaque operator id, not tied to any entity.
  - HMISAdmin        -> X-User-ID is an opaque operator id, not tied to any entity.
  - HousingNavigator -> X-User-ID is the id of the acting HousingNavigator entity
                        (entity_backed); ownership checks compare a resource's
                        navigator_id to X-User-ID.

The entity_backed HousingNavigator role MUST use the per-instance builder below with the
real HousingNavigator.id whenever a call is ownership-gated (referral accept/decline/enroll).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque roles, and for the navigator only in tests whose
# success does NOT depend on the caller owning the referral's navigator.
TEST_USERS = {
    "intake_headers": build_user_headers("test-intake-1", "IntakeSpecialist"),
    "shelter_manager_headers": build_user_headers("test-shelter-1", "ShelterManager"),
    "navigator_headers": build_user_headers("test-navigator-1", "HousingNavigator"),
    "hmis_admin_headers": build_user_headers("test-admin-1", "HMISAdmin"),
}


# Per-instance builder — required for the entity_backed HousingNavigator role.
def make_navigator_headers(user_id: str) -> dict:
    """For HousingNavigator (entity_backed:HousingNavigator). Pass the acting
    HousingNavigator.id as user_id whenever the call is ownership-gated (referral
    accept/decline/enroll compare navigator_id to X-User-ID)."""
    return build_user_headers(user_id, "HousingNavigator")

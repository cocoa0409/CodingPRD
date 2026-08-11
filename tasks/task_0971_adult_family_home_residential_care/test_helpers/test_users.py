"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers
from .constants import PROVIDER_1_USER_ID, PROVIDER_2_USER_ID

# Shared constants — safe for opaque roles (Provider, Nurse), and for tests
# that don't exercise entity-backed ownership.
TEST_USERS = {
    # opaque role: admission creator side of segregation of duties
    "provider_headers": build_user_headers(PROVIDER_1_USER_ID, "Provider"),
    # opaque role: admission approver side of segregation of duties
    "provider2_headers": build_user_headers(PROVIDER_2_USER_ID, "Provider"),
    # opaque role: canonical form for the assessing nurse
    "nurse_headers": build_user_headers("nurse-1", "Nurse"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    "caregiver_headers": build_user_headers("test-caregiver-1", "CaregiverRole"),
}


def make_provider_headers(user_id: str) -> dict:
    """Provider (opaque identity). Use a distinct user_id whenever segregation
    of duties requires a different operator than the admission's creator."""
    return build_user_headers(user_id, "Provider")


def make_nurse_headers(user_id: str) -> dict:
    """Nurse (opaque identity)."""
    return build_user_headers(user_id, "Nurse")


def make_caregiver_headers(user_id: str) -> dict:
    """CaregiverRole (entity_backed: Caregiver). Pass the actual Caregiver.id as
    user_id whenever the call is ownership-gated (e.g., on-shift care logging)."""
    return build_user_headers(user_id, "CaregiverRole")

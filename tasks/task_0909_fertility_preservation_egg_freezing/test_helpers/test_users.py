"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Coordinator, BillingAdmin, PlatformAdmin),
# and for tests that do not exercise entity ownership.
TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-1", "Coordinator"),
    "billing_admin_headers": build_user_headers("billing-1", "BillingAdmin"),
    "platform_admin_headers": build_user_headers("platform-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only
    # (e.g. RBAC-denial or 404 tests where no real entity id is needed).
    "physician_headers": build_user_headers("physician-1", "Physician"),
    "embryologist_headers": build_user_headers("embryologist-1", "Embryologist"),
    "patient_headers": build_user_headers("patient-1", "Patient"),
}


# Per-instance builders — required for entity_backed roles whenever the call is
# identity/ownership-gated (Physician/Embryologist == Provider.id; Patient == Patient.id).
def make_physician_headers(provider_id: str) -> dict:
    """For a Physician acting as Provider `provider_id` (records requester/authorizer id)."""
    return build_user_headers(provider_id, "Physician")


def make_embryologist_headers(provider_id: str) -> dict:
    """For an Embryologist acting as Provider `provider_id`."""
    return build_user_headers(provider_id, "Embryologist")


def make_patient_headers(patient_id: str) -> dict:
    """For a Patient acting on their own resources (directive create/revoke ownership)."""
    return build_user_headers(patient_id, "Patient")


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    return build_user_headers(user_id, "Coordinator")


def make_billing_admin_headers(user_id: str = "billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")


def make_platform_admin_headers(user_id: str = "platform-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")

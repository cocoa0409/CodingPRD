"""Pre-built caller headers for every role the PRD declares.

`Patient`, `Provider`, `Coach` and `PharmacyOperator` are entity-backed: their
`X-User-ID` must be the id of a real row, so ownership-gated calls MUST use the
matching per-instance builder. `BillingAdmin` and `PlatformAdmin` are opaque,
so the shared constants below are the canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the identifier is never matched against a row.
    "platform_admin_headers": build_user_headers("ops-platform-admin-1", "PlatformAdmin"),
    "billing_admin_headers": build_user_headers("ops-billing-admin-1", "BillingAdmin"),
    # Entity-backed roles — shared constants are safe only where ownership is
    # not exercised (unauthenticated / unauthorized / not-found probes).
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
    "pharmacy_operator_headers": build_user_headers("test-pharmacy-1", "PharmacyOperator"),
}

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_patient_headers(patient_id: str) -> dict:
    """Headers for the acting member; pass the real Patient id."""
    return build_user_headers(patient_id, "Patient")


def make_provider_headers(provider_id: str) -> dict:
    """Headers for the acting clinician; pass the real Provider id."""
    return build_user_headers(provider_id, "Provider")


def make_coach_headers(provider_id: str) -> dict:
    """Headers for the acting coach; pass the id of a Provider row whose
    provider_type is COACH."""
    return build_user_headers(provider_id, "Coach")


def make_pharmacy_operator_headers(pharmacy_id: str) -> dict:
    """Headers for the acting dispensing pharmacy; pass the real Pharmacy id."""
    return build_user_headers(pharmacy_id, "PharmacyOperator")


def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


def billing_admin_headers() -> dict:
    return TEST_USERS["billing_admin_headers"]

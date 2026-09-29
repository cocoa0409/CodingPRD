"""Pre-built caller headers for every role in the PRD.

`Customer` and `Prescriber` are entity-backed: `X-User-ID` must equal the id of
the addressed Customer / Prescriber row, so ownership-gated calls MUST use the
per-instance builders below. The three remaining roles are opaque operator
identities, for which the shared constants are the canonical form.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import ADMIN_ROOT, CO_ALPHA, CO_BRAVO, FO_ONE

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "admin_headers": build_user_headers(ADMIN_ROOT, "PlatformAdmin"),
    "compliance_headers": build_user_headers(CO_ALPHA, "ComplianceOfficer"),
    "compliance_second_headers": build_user_headers(CO_BRAVO, "ComplianceOfficer"),
    "fulfillment_headers": build_user_headers(FO_ONE, "FulfillmentOperator"),
    # Entity-backed roles — these shared constants are ONLY safe for tests that
    # do not exercise ownership (missing-payload, unknown-resource, role-gate).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "prescriber_headers": build_user_headers("test-prescriber-1", "Prescriber"),
}


def make_customer_headers(user_id: str) -> dict:
    """Headers for the Customer role. Pass the real Customer id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_prescriber_headers(user_id: str) -> dict:
    """Headers for the Prescriber role. Pass the real Prescriber id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Prescriber")


def make_compliance_headers(user_id: str) -> dict:
    """Headers for an arbitrary ComplianceOfficer operator id — used by the
    two-person workflows, where the two halves need distinct ids."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_fulfillment_headers(user_id: str) -> dict:
    """Headers for an arbitrary FulfillmentOperator operator id."""
    return build_user_headers(user_id, "FulfillmentOperator")


def make_admin_headers(user_id: str) -> dict:
    """Headers for an arbitrary PlatformAdmin operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


ADMIN_HEADERS = TEST_USERS["admin_headers"]
CO_ALPHA_HEADERS = TEST_USERS["compliance_headers"]
CO_BRAVO_HEADERS = TEST_USERS["compliance_second_headers"]
FO_HEADERS = TEST_USERS["fulfillment_headers"]

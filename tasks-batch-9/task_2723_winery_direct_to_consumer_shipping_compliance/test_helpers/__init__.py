"""Test infrastructure for the Winery DTC Shipping Compliance API.

Importing this package registers the error_id to HTTP status mapping of PRD §5
with the framework validators.
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from .api_client import ApiClient, DtcApiClient
from .assertions import (
    assert_canonical_order_money,
    assert_cents,
    assert_charge_chain,
    assert_immutable_identity,
    assert_instant_equals,
    assert_ledger_entry,
    assert_ledger_sums_to,
    assert_liters,
    assert_order_dimensions,
    assert_rejection,
    assert_request_id,
    assert_system_timestamp,
    assert_tracking_number,
    assert_versioned_identity,
    canonical_instant,
)
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_ERRORS
from .test_users import (
    ADMIN,
    CARRIER,
    OFFICER_A,
    OFFICER_B,
    TEST_USERS,
    make_carrier_headers,
    make_consumer_headers,
    make_officer_headers,
    make_winery_operator_headers,
)

__all__ = [
    "ApiClient",
    "DtcApiClient",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_ERRORS",
    "TEST_USERS",
    "ADMIN",
    "OFFICER_A",
    "OFFICER_B",
    "CARRIER",
    "make_winery_operator_headers",
    "make_consumer_headers",
    "make_officer_headers",
    "make_carrier_headers",
    "assert_canonical_order_money",
    "assert_cents",
    "assert_charge_chain",
    "assert_immutable_identity",
    "assert_instant_equals",
    "assert_ledger_entry",
    "assert_ledger_sums_to",
    "assert_liters",
    "assert_order_dimensions",
    "assert_rejection",
    "assert_request_id",
    "assert_system_timestamp",
    "assert_tracking_number",
    "assert_versioned_identity",
    "canonical_instant",
]

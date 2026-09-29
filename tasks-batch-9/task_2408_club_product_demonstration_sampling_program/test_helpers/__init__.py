"""Test helpers for the Club Demo Sampling Program API.

Importing this package registers the error_id -> HTTP status mapping with the
shared validators, so ``validate_error`` cross-checks the status code of every
rejection without each test having to name it.
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_cents,
    assert_common_fields,
    assert_created_at_ascending,
    assert_created_at_descending,
    assert_decimal2,
    assert_event_dimensions,
    assert_ledger_row_fields,
    assert_line_type_order,
    assert_subtotal_is_sum_of_lines,
    find_row,
    line_amounts_by_type,
)
from .test_users import (
    ADMIN_BILLING_HEADERS,
    ADMIN_BILLING_USER_ID,
    ADMIN_CONTROLLER_HEADERS,
    ADMIN_CONTROLLER_USER_ID,
    ADMIN_HQ_HEADERS,
    ADMIN_HQ_USER_ID,
    STAFF_OPS_HEADERS,
    STAFF_OPS_USER_ID,
    TEST_USERS,
    make_club_headers,
    make_demonstrator_headers,
    make_manufacturer_headers,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "ADMIN_HQ_USER_ID",
    "ADMIN_BILLING_USER_ID",
    "ADMIN_CONTROLLER_USER_ID",
    "STAFF_OPS_USER_ID",
    "ADMIN_HQ_HEADERS",
    "ADMIN_BILLING_HEADERS",
    "ADMIN_CONTROLLER_HEADERS",
    "STAFF_OPS_HEADERS",
    "make_manufacturer_headers",
    "make_club_headers",
    "make_demonstrator_headers",
    "assert_cents",
    "assert_common_fields",
    "assert_created_at_ascending",
    "assert_created_at_descending",
    "assert_decimal2",
    "assert_event_dimensions",
    "assert_ledger_row_fields",
    "assert_line_type_order",
    "assert_subtotal_is_sum_of_lines",
    "find_row",
    "line_amounts_by_type",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]

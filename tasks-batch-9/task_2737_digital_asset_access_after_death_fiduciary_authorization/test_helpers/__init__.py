"""
Test infrastructure for the Digital Estate Fiduciary Access API.

Re-exports the pieces test modules need most often so a test file can pull its
whole toolkit from one place.
"""

from . import assertions, factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_common_fields,
    assert_created,
    assert_created_at_ascending,
    assert_date_only,
    assert_envelope_array,
    assert_envelope_object,
    assert_estate_value_identity,
    assert_fields,
    assert_integer_cents,
    assert_inventory_counter_identity,
    assert_not_null_fields,
    assert_null_fields,
    assert_ok,
    assert_page,
    assert_refund_recovered_identity,
    assert_utc_timestamp,
)
from .fixtures import EstateContext
from .test_users import (
    COURT_REGISTRAR_HEADERS,
    ESTATE_ADMIN_HEADERS,
    TEST_USERS,
    make_court_registrar_headers,
    make_estate_admin_headers,
    make_fiduciary_headers,
    make_headers,
    make_platform_compliance_headers,
    make_unknown_role_headers,
)

__all__ = [
    "ApiClient",
    "api_client",
    "TEST_USERS",
    "EstateContext",
    "ERROR_HTTP_STATUS",
    "COURT_REGISTRAR_HEADERS",
    "ESTATE_ADMIN_HEADERS",
    "assertions",
    "factories",
    "fixtures",
    "assert_common_fields",
    "assert_created",
    "assert_created_at_ascending",
    "assert_date_only",
    "assert_envelope_array",
    "assert_envelope_object",
    "assert_estate_value_identity",
    "assert_fields",
    "assert_integer_cents",
    "assert_inventory_counter_identity",
    "assert_not_null_fields",
    "assert_null_fields",
    "assert_ok",
    "assert_page",
    "assert_refund_recovered_identity",
    "assert_utc_timestamp",
    "make_court_registrar_headers",
    "make_estate_admin_headers",
    "make_fiduciary_headers",
    "make_headers",
    "make_platform_compliance_headers",
    "make_unknown_role_headers",
]

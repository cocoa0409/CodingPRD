"""
Test infrastructure for the Qualified Opportunity Fund compliance API.

Importing this package registers the error_id -> HTTP status map with the
framework validators, so `validate_error(response, ApiErrorId.X)` cross-checks
the status without the test naming it.
"""

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_asset_test_measurement,
    assert_bare_uuid,
    assert_business_test_prongs,
    assert_common_fields,
    assert_distinct_measurer_and_certifier,
    assert_fund_aggregates,
    assert_fund_state,
    assert_gain_dollars_conserved,
    assert_ids_unique,
    assert_iso_timestamp,
    assert_ledger_fields,
    assert_money,
    assert_money_precision,
    assert_noncompliance_months_conserved,
    assert_pagination_meta,
    assert_percent,
    assert_percent_precision,
    assert_request_id_prefixed,
    assert_version_is,
)
from .factories import OMIT
from .test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    CERTIFIER_HEADERS,
    FUND_MANAGER_USER_ID,
    MANAGER_HEADERS,
    MEASURER_HEADERS,
    OFFICER_CERTIFIER_USER_ID,
    OFFICER_MEASURER_USER_ID,
    OTHER_FUND_MANAGER_USER_ID,
    OTHER_MANAGER_HEADERS,
    TEST_USERS,
    make_compliance_officer_headers,
    make_fund_manager_headers,
    make_headers,
    make_investor_headers,
    make_platform_admin_headers,
)

__all__ = [
    # submodules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    # client
    "ApiClient",
    "api_client",
    # errors
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # factories
    "OMIT",
    # identities
    "TEST_USERS",
    "ADMIN_USER_ID",
    "FUND_MANAGER_USER_ID",
    "OTHER_FUND_MANAGER_USER_ID",
    "OFFICER_MEASURER_USER_ID",
    "OFFICER_CERTIFIER_USER_ID",
    "ADMIN_HEADERS",
    "MANAGER_HEADERS",
    "OTHER_MANAGER_HEADERS",
    "MEASURER_HEADERS",
    "CERTIFIER_HEADERS",
    "make_investor_headers",
    "make_fund_manager_headers",
    "make_compliance_officer_headers",
    "make_platform_admin_headers",
    "make_headers",
    # assertions
    "assert_asset_test_measurement",
    "assert_bare_uuid",
    "assert_business_test_prongs",
    "assert_common_fields",
    "assert_distinct_measurer_and_certifier",
    "assert_fund_aggregates",
    "assert_fund_state",
    "assert_gain_dollars_conserved",
    "assert_ids_unique",
    "assert_iso_timestamp",
    "assert_ledger_fields",
    "assert_money",
    "assert_money_precision",
    "assert_noncompliance_months_conserved",
    "assert_pagination_meta",
    "assert_percent",
    "assert_percent_precision",
    "assert_request_id_prefixed",
    "assert_version_is",
]

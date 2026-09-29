"""Test helper package for task 2679.

Importing this package installs the error_id -> HTTP status map on the
framework validators and re-exports the domain helpers the suite uses.
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from . import assertions, factories, fixtures, types
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, expected_status_for
from .assertions import (
    as_decimal,
    assert_acreage,
    assert_append_only_entity_shape,
    assert_burden,
    assert_decimal_interest,
    assert_division_order_revenue_conserved,
    assert_envelope_meta,
    assert_full_entity_shape,
    assert_has_fields,
    assert_identity_fields,
    assert_money,
    assert_ordered_by,
    assert_ordered_by_pair,
    assert_pagination_meta,
    assert_quantized,
    assert_rate,
    assert_unit_acreage_conserved,
    assert_version_bumped_by,
)
from .constants import (
    ACTIVITY_MULTIPLIER,
    ALL_ROLES,
    BURDEN_CAP,
    DEFAULT_CLOCK_DATE,
    DEFAULT_CLOCK_UTC,
    DEPLETION_INCOME_CAP_PCT,
    DEPLETION_RATE,
    DISCOUNT_RATE_ANNUAL,
    ESCHEAT_MONTHS,
    HORIZON_YEARS,
    MAX_COUNTER_ROUNDS,
    NON_CONSENT_ELECTION_FACTOR,
    PSA_TERMINATION_THRESHOLD_PCT,
    PSA_WINDOW_BUFFER_DAYS,
    RISK_FACTOR_UNDEVELOPED,
    ROLE_ACQUISITION_MANAGER,
    ROLE_DIVISION_ORDER_ADMIN,
    ROLE_OPERATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_ROYALTY_OWNER,
    ROLE_TITLE_ANALYST,
    SEVERANCE_RATES,
    SUSPENSE_INTEREST_ANNUAL,
    UPSIDE_PER_NET_ACRE,
)
from .test_users import (
    ADMIN_ALT_HEADERS,
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    ANALYST_ALT_HEADERS,
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    MANAGER_ALT_HEADERS,
    MANAGER_HEADERS,
    MANAGER_USER_ID,
    MANAGER_USER_ID_ALT,
    OPERATOR_ALT_HEADERS,
    OPERATOR_HEADERS,
    OPERATOR_USER_ID,
    OPERATOR_USER_ID_ALT,
    PLATFORM_ADMIN_HEADERS,
    headers_without_role,
    headers_without_user_id,
    TEST_USERS,
    make_headers,
    make_royalty_owner_headers,
)

api_client = ApiClient()

__all__ = [
    "ApiClient",
    "api_client",
    "TEST_USERS",
    "assertions",
    "factories",
    "fixtures",
    "types",
    "ERROR_HTTP_STATUS",
    "expected_status_for",
]

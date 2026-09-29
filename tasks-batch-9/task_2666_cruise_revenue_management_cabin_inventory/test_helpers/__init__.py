"""
Test infrastructure for the Cruise Revenue Management & Cabin Inventory API.

Import everything from this package; the submodules are an implementation
detail. ``api_client`` is a ready-made client instance bound to the server the
runner started.

    from test_helpers import api_client, fixtures as fx, ERR_CATEGORY_SOLD_OUT
"""

from . import assertions, constants, factories, fixtures
from .api_client import ApiClient
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_allotment_counters,
    assert_booking_state,
    assert_capacity_identity,
    assert_cents,
    assert_common_fields,
    assert_fields_present,
    assert_instant_equals,
    assert_money,
    assert_payment_event_shape,
    assert_posture_for_occupancy,
    assert_revenue_alert_consistent,
    assert_settlement_cash_identity,
    assert_sorted_by,
    assert_two_decimal_pct,
    assert_version_is,
    assert_version_unchanged,
    ids_of,
)
from .constants import *  # noqa: F401,F403
from .test_users import (
    EMPTY_ROLE_HEADERS,
    EMPTY_USER_HEADERS,
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    GROUP_SALES_AGENT_2_USER_ID,
    GROUP_SALES_AGENT_3,
    GROUP_SALES_AGENT_3_USER_ID,
    GROUP_SALES_AGENT_USER_ID,
    MISSING_ROLE_HEADERS,
    MISSING_USER_HEADERS,
    NO_AUTH_HEADERS,
    PORT_OPS_COORDINATOR,
    PORT_OPS_COORDINATOR_USER_ID,
    RESERVATION_AGENT,
    RESERVATION_AGENT_USER_ID,
    REVENUE_MANAGER,
    REVENUE_MANAGER_USER_ID,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    headers_with_role,
    make_guest_headers,
)

#: Shared client instance. The runner exports ``API_BASE_URL``.
api_client = ApiClient()

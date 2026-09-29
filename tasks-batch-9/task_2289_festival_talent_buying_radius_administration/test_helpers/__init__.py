"""Test infrastructure for the festival talent-buying API.

Importing this package registers the error_id -> HTTP status map with the
framework validators, so `validate_error` cross-checks statuses automatically.
"""

from . import api_errors  # noqa: F401  (registers the status map on import)
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_booking_state,
    assert_common_fields,
    assert_envelope_meta,
    assert_ordered_by,
    assert_version_bumped,
    expected_adjudicated_risk_score,
    expected_contracted_contribution,
    expected_deposit_pct,
    expected_distance_miles,
    expected_draw_penalty,
    expected_line_cost_cents,
    expected_promoter_share_pct,
    expected_settlement_total_cents,
    expected_strict_risk_score,
    haversine_miles,
    round_half_up,
    round_half_up_2dp,
)
from .test_users import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    NO_AUTH_HEADERS,
    PRODUCTION_MANAGER,
    PRODUCTION_MANAGER_2,
    TALENT_BUYER,
    TEST_USERS,
    make_artist_rep_headers,
    make_headers,
    make_production_manager_headers,
)

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "TEST_USERS",
    "TALENT_BUYER",
    "BUSINESS_AFFAIRS",
    "PRODUCTION_MANAGER",
    "PRODUCTION_MANAGER_2",
    "FINANCE_CONTROLLER",
    "NO_AUTH_HEADERS",
    "make_artist_rep_headers",
    "make_production_manager_headers",
    "make_headers",
    "assert_common_fields",
    "assert_envelope_meta",
    "assert_booking_state",
    "assert_ordered_by",
    "assert_version_bumped",
    "round_half_up",
    "round_half_up_2dp",
    "haversine_miles",
    "expected_distance_miles",
    "expected_line_cost_cents",
    "expected_contracted_contribution",
    "expected_draw_penalty",
    "expected_strict_risk_score",
    "expected_adjudicated_risk_score",
    "expected_deposit_pct",
    "expected_promoter_share_pct",
    "expected_settlement_total_cents",
]

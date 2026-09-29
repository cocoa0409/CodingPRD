"""
Test infrastructure for the Prepaid Restaurant Ticketing API.

Importing this package registers the error catalogue's error_id -> HTTP status
mapping with the framework validators, so ``validate_error`` cross-checks the
HTTP status of every rejection automatically.
"""

from . import api_errors  # noqa: F401  (registers the error/status mapping)
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_ERRORS
from .assertions import (
    assert_balance_due,
    assert_common_fields,
    assert_created_at_ascending,
    assert_credit_identity,
    assert_credit_status,
    assert_derived_ledger_figures,
    assert_fulfillment_status,
    assert_ladder_status,
    assert_ledger_row_shape,
    assert_money_breakdown,
    assert_pagination_meta,
    assert_payment_status,
    assert_seat_pool,
    assert_seat_pool_identity,
    assert_sell_through,
    assert_settled_ledger_identity,
    assert_signed_amount,
    assert_signed_sum_matches,
    assert_version_advanced_by,
)
from .constants import (
    ALL_ROLES,
    CLOCK_EPOCH,
    DOW_BP,
    PRICE_CAP_BP,
    PRICE_FLOOR_BP,
    ROLE_GUEST,
    ROLE_GUEST_SERVICES,
    ROLE_KITCHEN_LEAD,
    ROLE_PLATFORM_ADMIN,
    ROLE_RESTAURANT_MANAGER,
    TIER_BP,
    apply_bp,
    charge_breakdown,
    deposit_due,
    forfeiture_band_bp,
    list_price_per_cover,
    prep_minutes_total,
    priority_score,
    rebook_fee_cents,
    release_price_per_cover,
    release_seat_count,
    scarcity_step_bp,
    sell_through_bp,
    settle_cancellation,
)
from .test_users import (
    ADMIN_HEADERS,
    CARE_DECIDER_HEADERS,
    CARE_FILER_HEADERS,
    CARE_HEADERS,
    CARE_ISSUER_HEADERS,
    CARE_REVOKER_HEADERS,
    GUEST_SERVICES_DECIDER_ID,
    GUEST_SERVICES_FILER_ID,
    GUEST_SERVICES_ID,
    GUEST_SERVICES_ISSUER_ID,
    GUEST_SERVICES_REVOKER_ID,
    PLATFORM_ADMIN_ID,
    headers_with_blank,
    headers_without,
    make_admin_headers,
    make_care_headers,
    make_guest_headers,
    make_headers,
    make_kitchen_headers,
    make_kitchen_lead_headers,
    make_manager_headers,
    make_restaurant_headers,
)

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_ERRORS",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]

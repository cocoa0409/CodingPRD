"""Barrel export: framework generics + Credit-Card-Rewards-specific test helpers."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# Domain types
from .types import (  # noqa: F401
    UserRole,
    CardProductStatus,
    CashbackCategoryStatus,
    TransferPartnerType,
    TransferPartnerStatus,
    CardAccountStatus,
    SignupBonusStatus,
    TransactionStatus,
    PointsLotType,
    PointsLotStatus,
    RedemptionType,
    RedemptionStatus,
    CategoryActivationStatus,
    CardProduct,
    CashbackCategory,
    QuarterlyCategory,
    TransferPartner,
    CardAccount,
    Transaction,
    PointsLot,
    Redemption,
    CategoryActivation,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (  # noqa: F401
    assert_common_fields,
    assert_card_product,
    assert_transfer_partner,
    assert_card_account,
    assert_transaction,
    assert_redemption,
    assert_category_activation,
    assert_points_lot,
    assert_points_lot_has_no_version_fields,
)

# Factories
from .factories import (  # noqa: F401
    DEFAULTS,
    set_clock_payload,
    create_product_payload,
    create_cashback_category_payload,
    create_quarterly_category_payload,
    create_transfer_partner_payload,
    create_account_payload,
    create_transaction_payload,
    create_redemption_payload,
    create_category_activation_payload,
)

# Constants
from .constants import (  # noqa: F401
    PAGINATION,
    BPS_DENOM,
    POINTS_DIVISOR,
    STATEMENT_CREDIT_CENTS_PER_POINT,
    IMPLICIT_TIER_MULTIPLIER_BPS,
)

# Role headers
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_cardholder_headers,
    make_program_admin_headers,
    make_rewards_ops_headers,
    make_headers,
)

# Composite fixtures
from .fixtures import (  # noqa: F401
    set_clock,
    create_product,
    retire_product,
    create_cashback_category,
    create_quarterly_category,
    create_transfer_partner,
    suspend_transfer_partner,
    create_account,
    create_active_account,
    setup_active_account,
    get_account,
    account_version,
    create_pending_transaction,
    post_transaction,
    create_and_post_transaction,
    setup_account_with_balance,
    create_redemption,
    confirm_redemption,
    create_and_confirm_redemption,
    setup_account_with_activated_quarterly,
    list_account_lots,
    list_lots_by_source_txn,
    close_period,
)

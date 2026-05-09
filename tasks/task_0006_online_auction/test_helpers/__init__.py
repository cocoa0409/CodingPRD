"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import (
    UserRole, SellerStatus, BidderStatus, LotStatus, LotCategory, LotCondition,
    BidStatus, BidSource, AutoBidProxyStatus, DepositStatus, DepositTerminalReason,
    InvoiceStatus, DisputeStatus, DisputeOutcome, DisputeFiledBy,
    Seller, Bidder, Lot, Bid, AutoBidProxy, Deposit, Invoice, Dispute,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_seller, assert_bidder, assert_lot, assert_bid,
    assert_auto_bid_proxy, assert_invoice, assert_dispute, assert_deposit,
    assert_invoice_money_invariants, assert_error_envelope,
)
from .factories import (
    create_seller_payload, create_bidder_payload, credit_wallet_payload,
    create_lot_payload, place_bid_payload, create_proxy_payload,
    file_dispute_payload, resolve_dispute_payload,
    advance_clock_payload, event_payment_confirmed_payload,
    event_identity_verified_payload, event_logistics_delivered_payload,
    event_account_takeover_payload, unique_serial,
)
from .constants import (
    LADDER, required_increment, min_required_bid_cents,
    DEPOSIT_RATE, DEPOSIT_MIN_CENTS, DEPOSIT_MAX_CENTS, deposit_required_cents,
    SOFT_CLOSE_TRIGGER_SECONDS, SOFT_CLOSE_EXTENSION_SECONDS,
    BP_TIER_1_UPPER_INCLUSIVE_CENTS, BP_TIER_2_UPPER_INCLUSIVE_CENTS,
    BP_TIER_1_RATE, BP_TIER_2_RATE, BP_TIER_3_RATE,
    JEWELRY_SURCHARGE_RATE, VERIFIED_DISCOUNT_RATE, MIN_PREMIUM_CENTS,
    buyer_premium_cents,
    SC_TIER_1_UPPER_INCLUSIVE_CENTS, SC_TIER_2_UPPER_INCLUSIVE_CENTS,
    SC_TIER_1_RATE, SC_TIER_2_RATE, SC_TIER_3_RATE, seller_commission_cents,
    commission_reversal_cents,
    PARTIAL_REFUND_RATE_WHEN_REOFFER_FILLED,
    WITHDRAWAL_WEIGHT, DISPUTE_LOSS_WEIGHT,
    ACUTE_PENALTY_SHILL, ACUTE_PENALTY_TAKEOVER, ACUTE_PENALTY_DEFAULT,
    RISK_MAX_SCORE, RISK_RESTRICT_THRESHOLD, RISK_SUSPEND_THRESHOLD,
    SHILL_VELOCITY_WINDOW_SECONDS, SHILL_VELOCITY_THRESHOLD,
    LOT_DURATION_MIN_SECONDS, TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS, make_seller_headers, make_bidder_headers,
    make_arbitrator_headers, make_admin_headers,
)
from .fixtures import (
    iso_future, iso_relative, current_clock_now, advance_clock,
    create_seller, create_bidder,
    create_lot_for_seller, publish_lot, cancel_lot, create_and_publish_lot,
    setup_live_lot, setup_live_lot_with_bid, setup_sold_lot,
    setup_paid_lot, setup_paid_and_delivered_lot, setup_dispute_under_review,
    place_bid_on_lot, close_lot_to_sold, get_lot,
    pay_invoice, deliver_lot,
    file_dispute_for_lot, resolve_dispute, find_deposit_id_for_bid,
    ADMIN_HEADERS,
)

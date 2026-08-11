"""Barrel export: framework generics + PRD-specific test infrastructure."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    GenericApiClient,
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import (
    UserRole, ZoneCode, HouseholdStatus, SubscriptionStatus, CoopStatus, PredatorGrade,
    VisitType, VisitStatus, Coverage, EngagementStatus, RouteStatus, StopStatus,
    ProductCategory, OrderStatus, InvoiceStatus, InvoiceLineSourceType,
    HouseholdAccount, Subscription, CoopSite, ServiceVisit, SittingEngagement,
    SittingRoute, RouteStop, OrderLine, SupplyOrder, Invoice, SubscriptionPlan,
    Product, InvoiceLine, SeasonalWindow,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_same_instant,
    assert_household, assert_subscription, assert_coop_site, assert_service_visit,
    assert_sitting_engagement, assert_sitting_route, assert_route_stop,
    assert_supply_order, assert_invoice, assert_invoice_line,
    assert_subscription_plan, assert_product, assert_seasonal_window,
    assert_invoice_money_invariants, assert_wallet_non_negative,
)
from .factories import (
    create_household_payload, create_subscription_plan_payload, create_product_payload,
    create_seasonal_window_payload, create_subscription_payload, create_coop_site_payload,
    create_service_visit_payload, assign_visit_payload, complete_visit_payload,
    create_sitting_engagement_payload, create_sitting_route_payload, add_route_stop_payload,
    create_supply_order_payload, add_order_line_payload, create_invoice_payload,
    wallet_adjustment_payload, plan_change_payload, resolve_dispute_payload, clock_payload,
)
from .constants import (
    DEFAULT_CLOCK_ISO, BASE_RATE_CENTS, ZONE_MULTIPLIER,
    FLOCK_TIER_BOUNDARY_1, FLOCK_TIER_BOUNDARY_2, FLOCK_TIER_BOUNDARY_3,
    FLOCK_FEE_TIER_2_CENTS, FLOCK_FEE_TIER_3_CENTS, FLOCK_FEE_PER_EXTRA_HEN_CENTS,
    STANDARD_DURATION_MINUTES, OVERTIME_BLOCK_MINUTES, OVERTIME_BLOCK_FEE_CENTS,
    DAILY_RATE_CENTS, FREE_NOTICE_HOURS, REDUCED_NOTICE_HOURS,
    REDUCED_FEE_PCT, LATE_FEE_PCT, MAX_ENGAGEMENT_NIGHTS, STOP_DURATION_MINUTES,
    TRAVEL_BUFFER_MINUTES, MAX_RESCHEDULE_COUNT, TAX_RATE, DUE_DAYS,
    CREDIT_LIMIT_CENTS, THRESHOLDS,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_service_tech_headers,
    make_dispatcher_headers, make_billing_admin_headers, make_platform_admin_headers,
)
from .fixtures import (
    set_logical_clock,
    create_household, create_plan, create_product, create_window, create_coop,
    create_subscription, create_visit, assign_visit, check_in_visit, complete_visit,
    create_scheduled_visit, create_completed_visit,
    install_coop, proof_coop_once,
    setup_household_with_installed_coop, setup_household_with_grade_b_coop,
    setup_active_subscription,
    create_route, create_published_route, create_engagement, quote_engagement,
    confirm_engagement, list_engagement_stops,
    setup_quoted_engagement, setup_confirmed_engagement,
    create_order, place_order, create_placed_order,
    generate_invoice, issue_invoice, setup_issued_invoice, credit_wallet,
)

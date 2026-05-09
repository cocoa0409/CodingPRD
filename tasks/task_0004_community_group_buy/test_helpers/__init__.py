"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_community, assert_group_leader, assert_customer,
    assert_supplier, assert_warehouse,
    assert_flash_campaign, assert_group_buy_campaign,
    assert_order, assert_shipment, assert_pickup_point,
    assert_consolidation_batch, assert_after_sales_case,
    assert_commission_entry, assert_payout, assert_risk_alert,
    assert_pickup_summary, assert_flash_inventory_invariant,
)
from .factories import (
    DEFAULTS,
    create_community_payload, create_group_leader_payload, create_customer_payload,
    create_supplier_payload, create_warehouse_payload, create_pickup_point_payload,
    create_flash_campaign_payload, create_group_buy_campaign_payload,
    create_join_payload, create_flash_purchase_payload,
    create_after_sales_payload, create_resolve_payload,
    create_plan_shipments_payload, create_consolidation_batch_payload,
    create_payout_payload, create_risk_alert_payload,
)
from .constants import (
    THRESHOLDS,
    PRIMARY_RATE_BP_BY_TIER, SECONDARY_BONUS_RATE_BP_BY_TIER,
    UPSTREAM_RATE_BP_BY_DEPTH, PAYOUT_LAG_BY_TIER,
)
from .test_users import (
    TEST_USERS,
    make_group_leader_headers, make_customer_headers, make_supplier_headers,
    make_platform_admin_headers, make_pickup_operator_headers,
    make_customer_service_headers,
)
from .fixtures import (
    ADMIN, PICKUP_OP, CS_AGENT,
    create_community, create_supplier, create_customer, create_warehouse,
    create_pickup_point, create_active_leader, create_pending_leader,
    setup_basic_scaffold, create_group_buy_campaign,
    join_campaign, pay_order, close_campaign,
    setup_paid_succeeded_order, plan_shipments_for_order,
    dispatch_shipment, arrive_shipment, pickup_confirm,
    progress_order_to_picked_up, setup_picked_up_order,
    setup_flash_scenario,
    file_after_sales, start_review, resolve_case,
    assemble_payout, advance_clock, run_payouts_sweep, recompute_risk,
    setup_multi_customer_paid,
    find_commission_entry, list_commission_entries,
)

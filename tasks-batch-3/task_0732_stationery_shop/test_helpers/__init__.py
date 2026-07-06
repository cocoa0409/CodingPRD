"""Barrel export: framework generics + PRD-specific code."""
# Framework generics
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
    UserRole,
    PaperStockStatus, FinishOptionStatus, EventPackageStatus, EventPackageType,
    DesignStatus, ProofStatus, OrderStatus,
    AddressingJobType, AddressingJobStatus,
    WorkOrderProductionStatus, WorkOrderAddressingStatus,
    ShipmentStatus,
    Customer, Designer, PaperStock, FinishOption, EventPackage,
    Design, Proof, Order, LineItem, AddressingJob, WorkOrder, Shipment,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_customer, assert_designer, assert_paper_stock, assert_finish_option,
    assert_event_package, assert_design, assert_proof, assert_order,
    assert_line_item, assert_addressing_job, assert_work_order, assert_shipment,
)
from .factories import (
    create_customer_payload, create_designer_payload, create_paper_stock_payload,
    create_finish_option_payload, create_event_package_payload,
    create_design_payload, create_order_payload, create_line_item_payload,
    create_addressing_job_payload, create_initial_proof_payload,
)
from .constants import (
    REORDER_WINDOW_DAYS, REORDER_DISCOUNT_PCT,
    RUSH_MIN_DAYS, RUSH_MAX_DAYS, RUSH_TIER_15D_PCT, RUSH_TIER_7D_PCT,
    ADDRESSING_LEAD_DAYS, RUSH_LEAD_DAY_SPEEDUP,
    REVISION_FEE_CENTS, REVISION_FREE_COUNT,
    ADDRESSING_DAILY_CAPACITY, QUANTITY_TIERS, TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_designer_headers, make_shop_admin_headers,
)
from .fixtures import (
    create_customer, create_designer, create_paper_stock, create_finish_option,
    create_event_package, set_clock,
    setup_standard_catalog,
    create_design_for, create_cart_order_for, add_line_item_to_cart,
    setup_cart_order_with_line,
    confirm_order, simulate_deposit_full,
    setup_deposit_pending, setup_deposit_paid_no_proof,
    create_and_submit_proof, create_draft_proof, approve_proof,
    setup_deposit_pending_with_submitted_proof,
    setup_in_production_order,
    advance_production, advance_addressing, run_production_to_completed,
    setup_ready_to_ship, setup_delivered_order,
)

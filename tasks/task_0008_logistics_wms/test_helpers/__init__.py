"""Barrel export: framework generics + WMS-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)
# WMS-specific
from .types import (
    UserRole, WarehousePosture, PutawayStrategy, BinZone, BinStatus,
    LotCategory, LotStatus, RecallReason,
    InboundShipmentStatus, InboundLineStatus,
    WaveStrategy, WaveStatus,
    OrderStatus, OrderCarrier, PickStrategy, PickTaskStatus,
    CycleCountStatus,
    Warehouse, Bin, Lot, InboundShipment, InboundLine,
    Inventory, PickTask, Order, Wave, CycleCount,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_warehouse, assert_bin, assert_lot,
    assert_inbound_shipment, assert_inbound_line,
    assert_inventory, assert_order, assert_pick_task,
    assert_wave, assert_cycle_count,
    assert_posture_consistent_with_score, assert_inventory_invariant,
)
from .factories import (
    create_warehouse_payload, create_bin_payload, create_lot_payload,
    create_inbound_shipment_payload, create_inbound_shipment_multiline_payload,
    create_complete_inspection_payload,
    create_order_payload, create_wave_payload,
    create_cycle_count_payload, create_recall_payload,
    create_clock_advance_payload, create_pack_payload,
    create_pick_complete_payload, create_submit_count_payload,
)
from .constants import (
    INSPECTION_SAMPLE_TIERS, INSPECTION_SAMPLE_DEFAULT, AQL_PASS_THRESHOLD,
    CARTON_VOLUME_CM3, CARTON_WEIGHT_G,
    SHRINKAGE_DENOMINATOR_CENTS, ABNORMAL_EVENT_WEIGHT, RECALL_WEIGHT,
    RISK_SCORE_MAX, POSTURE_FROZEN_THRESHOLD, POSTURE_RESTRICTED_THRESHOLD,
    NEAR_EXPIRY_DAYS, ABNORMAL_EVENT_WINDOW_SECONDS, SHRINKAGE_WINDOW_DAYS,
    SECONDS_PER_DAY, TRACKING_PREFIX, VALID_CARRIERS,
    ZONES, PICK_STRATEGIES, PUTAWAY_STRATEGIES, RECALL_REASONS,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS, STAFF_USER_ID, STAFF_USER_ID_ALT,
    AUDITOR_USER_ID, AUDITOR_USER_ID_ALT, MANAGER_USER_ID,
    make_staff_headers, make_auditor_headers, make_manager_headers,
)
from .fixtures import (
    create_warehouse, create_bin, create_lot,
    putaway_lot_units, setup_warehouse_with_inventory,
    create_allocated_order, get_pick_tasks_for_order,
    setup_released_wave_for_order, setup_picking_pick_task,
    setup_warehouse_with_recalls, setup_cycle_count_in_state,
    setup_two_lots_same_sku, setup_two_bins_distinct_distance_capacity,
    get_inventory_row, sum_inventory_qty_for_lot,
)

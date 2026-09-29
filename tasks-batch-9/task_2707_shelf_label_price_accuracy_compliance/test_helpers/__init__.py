"""Test infrastructure for the Shelf Label & Price Accuracy Compliance API."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import api_errors, factories
from .api_client import PriceIntegrityApiClient
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_common_fields,
    assert_fields_unchanged,
    assert_instant_is,
    assert_label_serial,
    assert_money_cents,
    assert_pct,
    assert_posture,
    assert_scan_line_shape,
    assert_version_bumped_by,
    expected_assessed_penalty_cents,
    expected_claimed_amount_cents,
    expected_gross_error_rate_pct,
    expected_net_overcharge_rate_pct,
    expected_occurrence_weighted_score,
    expected_penalty_component_cents,
    expected_penalty_exposure_cents,
    expected_refund_credit_cents,
    expected_task_weighted_score,
    expected_unit_price_display_cents,
    floor_div,
    ids_of,
    normalise_instant,
    pct,
    round_half_up_2dp,
    tier_multiplier,
    unit_price_basis,
)
from .constants import *  # noqa: F401,F403
from .fixtures import Builder
from .test_users import (
    make_compliance_officer_headers,
    make_customer_service_desk_headers,
    make_entity_backed_headers_without_user_id,
    make_headers,
    make_headers_with_empty_role,
    make_headers_with_empty_user_id,
    make_headers_without_role,
    make_label_associate_headers,
    make_price_auditor_headers,
    make_pricing_admin_headers,
    make_store_manager_headers,
    make_unknown_role_headers,
)
from .types import (
    AccountabilityAction,
    Aisle,
    Associate,
    ExceptionReport,
    InspectionFinding,
    Jurisdiction,
    LabelTask,
    PriceChangeFile,
    PriceChangeLine,
    PromoSignage,
    RefundClaim,
    RegulatoryInspection,
    ScanLine,
    ScannerAudit,
    SignageSweepResult,
    Store,
)

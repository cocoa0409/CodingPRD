"""Test helpers for the LTL Freight Classification API.

Layered on top of ``prd_bench_local_runner.testing``: the framework supplies the
generic HTTP client, envelope validators and race utilities; this package
supplies everything specific to this contract -- the endpoint client, the error
catalogue with its HTTP statuses, payload factories, entity assertions, domain
constants and composite setup fixtures.
"""

# --- Framework generics -------------------------------------------------
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

# --- This contract ------------------------------------------------------
from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_append_only_resource_fields,
    assert_capture_event,
    assert_commodity_profile,
    assert_correction_notice,
    assert_credit_memo,
    assert_customer,
    assert_customer_offender_record,
    assert_dispute,
    assert_exception_agreement,
    assert_four_decimal_places,
    assert_identity_fields,
    assert_inspection_finding,
    assert_integer_cents,
    assert_mutable_resource_fields,
    assert_rate_program,
    assert_recognized_class_code,
    assert_repricing_run,
    assert_shipment,
    assert_shipment_ledger_identity,
    assert_shipment_line,
    assert_status_dimensions_independent,
    assert_strike_count_conserved,
    assert_tariff_version,
    assert_terminal,
    assert_two_decimal_places,
)
from .constants import (
    CLASS_CODES,
    CLOCK_STARTUP_UTC,
    DISPUTE_WINDOW_BY_TIER,
    HANDLING_FLOOR,
    LIABILITY_FLOOR,
    MINIMAL_DENSITY_BREAKS,
    RECLASS_FEE_CENTS,
    REWEIGH_FEE_CENTS,
    STANDARD_DENSITY_BREAKS,
    STOWABILITY_FLOOR,
    TEST_DEFAULTS,
    WEIGHT_BREAK_FACTORS,
)
from .test_users import (
    TEST_USERS,
    make_classification_auditor_headers,
    make_dispute_reviewer_headers,
    make_freight_inspector_headers,
    make_headers_without_role,
    make_headers_without_user_id,
    make_pricing_analyst_headers,
    make_shipper_headers,
    make_terminal_operator_headers,
)

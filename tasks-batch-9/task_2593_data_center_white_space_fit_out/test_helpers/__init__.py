"""Test helpers for the data centre white space fit-out API.

Re-exports the framework generics alongside this suite's domain-specific client,
error catalogue, payload factories, assertions, constants, role headers and
composite setup fixtures so tests can import everything from one place.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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

from . import assertions, factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_busway,
    assert_cage,
    assert_commissioning_package,
    assert_containment_zone,
    assert_cooling_unit,
    assert_custody_partition,
    assert_five_decimal_places,
    assert_hall,
    assert_hall_power_ledger_balances,
    assert_kw,
    assert_kw3,
    assert_kw5,
    assert_load_bank_test,
    assert_mop,
    assert_mop_approval,
    assert_pdu,
    assert_rack,
    assert_rack_feed,
    assert_release_packet,
    assert_security_device,
    assert_tenant,
    assert_three_decimal_places,
    assert_two_decimal_places,
)
from .constants import (
    AIRFLOW_ACCEPTANCE_FRACTION,
    AIRFLOW_COEFFICIENT,
    BTU_PER_HOUR_PER_KW,
    CONTINUOUS_LOAD_FACTOR,
    DIVERSITY_FACTOR,
    LOAD_BANK_MIN_RETURN_DELTA_T_F,
    LOAD_BANK_TOLERANCE,
    POWER_FACTOR,
    RACK_OVERHEAD_FACTOR,
    STATIC_PRESSURE_FLOOR_FRACTION,
    TEST_DEFAULTS,
    THREE_PHASE_CONSTANT,
    THRESHOLDS,
    USER_IDS,
)
from .test_users import (
    TEST_USERS,
    headers_without_role,
    headers_without_user_id,
    make_change_manager_headers,
    make_commissioning_agent_headers,
    make_electrical_contractor_headers,
    make_facility_planner_headers,
    make_headers,
    make_mechanical_contractor_headers,
    make_operations_manager_headers,
    make_security_administrator_headers,
    make_tenant_representative_headers,
    make_witness_authority_headers,
)
from .types import UserRole

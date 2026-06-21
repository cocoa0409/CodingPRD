"""Barrel export: framework generics + PRD-specific code.

Tests import everything from ``test_helpers`` for one consistent source.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    run_race, build_user_headers, NON_EXISTENT_UUID,
    GenericApiClient,
)

from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_common_fields,
    assert_immutable_fields,
)
from .factories import (
    create_region_payload,
    create_payment_standard_payload,
    create_household_payload,
    create_voucher_payload,
    create_landlord_payload,
    create_unit_payload,
    create_rent_reasonableness_payload,
    create_inspection_payload,
    create_hap_contract_payload,
    create_portability_move_payload,
    create_annual_review_payload,
    finalize_annual_review_payload,
    create_special_mobility_grant_payload,
    set_clock_payload,
)
from .constants import (
    DEPENDENT_DEDUCTION_CENTS,
    ELDERLY_DEDUCTION_CENTS,
    REGION_VLI_BASE_CENTS,
    MINIMUM_RENT_CENTS,
    MAX_BEDROOM,
    CURE_WINDOW_DAYS,
    DEFAULT_TERM_DAYS,
    DEFAULT_TERM_EXTENSION_DAYS,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
)
from .test_users import TEST_USERS, make_landlord_headers
from .fixtures import (
    set_clock,
    create_region,
    create_payment_standard,
    create_household,
    make_eligible_household,
    issue_voucher,
    create_landlord,
    create_unit,
    create_passed_initial_inspection,
    setup_leaseup_ready,
    lease_up,
    setup_active_hap_contract,
    schedule_annual_inspection,
    setup_abated_contract,
    request_portability_move,
    grant_special_mobility,
    draft_annual_review,
    ADMIN, CASEWORKER, INSPECTOR, COORDINATOR,
)

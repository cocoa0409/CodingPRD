"""Test helpers for the Likeness Rights Clearance API.

Re-exports the framework generics alongside the domain-specific client, error
catalogue, factories, assertions, constants, role headers and scenario builders,
so a test file imports everything it needs from one place.
"""

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

from . import assertions, factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    SWEEP_COUNT_FIELDS,
    assert_entry_types,
    assert_exact_negation,
    assert_fields_absent,
    assert_fields_null,
    assert_immutable_record,
    assert_ledger_entry,
    assert_ledger_sums_to,
    assert_money_is_number,
    assert_pagination,
    assert_posture,
    assert_split_reconstructs_amount,
    assert_subset_equal,
    assert_sweep_changed_nothing,
    assert_sweep_counts,
    assert_talent_counters,
    assert_version_advanced_by,
    assert_versioned,
)
from .constants import (
    CLOCK_DEFAULT,
    COMPLIANCE_OFFICER_ONE,
    COMPLIANCE_OFFICER_TWO,
    DISCLOSURE_PLACEMENT_RANK,
    LICENSEE_ONE,
    LICENSEE_TWO,
    MEDIA_FLOOR_RANK,
    MEDIA_MULTIPLIER,
    POSTURE_FACTOR,
    RIGHTS_ADMIN_ONE,
    RIGHTS_ADMIN_TWO,
    TEST_DEFAULTS,
    THRESHOLDS,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_estate_representative_headers,
    make_licensee_producer_headers,
    make_rights_administrator_headers,
    make_talent_representative_headers,
)

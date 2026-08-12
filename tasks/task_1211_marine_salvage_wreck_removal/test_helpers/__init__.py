"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .factories import *
from .constants import PERMIT_MAP, TEST_DEFAULTS, THRESHOLDS
from .test_users import (
    TEST_USERS,
    make_arbitrator_headers,
    make_contracts_officer_headers,
    make_environmental_officer_headers,
    make_insurer_surveyor_headers,
    make_marine_surveyor_headers,
    make_operations_director_headers,
    make_salvage_master_headers,
)
from .fixtures import *

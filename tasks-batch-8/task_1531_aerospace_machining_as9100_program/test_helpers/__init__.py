"""Barrel export: framework generics + PRD-specific helpers."""
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
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import TEST_USERS, make_headers
from . import test_users as _tu
from .fixtures import *

# Named user ids (re-exported for delegation/SOD assertions)
USER_CONTRACTS_MANAGER = _tu.USER_CONTRACTS_MANAGER
USER_SUPPLY_CHAIN_MANAGER = _tu.USER_SUPPLY_CHAIN_MANAGER
USER_MANUFACTURING_PLANNER = _tu.USER_MANUFACTURING_PLANNER
USER_QUALITY_INSPECTOR = _tu.USER_QUALITY_INSPECTOR
USER_QUALITY_INSPECTOR_2 = _tu.USER_QUALITY_INSPECTOR_2
USER_QUALITY_INSPECTOR_3 = _tu.USER_QUALITY_INSPECTOR_3
USER_QUALITY_INSPECTOR_9 = _tu.USER_QUALITY_INSPECTOR_9
USER_MRB_MEMBER = _tu.USER_MRB_MEMBER
USER_QUALITY_MANAGER = _tu.USER_QUALITY_MANAGER
USER_CUSTOMER_QUALITY_REP = _tu.USER_CUSTOMER_QUALITY_REP
USER_SYSTEM_ADMIN = _tu.USER_SYSTEM_ADMIN

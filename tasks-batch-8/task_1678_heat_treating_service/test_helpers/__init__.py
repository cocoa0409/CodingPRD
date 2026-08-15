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
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_quality_engineer_headers,
)
from . import test_users as _tu
from .fixtures import *

# Named user ids (re-exported for segregation-of-duties assertions, PRD §3.7)
USER_QUALITY_ENGINEER = _tu.USER_QUALITY_ENGINEER
USER_QUALITY_ENGINEER_2 = _tu.USER_QUALITY_ENGINEER_2
USER_CUSTOMER_SERVICE_REP = _tu.USER_CUSTOMER_SERVICE_REP
USER_SHOP_SCHEDULER = _tu.USER_SHOP_SCHEDULER
USER_FURNACE_OPERATOR = _tu.USER_FURNACE_OPERATOR
USER_CALIBRATION_TECH = _tu.USER_CALIBRATION_TECH
USER_NADCAP_AUDITOR = _tu.USER_NADCAP_AUDITOR

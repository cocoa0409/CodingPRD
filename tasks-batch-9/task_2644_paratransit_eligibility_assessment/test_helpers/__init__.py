"""Test infrastructure for the paratransit eligibility API.

Re-exports the generic framework helpers alongside this contract's own client,
error catalogue, entity assertions, payload factories, business constants,
acting identities and composite setup builders, so a test module can import
everything it needs from one place.
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
from .api_client import ApiClient
from .api_errors import *  # noqa: F401,F403
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403

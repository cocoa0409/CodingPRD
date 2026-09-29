"""Shared test infrastructure for the repertory cinema programming API.

Everything a test file needs is re-exported here, so a test module opens with a
single import:

    from test_helpers import (
        api_client, ApiErrorId, validate_success, validate_error,
        setup_programming_baseline, TEST_USERS,
    )
"""

# ── Framework generics ────────────────────────────────────────────────────
from prd_bench_local_runner.testing import (
    GenericApiClient,
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

# ── Domain vocabulary, wire client, error catalogue ───────────────────────
from .types import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .api_client import ApiClient, api_client
from .test_users import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403

"""Shared test infrastructure for the Correspondent Banking Due Diligence API.

Everything a test needs is re-exported here: the framework generics, the typed
API client, the error-id enum, the domain constants, the role headers, the
payload factories, the entity assertions and the scenario fixtures.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_ID,
    ANALYST_ID,
    ANALYST_ID_2,
    COMMITTEE_ID,
    COMMITTEE_ID_2,
    HEADERS_BY_ROLE,
    OFFICER_ID,
    OFFICER_ID_2,
    RM_ID,
    RM_ID_2,
    TEST_USERS,
    make_admin_headers,
    make_analyst_headers,
    make_committee_headers,
    make_officer_headers,
    make_respondent_headers,
    make_rm_headers,
)
from .types import *  # noqa: F401,F403

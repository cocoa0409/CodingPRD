"""Shared test infrastructure for the Senior Games API compliance suite.

Import everything from this package:

    from test_helpers import *

which re-exports the runner's validation framework alongside this suite's own
client, factories, assertions and composite setup helpers.
"""
from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    run_race,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    build_user_headers,
    NON_EXISTENT_UUID,
)

from .types import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .api_client import ApiClient, api_client, PREFIX  # noqa: F401
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_games_admin_headers,
    make_registration_officer_headers,
    make_medical_director_headers,
    make_records_ratifier_headers,
    make_sponsor_liaison_headers,
    make_athlete_headers,
    make_sport_official_headers,
)
from .factories import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403

"""Test helpers for the Hyperscale Site Selection & Power Procurement API.

Import everything a test needs from this package:

    from test_helpers import (
        api_client, TEST_USERS, ApiErrorId,
        validate_success, validate_error,
        setup_reserved_application, assert_money,
    )
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_NAMES,
    ANALYST_2_USER_ID,
    ANALYST_USER_ID,
    AUTHORITY_USER_ID,
    CHAIR_2_USER_ID,
    CHAIR_USER_ID,
    DIRECTOR_USER_ID,
    NEGOTIATOR_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_authority_headers,
    make_chair_headers,
    make_director_headers,
    make_negotiator_headers,
    make_utility_planner_headers,
)
from .types import (
    COMMON_FIELDS,
    LOAD_STUDY_FORBIDDEN_FIELDS,
    LOAD_STUDY_IDENTITY_FIELDS,
    CandidateSite,
    IncentiveNegotiation,
    InterconnectionApplication,
    LandParcelOption,
    LoadStudy,
    PowerPurchaseAgreement,
    SitingProgram,
    Utility,
    WaterSource,
    ZoningApplication,
)

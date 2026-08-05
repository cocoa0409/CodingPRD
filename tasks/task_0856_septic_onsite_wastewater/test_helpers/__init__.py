"""Barrel export: framework generics plus the register's own test infrastructure."""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    APPLICANT_USER_ID,
    DESIGN_PROFESSIONAL_USER_ID,
    EHS_FIELD_USER_ID,
    EHS_REVIEWER_USER_ID,
    HEALTH_OFFICER_USER_ID,
    NO_AUTH_HEADERS,
    OTHER_APPLICANT_USER_ID,
    OTHER_DESIGN_PROFESSIONAL_USER_ID,
    RECORDS_CLERK_USER_ID,
    TEST_USERS,
    make_applicant_headers,
    make_design_professional_headers,
    make_ehs_headers,
    make_health_officer_headers,
    make_installer_headers,
    make_pumper_headers,
    make_records_clerk_headers,
)
from .types import *  # noqa: F401,F403

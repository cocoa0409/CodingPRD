"""Barrel export: framework generics plus the Work-Based Learning specifics."""

# Framework generics, re-exported so tests have one import source.
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
    COMPLIANCE_OFFICER_USER,
    COORDINATOR_APPROVER,
    COORDINATOR_AWARDER,
    COORDINATOR_DRAFTER,
    COORDINATOR_SIGNER,
    SAFETY_REVIEWER_USER,
    TEST_USERS,
    make_compliance_officer_headers,
    make_coordinator_headers,
    make_employer_supervisor_headers,
    make_safety_reviewer_headers,
    make_student_headers,
)
from .types import *  # noqa: F401,F403

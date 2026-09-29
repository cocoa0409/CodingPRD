"""Barrel export: framework generics plus the PRD-specific test infrastructure."""

# Framework generics, re-exported so tests have one import source.
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

# PRD-specific infrastructure.
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    COMPLIANCE_AUDITOR,
    DELIVERY_DRIVER,
    HEADERS_BY_ROLE,
    INTAKE_COORDINATOR,
    PHYSICIAN,
    RESPIRATORY_THERAPIST,
    ROLE_NAMES,
    TEST_USERS,
    USER_IDS,
    headers_without_auth,
    make_compliance_auditor_headers,
    make_headers,
    make_intake_coordinator_headers,
    make_physician_headers,
)
from .types import *  # noqa: F401,F403

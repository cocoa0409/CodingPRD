"""Test infrastructure for the protective-equipment reconditioning API.

Re-exports the framework's generic validators alongside this PRD's own types,
client, error catalogue, assertions, factories, constants and fixtures so test
modules import from a single place.
"""
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
    ALL_PLANT_ROLE_HEADERS,
    COMPLIANCE_1,
    COMPLIANCE_2,
    COMPLIANCE_OFFICER_1_USER_ID,
    COMPLIANCE_OFFICER_2_USER_ID,
    CERTIFYING_INSPECTOR_1_USER_ID,
    CERTIFYING_INSPECTOR_2_USER_ID,
    INSPECTOR_1,
    INSPECTOR_2,
    INTAKE_CLERK,
    INTAKE_CLERK_USER_ID,
    PLANT_MANAGER,
    PLANT_MANAGER_USER_ID,
    TECHNICIAN_1,
    TECHNICIAN_1_USER_ID,
    TECHNICIAN_2,
    TECHNICIAN_2_USER_ID,
    TEST_USERS,
    make_certifying_inspector_headers,
    make_compliance_officer_headers,
    make_customer_contact_headers,
    make_intake_clerk_headers,
    make_plant_manager_headers,
    make_technician_headers,
)
from .types import *  # noqa: F401,F403

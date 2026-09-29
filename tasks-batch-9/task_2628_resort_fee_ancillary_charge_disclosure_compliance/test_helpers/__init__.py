"""Barrel export: framework generics plus the resort-fee disclosure helpers."""
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
    ALL_ROLE_NAMES,
    TEST_USERS,
    USER_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER_2,
    USER_GUEST_SERVICES_AGENT,
    USER_GUEST_SERVICES_AGENT_2,
    USER_PLATFORM_ADMIN,
    USER_REGULATORY_LIAISON,
    USER_REGULATORY_LIAISON_2,
    USER_REVENUE_MANAGER,
    USER_REVENUE_MANAGER_2,
    make_channel_operator_headers,
    make_compliance_officer_headers,
    make_guest_headers,
    make_guest_services_agent_headers,
    make_platform_admin_headers,
    make_regulatory_liaison_headers,
    make_revenue_manager_headers,
)
from .types import *  # noqa: F401,F403

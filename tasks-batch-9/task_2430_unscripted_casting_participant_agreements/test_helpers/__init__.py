"""Test helpers for the Unscripted Casting & Participant Agreements API.

Re-exports the shared framework primitives alongside the PRD-specific client,
error catalogue, payload factories, assertions, constants, role headers and
composite setup helpers, so tests need only import from ``test_helpers``.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    build_user_headers,
    get_success_data,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import PREFIX, ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    BUSINESS_AFFAIRS_1_USER_ID,
    BUSINESS_AFFAIRS_2_USER_ID,
    CASTING_DIRECTOR_USER_ID,
    COMPLIANCE_OFFICER_1_USER_ID,
    COMPLIANCE_OFFICER_2_USER_ID,
    PRODUCTION_ADMIN_USER_ID,
    TEST_USERS,
    WELFARE_OFFICER_1_USER_ID,
    WELFARE_OFFICER_2_USER_ID,
    make_applicant_headers,
    make_business_affairs_headers,
    make_casting_director_headers,
    make_compliance_officer_headers,
    make_production_admin_headers,
    make_welfare_officer_headers,
)
from .types import *  # noqa: F401,F403

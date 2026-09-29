"""Test infrastructure for the nuclear refueling outage management API.

Importing this package registers the PRD's error-to-HTTP-status map with the
framework validators, so ``validate_error`` checks the status code as well as
the error identifier.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from prd_bench_local_runner.testing.constants import NON_EXISTENT_UUID  # noqa: F401
from prd_bench_local_runner.testing.validators import get_success_data  # noqa: F401

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    SECOND_USERS,
    TEST_USERS,
    make_access_authority_headers,
    make_contractor_coordinator_headers,
    make_headers_for_role,
    make_headers_with_unknown_role,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    make_station_admin_headers,
)
from .types import *  # noqa: F401,F403

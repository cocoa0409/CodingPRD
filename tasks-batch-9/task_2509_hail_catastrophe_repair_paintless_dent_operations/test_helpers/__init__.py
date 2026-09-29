"""Test helpers for the Hail Catastrophe Repair / Paintless Dent Operations API.

Importing this package registers the error/HTTP-status map with the framework's
``validate_error`` and re-exports everything the test modules need, so a test
file needs a single import line.
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

from .api_client import PREFIX, ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    NO_HEADERS,
    TEST_USERS,
    headers_without_user_id,
    make_billing_coordinator_headers,
    make_crew_coordinator_headers,
    make_director_headers,
    make_insurer_adjuster_headers,
    make_intake_advisor_headers,
    make_pdr_technician_headers,
    make_permit_officer_headers,
    make_quality_inspector_headers,
    make_shop_estimator_headers,
    make_undeclared_role_headers,
)
from .types import *  # noqa: F401,F403

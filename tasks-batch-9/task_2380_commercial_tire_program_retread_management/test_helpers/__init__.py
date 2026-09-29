"""Barrel export: framework generics plus the API-specific test infrastructure."""

# Framework generics, re-exported so tests have a single import source.
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

from . import factories  # noqa: F401
from . import fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    DUAL_ROLE_OPERATOR_ID,
    INSPECTOR_ONE_ID,
    INSPECTOR_TWO_ID,
    OFFICER_CERTIFIER_ID,
    OFFICER_SIGNER_ID,
    TEST_USERS,
    make_billing_clerk_headers,
    make_casing_inspector_headers,
    make_compliance_officer_headers,
    make_dealer_admin_headers,
    make_dispatch_coordinator_headers,
    make_fleet_manager_headers,
    make_plant_scheduler_headers,
    make_tire_technician_headers,
)
from .types import *  # noqa: F401,F403

"""Test helper package for the residential HVAC equipment plant API.

Importing this package re-exports the generic framework helpers alongside the
domain-specific client, factories, assertions, and composite setup helpers, so
that a test module needs a single import block.
"""

from prd_bench_local_runner.testing import (
    GenericApiClient,
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

from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ROLE_NAMES,
    TEST_USERS,
    USER_IDS,
    make_certification_engineer_headers,
    make_design_engineer_headers,
    make_distributor_rep_headers,
    make_headers,
    make_plant_admin_headers,
    make_production_planner_headers,
    make_production_technician_headers,
    make_quality_technician_headers,
    make_regulatory_auditor_headers,
    make_reliability_engineer_headers,
    make_supply_planner_headers,
    make_warranty_analyst_headers,
)
from .fixtures import *  # noqa: F401,F403

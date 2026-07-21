"""Barrel export: framework generics + PRD-specific test infrastructure."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific modules.
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS, UW1, UW2, CA1, CO1, CO2, RA1, ADMIN1,
    make_underwriter_headers, make_claims_adjuster_headers,
    make_compliance_officer_headers, make_platform_admin_headers,
    make_recovery_agent_headers, make_landlord_headers, make_applicant_headers,
)
from .fixtures import *  # noqa: F401,F403

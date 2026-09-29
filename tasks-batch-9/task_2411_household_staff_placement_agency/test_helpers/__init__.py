"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, VALIDATION_PRECEDENCE, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_NAMES,
    COMPLIANCE_OPENER_USER_ID,
    COMPLIANCE_RESOLVER_USER_ID,
    TEST_USERS,
    VETTING_RECORDER_USER_ID,
    VETTING_VERIFIER_USER_ID,
    make_agency_principal_headers,
    make_billing_administrator_headers,
    make_candidate_headers,
    make_client_headers,
    make_compliance_officer_headers,
    make_placement_consultant_headers,
    make_vetting_specialist_headers,
)
from .fixtures import *  # noqa: F401,F403

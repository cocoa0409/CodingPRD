"""Test helper package for the post-election audit and recount service.

Re-exports the generic framework validators alongside the PRD-specific client,
error catalogue, assertions, factories and composite setup helpers, so a test
module needs a single import root.
"""

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

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    ALL_ROLE_NAMES,
    TEST_USERS,
    make_audit_manager_headers,
    make_candidate_representative_headers,
    make_canvassing_board_member_headers,
    make_custody_officer_headers,
    make_elections_director_headers,
    make_observer_headers,
    make_tally_team_lead_headers,
)

__all__ = [
    # framework generics
    "validate_success",
    "validate_error",
    "validate_paginated",
    "validate_error_is_one_of",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # PRD-specific
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "ALL_ROLE_NAMES",
    "make_elections_director_headers",
    "make_audit_manager_headers",
    "make_custody_officer_headers",
    "make_canvassing_board_member_headers",
    "make_candidate_representative_headers",
    "make_tally_team_lead_headers",
    "make_observer_headers",
    "types",
    "constants",
    "factories",
    "assertions",
    "fixtures",
]

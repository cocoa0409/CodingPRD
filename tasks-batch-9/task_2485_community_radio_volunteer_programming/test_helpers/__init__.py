"""Test helper package for the community radio volunteer programming API.

Re-exports the framework generics alongside this suite's domain helpers so a
test module can pull everything it needs from one place.
"""

from prd_bench_local_runner.testing import (
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

from . import assertions, constants, factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    DEVELOPMENT_HEADERS,
    DEVELOPMENT_ONE,
    DIRECTOR_HEADERS,
    DIRECTOR_ONE,
    OFFICER_ADJUDICATOR,
    OFFICER_COPY_DESK,
    OFFICER_HEADERS,
    OFFICER_LOGS,
    OFFICER_ONE,
    OFFICER_SWEEPER,
    OFFICER_TWO,
    TEST_USERS,
    TRAINER_HEADERS,
    TRAINER_ONE,
    make_committee_member_headers,
    make_compliance_officer_headers,
    make_development_coordinator_headers,
    make_program_director_headers,
    make_training_coordinator_headers,
    make_volunteer_headers,
)
from .types import UserRole

__all__ = [
    # framework generics
    "GenericApiClient",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "run_race",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    # suite helpers
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "UserRole",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    # identities
    "TEST_USERS",
    "DIRECTOR_HEADERS",
    "OFFICER_HEADERS",
    "TRAINER_HEADERS",
    "DEVELOPMENT_HEADERS",
    "DIRECTOR_ONE",
    "TRAINER_ONE",
    "DEVELOPMENT_ONE",
    "OFFICER_ONE",
    "OFFICER_TWO",
    "OFFICER_ADJUDICATOR",
    "OFFICER_COPY_DESK",
    "OFFICER_LOGS",
    "OFFICER_SWEEPER",
    "make_volunteer_headers",
    "make_committee_member_headers",
    "make_program_director_headers",
    "make_compliance_officer_headers",
    "make_training_coordinator_headers",
    "make_development_coordinator_headers",
]

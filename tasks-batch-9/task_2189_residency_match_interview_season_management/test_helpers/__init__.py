"""Test helpers for the residency match interview season API.

Importing this package registers the PRD §5 error-to-HTTP-status map with the
shared validator layer, so ``validate_error`` checks status codes too.
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    NRMP_ADMIN_HEADERS,
    PROGRAM_COORDINATOR_HEADERS,
    TEST_USERS,
    make_applicant_headers,
    make_committee_member_headers,
    make_compliance_officer_headers,
    make_interviewer_headers,
    make_nrmp_admin_headers,
    make_program_coordinator_headers,
    make_program_director_headers,
    make_reviewer_headers,
)
from .types import *  # noqa: F401,F403

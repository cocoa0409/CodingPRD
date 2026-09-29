"""Test infrastructure for the multi-dose adherence packaging API.

Re-exports the framework generics together with this suite's typed client,
factories, domain assertions and composite state builders, so that a test file
needs a single import.
"""

# Framework generics.
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

# Suite-specific infrastructure.
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    PHARMACIST_ID,
    PHARMACIST_ID_2,
    PHARMACY_OPS_ID,
    PLATFORM_ADMIN_ID,
    PRESCRIBER_ID,
    PRESCRIBER_ID_2,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
    TECHNICIAN_ID_3,
    TEST_USERS,
    admin_headers,
    headers_for_role,
    ops_headers,
    patient_headers,
    pharmacist_headers,
    prescriber_headers,
    technician_headers,
    unauthenticated_headers,
)
from .types import *  # noqa: F401,F403

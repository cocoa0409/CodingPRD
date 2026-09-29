"""Test infrastructure for the resilient-flooring plant operations API.

Importing this package registers the PRD's error-code/HTTP-status map with the
framework validators, so ``validate_error`` can check status codes on its own.

Everything a test needs is re-exported here: framework generics, the endpoint
client, the error catalogue, domain assertions, payload factories, PRD-quoted
constants, role headers and the composite setup helpers.
"""

# Framework generics.
from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALL_ROLE_HEADERS,
    FORMULATOR,
    FORMULATOR_B,
    PLANT_ADMIN,
    PRODUCTION_PLANNER,
    QA_TECHNICIAN,
    QA_TECHNICIAN_B,
    TECHNICAL_DIRECTOR,
    TECHNICAL_DIRECTOR_B,
    TEST_USERS,
    USER_IDS,
    WARRANTY_ADJUSTER,
    WARRANTY_ADJUSTER_B,
    distributor_headers,
)
from .types import *  # noqa: F401,F403

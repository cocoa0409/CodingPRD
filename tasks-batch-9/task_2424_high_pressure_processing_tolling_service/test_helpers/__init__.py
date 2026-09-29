"""Barrel export: framework generics plus the code specific to this API."""

# Framework generics (re-exported so tests have a single import source).
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

# API-specific code.
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    NOT_FOUND_BY_ENTITY,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_ROOT,
    ALL_ROLE_NAMES,
    OPERATOR_BOB,
    OPERATOR_INES,
    QM_ALICE,
    QM_CAROL,
    QM_DAVE,
    SCHEDULER_NINA,
    TEST_USERS,
    make_customer_headers,
    make_facility_admin_headers,
    make_plant_operator_headers,
    make_plant_scheduler_headers,
    make_quality_manager_headers,
)
from .types import *  # noqa: F401,F403

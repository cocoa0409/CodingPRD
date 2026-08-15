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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (
    ADMIN_1,
    PO_1,
    QE_ALICE,
    QE_CAROL,
    QM_BOB,
    RA_1,
    SQE_1,
    TEST_USERS,
    make_production_operator_headers,
    make_quality_engineer_headers,
    make_quality_manager_headers,
    make_qms_admin_headers,
    make_regulatory_affairs_headers,
    make_supplier_quality_engineer_headers,
)
from .fixtures import *  # noqa: F401,F403

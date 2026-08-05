"""Barrel export: framework generics plus this program's own test helpers."""

# Framework generics (re-exported for convenience)
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

from . import fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMITTING_PHYSICIAN,
    BILLING_ANALYST,
    COMMUNITY_PARAMEDIC,
    FIELD_NURSE,
    LOGISTICS_COORDINATOR,
    NO_AUTH_HEADERS,
    PHARMACY_AUTHORIZER,
    PROGRAM_ADMIN,
    TEST_USERS,
    make_admitting_physician_headers,
    make_billing_analyst_headers,
    make_community_paramedic_headers,
    make_field_nurse_headers,
    make_logistics_coordinator_headers,
    make_patient_headers,
    make_pharmacy_authorizer_headers,
    make_program_admin_headers,
)
from .types import *  # noqa: F401,F403

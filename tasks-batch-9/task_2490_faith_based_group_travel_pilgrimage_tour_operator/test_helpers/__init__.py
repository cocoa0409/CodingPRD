"""Test helpers for the faith-based group travel and pilgrimage tour operator API.

Importing this package registers the PRD §5 error catalogue with the framework's
validators, so `validate_error` can check the HTTP status on the test's behalf.
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
    ALL_ROLE_NAMES,
    OPERATOR_ROLE_NAMES,
    TEST_USERS,
    make_air_desk_agent_headers,
    make_finance_controller_headers,
    make_group_leader_headers,
    make_headers,
    make_land_contractor_headers,
    make_program_manager_headers,
    make_protection_administrator_headers,
    make_risk_officer_headers,
)
from .types import (
    ALL_ROLES,
    OPERATOR_ROLES,
    AirBlockRow,
    DepartureRow,
    GroupLeaderAgreementRow,
    LandAssignmentRow,
    LandResourceRow,
    PaymentPlanRow,
    PaymentRow,
    PilgrimRow,
    ProgramRow,
    RiskAdvisoryRow,
    SacredSiteRow,
    ServiceBookingRow,
    TravelProtectionRow,
)

"""Barrel export: framework generics plus this PRD's own test infrastructure."""

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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import (  # noqa: F401
    HTTP_STATUS_CODES,
    NOT_FOUND_BY_COLLECTION,
    ApiErrorId,
)
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ANCHOR_INSPECTOR_USER_ID,
    CLAIMS_ADJUSTER_USER_ID,
    FINAL_INSPECTOR_USER_ID,
    NETWORK_ADMIN_USER_ID,
    PERMIT_DESK_USER_ID,
    SITE_INSPECTOR_USER_ID,
    TEST_USERS,
    headers_for_role,
    make_claims_adjuster_headers,
    make_inspector_headers,
    make_network_admin_headers,
    make_permit_desk_headers,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    make_transport_manager_headers,
)
from .types import *  # noqa: F401,F403

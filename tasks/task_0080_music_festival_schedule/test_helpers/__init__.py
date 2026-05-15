"""Barrel-export for the festival-program-schedule test helpers.

Tests import every name they need from this single source — the
framework's generic validators and race utilities, the PRD-specific
ApiClient with its endpoint methods, the entity-shape assertion helpers,
the constants block, the role-header bundles, the payload factories, and
the composite fixture helpers.
"""
# --- Framework generics — re-exported so tests have one import source.
from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
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

# --- PRD-specific
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    AUDIT_HEADERS,
    LIAISON_HEADERS,
    NO_HEADERS,
    PRODUCER_HEADERS,
    ROLE_ALLOWLISTS,
    SPONSOR_HEADERS,
    STAGE_HEADERS,
    TEST_USERS,
    TICKETING_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    header_bundle_for_role,
    header_bundle_outside_set,
)
from .types import *  # noqa: F401,F403

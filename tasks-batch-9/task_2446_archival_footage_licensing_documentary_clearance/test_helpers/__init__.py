"""Test helpers for the Archival Footage Licensing and Documentary Clearance API.

A single import surface: framework primitives re-exported alongside the
domain client, payload factories, entity assertions and setup helpers.
"""

# ─── Framework primitives ────────────────────────────────────────────────────
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

# ─── Domain surface ──────────────────────────────────────────────────────────
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ARCHIVE_RESEARCHER,
    ARCHIVE_RESEARCHER_USER_ID,
    CLEARANCE_SUPERVISOR,
    CLEARANCE_SUPERVISOR_USER_ID,
    LEGAL_COUNSEL,
    LEGAL_COUNSEL_USER_ID,
    PRODUCTION_ADMIN,
    PRODUCTION_ADMIN_USER_ID,
    REVIEWING_COUNSEL,
    REVIEWING_COUNSEL_USER_ID,
    SECOND_SUPERVISOR,
    SECOND_SUPERVISOR_USER_ID,
    TEST_USERS,
    make_archive_researcher_headers,
    make_clearance_supervisor_headers,
    make_legal_counsel_headers,
    make_production_admin_headers,
    make_rights_holder_rep_headers,
)
from .types import *  # noqa: F401,F403

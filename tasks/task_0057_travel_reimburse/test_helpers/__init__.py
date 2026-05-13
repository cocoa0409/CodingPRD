"""Barrel export for the Travel Reimburse test helpers.

Combines:
- Framework generics (validators, format checkers, race utilities,
  build_user_headers, NON_EXISTENT_UUID) re-exported for convenience.
- PRD-specific types, api_client, errors, assertions, factories,
  constants, role headers, and composite fixtures.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Framework generics
# ---------------------------------------------------------------------------
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# ---------------------------------------------------------------------------
# PRD-specific exports
# ---------------------------------------------------------------------------
from .types import *  # noqa: F401, F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401, F403
from .factories import *  # noqa: F401, F403
from .constants import *  # noqa: F401, F403
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_admin_headers,
    make_applicant_headers,
    make_supervisor_headers,
    make_dept_head_headers,
    make_finance_headers,
    make_general_manager_headers,
)
from .fixtures import *  # noqa: F401, F403

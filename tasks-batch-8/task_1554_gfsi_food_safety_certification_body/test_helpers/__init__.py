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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import TEST_USERS
from . import test_users as _test_users
from .fixtures import *

make_scheme_admin_headers = _test_users.make_scheme_admin_headers
make_client_admin_headers = _test_users.make_client_admin_headers
make_auditor_headers = _test_users.make_auditor_headers
make_decision_maker_headers = _test_users.make_decision_maker_headers
make_anonymous_headers = _test_users.make_anonymous_headers

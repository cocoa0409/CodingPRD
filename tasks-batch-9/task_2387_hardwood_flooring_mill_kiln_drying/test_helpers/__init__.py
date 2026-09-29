"""Test helpers for the hardwood flooring mill API.

A single import surface for the test suite: the framework's HTTP/validation
primitives, the typed entity shapes, the endpoint client, the error catalogue,
the domain constants, the payload factories, the entity assertions, the role
headers and the composite setup helpers.
"""

# --- framework primitives -------------------------------------------------
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

# --- local helpers --------------------------------------------------------
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .assertions import __all__ as _assertions_all
from .constants import *  # noqa: F401,F403
from .constants import __all__ as _constants_all
from .factories import *  # noqa: F401,F403
from .factories import __all__ as _factories_all
from .fixtures import *  # noqa: F401,F403
from .fixtures import __all__ as _fixtures_all
from .test_users import *  # noqa: F401,F403
from .test_users import __all__ as _test_users_all
from .types import *  # noqa: F401,F403
from .types import __all__ as _types_all

__all__ = [
    # framework
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_paginated",
    "validate_error_is_one_of",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # local
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    *_types_all,
    *_constants_all,
    *_factories_all,
    *_assertions_all,
    *_test_users_all,
    *_fixtures_all,
]

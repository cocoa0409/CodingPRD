"""Test infrastructure for the District Energy System Operations API.

A single import point for the suite: the framework's generic response validators
and race helpers, the typed client, the error catalogue, the domain assertions,
the payload factories, the numeric constants, the role header sets and the
composite setup helpers.

Importing this package also registers the error_id to HTTP status mapping, so
``validate_error(response, ApiErrorId.LOOP_NOT_FOUND)`` checks the status code
without the call site restating it.
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
    # framework generics
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "run_race",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # local infrastructure
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    *_types_all,
    *_constants_all,
    *_test_users_all,
    *_factories_all,
    *_assertions_all,
    *_fixtures_all,
]

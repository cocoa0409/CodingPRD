"""Test helper package for the performing arts center season API.

Importing this package registers the error-to-HTTP-status map with the shared
validators, so ``validate_error()`` checks the status code of every rejection
without the test having to name it.
"""

from prd_bench_local_runner.testing import (
    GenericApiClient,
    NON_EXISTENT_UUID,
    assert_cost_precision,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
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

_FRAMEWORK_EXPORTS = [
    "GenericApiClient",
    "NON_EXISTENT_UUID",
    "assert_cost_precision",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "assert_at_least_one_succeeds",
    "assert_exactly_one_succeeds",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]

__all__ = (
    _FRAMEWORK_EXPORTS
    + ["ApiClient", "api_client", "ApiErrorId", "HTTP_STATUS_CODES"]
    + list(_types_all)
    + list(_constants_all)
    + list(_test_users_all)
    + list(_factories_all)
    + list(_assertions_all)
    + list(_fixtures_all)
)

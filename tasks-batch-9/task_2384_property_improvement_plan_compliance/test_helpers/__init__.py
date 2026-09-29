"""Test infrastructure for the Property Improvement Plan Compliance API.

Importing this package gives a test everything it needs: the framework's generic
request/response validators, the endpoint-per-method client, the error-id catalogue
(whose HTTP status map is registered with the framework as a side effect of the
import), the domain assertions, the payload factories, the business constants and
the composite setup helpers.
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
    # Framework generics
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "build_user_headers",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_timestamp_format",
    "assert_version_incremented",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "NON_EXISTENT_UUID",
    # Client and error catalogue
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
]

__all__ += list(_types_all)
__all__ += list(_test_users_all)
__all__ += list(_constants_all)
__all__ += list(_factories_all)
__all__ += list(_assertions_all)
__all__ += list(_fixtures_all)

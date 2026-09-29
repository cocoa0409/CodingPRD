"""Test helpers for the Marine Bunkering & Vessel Fuel Supply API.

A single import surface for the whole suite: the framework generics
(``validate_success``, ``validate_error``, ``run_race`` and friends) alongside the
API-specific client, error catalogue, payload factories, domain assertions, role
headers and composite state builders.
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
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403

from . import assertions as _assertions
from . import constants as _constants
from . import factories as _factories
from . import fixtures as _fixtures
from . import test_users as _test_users
from . import types as _types

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
    "assert_timestamp_format",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "NON_EXISTENT_UUID",
    # API-specific
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
] + (
    list(_types.__all__)
    + list(_constants.__all__)
    + list(_assertions.__all__)
    + list(_factories.__all__)
    + list(_test_users.__all__)
    + list(_fixtures.__all__)
)

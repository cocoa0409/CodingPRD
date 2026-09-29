"""Test infrastructure for the Instant Payments Participation & Liquidity API.

A single barrel import so that a test module names only the behaviour it needs:
the framework generics, the endpoint client, the error catalogue, the entity
assertions, the payload factories, the business constants, the shared identities
and the composite scenario builders.
"""

# Framework generics, re-exported so tests have one import source.
from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
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

from . import api_errors  # noqa: F401
from . import constants  # noqa: F401
from . import factories  # noqa: F401
from . import fixtures  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403

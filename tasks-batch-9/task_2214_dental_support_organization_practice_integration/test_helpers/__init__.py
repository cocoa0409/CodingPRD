"""Test helpers for the DSO Practice Integration API compliance suite.

Importing this package registers the error-to-HTTP-status map with the
framework validators, so `validate_error` cross-checks status codes.
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
from .constants import (
    CLOCK_CLOSE_DAY,
    CLOCK_DEFAULT_UTC,
    FINANCE_RESERVER_USER_ID,
    FINANCE_SETTLER_USER_ID,
    OPEN_ENDED_TERM_DATE,
    TEST_DEFAULTS,
    THRESHOLDS,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
)
from .factories import *  # noqa: F401,F403
from .factories import __all__ as _factories_all
from .fixtures import *  # noqa: F401,F403
from .fixtures import __all__ as _fixtures_all
from .test_users import (
    ALL_ROLE_NAMES,
    TEST_USERS,
    make_clinical_director_headers,
    make_deal_counsel_headers,
    make_dentist_headers,
    make_finance_controller_headers,
    make_integration_lead_headers,
    no_identity_headers,
)
from .types import *  # noqa: F401,F403
from .types import __all__ as _types_all

__all__ = (
    [
        # framework generics
        "GenericApiClient",
        "validate_success",
        "validate_error",
        "validate_error_is_one_of",
        "validate_paginated",
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
        # local surface
        "ApiClient",
        "api_client",
        "ApiErrorId",
        "HTTP_STATUS_CODES",
        "THRESHOLDS",
        "TEST_DEFAULTS",
        "CLOCK_DEFAULT_UTC",
        "CLOCK_CLOSE_DAY",
        "OPEN_ENDED_TERM_DATE",
        "UNKNOWN_UUID",
        "UNKNOWN_UUID_ALT",
        "FINANCE_RESERVER_USER_ID",
        "FINANCE_SETTLER_USER_ID",
        "TEST_USERS",
        "ALL_ROLE_NAMES",
        "make_deal_counsel_headers",
        "make_integration_lead_headers",
        "make_finance_controller_headers",
        "make_clinical_director_headers",
        "make_dentist_headers",
        "no_identity_headers",
    ]
    + list(_types_all)
    + list(_assertions_all)
    + list(_factories_all)
    + list(_fixtures_all)
)

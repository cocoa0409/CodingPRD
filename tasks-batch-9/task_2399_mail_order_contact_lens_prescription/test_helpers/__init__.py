"""Test helpers for the mail-order contact lens prescription platform.

One import surface for the whole suite: the framework generics are re-exported
alongside the domain-specific client, payload factories, assertions, constants,
role headers and composite setup helpers.

    from test_helpers import (
        api_client, validate_success, validate_error, ApiErrorId,
        setup_delivered_order, CO_ALPHA_HEADERS,
    )
"""

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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_HEADERS,
    CO_ALPHA_HEADERS,
    CO_BRAVO_HEADERS,
    FO_HEADERS,
    TEST_USERS,
    make_admin_headers,
    make_compliance_headers,
    make_customer_headers,
    make_fulfillment_headers,
    make_prescriber_headers,
)
from .types import *  # noqa: F401,F403

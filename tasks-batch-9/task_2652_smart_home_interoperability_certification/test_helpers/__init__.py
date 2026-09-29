"""Test infrastructure for the Smart Home Interoperability Certification API.

Importing this package registers the error-to-HTTP-status map with the shared
validators, so ``validate_error`` cross-checks every rejection's status code.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from . import api_errors, constants, factories, types  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .assertions import (  # noqa: F401
    as_decimal,
    assert_cents,
    assert_common_fields,
    assert_credit_ledger_invariant,
    assert_freshly_created,
    assert_listing_reference,
    assert_penalty,
    assert_ratio_equals,
    assert_reserved_bench_minutes,
    assert_score,
    assert_states,
    assert_version,
    capacity_ceiling,
    expected_certification_fee,
    expected_penalty,
    ratio,
    round_cents,
    round_half_up,
    score_from_components,
    weighted_component,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403

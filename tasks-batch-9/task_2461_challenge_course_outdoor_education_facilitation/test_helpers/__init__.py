"""Shared test infrastructure for the Challenge Course Operations API."""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import api_errors, assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .assertions import (  # noqa: F401
    assert_append_only_record,
    assert_belay_requirement,
    assert_course_counters,
    assert_element_forecast,
    assert_error_envelope_meta,
    assert_instant,
    assert_kg,
    assert_ledger,
    assert_money,
    assert_one_decimal,
    assert_posture,
    assert_settlement,
    assert_versioned_record,
)
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    PROGRAM_DIRECTOR,
    PROGRAM_DIRECTOR_USER_ID,
    make_facilitator_headers,
    make_group_coordinator_headers,
    make_headers,
    make_professional_inspector_headers,
    make_program_director_headers,
    make_safety_officer_headers,
)

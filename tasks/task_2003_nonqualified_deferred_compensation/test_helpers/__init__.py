"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
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

# PRD-specific
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_account,
    assert_account_invariants,
    assert_cic_event,
    assert_crediting_run,
    assert_deferral_election,
    assert_distribution_request,
    assert_document_finding,
    assert_election_window,
    assert_ledger_entry,
    assert_notional_fund,
    assert_operational_failure,
    assert_participant,
    assert_plan,
    assert_rabbi_trust,
    assert_separation_case,
    assert_specified_employee_list,
)
from .constants import CLOCK_START, TEST_DEFAULTS, THRESHOLDS
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_participant_headers,
)
from .types import *  # noqa: F401,F403

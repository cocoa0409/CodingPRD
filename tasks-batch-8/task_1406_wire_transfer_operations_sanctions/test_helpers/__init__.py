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
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *
from .factories import *
from .constants import (
    BENEPAY_SHARE,
    DEDUCTED_FACTOR,
    LOGICAL_CLOCK_START,
    TEST_DEFAULTS,
    THRESHOLDS,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_beneficiary_bank_headers,
    make_compliance_officer_headers,
    make_fraud_analyst_headers,
    make_repair_specialist_headers,
    make_sanctions_screener_headers,
    make_wire_approver_headers,
    make_wire_investigator_headers,
    make_wire_ops_admin_headers,
    make_wire_operator_headers,
)
from .fixtures import *

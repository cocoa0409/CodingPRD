"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import TEST_USERS
from . import fixtures
from .fixtures import (
    create_case,
    create_and_approve_case,
    create_case_with_statement,
    create_case_with_plan,
    create_case_with_review,
    set_clock,
    get_clock,
    create_revocation_task,
    create_asset_item,
    create_exit_interview,
    create_benefits_notice,
    create_covenant_ack,
    create_kt_session,
    make_task_ready,
    execute_task,
    verify_task,
    drive_task_to_verified,
    calculate_statement,
    approve_statement,
    disburse_statement,
    drive_case_to_payroll_pending,
    drive_case_to_clearance,
    drive_case_to_ready_to_close,
    close_case,
    ADMIN,
    HR_INTAKE,
    HR_APPROVER,
    HR_REVIEWER,
    HR_DIRECTOR,
    PAYROLL_CALC,
    PAYROLL_APPROVER,
    IT_OP,
    IT_VER,
    IT_MGR,
    MGR,
    CLERK,
    BEN_ADMIN,
)

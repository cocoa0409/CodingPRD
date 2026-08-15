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
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_academic_year,
    assert_attendance_entry,
    assert_compliance_report,
    assert_coop_class,
    assert_coop_enrollment,
    assert_course_credit,
    assert_curriculum_plan,
    assert_enrollment,
    assert_evaluation,
    assert_exam_session,
    assert_family,
    assert_family_ledger,
    assert_graduation_application,
    assert_notice,
    assert_portfolio,
    assert_student,
    assert_test_registration,
    assert_transcript,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_director_headers,
    make_parent_headers,
    make_reviewer_headers,
)
from .types import *  # noqa: F401,F403

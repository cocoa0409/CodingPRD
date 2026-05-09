"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import (
    UserRole, DepartmentStatus, StudentStatus, ProfessorRank, TermStatus,
    CourseOfferingStatus, EnrollmentRequestAcademicStatus,
    EnrollmentRequestFinancialStatus, OverLimitApplicationStatus,
    WaitlistEntryStatus, DepartmentAccessGrantStatus, SyncEventType,
    Department, Campus, Student, Professor, Term, Course, CourseOffering,
    LabEquipment, EnrollmentRequest, OverLimitApplication, DepartmentAccessGrant,
    WaitlistEntry, CreditEquivalencePolicy, SyncEvent,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_department, assert_campus, assert_student, assert_professor,
    assert_term, assert_course, assert_course_offering, assert_lab_equipment,
    assert_enrollment_request, assert_over_limit_application,
    assert_department_access_grant, assert_waitlist_entry,
    assert_credit_equivalence_policy, assert_sync_event,
    assert_credit_precision, assert_offering_capacity_invariant,
    find_sync_event, has_sync_event,
)
from .factories import (
    create_student_payload, create_department_payload, create_campus_payload,
    create_professor_payload, create_lab_equipment_payload, create_term_payload,
    create_course_payload, create_course_offering_payload,
    create_enrollment_request_payload, create_over_limit_application_payload,
    create_department_access_grant_payload, create_credit_equivalence_policy_payload,
    advance_clock_payload,
)
from .constants import (
    PRIORITY_WEIGHTS, CREDIT_QUOTA_TIERS, FRAUD, RECOMMENDATION_WEIGHTS,
    CREDIT_DECIMAL_PLACES, PAGINATION, SYNC_TARGETS, DEFAULTS,
)
from .test_users import (
    TEST_USERS, make_student_headers, make_professor_headers,
    make_registrar_headers, make_finance_headers,
)
from .fixtures import (
    advance_clock, run_sweep,
    create_campus, create_department, create_professor, create_student,
    create_lab_equipment, create_course, create_term_in_planning,
    create_offering, open_offering, close_offering,
    setup_basic_world, setup_open_offering,
    submit_enrollment, submit_enrollment_success,
    cancel_enrollment, settle_tuition,
    setup_offering_with_seat_taken, get_offering, get_enrollment_request,
    list_waitlist, list_student_sync_events,
    create_over_limit_application, submit_application,
    sign_application, reject_application, revise_application, get_application,
    setup_cross_department_world, grant_cross_department_access,
    setup_two_program_world_with_completed_source_course,
    create_credit_equivalence_policy, get_degree_plan,
    load_student_credits_via_approved, raise_student_fraud_score,
    get_student,
)

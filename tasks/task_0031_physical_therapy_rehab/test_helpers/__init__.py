"""Barrel export: framework generics + PT-rehab-specific test helpers."""
# Framework generics (re-exported for convenience).
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

# Domain types
from .types import (  # noqa: F401
    PatientStatus,
    PlanOfCareStatus,
    CappedStatus,
    AuthorizationGrantStatus,
    VisitStatus,
    HomeExerciseProgramStatus,
    VeteranReferralStatus,
    MIPSStatus,
    EvaluationKind,
    CPTCode,
    InsuranceType,
    MIPSMeasureCode,
    DischargeOutcome,
    UserRole,
    Patient,
    Therapist,
    VeteranReferral,
    PlanOfCare,
    Evaluation,
    AuthorizationGrant,
    Visit,
    HomeExerciseProgram,
    MIPSQualityMeasure,
    DischargeAssessment,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_common_fields,
    assert_patient,
    assert_therapist,
    assert_veteran_referral,
    assert_plan_of_care,
    assert_evaluation,
    assert_authorization_grant,
    assert_visit,
    assert_home_exercise_program,
    assert_mips_measure,
    assert_discharge_assessment,
    assert_grant_consumption_invariant,
    assert_capped_posture_consistent,
)

# Payload factories
from .factories import (
    create_patient_payload,
    create_therapist_payload,
    create_veteran_referral_payload,
    create_plan_of_care_payload,
    recertify_plan_payload,
    create_evaluation_payload,
    create_authorization_grant_payload,
    create_visit_payload,
    complete_visit_payload,
    finalize_visit_payload,
    create_home_exercise_program_payload,
    create_mips_measure_payload,
    revise_mips_payload,
    create_discharge_assessment_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    CAPPED_DOLLAR_LIMIT_CENTS,
    WARNING_RATIO,
    UNIT_MINUTES,
    MIN_BILLABLE_MINUTES,
    CPT_RATE_CENTS,
    MPPR_FACTOR,
    MIPS_BASE_SCORE,
    MIPS_NUMERATOR_BONUS,
    MIPS_ENGAGEMENT_PER_HEP,
    MIPS_ENGAGEMENT_CAP,
    MIPS_IMPROVEMENT_FACTOR,
    MIPS_IMPROVEMENT_CAP,
    MIPS_ACCEPTANCE_THRESHOLD,
    DISCHARGE_SUCCESS_THRESHOLD,
    DISCHARGE_PARTIAL_THRESHOLD,
    DEFAULT_DIAGNOSIS_ICD10,
    DEFAULT_LICENSE_STATE,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_therapist_headers,
    make_admin_headers,
    make_case_manager_headers,
    make_billing_clerk_headers,
    make_va_coordinator_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    create_therapist,
    create_patient,
    create_veteran_referral,
    create_draft_poc,
    record_initial_evaluation,
    record_re_evaluation,
    activate_poc,
    setup_active_poc,
    setup_active_va_poc,
    create_grant,
    schedule_visit,
    complete_visit,
    get_poc_version,
    finalize_visit,
    complete_and_finalize_visit,
    setup_poc_with_grant,
    setup_completed_visit,
    setup_recert_due_poc,
    record_discharge_assessment,
    discharge_poc,
    create_hep,
    create_mips,
)

"""Barrel export: framework generics + Special-Education-IEP-specific helpers."""
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
    UserRole,
    StudentEligibilityStatus,
    DisabilityCategory,
    EvaluationStatus,
    EvalType,
    EvaluationOutcome,
    IEPStatus,
    LRESetting,
    GoalDomain,
    GoalStatus,
    ServiceType,
    RelatedServiceStatus,
    ConsentType,
    ConsentStatus,
    ConsentDecision,
    TransitionPlanStatus,
    Student,
    Evaluation,
    IEP,
    Goal,
    ProgressReport,
    RelatedService,
    ConsentRequest,
    TransitionPlan,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (  # noqa: F401
    assert_common_fields,
    assert_student,
    assert_evaluation,
    assert_iep,
    assert_goal,
    assert_progress_report,
    assert_progress_report_is_immutable,
    assert_related_service,
    assert_consent_request,
    assert_transition_plan,
)

# Factories
from .factories import (  # noqa: F401
    DEFAULTS,
    set_clock_payload,
    create_student_payload,
    create_evaluation_payload,
    decide_consent_payload,
    create_iep_payload,
    open_amendment_payload,
    create_goal_payload,
    create_progress_report_payload,
    create_related_service_payload,
    discontinue_related_service_payload,
    create_transition_plan_payload,
)

# Constants
from .constants import (  # noqa: F401
    ELIGIBILITY_THRESHOLD,
    W_ADAPTIVE,
    W_ACADEMIC,
    GAP_WEIGHT_INITIAL,
    GAP_WEIGHT_TRIENNIAL,
    DAYS_PER_WEEK,
    FULL_INCLUSION_FLOOR,
    RESOURCE_FLOOR,
    TRANSITION_AGE,
    REEVAL_WINDOW_DAYS,
    PAGINATION,
)

# Role headers
from .test_users import (  # noqa: F401
    TEST_USERS,
    make_admin_headers,
    make_case_manager_headers,
    make_evaluator_headers,
    make_parent_headers,
    make_headers,
)

# Composite fixtures
from .fixtures import (  # noqa: F401
    DEFAULT_CLOCK,
    set_clock,
    create_student,
    get_student,
    get_iep,
    iep_version,
    get_goal,
    make_eligible_student,
    make_finalized_evaluation,
    make_evaluation_in_progress,
    create_draft_iep,
    make_draft_iep_for_eligible_student,
    grant_placement_consent,
    make_meeting_held_iep,
    make_active_iep,
    create_goal,
    make_goal_on_eligible_student,
    record_progress_report,
    setup_goal_with_reports,
    add_related_service,
    make_draft_iep_with_service,
    discontinue_service,
    create_transition_plan,
)

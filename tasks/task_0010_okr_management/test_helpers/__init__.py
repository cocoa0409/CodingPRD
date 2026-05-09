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
    UserRole, UserStatus, UserRoleType,
    CycleStatus, ObjectiveLevel, ObjectiveStatus,
    MeasurementType, KeyResultStatus, ProgressUpdateType,
    DependencyType, AlignmentLinkStatus, CoOwnershipStatus,
    ReviewStatus, AccessGrantStatus, SourceSystem, ProcessingStatus,
    AuditEntityType, AuditAction,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_score_in_range, assert_4dp,
    assert_common_fields, assert_append_only_fields,
    assert_department, assert_user, assert_cycle,
    assert_objective, assert_key_result, assert_progress_update,
    assert_alignment_link, assert_co_ownership, assert_review_score,
    assert_access_grant, assert_audit_log, assert_external_event,
)
from .factories import (
    create_department_payload, create_user_payload, create_cycle_payload,
    create_objective_payload, create_kr_payload,
    create_numeric_kr_payload, create_percentage_kr_payload, create_milestone_kr_payload,
    create_value_change_payload, create_milestone_toggle_payload,
    create_alignment_link_payload, create_reject_link_payload,
    create_co_owner_payload, create_access_grant_payload,
    self_submit_payload, manager_submit_payload, calibrate_payload,
    create_external_event_payload,
)
from .constants import (
    PRECISION_DECIMALS, WEIGHT_TOLERANCE,
    STALE_THRESHOLD_DAYS, SECONDS_PER_DAY,
    ATTENUATION, UPSTREAM_INFLUENCE,
    MIN_CALIBRATION_DELTA, SELF_WEIGHT, MANAGER_WEIGHT, CALIBRATION_DELTA_TRIGGER,
    DEDUP_WINDOW_MINUTES, DEDUP_WINDOW_SECONDS,
    PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers, make_manager_headers,
    make_admin_headers, make_hrbp_headers,
)
from .fixtures import (
    create_department, create_user,
    create_cycle, open_cycle, create_open_cycle,
    create_objective, add_kr,
    add_numeric_kr, add_percentage_kr, add_milestone_kr,
    publish_objective, post_progress, post_value_change, post_milestone_toggle,
    setup_org,
    setup_active_individual_objective, setup_objective_with_progress,
    setup_alignment_pair, setup_accepted_alignment_pair,
    setup_three_level_hierarchy,
    setup_review_at_pending_self, setup_review_at_pending_manager,
    setup_review_at_pending_calibration, setup_locked_review,
    setup_dual_variant_objective, setup_objective_with_two_active_krs,
    setup_confidential_objective,
    setup_locked_cycle_with_two_objectives_and_link,
)

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
    UserRole, PolicyStatus, CoverageType, AdjusterStatus, RepairShopStatus,
    ClaimStatus, ReportChannel, ReviewPath, InvestigationStatus,
    ReviewLevel, ReviewOutcome, AppealStatus, AppealOutcome, PayoutStatus,
    FraudSignal, AuditEventType,
    Policy, Adjuster, RepairShop, Claim, Investigation, Appeal, Payout,
    EstimateLineItem, ReviewDecision, FraudFlag, AuditLogEntry,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_policy, assert_adjuster, assert_repair_shop, assert_claim,
    assert_investigation, assert_appeal, assert_payout,
    assert_estimate_line_item, assert_review_decision, assert_fraud_flag,
    assert_audit_log_entry,
    assert_payout_balance_invariant, find_audit_entry, has_audit_entry,
    CLAIM_NUMBER_RE,
)
from .factories import (
    create_policy_payload, create_adjuster_payload, create_repair_shop_payload,
    create_claim_payload, create_investigation_payload, patch_investigation_payload,
    create_estimate_line_item_payload, create_decision_payload,
    create_appeal_payload, create_appeal_decision_payload,
    create_subrogation_payload, create_fraud_flag_payload,
    advance_clock_payload, bank_event_payload,
)
from .constants import (
    AUTO_APPROVAL_THRESHOLD_CENTS, AUTO_FRAUD_GATE, FRAUD_HOLD_THRESHOLD,
    DECAY_PER_FLAG, BLACKLIST_THRESHOLD, COLLUSION_PATTERN_THRESHOLD,
    LOOKBACK_DAYS, W_PATTERN, W_COLLUSION, W_FORGERY, W_RAPID,
    IDEMPOTENCY_WINDOW_HOURS, DEFAULT_REPORTING_WINDOW_DAYS,
    PAGINATION, DEFAULTS, SECONDS_PER_DAY,
)
from .test_users import (
    TEST_USERS, make_adjuster_headers, make_customer_headers,
    make_reviewer_headers, make_payout_officer_headers, make_admin_headers,
)
from .fixtures import (
    # primitive creators
    create_policy, create_adjuster, create_repair_shop,
    patch_policy_status, get_policy, get_repair_shop, get_claim, list_audit_log,
    # control endpoints
    advance_clock, bank_settle, bank_fail,
    # state-progression helpers
    setup_basic_world, file_claim, open_investigation, update_investigation,
    add_estimate_line_item, submit_for_review,
    setup_claim_under_investigation, setup_claim_under_review,
    record_primary_decision, setup_claim_approved, setup_claim_denied,
    create_payout, setup_claim_paid, setup_claim_settled,
    # appeals
    create_appeal, record_appeal_decision, setup_claim_appealed,
    # fraud flags / collusion
    add_fraud_flag, setup_three_collusion_flagged_claims, submit_all_for_review,
    # subrogation
    post_subrogation,
    # time helpers
    now_utc, days_ago, days_ahead,
)

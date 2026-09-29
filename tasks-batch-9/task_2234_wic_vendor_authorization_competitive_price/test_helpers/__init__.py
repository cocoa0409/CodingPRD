"""
Test helpers for the WIC vendor authorization and competitive price API.

Importing this package registers the error-id to HTTP-status map with the
framework, so ``validate_error`` checks both the identifier and the status.

A test file normally needs only::

    from test_helpers import (
        ApiClient, ApiErrorId, validate_success, validate_error, validate_paginated,
        fixtures, factories, ...
    )
"""

# --- Framework re-exports ---------------------------------------------------
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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

# --- Modules, for callers that prefer qualified access ----------------------
from . import assertions, constants, factories, fixtures, types  # noqa: F401

# --- Client and error catalogue ---------------------------------------------
from .api_client import ApiClient
from .api_errors import HTTP_STATUS_CODES, ApiErrorId

# --- Constants --------------------------------------------------------------
from .constants import (
    AVG_REDEMPTION_MONTHS,
    BASE_TIER_BY_VIOLATION,
    CMP_CAP_CENTS,
    CMP_ELECTION_DAYS,
    CMP_MONTHS_BY_TIER,
    CMP_MULTIPLIER_BY_TIER,
    COMPLIANCE_BUY_LEAD_DAYS,
    CURE_PERIOD_DAYS,
    DEFAULT_LIMIT,
    DEFAULT_LOGICAL_CLOCK,
    DEFAULT_LOGICAL_CLOCK_ISO,
    DEFAULT_MIN_SUBMISSIONS_FOR_CEILING,
    DEFAULT_OFFSET,
    DISQ_MONTHS_BY_TIER,
    ELEVATED_TIER_MIN,
    ESCALATION_THRESHOLDS,
    HIGH_RISK_FINDING_THRESHOLD,
    HIGH_TIER_MIN,
    MAX_LIMIT,
    MAX_RISK_SCORE,
    MAX_SUBMISSION_REVISIONS,
    MONITORING_BLACKOUT_DAYS,
    POINT_CAP,
    POINT_WEIGHT,
    POINTS_BY_BASE_TIER,
    REAUTH_CYCLE_MONTHS,
    REAUTH_WINDOW_DAYS,
    RISK_WINDOW_DAYS,
    STATEWIDE_CAP_MULTIPLE,
    TRAINING_VALID_MONTHS,
    UNBOUNDED_BAND_SENTINEL_CENTS,
    W_EDIT,
    W_PRICE,
    W_VISIT,
)

# --- Assertions -------------------------------------------------------------
from .assertions import (
    assert_adjudicated_total_is_sum_of_allowed,
    assert_authorized_food_item,
    assert_ceiling_derivation,
    assert_claim_line,
    assert_claim_line_counts,
    assert_claim_net_payable,
    assert_common_fields,
    assert_field_values,
    assert_food_category,
    assert_iso_millis,
    assert_line_recoupments,
    assert_monitoring_visit,
    assert_no_data_payload,
    assert_peer_group,
    assert_price_ceiling,
    assert_price_cycle,
    assert_price_submission,
    assert_proration_sums_per_line,
    assert_redemption_claim,
    assert_reimbursement_adjustment,
    assert_risk_score_components,
    assert_sanction_case,
    assert_sanction_schedule,
    assert_stock_finding,
    assert_vendor,
    find_stock_finding,
    round_half_up,
    round_half_up_cents,
)

# --- Principals and headers -------------------------------------------------
from .test_users import (
    ANALYST_HEADERS,
    ANALYST_ONE,
    ANALYST_TWO,
    ANALYST_TWO_HEADERS,
    INVESTIGATOR_HEADERS,
    INVESTIGATOR_ONE,
    INVESTIGATOR_TWO,
    INVESTIGATOR_TWO_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_ONE,
    SUPERVISOR_TWO,
    SUPERVISOR_TWO_HEADERS,
    SYSTEM_HEADERS,
    SYSTEM_ONE,
    TEST_USERS,
    make_analyst_headers,
    make_headers,
    make_investigator_headers,
    make_partial_headers,
    make_supervisor_headers,
    make_system_operator_headers,
    make_vendor_operator_headers,
)

# --- Domain enums -----------------------------------------------------------
from .types import (
    SYSTEM_PRINCIPAL,
    AdjustmentReasonCode,
    AdjustmentStatus,
    BlockedReason,
    CeilingBasis,
    CeilingStatus,
    ClaimStatus,
    EditCode,
    EditResult,
    FoodItemStatus,
    FormulaRestrictionLevel,
    MarMethod,
    PeerGroupStatus,
    PriceCycleStatus,
    ReviewDecision,
    ReviewReason,
    RiskBasis,
    RiskFlag,
    RiskTier,
    Role,
    SanctionResolution,
    SanctionStatus,
    StockVerdict,
    StoreType,
    SubmissionStatus,
    SupersededReason,
    TrainingType,
    VendorStatus,
    ViolationCode,
    VisitOutcome,
    VisitStatus,
    VisitType,
    VoidedReason,
)

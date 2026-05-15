"""Barrel export: framework generics + PRD-specific test infrastructure.

Tests import everything from `test_helpers` and never reach into
sub-modules directly.

PRD §2.1 identity rules:
- PlanAdministrator is OPAQUE — TEST_USERS["admin_headers"] is canonical
  for all administrator-only calls.
- Donor is ENTITY-BACKED — every ownership-gated Donor call MUST mint
  headers via make_donor_headers(donor["id"]).
- Beneficiary is ENTITY-BACKED — every ownership-gated Beneficiary read
  MUST mint headers via make_beneficiary_headers(beneficiary["id"]).
"""
# Framework generics — re-exported for convenience.
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

# PRD-specific.
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_account,
    assert_account_balance_invariant,
    assert_beneficiary,
    assert_beneficiary_change_request,
    assert_contribution,
    assert_donor,
    assert_education_expense,
    assert_recurring_plan,
    assert_state_rule,
    assert_tax_report,
    assert_version_incremented_by_one,
    assert_withdrawal,
    assert_withdrawal_classification_sums_to_requested,
    assert_withdrawal_split_sums_to_requested,
)
from .constants import (
    ANNUAL_GIFT_EXCLUSION_CENTS,
    CADENCE_ANNUAL_DAYS,
    CADENCE_BIWEEKLY_DAYS,
    CADENCE_MONTHLY_DAYS,
    CADENCE_QUARTERLY_DAYS,
    CADENCE_WEEKLY_DAYS,
    GENERATION_SKIP_UPWARD_RELATIONSHIPS,
    K12_ANNUAL_CAP_CENTS,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    PENALTY_RATE,
    PERMISSIBLE_RELATIONSHIPS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
    VALID_CADENCE_DAYS,
)
from .factories import (
    attach_education_expense_payload,
    clock_advance_payload,
    create_account_payload,
    create_beneficiary_change_request_payload,
    create_beneficiary_payload,
    create_contribution_payload,
    create_donor_payload,
    create_recurring_plan_payload,
    create_state_rule_payload,
    create_tax_report_payload,
    create_withdrawal_payload,
    date_in_year,
    iso_now,
    iso_offset,
    iso_utc,
    patch_recurring_plan_payload,
    random_ssn_last_four,
    random_suffix,
    reject_beneficiary_change_request_payload,
    reject_withdrawal_payload,
    utcnow,
)
from .fixtures import (
    accumulate_k12_qualified,
    advance_clock_to,
    approve_beneficiary_change,
    attach_expense,
    classify_withdrawal,
    create_beneficiary,
    create_donor,
    create_pending_contribution,
    create_recurring_plan,
    create_state_rule,
    create_tax_report,
    create_withdrawal,
    disburse_withdrawal,
    ensure_state_rule,
    finalize_tax_report,
    open_account,
    release_account,
    restrict_account,
    server_now_date,
    server_now_iso,
    settle_contribution,
    settle_lump_sum,
    setup_account_with_balance,
    setup_donor_beneficiary_account,
    submit_beneficiary_change,
    top_up_account,
    withdraw_and_classify,
)
from .test_users import (
    BENEFICIARY_FALLBACK_ID,
    DONOR_FALLBACK_ID,
    PLAN_ADMINISTRATOR_ID,
    PLAN_ADMINISTRATOR_ID_ALT,
    TEST_USERS,
    make_admin_headers,
    make_beneficiary_headers,
    make_donor_headers,
)
from .types import (
    Account,
    AccountStatus,
    Beneficiary,
    BeneficiaryChangeRequest,
    BeneficiaryChangeRequestRejectionReason,
    BeneficiaryChangeRequestStatus,
    CadenceDays,
    Contribution,
    ContributionKind,
    ContributionStatus,
    Donor,
    EducationExpense,
    ExpenseCategory,
    RecurringPlan,
    RecurringPlanStatus,
    RelationshipFamilyCode,
    StateRule,
    StateRuleParity,
    TaxReport,
    UserRole,
    Withdrawal,
    WithdrawalRejectedReason,
    WithdrawalStatus,
)

"""Barrel export: framework generics + PRD-specific code.

Tests import everything from `test_helpers`; nothing in the suite should
reach into individual submodules.
"""
# Framework generics
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
    ApplicationStatus, OfficeActionStatus, OfficeActionResponseStatus,
    MaintenanceFeeStatus, FeePaymentStatus, PCTPhaseStatus,
    EntitySize, ApplicationType, ContinuationType, ActionType,
    PaymentCategory, UserRole,
    Applicant, Application, OfficeAction, OfficeActionResponse,
    MaintenanceFee, PCTPhaseEntry, FeePayment,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_applicant, assert_application, assert_office_action,
    assert_office_action_response, assert_maintenance_fee,
    assert_pct_phase_entry, assert_fee_payment,
)
from .factories import (
    create_applicant_payload, create_application_payload,
    create_office_action_payload, create_office_action_response_payload,
    create_fee_payment_payload, create_pct_phase_entry_payload,
    create_pay_issue_fee_payload, create_convert_provisional_payload,
)
from .constants import (
    ENTITY_MULTIPLIER, FILING_BASE_CENTS, ISSUE_BASE_CENTS,
    EXCESS_CLAIM_BASE_CENTS, EXCESS_INDEP_BASE_CENTS,
    EXTENSION_BASE_CENTS, MAINTENANCE_BASE_CENTS,
    LATE_SURCHARGE_BASE_CENTS,
    MICRO_INCOME_CEILING_CENTS, MICRO_PRIOR_APPS_CEILING,
    UTILITY_TERM_YEARS, DESIGN_TERM_YEARS, PROVISIONAL_TERM_MONTHS,
    filing_fee_cents, issue_fee_cents, extension_fee_cents,
    maintenance_base_fee_cents, maintenance_late_surcharge_cents,
    excess_claims_fee_cents,
)
from .test_users import TEST_USERS, make_applicant_headers
from .fixtures import (
    EXAMINER, ADMIN,
    set_clock, run_sweep,
    create_applicant, create_application, pay_filing_fee, docket_application,
    issue_office_action, file_oa_response, get_application, pay_issue_fee,
    list_maintenance_fees, pay_maintenance,
    setup_applicant_and_application,
    setup_application_in_awaiting_examination,
    setup_application_with_outstanding_oa,
    setup_application_in_allowed,
    setup_application_in_issued,
    setup_utility_with_maintenance_fees,
    setup_provisional_filed,
    setup_parent_application_in_filed,
    setup_parent_application_abandoned,
    setup_utility_at_w1_due_date,
    setup_pct_application_with_entry,
    setup_multi_oa_cycle,
)

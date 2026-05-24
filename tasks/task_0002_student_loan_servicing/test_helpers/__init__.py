"""Barrel export: framework generics + PRD-specific code.

Tests import everything from `test_helpers` so they have one consistent source
for both the runner's generic utilities and this domain's specifics.
"""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
    GenericApiClient,
)

# PRD-specific
from .types import (
    LoanStatus, LoanType, BorrowerStatus, MilitaryStatus,
    RepaymentPlanType, RepaymentPlanStatus, StateOfResidence,
    PaymentStatus, PaymentSource,
    ServicingEventType, ServicingReasonCode,
    EmployerType, EmploymentCertificationStatus,
    PSLFTrackerStatus, DischargeType, DischargeApplicationStatus,
    DelinquencyOutcome, UserRole,
    Borrower, Loan, RepaymentPlan, Payment, ServicingEvent,
    EmploymentCertification, PSLFTracker, DischargeApplication, DelinquencyRecord,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_borrower, assert_loan, assert_repayment_plan,
    assert_payment, assert_servicing_event,
    assert_employment_certification, assert_pslf_tracker,
    assert_discharge_application, assert_delinquency_record,
)
from .factories import (
    create_borrower_payload, create_loan_payload,
    create_servicing_event_payload,
    create_standard_10yr_plan_payload, create_idr_plan_payload,
    create_recertify_payload,
    create_payment_payload,
    create_employment_certification_payload,
    create_pslf_tracker_payload, force_pslf_tracker_state_payload,
    create_discharge_application_payload, approve_discharge_payload,
    advance_clock_payload, patch_military_status_payload,
)
from .constants import (
    POVERTY_LINES_BY_STATE,
    IBR_DISCRETIONARY_THRESHOLD_PCT, PAYE_DISCRETIONARY_THRESHOLD_PCT,
    SAVE_DISCRETIONARY_THRESHOLD_PCT,
    IBR_PAYMENT_PCT, PAYE_PAYMENT_PCT, SAVE_PAYMENT_PCT,
    STANDARD_TERM_MONTHS, TREASURY_OFFSET_FEE_PCT,
    DAILY_ACCRUAL_BASIS_DAYS, PSLF_REQUIRED_COUNT,
    ON_TIME_BACK_WINDOW_DAYS, ON_TIME_FORWARD_WINDOW_DAYS,
    DEFAULT_THRESHOLD_DAYS, PAYMENT_BACKDATE_WINDOW_DAYS,
    PAYMENT_REVERSAL_WINDOW_DAYS, ONGOING_CERTIFICATION_END,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers, make_servicer_headers,
    make_pslf_adjudicator_headers, make_va_officer_headers,
)
from .fixtures import (
    # primitives
    advance_clock, create_borrower, create_loan, fire_servicing_event,
    get_loan_version, get_loan,
    # state-progression builders
    create_loan_in_grace, create_loan_in_repayment,
    attach_standard_10yr_plan, attach_idr_plan,
    setup_loan_in_repayment_with_standard_plan,
    setup_loan_in_forbearance,
    setup_loan_paid_off,
    setup_loan_in_default,
    setup_loan_in_delinquent_via_clock,
    # cross-entity setups
    setup_borrower_with_all_loans_discharged_veteran,
    setup_pslf_tracker_at_threshold,
    setup_pslf_discharge_ready,
    setup_veteran_discharge_ready,
    setup_pslf_sod_violation_scenario,
    setup_payments_then_cert_for_relaxed_lookback,
    setup_borrower_with_n_qualifying_payments,
)

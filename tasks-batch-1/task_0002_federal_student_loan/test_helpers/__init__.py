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
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_common_fields,
    assert_borrower,
    assert_loan,
    assert_repayment_plan,
    assert_income_certification,
    assert_qualifying_employment,
    assert_payment,
    assert_discharge_application,
    assert_status_change,
    assert_reversal_invariant,
)
from .factories import (
    create_borrower_payload,
    create_loan_payload,
    create_repayment_plan_payload,
    create_income_certification_payload,
    create_qualifying_employment_payload,
    create_payment_payload,
    create_discharge_application_payload,
)
from .constants import (
    POVERTY_BASE_CENTS, POVERTY_PER_MEMBER_CENTS,
    DISCRETIONARY_MULTIPLIER_IBR_PAYE, DISCRETIONARY_MULTIPLIER_SAVE,
    IBR_RATE, PAYE_RATE, SAVE_RATE,
    STANDARD_TERM_MONTHS, DAYS_PER_YEAR,
    DEFAULT_DELINQUENCY_THRESHOLD, REHABILITATION_PAYMENT_COUNT,
    PSLF_QUALIFYING_PAYMENT_THRESHOLD, QUALIFYING_EMPLOYER_TYPES,
)
from .test_users import TEST_USERS, make_borrower_headers
from .fixtures import (
    set_clock,
    create_borrower,
    create_loan,
    walk_loan_to_repayment,
    setup_borrower_and_loan_in_repayment,
    setup_borrower_and_loan_in_school,
    create_and_certify_income,
    create_repayment_plan,
    create_and_activate_plan,
    create_and_certify_qualifying_employment,
    post_payment,
    post_and_apply_payment,
    file_discharge_application,
    file_and_begin_review_discharge,
    setup_idr_certified_borrower_in_repayment,
    setup_loan_with_active_standard_plan,
    setup_discharge_application_under_review,
    setup_loan_in_default,
)

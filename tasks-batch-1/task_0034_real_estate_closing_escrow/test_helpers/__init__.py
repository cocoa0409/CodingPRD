"""Barrel export: framework generics + real-estate-closing-escrow test helpers."""
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
    PurchaseAgreementStatus,
    EscrowAccountStatus,
    EarnestMoneyDepositStatus,
    TitleSearchStatus,
    TitleInsurancePolicyStatus,
    ClosingDisclosureStatus,
    CDProductType,
    WireInstructionStatus,
    WireParty,
    DisbursementStatus,
    DisbursementPurpose,
    DepositorRole,
    ExchangeAccountStatus,
    UserRole,
    DefectSeverity,
    PurchaseAgreement,
    EscrowAccount,
    EarnestMoneyDeposit,
    TitleSearch,
    TitleInsurancePolicy,
    CCRReview,
    ClosingDisclosure,
    WireInstruction,
    Disbursement,
    ExchangeAccount,
    User,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_common_fields,
    assert_append_only_fields,
    assert_purchase_agreement,
    assert_escrow_account,
    assert_earnest_money_deposit,
    assert_title_search,
    assert_title_insurance_policy,
    assert_ccr_review,
    assert_closing_disclosure,
    assert_wire_instruction,
    assert_disbursement,
    assert_exchange_account,
    assert_user,
)

# Payload factories
from .factories import (
    create_user_payload,
    create_purchase_agreement_payload,
    create_earnest_money_deposit_payload,
    confirm_deposit_payload,
    create_title_search_payload,
    complete_title_search_payload,
    resolve_title_search_payload,
    create_title_insurance_policy_payload,
    create_ccr_review_payload,
    create_closing_disclosure_payload,
    reissue_closing_disclosure_payload,
    create_wire_instruction_payload,
    callback_verify_wire_payload,
    create_disbursement_payload,
    create_exchange_account_payload,
    identify_exchange_account_payload,
    terminate_purchase_agreement_payload,
    set_clock_payload,
    advance_clock_payload,
)

# Domain constants
from .constants import (
    TIER1_BREAK_CENTS,
    TIER2_BREAK_CENTS,
    TIER3_BREAK_CENTS,
    TIER1_RATE,
    TIER2_RATE,
    TIER3_RATE,
    TIER4_RATE,
    LENDER_CONCURRENT_DISCOUNT,
    CD_WAIT_PERIOD_SECONDS,
    APR_REISSUE_BPS_THRESHOLD,
    EXCHANGE_IDENTIFICATION_DAYS,
    EXCHANGE_DEADLINE_DAYS,
    EXCHANGE_IDENTIFICATION_SECONDS,
    EXCHANGE_DEADLINE_SECONDS,
    PRICE_FLOOR_CENTS,
    PRICE_CEILING_CENTS,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_escrow_officer_headers,
    make_title_agent_headers,
    make_compliance_officer_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    bootstrap_compliance_officer,
    register_user,
    set_clock,
    advance_clock,
    setup_actors,
    create_agreement,
    activate_agreement,
    fetch_escrow_for_agreement,
    create_deposit,
    confirm_deposit,
    create_title_search,
    complete_title_search,
    resolve_title_search,
    issue_title_policy,
    create_ccr_review,
    create_closing_disclosure,
    deliver_closing_disclosure,
    acknowledge_closing_disclosure,
    create_wire,
    callback_verify_wire,
    lock_wire,
    reject_wire,
    verify_and_lock_wire,
    queue_disbursement,
    create_exchange_account,
    identify_exchange_account,
    setup_active_agreement,
    setup_under_contract_agreement,
    setup_resolved_clean_title,
    setup_locked_wire,
    setup_delivered_cd,
    setup_ready_for_clear_to_close,
    setup_cleared_to_close,
)

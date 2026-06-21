"""Barrel export: framework generics + personal-injury-domain code."""
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
    CaseStatus,
    Jurisdiction,
    MedicalRecordsRequestStatus,
    DamagesCategory,
    DamagesItemStatus,
    MedicalLienStatus,
    DemandLetterStatus,
    SettlementOfferStatus,
    SettlementParty,
    CourtEventType,
    CourtEventStatus,
    DisbursementStatus,
    UserRole,
    Client,
    Case,
    MedicalProvider,
    MedicalRecordsRequest,
    DamagesItem,
    MedicalLien,
    DemandLetter,
    SettlementOffer,
    CourtEvent,
    Disbursement,
    SystemClock,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_client,
    assert_case,
    assert_provider,
    assert_records_request,
    assert_damages_item,
    assert_lien,
    assert_demand_letter,
    assert_offer,
    assert_court_event,
    assert_disbursement,
    assert_system_clock,
    assert_money_conservation,
)

# Payload factories
from .factories import (
    create_client_payload,
    create_case_payload,
    create_provider_payload,
    create_records_request_payload,
    create_damages_item_payload,
    create_lien_payload,
    agree_lien_payload,
    create_demand_letter_payload,
    create_offer_payload,
    accept_offer_payload,
    create_court_event_payload,
    release_disbursement_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    STATUTE_YEARS,
    PRE_SUIT_RATE,
    POST_SUIT_RATE,
    FUTURE_MED_PV_FACTOR,
    TIER_LOW_CENTS,
    TIER_HIGH_CENTS,
    BUFFER_RATE_LOW,
    BUFFER_RATE_MID,
    BUFFER_RATE_HIGH,
    PAIN_SUFFERING_CAP_CENTS_CA_FL,
    OFFER_EXPIRY_DAYS,
    COURT_EVENT_BUFFER_HOURS,
    COURT_EVENT_MAX_DURATION_MINUTES,
    PAIN_MULTIPLIER_MIN,
    PAIN_MULTIPLIER_MAX,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_headers,
    make_paralegal_headers,
    make_attorney_headers,
    make_managing_partner_headers,
    make_platform_admin_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_proposed_damages,
    include_damages,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    negotiate_lien,
    dispute_lien,
    resume_lien,
    create_offer,
    get_case_version,
    accept_offer,
    create_court_event,
    file_suit,
    release_disbursement,
    get_case,
    get_disbursement_for_case,
    setup_client_and_case,
    setup_active_case,
    setup_active_case_with_reviewed_records,
    setup_case_ready_for_settlement,
    setup_case_in_negotiation_with_offer,
    settle_case_with_lien,
    setup_settled_case_with_paid_liens,
)

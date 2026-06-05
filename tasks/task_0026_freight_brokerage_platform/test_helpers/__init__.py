"""Barrel export: framework generics + freight-brokerage-specific code."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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

# Domain types.
from .types import (  # noqa: F401
    AccessorialCode,
    CarrierQualificationStatus,
    ContractRateStatus,
    DisputeClaimStatus,
    DisputeClaimType,
    FactoringRequestStatus,
    InvoiceStatus,
    LoadStatus,
    QuoteRequestStatus,
    RateMode,
    RejectionReasonCode,
    RequestedEquipment,
    ResolutionKind,
    ShipperStatus,
    SmartWayComplianceStatus,
    SmartWayTier,
    UserRole,
    Accessorial,
    Carrier,
    ContractRate,
    CreditRiskRead,
    DisputeClaim,
    FactoringRequest,
    Invoice,
    Load,
    QuoteRequest,
    Shipper,
    SmartWayAudit,
)

# API surface.
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId

# Assertions.
from .assertions import (
    assert_accessorial,
    assert_carrier,
    assert_contract_rate,
    assert_dispute_claim,
    assert_factoring_request,
    assert_invoice,
    assert_invoice_total_matches_components,
    assert_load,
    assert_quote_request,
    assert_shipper,
    assert_smartway_audit,
)

# Payload factories.
from .factories import (
    activate_contract_rate_payload,
    add_accessorial_payload,
    award_quote_payload,
    create_carrier_payload,
    create_contract_rate_payload,
    create_dispute_claim_payload,
    create_factoring_request_payload,
    create_quote_request_payload,
    create_shipper_payload,
    create_smartway_audit_payload,
    deliver_payload,
    payment_payload,
    pickup_payload,
    reject_carrier_payload,
    resolve_dispute_payload,
    set_clock_payload,
)

# Domain constants.
from .constants import (
    EQUIPMENT_UPLIFT_PCT,
    FACTORING_BASE_PCT,
    FACTORING_FEE_PCT_MAX,
    FACTORING_MID_PCT,
    FACTORING_UPPER_PCT,
    LATE_AGE_DAYS,
    QUOTE_WINDOW_PRE_PICKUP_BUFFER_MINUTES,
    SAFETY_REJECT_THRESHOLD,
    SMARTWAY_AT_RISK_THRESHOLD,
    SMARTWAY_PASS_THRESHOLD,
    SPOT_DETENTION_FREE_MINUTES,
    SPOT_DETENTION_RATE_PER_HOUR_CENTS,
    SPOT_FUEL_SURCHARGE_PER_MILE_CENTS,
    SPOT_TIER1_PER_MILE_CENTS,
    SPOT_TIER2_PER_MILE_CENTS,
    SPOT_TIER3_PER_MILE_CENTS,
    THRESHOLDS,
    W_DISPUTE,
    W_LATE,
    W_UTIL,
)

# Role headers & RBAC builders.
from .test_users import (
    TEST_USERS,
    make_broker_ops_headers,
    make_carrier_headers,
    make_headers,
    make_shipper_headers,
)

# Composite setup helpers.
from .fixtures import (
    attach_accessorial,
    award_quote_to_carrier,
    clock_advance,
    create_active_contract,
    create_carrier,
    create_qualified_carrier,
    create_quote,
    create_shipper,
    deliver_load,
    get_carrier,
    get_contract_rate,
    get_dispute,
    get_factoring_request,
    get_invoice,
    get_load,
    get_quote,
    get_shipper,
    invoice_load,
    open_dispute,
    open_factoring_request,
    pay_invoice,
    resolve_dispute,
    set_clock,
    setup_advanced_factoring,
    setup_awarded_load,
    setup_delivered_load,
    setup_invoiced_load,
    withdraw_dispute,
)

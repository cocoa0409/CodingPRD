"""Barrel export: framework generics + Product-Warranty-specific code."""
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

# Domain types
from .types import (  # noqa: F401
    Claim,
    ClaimStatus,
    CoverageTier,
    CoverageTierStatus,
    DefectCategory,
    DepreciationMethod,
    ExtendedWarranty,
    ExtendedWarrantyStatus,
    LedgerEntry,
    LedgerEntryType,
    LedgerReason,
    Owner,
    PremiumRefundMethod,
    Product,
    ProductCategory,
    ProductStatus,
    ProofDocumentType,
    ProofOfPurchase,
    ProofState,
    ProofStatus,
    Registration,
    RegistrationStatus,
    RejectionReason,
    ResolutionType,
    TierName,
    TransferStatus,
    UserRole,
    WarrantyTransfer,
)

# API surface
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId

# Assertions
from .assertions import (
    assert_claim,
    assert_common_fields,
    assert_coverage_conserved,
    assert_coverage_tier,
    assert_extended_warranty,
    assert_ledger_entry,
    assert_minimal_audit_fields,
    assert_owner,
    assert_product,
    assert_proof_of_purchase,
    assert_registration,
    assert_warranty_transfer,
)

# Factories
from .factories import (
    adjudicate_approve_payload,
    adjudicate_deny_payload,
    clock_payload,
    create_claim_payload,
    create_coverage_tier_payload,
    create_extended_warranty_payload,
    create_owner_payload,
    create_product_payload,
    create_proof_payload,
    create_registration_payload,
    transfer_payload,
)

# Domain constants
from .constants import (
    AMOUNT_TOLERANCE_CENTS,
    CATEGORY_SURCHARGE_CENTS,
    CLAIM_COOLDOWN_DAYS,
    COVERAGE_FLOOR_CENTS,
    DECLINING_RATE,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    SHORT_RATE_PENALTY,
    TRANSFER_FEE_FLOOR_CENTS,
    TRANSFER_RATE_YEAR1,
    TRANSFER_RATE_YEAR1_3,
    TRANSFER_RATE_YEAR3_PLUS,
    VALIDATION_WINDOW_DAYS,
)

# Role headers
from .test_users import (
    TEST_USERS,
    make_claims_processor_headers,
    make_headers,
    make_owner_headers,
    make_warranty_admin_headers,
)

# Composite fixtures
from .fixtures import (
    ADMIN,
    CP,
    adjudicate_approve,
    adjudicate_deny,
    advance_clock,
    cancel_extension,
    create_owner,
    create_product,
    create_registration,
    create_tier,
    file_claim,
    fulfill_claim,
    get_registration,
    get_registration_version,
    initiate_transfer,
    issue_rma,
    list_ledger,
    purchase_extension,
    set_clock,
    setup_active_registration,
    setup_active_registration_with_extension,
    setup_adjudicated_refund_claim,
    setup_claim_in_rma,
    setup_pending_transfer,
    submit_and_validate_proof,
    submit_proof,
    validate_proof,
)

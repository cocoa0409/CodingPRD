"""Barrel export: framework generics + Home-Warranty-specific code."""
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
    ContractPackageStatus,
    ContractStatus,
    ClaimTicketStatus,
    DispatchStatus,
    CoveredItemCategory,
    RejectionReason,
    UserRole,
    ContractPackage,
    Customer,
    Contract,
    CoveredItem,
    ClaimTicket,
    Dispatch,
    RenewalReminder,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_contract_package,
    assert_customer,
    assert_contract,
    assert_active_contract,
    assert_covered_item,
    assert_claim,
    assert_dispatch,
    assert_renewal_reminder,
)

# Factories
from .factories import (
    create_contract_package_payload,
    create_customer_payload,
    create_contract_payload,
    renew_contract_payload,
    create_covered_item_payload,
    create_claim_payload,
    assess_claim_payload,
    reject_claim_payload,
    dispatch_claim_payload,
    resolve_claim_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    EARLY_RENEWAL_DAYS_THRESHOLD,
    EARLY_RENEWAL_DISCOUNT_PCT,
    ITEM_SURCHARGE_PCT_PER_ITEM,
    COVERAGE_DAYS,
    RENEWAL_REMINDER_LEAD_DAYS,
    TECHNICIAN_BUFFER_SECONDS,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
)

# RBAC headers
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_dispatcher_headers,
    make_technician_headers,
    make_admin_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    tick_clock,
    create_package,
    create_default_package,
    register_customer,
    create_pending_contract,
    activate_contract,
    setup_active_contract,
    setup_active_contract_with_item,
    file_claim,
    assess_claim,
    reject_claim,
    dispatch_claim,
    resolve_claim,
    reopen_claim,
    get_dispatch_for_claim,
    start_dispatch,
    complete_dispatch,
    mark_dispatch_return_needed,
    walk_dispatch_to_completed,
    setup_item_with_completed_dispatch,
    setup_expiring_soon_contract,
    setup_expired_contract,
    setup_expired_contract_with_item,
    setup_active_contract_with_dispatched_claim,
    setup_dispatch_in_progress_after_start,
    setup_dispatch_return_needed,
)

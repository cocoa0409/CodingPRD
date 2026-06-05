"""Barrel export: framework generics + IRA-RMD-specific test helpers."""
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
    UserRole,
    IRAAccountStatus,
    ContributionStatus,
    DistributionStatus,
    ConversionStatus,
    BeneficiaryDesignationStatus,
    RMDScheduleStatus,
    RMDPosture,
    FilingStatus,
    AccountType,
    ContributionKind,
    DistributionReason,
    Relationship,
    AccountOwner,
    IRAAccount,
    BeneficiaryDesignation,
    Contribution,
    Conversion,
    Distribution,
    RMDSchedule,
    Form1099R,
    AuditEvent,
    SystemClock,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_common_fields,
    assert_append_only_fields,
    assert_account_owner,
    assert_ira_account,
    assert_contribution,
    assert_distribution,
    assert_conversion,
    assert_beneficiary_designation,
    assert_rmd_schedule,
    assert_form_1099r,
    assert_audit_event,
)

# Payload factories
from .factories import (
    create_owner_payload,
    patch_owner_agi_payload,
    declare_deceased_payload,
    create_account_payload,
    account_version_payload,
    create_contribution_payload,
    create_distribution_payload,
    create_conversion_payload,
    conversion_version_payload,
    create_beneficiary_designation_payload,
    create_rmd_schedule_payload,
    set_clock_payload,
    advance_year_rollover_payload,
)

# Domain constants
from .constants import (
    PAGINATION,
    BASE_LIMIT_CENTS,
    CATCH_UP_CENTS,
    CATCH_UP_AGE,
    RMD_AGE,
    ROTH_PHASEOUT,
    ROTH_FLOOR_CENTS,
    UNIFORM_LIFETIME_DIVISOR_BP,
    SECURE_YEARS,
    BENEFICIARY_TOTAL_BPS,
    FORM_1099R_CODES,
    SECURE_EXEMPT_RELATIONSHIPS,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_account_owner_headers,
    make_plan_admin_headers,
    make_irs_auditor_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    advance_year_rollover,
    get_clock_state,
    create_owner,
    create_account,
    get_account,
    get_owner,
    create_pending_contribution,
    confirm_contribution,
    fund_account_with_contribution,
    create_pending_distribution,
    confirm_distribution,
    initiate_conversion,
    complete_conversion,
    create_beneficiary,
    activate_beneficiary,
    add_active_beneficiary,
    create_rmd_schedule,
    get_rmd_schedule,
    declare_deceased,
    setup_clock_and_owner,
    setup_owner_with_traditional_account,
    setup_owner_with_roth_account,
    setup_owner_with_trad_and_roth,
    setup_funded_traditional,
    setup_funded_traditional_with_open_rmd,
    setup_inherited_traditional_with_secure_deadline,
    open_n_accounts,
)

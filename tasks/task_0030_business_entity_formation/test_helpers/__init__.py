"""Barrel export: framework generics + business-entity-formation-specific code."""
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
    BusinessEntityStatus,
    CompliancePosture,
    EntityType,
    RevenueBand,
    StateCode,
    OperatingAgreementStatus,
    OperatingAgreementTemplateType,
    EINApplicationStatus,
    RegisteredAgentStatus,
    RegisteredAgentType,
    AnnualReportStatus,
    ForeignQualificationStatus,
    BOIDisclosureStatus,
    BOITriggeringEvent,
    BOIControlRole,
    ComplianceEventType,
    UserRole,
    BusinessEntity,
    OperatingAgreement,
    EINApplication,
    RegisteredAgent,
    AnnualReport,
    ForeignQualification,
    BOIDisclosure,
    ComplianceEvent,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_business_entity,
    assert_operating_agreement,
    assert_ein_application,
    assert_registered_agent,
    assert_annual_report,
    assert_foreign_qualification,
    assert_boi_disclosure,
    assert_compliance_event,
)

# Payload factories
from .factories import (
    create_business_entity_payload,
    create_registered_agent_payload,
    create_operating_agreement_payload,
    create_ein_application_payload,
    create_annual_report_payload,
    create_foreign_qualification_payload,
    create_boi_disclosure_payload,
    amend_boi_disclosure_payload,
    issue_ein_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    BASE_BY_STATE,
    TIER_MULT_X100,
    MIN_FLOOR_BY_STATE,
    DAILY_RATE_BY_STATE_X100,
    LATE_FEE_CAP_CENTS,
    GRACE_DAYS_BY_TRIGGER,
    BOI_REFRESH_DAYS,
    SUPPORTED_STATES,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
)

# Role headers / RBAC
from .test_users import (
    TEST_USERS,
    make_filer_headers,
    make_state_admin_headers,
    make_compliance_officer_headers,
    make_anonymous_headers,
    make_headers,
)

# Composite setup helpers
from .fixtures import (
    set_clock,
    create_forming_business_entity,
    create_registered_agent_for,
    create_and_execute_operating_agreement,
    create_and_issue_ein,
    setup_active_llc,
    setup_active_corp,
    setup_active_lp,
    create_draft_annual_report,
    file_annual_report,
    void_annual_report,
    create_foreign_agent,
    create_pending_foreign_qualification,
    approve_foreign_qualification,
    setup_qualified_foreign_qualification,
    create_draft_boi_disclosure,
    submit_boi_disclosure,
    setup_dissolved_business_entity,
)

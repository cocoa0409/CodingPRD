"""Barrel export: framework generics + PRD-specific helpers."""
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

from .types import (
    UserRole,
    AgentStatus,
    PlanStatus,
    EnrollmentStatus,
    AnniversaryStatus,
    DealStatus,
    SettlementStatus,
    LegStatus,
    LegPayeeType,
    LedgerEntryType,
    TaxFormStatus,
    TrustKind,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_agent,
    assert_plan,
    assert_enrollment,
    assert_anniversary_period,
    assert_deal,
    assert_settlement,
    assert_disbursement_leg,
    assert_ledger_entry,
    assert_tax_form,
    assert_trust_transaction,
)
from .factories import (
    create_agent_payload,
    create_plan_p1_payload,
    create_plan_p2_payload,
    create_deal_payload,
    create_enrollment_payload,
    create_debit_adjustment_payload,
    create_tax_form_payload,
)
from .constants import THRESHOLDS, TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_agent_headers,
    make_broker_admin_headers,
    make_office_manager_headers,
    make_transaction_coordinator_headers,
    make_auditor_headers,
)
from .fixtures import (
    setup_active_agent,
    setup_active_plan_p1,
    setup_active_plan_p2,
    setup_agent_on_plan,
    setup_agent_with_debit,
    create_draft_deal,
    setup_pending_deal,
    setup_closed_deal,
    setup_settled_deal,
    get_settlement_legs,
    get_leg_by_type,
    authorize_leg,
    release_leg,
    authorize_and_release_leg,
    setup_released_deal,
    get_window_for_agent,
)

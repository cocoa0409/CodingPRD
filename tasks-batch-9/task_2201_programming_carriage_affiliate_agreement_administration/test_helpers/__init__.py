"""Test helpers for the carriage / affiliate agreement administration API.

Re-exports the framework generics alongside every domain-specific helper so a
test module needs a single import site.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
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

from .api_client import PREFIX, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .assertions import (
    assert_agreement,
    assert_append_only_shape,
    assert_audit_engagement,
    assert_audit_finding,
    assert_blackout_rule,
    assert_commitment_ledger_identities,
    assert_content_title,
    assert_distributor,
    assert_invoice,
    assert_logical_clock,
    assert_marketing_commitment,
    assert_mfn_clause,
    assert_mutable_resource_shape,
    assert_rate_card_entry,
    assert_rate_precision,
    assert_renewal_analysis,
    assert_rights_window,
    assert_settlement_summary,
    assert_subscriber_report,
    assert_whole_cents,
)
from .constants import *  # noqa: F401,F403
from .constants import DEFAULT_LOGICAL_CLOCK, TEST_DEFAULTS, THRESHOLDS
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ROLE_HEADER_KEYS,
    TEST_USERS,
    headers_for_role,
    make_affiliate_sales_exec_headers,
    make_audit_manager_headers,
    make_distributor_liaison_headers,
    make_network_admin_headers,
    make_revenue_accountant_headers,
    make_rights_administrator_headers,
)
from .types import ALL_ROLES, UserRole

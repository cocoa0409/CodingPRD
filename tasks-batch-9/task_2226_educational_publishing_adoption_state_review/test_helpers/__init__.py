"""Test infrastructure for the state adoption review service.

Importing this package registers the error-to-HTTP-status catalogue with the
shared response validators, so ``validate_error`` cross-checks statuses for free.
"""

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

from . import factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import (
    as_decimal,
    assert_append_only_record,
    assert_ascending_by_created_at,
    assert_decimal_equals,
    assert_mutable_record,
    assert_page_budget_conserved,
    assert_percentage_scale,
    assert_print_unit_ledger_balances,
    assert_ratio_scale,
    assert_same_members,
    assert_whole_cents,
)
from .constants import *  # noqa: F401,F403
from .fixtures import AdoptionWorld
from .test_users import (
    COMMITTEE_MEMBER_HEADERS,
    PUBLIC_COMMENTER_HEADERS,
    TEST_USERS,
    make_editorial_director_headers,
    make_platform_admin_headers,
    make_pricing_manager_headers,
    make_public_commenter_headers,
    make_publisher_editor_headers,
    make_review_committee_member_headers,
    make_sales_rep_headers,
    make_state_adoption_officer_headers,
    make_unauthenticated_headers,
)

__all__ = [
    # Shared framework
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # Client
    "ApiClient",
    "api_client",
    # Errors
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_ERROR_IDS",
    # Domain assertions
    "as_decimal",
    "assert_decimal_equals",
    "assert_percentage_scale",
    "assert_ratio_scale",
    "assert_whole_cents",
    "assert_mutable_record",
    "assert_append_only_record",
    "assert_print_unit_ledger_balances",
    "assert_page_budget_conserved",
    "assert_same_members",
    "assert_ascending_by_created_at",
    # Builders
    "factories",
    "fixtures",
    "AdoptionWorld",
    # Identities
    "TEST_USERS",
    "COMMITTEE_MEMBER_HEADERS",
    "PUBLIC_COMMENTER_HEADERS",
    "make_platform_admin_headers",
    "make_state_adoption_officer_headers",
    "make_review_committee_member_headers",
    "make_publisher_editor_headers",
    "make_editorial_director_headers",
    "make_pricing_manager_headers",
    "make_sales_rep_headers",
    "make_public_commenter_headers",
    "make_unauthenticated_headers",
]

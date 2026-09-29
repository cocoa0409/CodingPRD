"""Test infrastructure for the Lateral Partner Hiring API.

Importing this package registers the error-id to HTTP-status map with the shared
validators, so ``validate_error`` can check status codes without every test
restating them.
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_ERROR_IDS, ApiErrorId
from .assertions import (
    MONEY_TOLERANCE,
    RATIO_TOLERANCE,
    assert_append_only_fields,
    assert_candidate,
    assert_client_book_entry,
    assert_collection_record,
    assert_collection_record_has_no_mutable_fields,
    assert_committee_vote,
    assert_common_fields,
    assert_compensation_offer,
    assert_conflict_check,
    assert_conflict_waiver,
    assert_cross_sell_introduction,
    assert_guarantee_budget_identity,
    assert_instant_equals,
    assert_instant_is_null,
    assert_integration_plan,
    assert_matter_declination,
    assert_money_equals,
    assert_performance_review,
    assert_portability_assessment,
    assert_portable_book_identity,
    assert_practice_group,
    assert_questionnaire,
    assert_ratio_equals,
    assert_search_firm,
    assert_search_firm_engagement,
    assert_three_fractional_digits,
    assert_two_decimal_places,
    assert_vote_ledger_identity,
    days_after,
    money,
    parse_instant,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ADMIN_USER_ID,
    CHAIR_USER_ID,
    COORDINATOR_USER_ID,
    COUNSEL_USER_ID,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    MEMBER_4_USER_ID,
    MEMBER_5_USER_ID,
    PEER_CHAIR_USER_ID,
    SPONSOR_USER_ID,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_candidate_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_conflicts_counsel_headers,
    make_practice_group_leader_headers,
    make_recruiting_coordinator_headers,
    make_system_admin_headers,
)
from .types import *  # noqa: F401,F403

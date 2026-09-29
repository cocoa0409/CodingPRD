"""Test infrastructure for the municipal Public Art Conservation API.

Importing this package registers the PRD's error-to-HTTP-status map with the
framework, so `validate_error()` cross-checks the status code of every rejection.
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

from . import assertions, constants, factories, fixtures, types
from .api_client import BASE, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_artist,
    assert_artist_consultation,
    assert_artwork,
    assert_common_record_properties,
    assert_condition_assessment,
    assert_condition_index_precision,
    assert_conservator,
    assert_damage_incident,
    assert_deaccession_case,
    assert_estimate_breakdown,
    assert_funding_allocation,
    assert_funding_pool,
    assert_integer_cents,
    assert_maintenance_protocol,
    assert_maintenance_visit,
    assert_moral_rights_notice,
    assert_no_version_change,
    assert_pool_availability_identity,
    assert_priority_score_precision,
    assert_site,
    assert_treatment_proposal,
)
from .constants import DEFAULT_CLOCK_UTC, PAGINATION, TEST_DEFAULTS
from .test_users import (
    CHIEF_CONSERVATOR_USER_ID,
    COMMISSION_MEMBER_USER_IDS,
    CREW_USER_ID,
    FINANCE_USER_ID,
    MANAGER_USER_ID,
    REGISTRAR_USER_ID,
    SECOND_SURVEYOR_USER_ID,
    SURVEYOR_USER_ID,
    TEST_USERS,
    make_artist_representative_headers,
    make_chief_conservator_headers,
    make_commission_member_headers,
    make_conservator_vendor_headers,
    make_crew_headers,
    make_finance_headers,
    make_headers,
    make_manager_headers,
    make_registrar_headers,
    make_surveyor_headers,
)
from .types import UserRole

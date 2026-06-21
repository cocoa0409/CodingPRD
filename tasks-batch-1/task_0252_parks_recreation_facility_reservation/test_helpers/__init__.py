"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)
# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_patron, assert_facility, assert_insurance_certificate,
    assert_league, assert_permit, assert_payment, assert_refund,
    assert_lottery_round, assert_lottery_entry,
)
from .factories import (
    create_facility_payload, create_patron_payload,
    create_insurance_certificate_payload, create_permit_payload,
    create_payment_payload, create_league_payload,
    create_lottery_round_payload, create_lottery_entry_payload,
)
from .constants import REFUND_LEAD, STANDING, LOTTERY_WEIGHT, PAGINATION
from .test_users import (
    TEST_USERS, make_patron_headers, make_coordinator_headers, make_finance_headers,
)
from .fixtures import (
    set_clock, create_facility, create_patron, create_coi,
    apply_permit, capture_payment, facility_version, grant_permit,
    setup_granted_permit, setup_applied_permit, cancel_permit, get_first_refund,
    setup_league_with_children, create_lottery_round, enter_lottery,
    setup_lottery_round_with_entries,
)

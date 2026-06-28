"""Barrel export: framework generics + Flood Insurance PRD-specific code."""
# Framework generics (re-exported for convenience)
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_common_fields,
    assert_community,
    assert_property,
    assert_elevation_certificate,
    assert_policy,
    assert_claim,
    assert_proof_of_loss,
    assert_policy_transfer,
    assert_premium_conservation_on_cancel,
    assert_premium_conservation_on_transfer,
)
from .factories import (
    DEFAULTS,
    create_community_payload,
    create_property_payload,
    create_elevation_certificate_payload,
    create_policy_quote_payload,
    create_claim_payload,
    create_proof_of_loss_payload,
    create_policy_transfer_payload,
)
from .constants import (
    CRS_DISCOUNT_TABLE,
    BUILDING_RATE_RR2,
    CONTENTS_RATE_RR2,
    RR2_ZONE_BAND,
    BUILDING_RATE_LEGACY,
    CONTENTS_RATE_LEGACY,
    ICC_PREMIUM,
    FEDERAL_POLICY_FEE,
    HFIAA_PRIMARY,
    HFIAA_NONPRIMARY,
    BUILDING_COVERAGE_CAP,
    CONTENTS_COVERAGE_CAP,
    ALLOWED_DEDUCTIBLES,
    DEFAULT_BUILDING_DEDUCTIBLE,
    DEFAULT_CONTENTS_DEDUCTIBLE,
    ICC_COVERAGE_CAP,
    STANDARD_WAITING_DAYS,
    LENDER_WAITING_DAYS,
    TERM_DAYS,
    PROOF_OF_LOSS_DEADLINE_DAYS,
    REPETITIVE_LOSS_THRESHOLD,
    CLOCK_STARTUP_DEFAULT,
)
from .test_users import (
    TEST_USERS,
    make_policy_holder_headers,
    make_underwriter_headers,
    make_adjuster_headers,
    make_fema_admin_headers,
)
from .fixtures import (
    set_clock,
    create_community,
    create_property,
    create_elevation_certificate,
    quote_policy,
    quote_policy_as_underwriter,
    setup_community_property,
    setup_quoted_policy,
    setup_bound_policy,
    setup_active_policy,
    file_claim,
    open_review,
    file_proof_of_loss,
    accept_proof_of_loss,
    setup_claim_under_review,
    setup_claim_with_accepted_proof,
    approve_claim,
    deny_claim,
    setup_approved_claim,
)

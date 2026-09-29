"""Test helpers for the Surplus Lines Placement Tax API.

Importing this package registers the PRD section 5 error catalogue with the
framework validators, so ``validate_error`` cross-checks HTTP status codes
automatically. Tests should import everything they need from here.
"""

# Framework re-exports, so that a test file needs only one import root.
from prd_bench_local_runner.testing import (  # noqa: F401
    GenericApiClient,
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

from .api_client import ApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_allocation_row,
    assert_common_fields,
    assert_created_at_ascending,
    assert_filing_line,
    assert_integer_cents,
    assert_ledger_reconciles,
    assert_money_equals,
    assert_pagination_meta,
    assert_parts_sum_to,
    assert_policy_dimensions,
    assert_state_codes_ascending,
    assert_three_fraction_digits,
    assert_version_advanced_by,
    assert_version_is,
    by_state,
    largest_remainder,
    round_half_up,
)
from .constants import *  # noqa: F401,F403
from .factories import (  # noqa: F401
    OMIT,
    affidavit_payload,
    broker_license_payload,
    broker_payload,
    ca_program_payload,
    cancellation_payload,
    carrier_eligibility_payload,
    carrier_payload,
    declination_payload,
    endorsement_payload,
    exposure,
    filing_batch_payload,
    nv_program_payload,
    placement_payload,
    policy_payload,
    review_decision_payload,
    state_program_payload,
    tx_program_payload,
)
from .fixtures import (  # noqa: F401
    CANONICAL_DECLINATIONS,
    World,
)
from .test_users import (  # noqa: F401
    ANY_ROLE,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ANDERS,
    COMPLIANCE_OFFICER_ANDERS_ID,
    COMPLIANCE_OFFICER_BRIGID,
    COMPLIANCE_OFFICER_BRIGID_ID,
    HEADERS_BY_ROLE,
    PLATFORM_ADMIN,
    PLATFORM_ADMIN_ID,
    STATE_REGULATOR,
    STATE_REGULATOR_AZ,
    STATE_REGULATOR_CA,
    STATE_REGULATOR_GA,
    STATE_REGULATOR_NV,
    STATE_REGULATOR_TX,
    TAX_FILER,
    TAX_FILER_NINA,
    TAX_FILER_NINA_ID,
    TAX_FILER_OMAR,
    TAX_FILER_OMAR_ID,
    TAX_FILER_OWEN,
    TAX_FILER_OWEN_ID,
    make_compliance_officer_headers,
    make_headers,
    make_placement_broker_headers,
    make_platform_admin_headers,
    make_state_regulator_headers,
    make_tax_filer_headers,
)

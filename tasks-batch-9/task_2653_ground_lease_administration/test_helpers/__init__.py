"""
Test helpers for the Ground Lease Administration API compliance suite.

Barrel export: tests import everything they need from `test_helpers`.
Generic infrastructure (client base, envelope validators, race helpers) comes
from the installed `prd_bench_local_runner.testing` package and is re-exported
here so a test file needs one import block.
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

from . import factories, fixtures
from .api_client import GroundLeaseApiClient
from .api_errors import *  # noqa: F401,F403 — the whole error catalogue
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_appraisal_shape,
    assert_bps,
    assert_common_fields,
    assert_deposit_conserved,
    assert_envelope,
    assert_envelope_conserved,
    assert_fields,
    assert_instant,
    assert_integer_money,
    assert_proceeds_conserved,
    assert_transfer_fee_conserved,
    assert_version_unchanged,
    parse_instant,
    same_instant,
)
from .constants import *  # noqa: F401,F403 — domain constants
from .test_users import (
    ACCOUNTANT,
    ARBITRATOR,
    ASSET_MANAGER,
    LESSOR_ADMIN,
    make_accountant_headers,
    make_arbitrator_headers,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    make_headers_for_role,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
)
from .types import (
    APPRAISAL_SUBMISSION_FIELDS,
    COMMON_FIELDS,
    LEASE_DERIVED_FIELDS,
    LEASE_INPUT_FIELDS,
    LESSEE_INPUT_FIELDS,
    LOSS_EVENT_ALLOCATION_FIELDS,
    REVERSION_FIELDS,
    STATEMENT_DERIVED_FIELDS,
    TRANSFER_DERIVED_FIELDS,
)

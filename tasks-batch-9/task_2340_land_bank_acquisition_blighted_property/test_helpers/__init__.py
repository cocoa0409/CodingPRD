"""
Test helpers for the County Land Bank Authority API.

Importing this package registers the error_id -> HTTP status mapping with the
framework's envelope validators, so ``validate_error`` cross-checks statuses
automatically.

Everything a test needs is re-exported here: the generic framework validators
and race helpers, plus this API's client, error catalog, factories, assertions,
domain constants and composite fixtures.
"""

# --- framework re-exports ----------------------------------------------------
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

# --- this API's helpers ------------------------------------------------------
from . import assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import (  # noqa: F401
    assert_acquisition_packet,
    assert_append_only_fields,
    assert_applicant,
    assert_common_fields,
    assert_contractor,
    assert_demolition_run,
    assert_development_agreement,
    assert_disposition_application,
    assert_eligibility_screening,
    assert_funding_source,
    assert_inventory_area_conserved,
    assert_ledger_identity,
    assert_ledger_position,
    assert_maintenance_order,
    assert_parcel_adjacency,
    assert_property,
    assert_reuse_hearing,
    assert_same_instant,
    assert_score,
    assert_title_action,
    expected_admin_fee_cents,
    expected_demolition_estimate_cents,
    expected_mow_estimate_cents,
    expected_order_estimate_cents,
    expected_reserve_floor_cents,
    expected_secure_estimate_cents,
    round_half_up,
)
from .test_users import (  # noqa: F401
    BOARD_CLERK_1,
    CLERK_1,
    COUNTY_TREASURER_1,
    DISP_1,
    DISP_2,
    DISPOSITION_OFFICER_1,
    DISPOSITION_OFFICER_2,
    INTAKE_1,
    INTAKE_2,
    INTAKE_OFFICER_1,
    INTAKE_OFFICER_2,
    INV_1,
    INVENTORY_MANAGER_1,
    TEST_USERS,
    TREAS_1,
    make_applicant_headers,
    make_board_clerk_headers,
    make_county_treasurer_headers,
    make_disposition_officer_headers,
    make_intake_officer_headers,
    make_inventory_manager_headers,
)
from .types import (  # noqa: F401
    ALL_ROLES,
    APPEND_ONLY_ENTITIES,
    APPLICANT_TYPES,
    APPLICATION_STATUSES,
    CUSTODY_STATUSES,
    PROGRAMS,
    ROLE_APPLICANT,
    ROLE_BOARD_CLERK,
    ROLE_COUNTY_TREASURER,
    ROLE_DISPOSITION_OFFICER,
    ROLE_INTAKE_OFFICER,
    ROLE_INVENTORY_MANAGER,
    TITLE_STATUSES,
    WORK_TYPES,
)

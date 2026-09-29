"""
Test infrastructure for the mortgage servicing rights valuation and transfer API.

Import everything from this package:

    from test_helpers import (
        ApiClient, ADMIN, make_seller_headers,
        build_published_package, ERR_PACKAGE_INVALID_STATE,
    )

Modules:
  api_client  — one method per endpoint
  api_errors  — error identifiers and their HTTP statuses
  assertions  — envelope readers, the rounding mirror and invariant checks
  constants   — canonical payloads, loan pools, model constants, vocabularies
  factories   — one function per desk action
  fixtures    — layered environment builders and the pytest fixtures
  test_users  — role headers and the two entity-backed identity builders
  types       — shared type aliases
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import constants as C  # noqa: F401
from . import factories as F  # noqa: F401
from . import test_users as U  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .assertions import (  # noqa: F401
    assert_custodial_funds,
    assert_dimensions,
    assert_fields_present,
    assert_holdback_split,
    assert_identified,
    assert_readiness,
    assert_scenario_map,
    assert_settlement_wire,
    assert_status,
    assert_stratum_breakdown,
    assert_unversioned,
    assert_versioned,
    bps_of_upb,
    data_of,
    find_row,
    floor_cents,
    has_row,
    ids_of,
    loan_custodial_total,
    meta_of,
    payload_of,
    pct_of,
    price_at_bps,
    round_half_up,
    rows_of,
)
from .constants import (  # noqa: F401
    ADMIN_ID,
    AGENCY_ID,
    AGENCY_ID_2,
    ANALYST_ID,
    ASSUMPTION_DESK_BASE,
    BID_DEADLINE_AT,
    BUYER_BRAVO,
    BUYER_CHARLIE,
    CLOCK_DEFAULT,
    CLOCK_TRANSFER_DAY,
    COMPLIANCE_ID,
    COMPLIANCE_ID_2,
    CURVE_C1,
    CURVE_C2,
    HEDGE_ID,
    LOANS_M,
    LOANS_T,
    LOANS_V,
    MANAGER_ID,
    MARKETING_START_AT,
    SALE_DATE,
    SELLER_ALPHA,
    TRANSFER_DATE,
)
from .fixtures import (  # noqa: F401
    api,
    approved_agreement,
    awarded_trade,
    build_approved_agreement,
    build_attested_notices,
    build_awarded_trade,
    build_completed_transfer,
    build_desk,
    build_live_bid,
    build_locked_portfolio,
    build_published_package,
    build_ready_transfer,
    build_reconciled_data,
    build_settled_trade,
    build_stratified_package,
    build_valued_portfolio,
    completed_transfer,
    desk,
    live_bid,
    locked_portfolio,
    published_package,
    ready_transfer,
    refresh_agreement,
    refresh_package,
    refresh_portfolio,
    refresh_transfer,
    settled_trade,
    stratified_package,
    valued_portfolio,
)
from .test_users import (  # noqa: F401
    ADMIN,
    AGENCY_APPROVER,
    ANALYST,
    APPROVER,
    APPROVER_2,
    BUYER_SERVICER,
    COMPLIANCE,
    COMPLIANCE_2,
    COMPLIANCE_OFFICER,
    HEDGE,
    HEDGE_DESK,
    MANAGER,
    PLATFORM_ADMIN,
    SELLER_SERVICER,
    TRANSACTION_MANAGER,
    VALUATION_ANALYST,
    headers_with_empty_user_id,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_admin_headers,
    make_analyst_headers,
    make_approver_headers,
    make_buyer_headers,
    make_compliance_headers,
    make_hedge_headers,
    make_headers,
    make_manager_headers,
    make_seller_headers,
)
from .types import ApiResponse, Headers, JsonDict, JsonList  # noqa: F401

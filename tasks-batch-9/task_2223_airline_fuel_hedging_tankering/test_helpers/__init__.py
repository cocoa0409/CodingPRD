"""Test infrastructure for the Airline Fuel Hedging & Tankering API.

Importing this package registers the error-code -> HTTP status mapping with the
shared response validators, so ``validate_error(response, ERR_X)`` checks the
status code for free.

Layers:

* ``constants``   — business constants quoted from the PRD
* ``types``       — TypedDict shape of every resource
* ``api_errors``  — the error catalogue and its status mapping
* ``api_client``  — one method per endpoint
* ``factories``   — request-payload builders
* ``assertions``  — domain assertion helpers
* ``test_users``  — acting identities and their headers
* ``fixtures``    — composite scenario prefixes
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
from .api_client import ApiClient, api_client
from .api_errors import *  # noqa: F401,F403  (error id constants)
from .api_errors import ALL_NOT_FOUND_ERRORS, HTTP_STATUS_CODES
from .assertions import (
    assert_counterparty_credit,
    assert_effectiveness_outcome,
    assert_gallon_tenths,
    assert_identity_fields,
    assert_immutable_audit_record,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_millisecond_timestamp,
    assert_money,
    assert_mtm_totals,
    assert_nothing_pinned,
    assert_nothing_reconciled,
    assert_pagination_meta,
    assert_pct,
    assert_pinned_prices,
    assert_planned_economics,
    assert_price,
    assert_program_accounting,
    assert_program_coverage,
    assert_ratio,
    assert_reconciled_economics,
    assert_request_meta,
    assert_station_supply,
    assert_system_breach_exception,
    assert_undecided_exception,
    assert_versioned_resource,
    assert_whole_gallons,
    ids_of,
)
from .constants import (
    ADVERSE_MTM_FACTOR,
    ALL_ROLES,
    API_PREFIX,
    CHANGEOVER_BUFFER_DAYS,
    DEFAULT_CLOCK_UTC,
    DEFAULT_PAGE_LIMIT,
    EFFECTIVENESS_RATIO_MAX,
    EFFECTIVENESS_RATIO_MIN,
    FLEET_TANKER_BURN_FACTOR,
    INSTRUMENT_DELTA_FACTOR,
    LBS_PER_GALLON,
    MARGIN_RATE_PER_GAL,
    MAX_PAGE_LIMIT,
    PAYLOAD_PENALTY_SLOPE,
    PAYLOAD_RATIO_HINGE,
    ROLE_FUEL_ANALYST,
    ROLE_FUEL_OPS_CONTROLLER,
    ROLE_HEDGE_ACCOUNTANT,
    ROLE_RISK_POLICY_ADMIN,
    ROLE_STATION_COORDINATOR,
    ROLE_TREASURY_RISK_MANAGER,
    SEASON_FACTOR,
    SYSTEM_BREACH_JUSTIFICATION,
    TANKERING_RESERVE_GALLONS,
    UNDECLARED_ROLE,
)
from .test_users import (
    ACCOUNTANT,
    ACCOUNTANT_USER_ID,
    ADMIN,
    ADMIN_ALT,
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    ANALYST,
    ANALYST_ALT,
    ANALYST_USER_ID,
    ANALYST_USER_ID_ALT,
    DUAL_ADMIN,
    DUAL_ANALYST,
    DUAL_USER_ID,
    HEADERS_BY_ROLE,
    OPS,
    OPS_USER_ID,
    TEST_USERS,
    TREASURY,
    TREASURY_ALT,
    TRM_USER_ID,
    TRM_USER_ID_ALT,
    headers_for,
    headers_missing_role,
    headers_missing_user_id,
    headers_with_unknown_role,
    make_accountant_headers,
    make_admin_headers,
    make_analyst_headers,
    make_ops_headers,
    make_station_coordinator_headers,
    make_treasury_headers,
)
from .types import (
    CollateralPosting,
    ConsumptionForecast,
    Counterparty,
    EffectivenessTest,
    FlightLeg,
    HedgeInstrument,
    HedgePolicy,
    HedgeProgram,
    MarkToMarketRun,
    PolicyException,
    Station,
    SupplyContract,
    TankeringDirective,
)

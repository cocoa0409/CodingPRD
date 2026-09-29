"""Test infrastructure for the Battery Recycling & Second-Life Recovery API.

Re-exports the framework generics alongside the domain-specific client,
payload factories, assertions and composite state builders so test modules can
import everything from one place.
"""
# --- framework generics ---------------------------------------------------
from prd_bench_local_runner.testing import (
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

# --- domain infrastructure ------------------------------------------------
from . import assertions, constants, factories, fixtures, types
from .api_client import PREFIX, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_battery_passport,
    assert_credit_hold_consistent,
    assert_discharge_event,
    assert_facility,
    assert_hazmat_manifest,
    assert_identity_fields,
    assert_immutable_ledger_row,
    assert_intake,
    assert_intake_mass_conservation,
    assert_mass_precision,
    assert_metal_index_price,
    assert_module,
    assert_module_status_matches_disposition,
    assert_percentage_precision,
    assert_permit_allotment,
    assert_permit_allowance_invariant,
    assert_processing_campaign,
    assert_processing_line,
    assert_recovery_lot,
    assert_recovery_output,
    assert_settlement,
    assert_settlement_line_breakdown,
    assert_settlement_waterfall,
    assert_supplier,
    assert_supplier_obligation_invariant,
    assert_timestamp_with_three_fractional_digits,
    assert_triage_decision,
    assert_whole_cents,
    hazmat_surcharge_candidates,
    round_half_up,
    round_half_up_cents,
)
from .constants import CLOCK_INTAKE, CLOCK_PROCESS, CLOCK_STARTUP_DEFAULT, TEST_DEFAULTS
from .factories import OMIT
from .fixtures import (
    DEFAULT_MODULES,
    DEFAULT_OUTPUTS,
    LARGE_FOUR_METAL_INTAKE,
    SIX_METAL_OUTPUTS,
    TWO_LARGE_MODULES,
    WORLD_STAGES,
    advance_intake,
    advance_processing,
    bootstrap_network,
    build_world,
    charged_lot,
    credit_hold_world,
    disputed_settlement,
    finalized_lot,
    large_four_metal_disputed,
    large_four_metal_posted,
    large_four_metal_umpire_round,
    large_four_metal_world,
    permit_world,
    posted_final_settlement,
    released_intake,
    umpire_round_settlement,
)
from .test_users import (
    ROLE_HEADER_KEYS,
    TEST_USERS,
    make_assay_technician_headers,
    make_certification_officer_headers,
    make_compliance_officer_headers,
    make_headers,
    make_intake_clerk_headers,
    make_market_analyst_headers,
    make_plant_operator_headers,
    make_platform_admin_headers,
    make_settlement_accountant_headers,
    make_supplier_rep_headers,
    make_triage_engineer_headers,
)

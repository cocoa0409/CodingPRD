"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    GenericApiClient,
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
from .types import (
    UserRole, Crop, Grade, FumigationProduct,
    BinPosture, LotStatus, AlertStatus, FumigationStatus, PermitStatus,
    ContractStatus, TransportStatus, SettlementStatus, PolicyStatus,
    ClaimStatus, ValuationClause, ShrinkEventKind, CarryVariant,
    CarryRecommendation,
    Bin, GrainLot, TemperatureReading, SpoilageAlert, FumigationRecord,
    BinEntryPermit, StorageContract, LoadOut, Applicator, InsurancePolicy,
    InsuranceClaim, StorageAssessment, ShrinkEvent, ScaleTicket,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_bin, assert_lot, assert_reading, assert_alert, assert_fumigation,
    assert_permit, assert_contract, assert_loadout, assert_applicator,
    assert_policy, assert_claim, assert_assessment, assert_shrink_event,
    assert_instant_equal,
)
from .factories import (
    DEFAULTS,
    create_bin_payload, create_lot_payload, create_reading_payload,
    create_fumigation_payload, create_permit_payload, create_contract_payload,
    create_loadout_payload, create_policy_payload, create_claim_payload,
    create_applicator_payload, deliver_payload,
)
from .constants import (
    SHRINK_FACTOR_PCT_PER_POINT, STANDARD_MOISTURE_PCT,
    TEMP_EXCURSION_F, HOTSPOT_DELTA_F, HOTSPOT_ABS_F, STALE_DAYS_FULL,
    SCORE_WATCH, SCORE_ALERT, REI_HOURS,
    TIER1_FLOOR_CENTS, TIER2_FLOOR_CENTS, UNDER_DELIVERY_TOLERANCE_PCT,
    INVISIBLE_LOSS_MONTHLY_PCT, ANNUAL_INTEREST_PCT, SERVER_START_UTC,
)
from .test_users import (
    TEST_USERS,
    make_site_manager_headers, make_farm_owner_headers,
    make_applicator_headers, make_safety_officer_headers,
)
from .fixtures import (
    create_bin, create_lot, create_contract, create_applicator, create_policy,
    set_clock,
    setup_bin_with_lot, setup_bin_lot_contract, setup_bin_lot_contract_loadout,
    setup_dispatched_loadout, setup_delivered_loadout, setup_settled_loadout,
    get_lot, get_bin, get_contract, get_loadout, get_permit, get_claim,
    get_fumigation,
    create_hotspot_reading, get_first_alert_for_bin,
    create_confirmed_loss_alert, setup_confirmed_loss_claim,
    setup_active_fumigation,
)

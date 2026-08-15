"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
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

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_assay_result,
    assert_batch,
    assert_batch_consumption,
    assert_cleaning_validation,
    assert_customer,
    assert_formula,
    assert_formula_line,
    assert_identity_test,
    assert_lot_mass_invariant,
    assert_manufacturing_order,
    assert_material_lot,
    assert_production_line,
    assert_raw_material,
    assert_recall_event,
    assert_stability_chamber,
    assert_stability_study,
)
from .constants import (  # noqa: F401
    ACTUAL_BULK_MASS_G,
    ACTUAL_YIELD_UNITS,
    CLAIM_MAX_PCT,
    CLAIM_MIN_PCT,
    CONSUMPTION_QTY,
    DEFAULT_CHEMIST_ID,
    DEFAULT_CLOCK_INSTANT,
    DEFAULT_CLOCK_STAMP,
    DEFAULT_OPERATOR_ID,
    DEFAULT_QA_MANAGER_ID,
    FORMULA_DEFAULTS,
    LINE_DEFAULTS,
    LOT_QTY_RECEIVED,
    ORDERED_QTY,
    OVERAGE_PCT_MAX,
    OVERAGE_PCT_MIN,
    TIER_DEFAULTS,
    WINDOW_DAY1,
    WINDOW_DAY2,
    WINDOW_DAY3,
    YIELD_TOLERANCE_PCT,
)
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    make_brandrep_headers,
    make_production_operator_headers,
    make_production_planner_headers,
    make_qa_chemist_headers,
    make_qa_manager_headers,
)

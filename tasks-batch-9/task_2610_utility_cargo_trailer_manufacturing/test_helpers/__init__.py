"""Test infrastructure for the Utility & Cargo Trailer Manufacturing API."""

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

from . import api_errors, constants, factories, fixtures
from .api_client import ApiClient, TrailerPlantClient, api_client
from .api_errors import *  # noqa: F401,F403
from .assertions import (
    assert_append_only_audit_fields,
    assert_instant,
    assert_floor_plan_conserved,
    assert_full_audit_fields,
    assert_mco_number,
    assert_money,
    assert_no_money_computed,
    assert_one_decimal,
    assert_pagination_meta,
    assert_timestamp_with_millis,
    assert_unit_dimensions,
    assert_version_advanced,
    assert_vin_composition,
    assert_weight_budget_balances,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_HEADERS,
    ASSEMBLY_TECH,
    CERT_OFFICER,
    CERT_OFFICER_1_ID,
    CERT_OFFICER_2,
    CERT_OFFICER_2_ID,
    DEALER,
    DEALER_USER_ID,
    PLANT_ENGINEER,
    PLANT_ENGINEER_ID,
    QUALITY_INSPECTOR,
    QUALITY_INSPECTOR_ID,
    SALES_ADMIN,
    SALES_ADMIN_ID,
    TEST_USERS,
    WELD_SUPERVISOR,
    WELD_SUPERVISOR_ID,
    ASSEMBLY_TECH_ID,
    headers_for,
    make_dealer_headers,
    make_headers,
)
from .types import (
    ALL_ROLES,
    APPEND_ONLY_AUDIT_FIELDS,
    FULL_AUDIT_FIELDS,
    BuildStatus,
    CertificationDecision,
    CertificationStatus,
    ClaimDecision,
    ClaimStatus,
    ComplianceStatus,
    CoverageVariant,
    DealerStatus,
    FloorPlanStatus,
    InspectionResult,
    LabelStatus,
    OptionStatus,
    OrderStatus,
    ReservationStatus,
    RoadTestStatus,
    Role,
    SystemsStage,
)

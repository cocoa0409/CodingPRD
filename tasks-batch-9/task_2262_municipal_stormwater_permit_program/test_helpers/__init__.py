"""Test helper package for the Municipal Stormwater Permit Program API.

Layering: the pip-installed ``prd_bench_local_runner.testing`` framework provides
the generic HTTP client, envelope validators and header builder; this package
adds the PRD-specific endpoint surface, payload factories, domain assertions,
business constants, actor identities and composite state fixtures; the test
suite itself imports only from here.

Importing this package registers the error-id to HTTP-status mapping of the
PRD's error catalogue with the framework validators.
"""

from . import assertions, factories, fixtures
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_cents,
    assert_common_fields,
    assert_deficiency_score,
    assert_facility_currency,
    assert_fee_chain,
    assert_four_dp,
    assert_load_assessment,
    assert_measure_attainment,
    assert_page_meta,
    assert_penalty_derivation,
    assert_posture,
    assert_report_invalidated,
    assert_row_unchanged,
    assert_two_dp,
    assert_version_advanced_by,
)
from .constants import (
    BACTERIA_LIMIT_MPN,
    CLASS_SURCHARGE_PCT,
    COOLING_OFF_DAYS,
    CREDIT_CAP_PCT,
    CRITICAL_FINDING_POINTS,
    DEFAULT_ERU_SQFT,
    DEFAULT_LIMIT,
    DEFICIENCY_SCORE_CAP,
    ESCALATION_THRESHOLD,
    INITIAL_CLOCK,
    LARGE_SITE_ADDER,
    LB_PER_LANE_MILE,
    MAJOR_FINDING_POINTS,
    MAX_BILLABLE_DAYS,
    MAX_CREDIT_PCT,
    MAX_LIMIT,
    MAX_REOPEN_COUNT,
    MAX_RESUBMISSIONS,
    MG_PER_L_KL_TO_LB,
    MINOR_FINDING_POINTS,
    NO_AGREEMENT_ADDER,
    OVERDUE_ADDER,
    PENALTY_BASE_CENTS,
    PER_DAY_CENTS,
    RAINFALL_MULTIPLIER,
    RATE_TIER1_CENTS_PER_ERU,
    RATE_TIER2_CENTS_PER_ERU,
    RATE_TIER3_CENTS_PER_ERU,
    REQUIRED_SAMPLES_PER_YEAR,
    SIX_MEASURE_CODES,
    STANDARD_MEASURE_SET,
    SUBMISSION_WINDOW_DAYS,
    SURFACTANT_HARD_TRIGGER_MG_PER_L,
    SURFACTANT_LIMIT_MG_PER_L,
    UNRESOLVABLE_UUID,
)
from .test_users import (
    CLERK_HEADERS,
    CLERK_TWO_HEADERS,
    IDDE_HEADERS,
    IDDE_TWO_HEADERS,
    INSPECTOR_HEADERS,
    INSPECTOR_TWO_HEADERS,
    MANAGER_HEADERS,
    MANAGER_TWO_HEADERS,
    OFFICER_HEADERS,
    OFFICER_TWO_HEADERS,
    OPERATIONS_HEADERS,
    OPERATIONS_TWO_HEADERS,
    TEST_USERS,
    headers_for,
    headers_with_unknown_actor,
    make_property_owner_headers,
    role_only_headers,
)
from .types import UserRole

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "UserRole",
    "api_client",
    "assertions",
    "factories",
    "fixtures",
]

"""Barrel export: framework generics + LIHTC-specific test infrastructure."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific.
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .assertions import (  # noqa: F401
    assert_project, assert_building, assert_unit, assert_unit_li_invariant,
    assert_household, assert_certification, assert_lease, assert_inspection,
    assert_finding, assert_form8609,
)
from .factories import (  # noqa: F401
    create_project_payload, create_building_payload, create_unit_payload,
    create_household_payload, create_certification_payload, lease_payload,
    create_inspection_payload, issue_form8609_payload, approve_payload,
    recapture_payload, set_clock_payload,
)
from .constants import (  # noqa: F401
    HH_FACTOR_BP, AMI_PCT, CREDIT_BP, THRESHOLDS, TEST_DEFAULTS,
)
from .test_users import (  # noqa: F401
    TEST_USERS, make_owner_agent_headers, make_state_hfa_headers,
    STATE_HFA_1, STATE_HFA_2, NO_AUTH_HEADERS,
)
from .fixtures import *  # noqa: F401,F403
from .fixtures import (  # noqa: F401
    create_project, create_building, create_unit, create_household,
    setup_project_building, setup_project_building_unit,
    create_submitted_certification, create_approved_certification,
    make_qualified_unit, make_over_income_unit,
    setup_set_aside_met_with_designated_units, issue_provisional_8609,
    issue_final_8609, setup_building_at_provisional, setup_building_at_final,
    setup_dual_variant_building_at_final, schedule_inspection,
    setup_failed_inspection_with_open_finding,
    setup_noncompliant_project_with_final_building,
    FLAT_MONTHLY_QUALIFIED, DUAL_VARIANT_MONTHLY,
)

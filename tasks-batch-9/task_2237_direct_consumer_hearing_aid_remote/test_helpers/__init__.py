"""Barrel export: framework generics + domain-specific test infrastructure."""
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

from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN,
    CARE_OPS,
    CARE_OPS_2,
    COMPLIANCE,
    COMPLIANCE_2,
    FIRMWARE_ENGINEER,
    REIMBURSEMENT,
    REIMBURSEMENT_2,
    REPAIR_TECH,
    TEST_USERS,
    make_admin_headers,
    make_care_ops_headers,
    make_compliance_headers,
    make_firmware_engineer_headers,
    make_hearing_professional_headers,
    make_licensed_audiologist_headers,
    make_patient_headers,
    make_reimbursement_headers,
    make_repair_tech_headers,
)
from .types import *  # noqa: F401,F403

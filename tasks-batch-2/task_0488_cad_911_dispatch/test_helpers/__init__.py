"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    assert_cost_precision, assert_version_incremented, assert_timestamp_format,
    assert_race_outcome, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    run_race, build_user_headers, NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_agency, assert_station, assert_unit, assert_premise_alert,
    assert_incident, assert_assignment, assert_disposition, assert_cfs_report,
)
from .factories import (
    create_agency_payload, create_station_payload, create_unit_payload,
    create_premise_alert_payload, create_incident_payload,
    create_assignment_payload, create_disposition_payload, create_report_payload,
)
from .constants import (
    BASE_PRIORITY, REQUIRED_DISCIPLINES, CAPABILITY_PREFERENCE,
    UNKNOWN_CONFIDENCE_CLAMP, DEFAULT_CLOCK,
)
from .test_users import TEST_USERS, make_field_unit_headers
from .fixtures import (
    set_clock, create_agency, create_station, create_unit,
    setup_agency_station_unit, create_incident, dispatch_unit,
    advance_assignment, get_incident_version, setup_dispatched_incident,
    setup_onscene_incident, setup_closed_incident, setup_report,
    SUP, CALL, DISP, REC, CLOCK,
)

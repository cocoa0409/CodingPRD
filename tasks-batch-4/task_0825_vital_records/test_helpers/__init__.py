"""Barrel export: framework generics + Vital Records PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
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
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_common_fields,
    assert_facility,
    assert_certifier,
    assert_vital_event,
    assert_medical_certification,
    assert_copy_request,
    assert_event_ledger_nonnegative,
)
from .factories import (
    DEFAULTS,
    create_facility_payload,
    create_certifier_payload,
    create_vital_event_payload,
    create_certification_payload,
    create_amendment_payload,
    create_paternity_payload,
    create_copy_request_payload,
    create_apostille_payload,
    create_packet_payload,
    create_report_payload,
)
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    STATUTORY_WINDOW_DAYS,
    DELAYED_BASE_FEE_CENTS,
    PER_DAY_SURCHARGE_CENTS,
    MAX_SURCHARGE_CENTS,
    SEARCH_FEE_CENTS,
    ADDITIONAL_COPY_CENTS,
    EXPEDITE_SURCHARGE_CENTS,
    INFORMATIONAL_COPY_CENTS,
    PUBLIC_THRESHOLD_YEARS,
    ELIGIBLE_RELATIONSHIPS,
    STATE_SHARE_PCT,
    RESCISSION_WINDOW_DAYS,
    EVIDENCE_THRESHOLD_DAYS,
    HEARING_BUFFER_MINUTES,
)
from .test_users import (
    TEST_USERS,
    make_registrar_headers,
    make_applicant_headers,
    make_facility_filer_headers,
    make_medical_certifier_headers,
)
from .fixtures import (
    set_clock,
    create_facility,
    create_certifier,
    create_vital_event,
    file_event,
    register_event,
    return_event,
    void_event,
    create_certification,
    certify,
    create_amendment,
    submit_amendment,
    approve_amendment,
    reject_amendment,
    create_paternity,
    acknowledge_paternity,
    create_copy_request,
    verify_copy,
    issue_copy,
    create_apostille,
    create_packet,
    accept_packet,
    event_version,
    setup_registered_birth_event,
    setup_registered_death_event,
    setup_id_verified_copy,
)

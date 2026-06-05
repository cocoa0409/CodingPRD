"""Barrel export: framework generics + Lab-Results-specific code."""
# Framework generics (re-exported for convenience).
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
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

# Domain types
from .types import (  # noqa: F401
    AcknowledgementReceipt,
    AckMethod,
    AgeBand,
    AnalyteCode,
    Clinician,
    ClinicianRoleType,
    ContainerCode,
    Criticality,
    CriticalNotification,
    Instrument,
    InstrumentRun,
    InstrumentRunStatus,
    LabOrder,
    LabOrderPriority,
    LabOrderStatus,
    NotificationChannel,
    NotificationStatus,
    PanelCode,
    Patient,
    RejectReason,
    Result,
    ResultStatus,
    RetestReason,
    RetestRequest,
    RetestStatus,
    Specimen,
    SpecimenStatus,
    UserRole,
)

# API surface
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES

# Assertions
from .assertions import (
    assert_acknowledgement_receipt,
    assert_clinician,
    assert_common_fields,
    assert_critical_notification,
    assert_instrument,
    assert_instrument_run,
    assert_lab_order,
    assert_minimal_audit_fields,
    assert_patient,
    assert_result,
    assert_retest_request,
    assert_specimen,
)

# Factories
from .factories import (
    amend_result_payload,
    create_acknowledgement_payload,
    create_clinician_payload,
    create_instrument_payload,
    create_instrument_run_payload,
    create_lab_order_payload,
    create_patient_payload,
    create_result_payload,
    create_retest_request_payload,
    create_specimen_payload,
    reject_specimen_payload,
    release_result_payload,
    set_clock_payload,
)

# Domain constants
from .constants import (
    COLLECTOR_BUSY_WINDOW_MINUTES,
    DEFAULT_QC_BUFFER_MINUTES,
    NEONATE_GLUCOSE_PANIC_LOW,
    NEONATE_K_PANIC_HIGH,
    NEONATE_K_PANIC_LOW,
    NUMERIC_VALUE_DECIMAL_PLACES,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    PHONE_ACK_DEADLINE_MINUTES,
    QC_BUFFER_MAX,
    QC_BUFFER_MIN,
    SMS_ACK_DEADLINE_MINUTES,
)

# Role headers
from .test_users import (
    TEST_USERS,
    make_anonymous_headers,
    make_headers,
    make_lab_director_headers,
    make_lab_tech_headers,
    make_ordering_provider_headers,
    make_phlebotomist_headers,
)

# Composite fixtures
from .fixtures import (
    Actors,
    accession_specimen,
    acknowledge_notification,
    amend_result,
    bootstrap_actors,
    collect_specimen,
    complete_instrument_run,
    create_instrument_run,
    create_order,
    create_result,
    create_specimen,
    escalate_notification,
    get_lab_order,
    get_lab_order_version,
    get_notification_for_result,
    invalidate_result,
    register_clinician,
    register_director,
    register_instrument,
    register_lab_tech,
    register_ordering_provider,
    register_patient,
    register_phlebotomist,
    reject_specimen,
    release_result,
    send_notification,
    set_clock,
    setup_pending_critical_notification,
    setup_provisional_result,
    setup_released_result,
    setup_sent_critical_notification,
    transit_specimen,
    walk_specimen_to_accessioned,
)

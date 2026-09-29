"""Test infrastructure for the Fire Apparatus Body Manufacturing API.

Importing this package registers the error-to-HTTP-status catalogue with the
framework, so every ``validate_error`` call cross-checks the HTTP status of a
rejection without the test having to name it.
"""

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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ErrorCode
from .assertions import (
    assert_audit_fields,
    assert_axle_loads,
    assert_calendar_date,
    assert_clock_stamp,
    assert_created_at_precision,
    assert_ids_in_order,
    assert_immutable_record_fields,
    assert_list_meta,
    assert_price_reconciliation,
    assert_program_ledger,
    assert_response_envelope,
    assert_slot_occupancy,
    assert_spec_scores,
    assert_sweep_report,
    assert_unit_dimensions,
    assert_unit_money,
    assert_updated_at_refreshed,
    assert_version_advanced_by,
    assert_warranty_window,
    soft_ceiling,
)
from .constants import *  # noqa: F401,F403
from .factories import (
    build_certification_test_payload,
    build_change_order_payload,
    build_clause_payload,
    build_compliance_entry_payload,
    build_delivery_payload,
    build_disposition_payload,
    build_inspection_trip_payload,
    build_line_item,
    build_plant_bay_payload,
    build_program_payload,
    build_reservation_payload,
    build_revision_payload,
    build_slot_line_payload,
    build_specification_payload,
    build_test_result_payload,
    build_training_payload,
    build_unit_order_payload,
)
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ALL_ROLE_HEADER_BUILDERS,
    BODY_ENGINEER_ID,
    PROGRAM_ADMIN_ID,
    PURCHASING_OFFICER_ID,
    SECOND_BODY_ENGINEER_ID,
    SECOND_THIRD_PARTY_TESTER_ID,
    SPEC_AUTHOR_ID,
    SPEC_RELEASER_ID,
    THIRD_PARTY_TESTER_ID,
    make_body_engineer_headers,
    make_customer_committee_rep_headers,
    make_headers_missing_role,
    make_headers_missing_user_id,
    make_headers_with_unknown_role,
    make_program_admin_headers,
    make_purchasing_officer_headers,
    make_third_party_tester_headers,
)
from .types import (
    BuildStatus,
    CertificationStatus,
    CertificationTestStatus,
    ChangeOrderStatus,
    ClauseCategory,
    ComplianceDisposition,
    ComplianceResponse,
    ComponentType,
    InvalidatedReason,
    LongLeadStatus,
    ProgramStatus,
    ReservationStatus,
    SpecificationStatus,
    SuspensionReason,
    TestResult,
    TestStandard,
    TripStatus,
    TripType,
    UnitType,
    UserRole,
    WarrantyStatus,
    WeightStatus,
)

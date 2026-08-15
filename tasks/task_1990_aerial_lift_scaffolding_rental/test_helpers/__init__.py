"""Barrel export: framework generics + PRD-specific helpers."""
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
from .types import (
    CustomerStatus, EquipmentCategory, EquipmentUnitStatus,
    RentalContractStatus, RentalLineStatus, DeliveryTripStatus, TripType,
    InspectionResult, InspectionRecordStatus, ClaimType, DamageClaimStatus,
    ClaimDecision, UserRole,
    CustomerAccount, EquipmentClass, EquipmentUnit, RentalContract, RentalLine,
    DeliveryTrip, InspectionRecord, DamageClaim, TrainingRecord, InvoiceView,
)
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_customer_account, assert_equipment_class, assert_equipment_unit,
    assert_rental_contract, assert_rental_line, assert_delivery_trip,
    assert_inspection_record, assert_damage_claim, assert_training_record,
    assert_invoice,
)
from .factories import (
    create_customer_account_payload, create_equipment_class_payload,
    create_equipment_unit_payload, create_rental_contract_payload,
    create_rental_line_payload, create_delivery_trip_payload,
    create_trip_completion_payload, create_trip_failure_payload,
    create_trip_reschedule_payload, create_inspection_record_payload,
    create_training_record_payload, create_damage_claim_payload,
    create_claim_assessment_payload, create_claim_resolution_payload,
    set_clock_payload,
)
from .constants import (
    CLOCK_STARTUP_DEFAULT, SECONDS_PER_DAY, DAYS_PER_WEEK, DAYS_PER_MONTH,
    TRIP_FEE_CENTS, FREE_STANDBY_MINUTES, STANDBY_RATE_CENTS_PER_MINUTE,
    LABOR_RATE_CENTS_PER_HOUR, WAIVER_LIABILITY_PCT, RECOVERY_CREDIT_PCT,
    ROUTE_BUFFER_MINUTES, DEFAULT_CLASS_RATES,
)
from .test_users import (
    TEST_USERS, make_branch_manager_headers, make_rental_coordinator_headers,
    make_driver_headers, make_yard_technician_headers, make_customer_headers,
)
from .fixtures import (
    set_clock, create_customer, create_equipment_class, create_equipment_unit,
    create_contract, get_contract, add_line, activate_contract, close_contract,
    setup_draft_contract_with_line, schedule_trip, start_trip, complete_trip,
    fail_trip, deliver_line, setup_active_rental, off_rent, re_rent,
    pickup_line, setup_returned_line, create_training_record,
    create_inspection_record, certify_inspection, reject_inspection,
    create_claim, assess_claim, charge_claim, dispute_claim, resolve_claim,
    setup_charged_damage_claim, setup_suspended_customer, get_invoice,
    get_line, get_unit, get_customer, get_trip, get_claim, count_units,
)

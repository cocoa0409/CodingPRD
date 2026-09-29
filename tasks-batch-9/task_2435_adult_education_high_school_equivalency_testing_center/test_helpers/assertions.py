"""Shape assertions and conserved-quantity checkers for every record type."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants
from .types import (
    AccommodationStatus,
    AllocationStatus,
    AttendanceStatus,
    CenterAuthorizationStatus,
    CredentialIssuanceStatus,
    CredentialStanding,
    CredentialType,
    EnrollmentStatus,
    FundingPeriodStatus,
    IdentityStatus,
    IntakeStatus,
    MeasureType,
    OutcomeStatus,
    ProctorCertificationStatus,
    ProgramTrack,
    RegistrationStatus,
    RoomStatus,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestEventPurpose,
    TestEventStatus,
    TestForm,
    TranscriptDelivery,
    TranscriptDestination,
    TranscriptOrderStatus,
)

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def assert_common_fields(data: JsonDict) -> None:
    """Every record carries an id, two timestamps and an integer version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int), data["version"]
    assert data["version"] >= 1, data["version"]


def assert_fields_present(data: JsonDict, field_names: Iterable[str]) -> None:
    missing = [name for name in field_names if name not in data]
    assert not missing, f"missing fields {missing} in {sorted(data)}"


def assert_envelope_meta(meta: JsonDict) -> None:
    """The request identifier is opaque but always prefixed ``req_``."""
    assert isinstance(meta.get("api_request_id"), str), meta
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]


def assert_created_at_ascending(items: Iterable[JsonDict]) -> None:
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"not in created_at ascending order: {stamps}"


def assert_hours_value(value: Any, expected: Any = None) -> float:
    """Instructional hours are carried to two decimal places."""
    as_float = float(value)
    assert round(as_float, 2) == as_float, f"hours carry more than two decimals: {value!r}"
    if expected is not None:
        assert as_float == float(expected), f"expected {expected} hours, saw {value!r}"
    return as_float


# ---------------------------------------------------------------------------
# Entity shape assertions
# ---------------------------------------------------------------------------


def assert_student(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "full_name",
            "email",
            "primary_track",
            "intake_status",
            "orientation_completed_at",
            "placement_efl_level",
            "total_instructional_hours",
            "voucher_granted_cents",
            "voucher_balance_cents",
            "voucher_spent_cents",
            "self_pay_authorized",
            "exam_fee_owed_cents",
            "credential_status",
            "active_enrollment_count",
        ],
    )
    assert data["primary_track"] in vars(ProgramTrack).values(), data["primary_track"]
    assert data["intake_status"] in vars(IntakeStatus).values(), data["intake_status"]
    assert data["credential_status"] in vars(CredentialStanding).values(), data["credential_status"]
    assert isinstance(data["self_pay_authorized"], bool), data["self_pay_authorized"]
    assert isinstance(data["active_enrollment_count"], int), data["active_enrollment_count"]
    assert_hours_value(data["total_instructional_hours"])
    assert_voucher_ledger_conserved(data)
    return data


def assert_testing_center(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "name",
            "state_code",
            "authorization_status",
            "allowed_subtests",
            "max_sessions_per_week",
            "authorized_at",
            "suspended_reason",
        ],
    )
    assert (
        data["authorization_status"] in vars(CenterAuthorizationStatus).values()
    ), data["authorization_status"]
    assert isinstance(data["allowed_subtests"], list), data["allowed_subtests"]
    for subtest in data["allowed_subtests"]:
        assert subtest in Subtest.ALL, subtest
    assert isinstance(data["max_sessions_per_week"], int), data["max_sessions_per_week"]
    return data


def assert_testing_room(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "testing_center_id",
            "room_code",
            "seat_capacity",
            "turnaround_buffer_minutes",
            "status",
            "service_note",
        ],
    )
    assert data["status"] in vars(RoomStatus).values(), data["status"]
    assert (
        constants.MIN_SEAT_CAPACITY <= data["seat_capacity"] <= constants.MAX_SEAT_CAPACITY
    ), data["seat_capacity"]
    assert (
        constants.MIN_TURNAROUND_BUFFER_MINUTES
        <= data["turnaround_buffer_minutes"]
        <= constants.MAX_TURNAROUND_BUFFER_MINUTES
    ), data["turnaround_buffer_minutes"]
    return data


def assert_proctor(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "testing_center_id",
            "full_name",
            "certification_status",
            "certification_expires_at",
            "daily_hour_cap",
            "assigned_session_count",
        ],
    )
    assert (
        data["certification_status"] in vars(ProctorCertificationStatus).values()
    ), data["certification_status"]
    assert float(data["daily_hour_cap"]) > 0, data["daily_hour_cap"]
    assert float(data["daily_hour_cap"]) <= constants.MAX_DAILY_HOUR_CAP, data["daily_hour_cap"]
    assert isinstance(data["assigned_session_count"], int), data["assigned_session_count"]
    return data


def assert_class_section(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "program_track",
            "title",
            "instructor_user_id",
            "min_efl_level",
            "max_efl_level",
            "seats_total",
            "seats_taken",
            "seats_available",
            "weekly_hours",
            "status",
        ],
    )
    assert data["program_track"] in vars(ProgramTrack).values(), data["program_track"]
    assert data["status"] in vars(SectionStatus).values(), data["status"]
    assert data["min_efl_level"] <= data["max_efl_level"], data
    assert_section_seats_conserved(data)
    return data


def assert_enrollment(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "class_section_id",
            "status",
            "entry_efl_level",
            "posted_hours",
            "post_test_eligible",
            "withdrawn_at",
            "exit_reason",
        ],
    )
    assert data["status"] in vars(EnrollmentStatus).values(), data["status"]
    assert isinstance(data["post_test_eligible"], bool), data["post_test_eligible"]
    assert_hours_value(data["posted_hours"])
    return data


def assert_attendance_entry(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "enrollment_id",
            "attendance_date",
            "hours",
            "status",
            "void_reason",
            "posted_by_user_id",
        ],
    )
    assert data["status"] in vars(AttendanceStatus).values(), data["status"]
    hours = assert_hours_value(data["hours"])
    assert 0 < hours <= constants.MAX_ATTENDANCE_HOURS, hours
    assert isinstance(data["posted_by_user_id"], str) and data["posted_by_user_id"], data
    return data


def assert_test_event(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "enrollment_id",
            "purpose",
            "test_form",
            "scheduled_for",
            "test_date",
            "scale_score",
            "efl_level",
            "status",
            "invalidation_reason",
        ],
    )
    assert data["purpose"] in vars(TestEventPurpose).values(), data["purpose"]
    assert data["test_form"] in vars(TestForm).values(), data["test_form"]
    assert data["status"] in vars(TestEventStatus).values(), data["status"]
    if data["efl_level"] is not None:
        assert (
            constants.MIN_EFL_LEVEL <= data["efl_level"] <= constants.MAX_EFL_LEVEL
        ), data["efl_level"]
    return data


def assert_exam_session(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "testing_room_id",
            "proctor_id",
            "subtest",
            "starts_at",
            "ends_at",
            "requested_seats",
            "seat_capacity",
            "seats_taken",
            "duration_hours",
            "supported_formats",
            "status",
            "cancel_reason",
        ],
    )
    assert data["subtest"] in Subtest.ALL, data["subtest"]
    assert data["status"] in vars(SessionStatus).values(), data["status"]
    assert isinstance(data["supported_formats"], list), data["supported_formats"]
    assert_hours_value(data["duration_hours"])
    assert data["seats_taken"] <= data["seat_capacity"], data
    return data


def assert_exam_registration(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "exam_session_id",
            "accommodation_request_id",
            "identity_verified_by_proctor_id",
            "registration_status",
            "identity_status",
            "identity_document_type",
            "prior_scored_attempts",
            "gross_fee_cents",
            "accommodation_surcharge_cents",
            "discount_cents",
            "voucher_applied_cents",
            "fee_due_cents",
            "scale_score",
            "result_outcome",
            "checked_in_at",
            "refunded_cents",
        ],
    )
    assert (
        data["registration_status"] in vars(RegistrationStatus).values()
    ), data["registration_status"]
    assert data["identity_status"] in vars(IdentityStatus).values(), data["identity_status"]
    assert_registration_fee_arithmetic(data)
    return data


def assert_accommodation_request(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "requested_format",
            "documentation_ref",
            "status",
            "info_request_rounds",
            "granted_format",
            "valid_until",
            "decision_note",
        ],
    )
    assert data["status"] in vars(AccommodationStatus).values(), data["status"]
    assert 0 <= data["info_request_rounds"] <= 2, data["info_request_rounds"]
    return data


def assert_outcome_record(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "funding_period_id",
            "credential_issuance_id",
            "measure_type",
            "evidence_ref",
            "status",
            "recorded_by_user_id",
            "certified_by_user_id",
            "weight",
            "allocated_cents",
            "allocation_status",
            "rescission_reason",
        ],
    )
    assert data["measure_type"] in vars(MeasureType).values(), data["measure_type"]
    assert data["status"] in vars(OutcomeStatus).values(), data["status"]
    assert data["allocation_status"] in vars(AllocationStatus).values(), data["allocation_status"]
    assert float(data["weight"]) == constants.MEASURE_WEIGHTS[data["measure_type"]], data
    return data


def assert_credential_issuance(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "credential_type",
            "composite_score",
            "subtest_scores",
            "qualifying_registration_ids",
            "status",
            "issued_at",
            "void_reason",
        ],
    )
    assert data["credential_type"] == CredentialType.HSE_DIPLOMA, data["credential_type"]
    assert data["status"] in vars(CredentialIssuanceStatus).values(), data["status"]
    assert isinstance(data["subtest_scores"], dict), data["subtest_scores"]
    assert isinstance(data["qualifying_registration_ids"], list), data
    return data


def assert_transcript_order(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "student_id",
            "credential_issuance_id",
            "copies",
            "delivery",
            "destination_type",
            "base_charge_cents",
            "waiver_cents",
            "state_records_fee_cents",
            "total_charge_cents",
            "status",
            "fulfilled_at",
            "hold_reason",
        ],
    )
    assert data["delivery"] in vars(TranscriptDelivery).values(), data["delivery"]
    assert (
        data["destination_type"] in vars(TranscriptDestination).values()
    ), data["destination_type"]
    assert data["status"] in vars(TranscriptOrderStatus).values(), data["status"]
    assert_transcript_charge_arithmetic(data)
    return data


def assert_funding_period(data: JsonDict) -> JsonDict:
    assert_common_fields(data)
    assert_fields_present(
        data,
        [
            "label",
            "start_date",
            "end_date",
            "rate_cents_per_weight",
            "total_cents",
            "committed_cents",
            "available_cents",
            "allocation_run_count",
            "last_allocation_run_at",
            "last_allocation_variant",
            "status",
        ],
    )
    assert data["status"] in vars(FundingPeriodStatus).values(), data["status"]
    assert_funding_pool_conserved(data)
    return data


def assert_skill_gain_read(data: JsonDict) -> JsonDict:
    assert_fields_present(
        data,
        [
            "student_id",
            "variant",
            "entry_efl_level",
            "post_efl_level",
            "best_post_scale_score",
            "latest_post_scale_score",
            "levels_gained",
            "msg_achieved",
        ],
    )
    assert isinstance(data["msg_achieved"], bool), data["msg_achieved"]
    # ``levels_gained`` is defined as "the post level less the entry level"; the subtraction is
    # only an integer once a post side exists, so the shape check is scoped to that case.
    if data["post_efl_level"] is not None:
        assert isinstance(data["levels_gained"], int), data["levels_gained"]
    return data


def assert_allocation_preview(data: JsonDict) -> JsonDict:
    assert_fields_present(
        data,
        [
            "funding_period_id",
            "variant",
            "total_weight",
            "line_count",
            "projected_committed_cents",
            "projected_available_cents",
            "deferred_line_count",
        ],
    )
    assert isinstance(data["line_count"], int), data["line_count"]
    assert isinstance(data["deferred_line_count"], int), data["deferred_line_count"]
    return data


# ---------------------------------------------------------------------------
# Conserved-quantity checkers
# ---------------------------------------------------------------------------


def assert_voucher_ledger_conserved(student: JsonDict) -> None:
    """Granted funds always equal the balance plus what has been spent."""
    assert (
        student["voucher_granted_cents"]
        == student["voucher_balance_cents"] + student["voucher_spent_cents"]
    ), (
        "voucher ledger broken: granted="
        f"{student['voucher_granted_cents']} balance={student['voucher_balance_cents']} "
        f"spent={student['voucher_spent_cents']}"
    )


def assert_section_seats_conserved(section: JsonDict) -> None:
    """A section's free seats are its total less the seats taken."""
    assert section["seats_available"] == section["seats_total"] - section["seats_taken"], (
        f"section seats broken: total={section['seats_total']} taken={section['seats_taken']} "
        f"available={section['seats_available']}"
    )


def assert_funding_pool_conserved(period: JsonDict) -> None:
    """A period's available pool is its total less what is committed."""
    assert period["available_cents"] == period["total_cents"] - period["committed_cents"], (
        f"funding pool broken: total={period['total_cents']} "
        f"committed={period['committed_cents']} available={period['available_cents']}"
    )


def assert_registration_fee_arithmetic(registration: JsonDict) -> None:
    """The fee due is the discounted billable amount less the voucher applied."""
    billable = registration["gross_fee_cents"] + registration["accommodation_surcharge_cents"]
    net = billable - registration["discount_cents"]
    assert registration["voucher_applied_cents"] <= net, registration
    assert registration["fee_due_cents"] == net - registration["voucher_applied_cents"], (
        f"fee arithmetic broken: gross={registration['gross_fee_cents']} "
        f"surcharge={registration['accommodation_surcharge_cents']} "
        f"discount={registration['discount_cents']} "
        f"voucher={registration['voucher_applied_cents']} due={registration['fee_due_cents']}"
    )


def assert_transcript_charge_arithmetic(order: JsonDict) -> None:
    """The total charge is the waived base plus the state-records fee."""
    net = order["base_charge_cents"] - order["waiver_cents"]
    assert order["total_charge_cents"] == net + order["state_records_fee_cents"], (
        f"transcript charge broken: base={order['base_charge_cents']} "
        f"waiver={order['waiver_cents']} fee={order['state_records_fee_cents']} "
        f"total={order['total_charge_cents']}"
    )


def assert_session_seats_within_capacity(session: JsonDict) -> None:
    assert 0 <= session["seats_taken"] <= session["seat_capacity"], session


def assert_no_record_with_id(items: Iterable[JsonDict], record_id: Optional[str]) -> None:
    ids = [item["id"] for item in items]
    assert record_id not in ids, f"{record_id} should not exist, listing held {ids}"

"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §3.8)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_base(data: dict):
    _assert_common_fields(data, "Base")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]


def assert_aircraft(data: dict):
    _assert_common_fields(data, "Aircraft")
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert data["aircraft_class"] in ("ROTOR_WING", "FIXED_WING")
    assert data["medical_config"] in ("BLS_CAPABLE", "ALS_CAPABLE", "CCT_CAPABLE")
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "MAINTENANCE")


def assert_crew_member(data: dict):
    _assert_common_fields(data, "CrewMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["crew_role"] in ("PILOT", "NURSE", "PARAMEDIC")
    assert data["status"] in ("ACTIVE", "REMEDIATION_HOLD", "INACTIVE")
    assert isinstance(data["deficiency_points_90d"], int)
    assert isinstance(data["duty_minutes_calendar_day"], int)


def assert_crew_shift(data: dict):
    _assert_common_fields(data, "CrewShift")
    assert data["status"] in ("OPEN", "CLOSED")
    assert is_iso8601_timestamp(data["planned_start_iso"])
    assert is_iso8601_timestamp(data["planned_end_iso"])
    assert isinstance(data["planned_minutes"], int) and data["planned_minutes"] > 0


def assert_patient(data: dict):
    _assert_common_fields(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["weight_kg"] > 0


def assert_membership(data: dict):
    _assert_common_fields(data, "MembershipSubscription")
    assert data["tier"] in ("STANDARD", "FAMILY")
    assert data["status"] in ("ACTIVE", "LAPSED", "TERMINATED")
    assert isinstance(data["effective_from"], str)


def assert_mission_request(data: dict):
    _assert_common_fields(data, "MissionRequest")
    assert data["transport_class"] in (
        "EMERGENCY_SCENE", "EMERGENCY_INTERFACILITY",
        "SCHEDULED_INTERFACILITY", "INTERNATIONAL_REPATRIATION",
    )
    assert data["status"] in ("RECEIVED", "TRIAGED", "PENDING_INFO", "ACCEPTED", "DECLINED")


def assert_mission(data: dict):
    _assert_common_fields(data, "Mission")
    assert data["status"] in (
        "PLANNING", "LAUNCHED", "WEATHER_HOLD", "AT_PATIENT", "IN_TRANSIT",
        "DIVERTED", "AT_DESTINATION", "COMPLETED", "ABORTED", "CANCELLED",
    )
    assert data["ground_coordination_status"] in ("COORDINATED", "PENDING", "NEEDS_REPLAN")


def assert_crew_assignment(data: dict):
    _assert_common_fields(data, "CrewAssignment")
    assert data["role_in_mission"] in ("PILOT", "NURSE", "PARAMEDIC")
    assert data["status"] in ("ASSIGNED", "RELEASED", "COMPLETED")


def assert_weather_assessment(data: dict):
    """Immutable observation: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "WeatherAssessment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "WeatherAssessment.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "WeatherAssessment must not expose updated_at"
    assert "version" not in data, "WeatherAssessment must not expose version"
    assert data["decision"] in ("GO", "MARGINAL", "NO_GO")


def assert_ground_leg(data: dict):
    _assert_common_fields(data, "GroundTransportLeg")
    assert data["leg_type"] in ("ORIGIN", "DESTINATION")
    assert data["status"] in ("SCHEDULED", "ENROUTE", "AT_BEDSIDE", "COMPLETED", "CANCELLED")


def assert_bed_reservation(data: dict):
    _assert_common_fields(data, "BedReservation")
    assert data["bed_type"] in ("ICU", "CCU", "MED_SURGE", "NICU")
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED", "CONSUMED")


def assert_insurance_authorization(data: dict):
    _assert_common_fields(data, "InsuranceAuthorization")
    assert data["status"] in ("REQUESTED", "APPROVED", "PARTIAL", "DENIED", "APPEALED")


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["claim_status"] in (
        "DRAFT", "FINALIZED", "SUBMITTED", "PAID", "PARTIALLY_PAID",
        "DENIED", "APPEALED", "RESUBMITTED",
    )
    assert data["member_adjustment_status"] in (
        "UNEVALUATED", "MEMBER_PROTECTED", "NON_MEMBER", "WRITEOFF_POSTED", "BALANCE_BILLED",
    )
    for field in (
        "base_line_cents", "mileage_line_cents", "fuel_line_cents", "acuity_line_cents",
        "logistics_line_cents", "ground_line_cents", "provisional_total_cents",
        "insurer_paid_cents", "contractual_adjustment_cents", "member_writeoff_cents",
        "appeal_count",
    ):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents, got {data[field]!r}"


def assert_repatriation_case(data: dict):
    _assert_common_fields(data, "RepatriationCase")
    assert data["status"] in ("COLLECTING", "READY_TO_FLY")
    assert isinstance(data["documents"], list)


def assert_patient_care_report(data: dict):
    _assert_common_fields(data, "PatientCareReport")
    assert data["status"] in ("DRAFT", "SUBMITTED", "QA_APPROVED", "QA_FLAGGED", "AMENDED")
    assert isinstance(data["last_review_points"], int)


def assert_invoice_ledger_invariant(data: dict):
    """PRD §3.8 conserved invariant: insurer paid + contractual adjustment +
    member write-off + patient responsibility always equals final_total_cents."""
    total = data["final_total_cents"]
    lhs = (
        data["insurer_paid_cents"]
        + data["contractual_adjustment_cents"]
        + data["member_writeoff_cents"]
        + data["patient_responsibility_cents"]
    )
    assert lhs == total, (
        f"Ledger invariant violated: {data['insurer_paid_cents']} + "
        f"{data['contractual_adjustment_cents']} + {data['member_writeoff_cents']} + "
        f"{data['patient_responsibility_cents']} == {lhs}, expected {total}"
    )

"""Entity assertions and domain invariant checkers (PRD sections 2.4 and 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label}.id must be a server-minted UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label}.version must be a positive integer, got {data.get('version')}"


def assert_mariner(data: dict):
    _assert_common_fields(data, "Mariner")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["mariner_reference_number"], str)
    assert data["hire_channel"] in ("DIRECT", "UNION_HALL")
    assert data["rank_track"] in ("DECK", "ENGINE", "STEWARD")
    assert isinstance(data["rank_grade"], int) and 1 <= data["rank_grade"] <= 9
    assert data["status"] in ("APPLICANT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["readiness_posture"] in ("CLEAR", "RESTRICTED", "BLOCKED")
    assert isinstance(data["readiness_reasons"], list)
    assert isinstance(data["no_show_strike_count"], int)
    assert data["training_privileges"] in ("ENABLED", "SUSPENDED")


def assert_vessel(data: dict):
    _assert_common_fields(data, "Vessel")
    assert isinstance(data["vessel_name"], str) and data["vessel_name"]
    assert isinstance(data["imo_number"], str)
    assert data["vessel_class"] in ("TANKER", "CONTAINER", "BULK", "PASSENGER", "OSV")
    assert data["status"] in (
        "REGISTERED", "ACTIVE", "UNDERWAY", "LAID_UP", "DECOMMISSIONED")
    assert data["compliance_posture"] in (
        "COMPLIANT", "DEFICIENT", "CRITICAL_SHORTAGE")


def assert_manning_slot(data: dict):
    _assert_common_fields(data, "ManningSlot")
    assert isinstance(data["position_code"], str) and data["position_code"]
    assert data["rank_track"] in ("DECK", "ENGINE", "STEWARD")
    assert isinstance(data["min_rank_grade"], int) and 1 <= data["min_rank_grade"] <= 9
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["current_coverage"] in ("COVERED", "UNCOVERED")


def assert_rotation_plan(data: dict):
    _assert_common_fields(data, "CrewRotationPlan")
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "ARCHIVED")


def assert_credential(data: dict):
    _assert_common_fields(data, "Credential")
    assert data["credential_type"] in (
        "MMC_BASE", "OFFICER_ENDORSEMENT", "STCW", "TANKER", "SPECIAL")
    assert isinstance(data["endorsement_code"], str) and data["endorsement_code"]
    assert data["status"] in (
        "VALID", "RENEWAL_PENDING", "SUSPENDED_PREREQ", "EXPIRED", "REVOKED",
        "LAPSED")
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_sea_service_record(data: dict):
    _assert_common_fields(data, "SeaServiceRecord")
    assert data["service_region"] in (
        "OCEAN", "NEAR_COASTAL", "INLAND", "GREAT_LAKES")
    assert data["watch_schedule"] in ("EIGHT_HOUR", "TWELVE_HOUR")
    assert data["record_status"] in (
        "DRAFT", "SUBMITTED", "VERIFIED", "DISPUTED", "REJECTED")
    assert isinstance(data["provisional_days"], (int, float))
    assert data.get("verified_days") is None or isinstance(
        data["verified_days"], (int, float))


def assert_medical_certificate(data: dict):
    _assert_common_fields(data, "MedicalCertificate")
    assert data["cert_type"] in ("USCG_MEDICAL", "FLAG_STATE_MEDICAL", "FIT_FOR_DUTY")
    assert data["status"] in ("VALID", "SUSPENDED", "EXPIRED")


def assert_drug_test_record(data: dict):
    _assert_common_fields(data, "DrugTestRecord")
    assert data["test_type"] in (
        "PRE_EMPLOYMENT", "PERIODIC", "RANDOM", "REASONABLE_CAUSE",
        "RETURN_TO_DUTY")
    assert data["status"] in ("PENDING", "COMPLETED")
    assert data.get("result") is None or data["result"] in (
        "NEGATIVE", "POSITIVE", "REFUSAL")


def assert_course(data: dict):
    _assert_common_fields(data, "TrainingCourse")
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert data["status"] in ("SCHEDULED", "CANCELLED")
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["seats_reserved"], int)
    assert isinstance(data["seats_open"], int)
    assert_course_seat_invariant(data)


def assert_course_seat_invariant(data: dict):
    """PRD section 3.9: seats_open == seat_capacity - seats_reserved always."""
    assert data["seats_reserved"] + data["seats_open"] == data["seat_capacity"], (
        f"seat ledger broken: {data['seats_reserved']} reserved + "
        f"{data['seats_open']} open != capacity {data['seat_capacity']}")
    assert 0 <= data["seats_reserved"] <= data["seat_capacity"]


def assert_enrollment(data: dict):
    _assert_common_fields(data, "TrainingEnrollment")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "REJECTED", "ENROLLED", "COMPLETED", "NO_SHOW",
        "CANCELLED", "REIMBURSED")


def assert_training_budget(data: dict):
    _assert_common_fields(data, "TrainingBudget")
    assert isinstance(data["annual_cap_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["used_cents"], int)
    assert_budget_invariant(data)


def assert_budget_invariant(data: dict):
    """PRD section 3.9: available == cap - reserved - used always."""
    assert data["available_cents"] == (
        data["annual_cap_cents"] - data["reserved_cents"] - data["used_cents"]), (
        f"budget invariant broken: {data['available_cents']} != "
        f"{data['annual_cap_cents']} - {data['reserved_cents']} - "
        f"{data['used_cents']}")


def assert_union_hall(data: dict):
    _assert_common_fields(data, "UnionHall")
    assert isinstance(data["local_number"], str) and data["local_number"]


def assert_union_registration(data: dict):
    _assert_common_fields(data, "UnionRegistration")
    assert data["status"] in ("REGISTERED", "SUSPENDED")


def assert_assignment(data: dict):
    _assert_common_fields(data, "Assignment")
    assert data["assignment_status"] in (
        "PROPOSED", "CONFIRMED", "ONBOARD", "SUSPENDED", "RELIEVED", "CLOSED",
        "CANCELLED")
    assert data["travel_status"] in ("PENDING", "READY", "WAIVED")
    assert data["repatriation_status"] in ("NOT_DUE", "DUE", "ARRANGED", "COMPLETED")
    assert data["assignment_channel"] in ("DIRECT_HIRE", "UNION_DISPATCH")


def assert_travel_booking(data: dict):
    _assert_common_fields(data, "TravelBooking")
    assert data["direction"] in ("JOIN", "REPATRIATION")
    assert data["status"] in (
        "QUOTED", "BOOKED", "TICKETED", "COMPLETED", "CANCELLED")
    assert isinstance(data["legs"], list)

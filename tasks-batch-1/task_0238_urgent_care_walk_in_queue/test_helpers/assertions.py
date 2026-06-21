"""Entity assertions and domain invariant checkers.

Every entity in this domain carries id, created_at, updated_at, and version
(PRD §2.4). Money is whole cents as integers (PRD §2.8).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["exam_room_capacity"], int) and data["exam_room_capacity"] >= 1
    assert data["posture"] in ("OPEN", "SURGE", "DIVERSION")
    assert isinstance(data["active_queue_depth"], int) and data["active_queue_depth"] >= 0
    assert isinstance(data["rooms_occupied"], int) and data["rooms_occupied"] >= 0
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0


def assert_exam_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_label"], str) and len(data["room_label"]) > 0
    assert data["room_type"] in ("STANDARD", "ISOLATION", "PROCEDURE")
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "CLEANING", "OUT_OF_SERVICE")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential"] in ("MD", "DO", "NP", "PA")
    assert isinstance(data["on_shift"], bool)
    assert isinstance(data["active_visit_count"], int) and data["active_visit_count"] >= 0
    assert isinstance(data["max_concurrent_visits"], int) and data["max_concurrent_visits"] >= 1


def assert_queue_entry(data: dict):
    _assert_common(data)
    assert data["arrival_channel"] in ("ONLINE", "WALK_IN")
    assert isinstance(data["chief_complaint"], str)
    assert data["status"] in (
        "RESERVED", "WAITING", "TRIAGED", "IN_REGISTRATION", "READY_FOR_PROVIDER",
        "ROOMED", "LEFT_WITHOUT_SEEN", "EXPIRED", "CANCELLED",
    )
    if data.get("esi_level") is not None:
        assert 1 <= data["esi_level"] <= 5


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["consent_signed"], bool)


def assert_coverage(data: dict):
    _assert_common(data)
    assert data["coverage_type"] in ("INSURANCE", "SELF_PAY")
    assert data["eligibility_status"] in ("UNVERIFIED", "ELIGIBLE", "INELIGIBLE")
    assert isinstance(data["copay_cents"], int) and data["copay_cents"] >= 0


def assert_visit(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in (
        "IN_EXAM", "CHARTING", "PENDING_DISCHARGE", "DISCHARGED", "TRANSFERRED",
    )
    assert data["billing_status"] in ("OPEN", "CHARGES_POSTED", "INVOICED", "SETTLED")
    assert isinstance(data["charges_subtotal_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert 1 <= data["acuity_at_rooming"] <= 5
    if data.get("disposition") is not None:
        assert data["disposition"] in ("HOME", "ER_TRANSFER", "LWBS")


def assert_charge(data: dict):
    _assert_common(data)
    assert isinstance(data["cpt_code"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source_type"] in ("VISIT", "OCC_HEALTH")
    assert isinstance(data["voided"], bool)


def assert_occ_health_order(data: dict):
    _assert_common(data)
    assert data["order_type"] in ("DRUG_SCREEN", "PHYSICAL", "RESPIRATOR_FIT")
    assert isinstance(data["employer_name"], str) and len(data["employer_name"]) > 0
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 5
    assert data["result"] in ("PENDING", "NEGATIVE", "POSITIVE", "PASS", "FAIL")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["destination_facility"], str) and len(data["destination_facility"]) > 0
    assert data["transfer_reason"] in ("ACUITY_ESCALATION", "CAPABILITY_GAP", "PATIENT_REQUEST")
    assert data["mode"] in ("AMBULANCE", "PRIVATE_VEHICLE")
    assert data["status"] in ("INITIATED", "ACCEPTED", "CANCELLED")


def assert_discharge_instruction(data: dict):
    _assert_common(data)
    assert isinstance(data["instructions_text"], str) and len(data["instructions_text"]) > 0
    assert data["follow_up_status"] in ("NONE", "PENDING", "DUE", "OVERDUE")

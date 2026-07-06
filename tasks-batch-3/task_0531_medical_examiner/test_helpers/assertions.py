"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["decedent_name"], str) and len(data["decedent_name"]) > 0
    assert data["status"] in [
        "REPORTED", "ACCEPTED", "INVESTIGATING", "CERTIFIED", "CLOSED", "DECLINED",
    ]
    assert data["case_type"] in ["NATURAL", "ACCIDENT", "HOMICIDE", "PENDING"]
    assert isinstance(data.get("autopsy_required"), bool)


def assert_investigator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_no"], str)
    assert isinstance(data["active"], bool)


def assert_pathologist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_no"], str)
    assert isinstance(data["is_medical_examiner"], bool)


def assert_cooler_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert isinstance(data["out_of_service"], bool)


def assert_body(data: dict):
    _assert_common(data)
    assert isinstance(data["tag_no"], str)
    assert data["storage_status"] in ["INTAKE", "STORED", "RELEASED"]
    assert isinstance(data["release_blocked"], bool)


def assert_autopsy_exam(data: dict):
    _assert_common(data)
    assert data["exam_status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 30
    assert isinstance(data["estimated_fee_cents"], int)


def assert_specimen(data: dict):
    _assert_common(data)
    assert data["specimen_type"] in ["BLOOD", "URINE", "VITREOUS", "TISSUE"]
    assert data["chain_status"] in ["COLLECTED", "SENT_TO_LAB", "CONSUMED", "DISCARDED"]


def assert_tox_screen(data: dict):
    _assert_common(data)
    assert data["panel"] in ["BASIC", "EXPANDED", "CONFIRMATORY"]
    assert data["result_status"] in ["ORDERED", "RESULTED", "AMENDED"]
    assert data["interpretation"] in ["PENDING", "POSITIVE", "NEGATIVE"]


def assert_death_certificate(data: dict):
    _assert_common(data)
    assert data["cert_status"] in ["DRAFT", "SIGNED", "AMENDED", "VOID"]
    assert data["manner_of_death"] in ["NATURAL", "ACCIDENT", "HOMICIDE", "UNDETERMINED"]
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_next_of_kin(data: dict):
    _assert_common(data)
    assert data["relationship"] in ["SPOUSE", "CHILD", "PARENT", "SIBLING", "OTHER"]
    assert isinstance(data["verified"], bool)


def assert_property_item(data: dict):
    _assert_common(data)
    assert data["item_status"] in ["HELD", "RELEASED", "ESCHEATED"]
    assert isinstance(data["valuation_cents"], int) and data["valuation_cents"] >= 0


def assert_property_release(data: dict):
    _assert_common(data)
    assert data["release_status"] in ["REQUESTED", "APPROVED", "DENIED"]
    assert isinstance(data["released_item_count"], int) and data["released_item_count"] >= 0


def assert_indigent_disposition(data: dict):
    _assert_common(data)
    assert data["disposition_status"] in ["DECLARED", "APPROVED", "BURIED"]
    assert isinstance(data["county_payable_cents"], int)

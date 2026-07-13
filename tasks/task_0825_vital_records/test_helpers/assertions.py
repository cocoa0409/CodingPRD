"""Entity assertions and domain invariant checkers (Vital Records PRD)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["facility_type"] in ("HOSPITAL", "FUNERAL_HOME", "BIRTHING_CENTER")
    assert isinstance(data["jurisdiction_code"], str)
    assert isinstance(data["registered_count"], int)
    assert data["registered_count"] >= 0


def assert_certifier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["certifier_type"] in ("PHYSICIAN", "MEDICAL_EXAMINER", "CORONER")
    assert isinstance(data["locked_certification_count"], int)
    assert data["locked_certification_count"] >= 0


def assert_vital_event(data: dict):
    assert_common_fields(data)
    assert data["event_type"] in ("BIRTH", "DEATH", "FETAL_DEATH")
    assert data["status"] in (
        "DRAFT", "FILED", "RETURNED", "REGISTERED", "AMENDED", "VOIDED",
    )
    assert data["sex"] in ("MALE", "FEMALE", "UNDETERMINED")
    assert isinstance(data["days_late"], int)
    assert isinstance(data["delayed_fee_cents"], int)
    assert isinstance(data["certification_required"], bool)
    assert isinstance(data["copies_issued_count"], int)
    assert isinstance(data["fees_collected_cents"], int)


def assert_medical_certification(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "CERTIFIED", "LOCKED", "AMENDED")
    assert data["manner_of_death"] in (
        "NATURAL", "ACCIDENT", "SUICIDE", "HOMICIDE",
        "PENDING_INVESTIGATION", "UNDETERMINED",
    )


def assert_copy_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "ID_VERIFIED", "ISSUED", "DENIED")
    assert isinstance(data["copy_count"], int)
    assert isinstance(data["fee_total_cents"], int)


def assert_event_ledger_nonnegative(data: dict):
    """Conserved counters on a vital event must never go negative (PRD §2.5)."""
    assert data["copies_issued_count"] >= 0, "copies_issued_count must be >= 0"
    assert data["fees_collected_cents"] >= 0, "fees_collected_cents must be >= 0"
    assert data["amendment_count"] >= 0, "amendment_count must be >= 0"

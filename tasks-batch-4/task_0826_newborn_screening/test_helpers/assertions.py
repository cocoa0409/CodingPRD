"""Entity assertions and domain invariant checkers (Newborn Screening PRD)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version begins at 1 and increments on mutation"


def assert_facility(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["facility_type"] in ("HOSPITAL", "BIRTHING_CENTER", "LAB")
    assert isinstance(data["state_region"], str)
    assert isinstance(data["total_booked_minutes"], int)
    assert data["total_booked_minutes"] >= 0


def assert_infant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["facility_id"], str)
    assert is_iso8601_timestamp(data["birth_datetime"])
    assert isinstance(data["gestational_age_weeks"], int)
    assert isinstance(data["birth_weight_grams"], int)
    assert data["sex"] in ("M", "F", "U")
    assert isinstance(data["multiple_birth"], bool)
    assert data["consent_status"] in ("PENDING", "CONSENTED", "REFUSED")
    assert isinstance(data["open_recollection_count"], int)
    assert isinstance(data["open_case_count"], int)
    assert data["followup_status"] in ("CLEAR", "ACTIVE")


def assert_specimen(data: dict):
    assert_common_fields(data)
    assert isinstance(data["infant_id"], str)
    assert data["specimen_type"] in ("INITIAL", "REPEAT")
    assert is_iso8601_timestamp(data["collection_datetime"])
    assert data["status"] in (
        "COLLECTED", "RECEIVED", "SATISFACTORY", "UNSATISFACTORY",
        "IN_TESTING", "TESTED", "VOIDED",
    )
    assert isinstance(data["collection_age_hours"], (int, float))


def assert_screen(data: dict):
    assert_common_fields(data)
    assert isinstance(data["specimen_id"], str)
    assert data["metabolic_status"] in (
        "PENDING", "REPORTED_NORMAL", "BORDERLINE", "PRESUMPTIVE_POSITIVE", "CANCELLED",
    )
    assert data["hearing_status"] in ("NOT_DONE", "PASS", "REFER")
    assert data["cchd_status"] in ("NOT_DONE", "PASS", "RETEST", "FAIL")
    assert data["overall_disposition"] in ("PENDING", "CLEARED", "FLAGGED", "CANCELLED")
    assert isinstance(data["critical_analyte_count"], int)


def assert_recollection_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["specimen_id"], str)
    assert data["reason"] in ("UNSAT_QUANTITY", "UNSAT_EARLY", "UNSAT_TRANSIT")
    assert data["status"] in ("ORDERED", "COLLECTED", "CANCELLED")
    assert is_iso8601_timestamp(data["deadline_datetime"])


def assert_follow_up_case(data: dict):
    assert_common_fields(data)
    assert isinstance(data["infant_id"], str)
    assert isinstance(data["screen_id"], str)
    assert data["case_type"] in ("SHORT_TERM", "LONG_TERM")
    assert isinstance(data["critical_flag_count"], int)
    assert isinstance(data["repeat_count"], int)
    assert data["priority_variant"] in ("INITIAL", "REVISED")
    assert isinstance(data["priority_score"], int)
    assert data["status"] in (
        "OPEN", "REPEAT_REQUESTED", "REPEAT_RECEIVED", "CONFIRMED_POSITIVE",
        "LONG_TERM_MONITORING", "RESOLVED_NORMAL", "CLOSED",
    )


def assert_specialty_clinic(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["specialty"] in ("METABOLIC_GENETICS", "AUDIOLOGY", "CARDIOLOGY")
    assert isinstance(data["concurrent_capacity"], int)
    assert data["concurrent_capacity"] >= 1


def assert_referral(data: dict):
    assert_common_fields(data)
    assert isinstance(data["follow_up_case_id"], str)
    assert isinstance(data["specialty_clinic_id"], str)
    assert data["referral_reason"] in ("METABOLIC_GENETICS", "AUDIOLOGY", "CARDIOLOGY")
    assert data["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED", "NO_SHOW", "DECLINED")


def assert_confirmatory_appointment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["referral_id"], str)
    assert isinstance(data["specialty_clinic_id"], str)
    assert is_iso8601_timestamp(data["start_datetime"])
    assert is_iso8601_timestamp(data["end_datetime"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW")


def assert_assay_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["instrument_code"], str)
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in ("SCHEDULED", "CANCELLED")

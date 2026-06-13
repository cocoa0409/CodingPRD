"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural contract for that entity's response.
Field names are exactly as named in the PRD. The Invoice carries only id +
created_at (no updated_at, no version) per PRD 2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for entities with common_fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_household(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_name"], str) and len(data["account_name"]) > 0
    assert isinstance(data["account_credit_cents"], int)
    assert data["account_credit_cents"] >= 0, "account_credit_cents is never negative"
    assert isinstance(data["lifetime_invoiced_cents"], int)
    assert data["lifetime_invoiced_cents"] >= 0
    assert data["status"] == "ACTIVE"


def assert_owner(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["is_primary"], bool)


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["species"] in ["DOG", "CAT", "RABBIT", "FERRET"]
    assert isinstance(data["weight_kg"], (int, float)) and data["weight_kg"] > 0
    assert data["status"] in ["ACTIVE", "INACTIVE", "DECEASED"]


def assert_wellness_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["tier"] in ["BASIC", "PLUS", "PREMIER"]
    assert isinstance(data["service_discount_pct"], (int, float))
    assert isinstance(data["bundled_vaccines_remaining"], int)
    assert data["bundled_vaccines_remaining"] >= 0
    assert isinstance(data["realized_savings_cents"], int)
    assert data["realized_savings_cents"] >= 0
    assert data["status"] == "ACTIVE"


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert data["status"] in ["SCHEDULED", "CHECKED_IN", "IN_EXAM",
                              "COMPLETED", "CANCELLED", "NO_SHOW"]


def assert_vaccination(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["vaccine_code"] in ["RABIES", "DHPP", "BORDETELLA", "FVRCP"]
    assert is_iso8601_timestamp(data["administered_at"])
    assert isinstance(data["bundled"], bool)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert is_iso8601_timestamp(data["next_due_at"])
    assert is_iso8601_timestamp(data["reminder_at"])


def assert_prescription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["drug_name"], str) and len(data["drug_name"]) > 0
    assert isinstance(data["is_controlled"], bool)
    assert isinstance(data["refills_authorized"], int) and data["refills_authorized"] >= 0
    assert isinstance(data["refills_used"], int) and data["refills_used"] >= 0
    assert data["refills_used"] <= data["refills_authorized"]
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "VOIDED"]


def assert_estimate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["line_items"], list)
    assert isinstance(data["deposit_required_cents"], int) and data["deposit_required_cents"] >= 0
    assert isinstance(data["deposit_posted_cents"], int) and data["deposit_posted_cents"] >= 0
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["DRAFT", "PRESENTED", "APPROVED", "DECLINED", "EXPIRED"]


def assert_surgery(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["operatory_id"])
    assert is_valid_uuid(data["estimate_id"])
    assert isinstance(data["procedure_name"], str) and len(data["procedure_name"]) > 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["surgery_total_cents"], int) and data["surgery_total_cents"] >= 0
    assert isinstance(data["deposit_consumed_cents"], int) and data["deposit_consumed_cents"] >= 0
    assert data["status"] in ["BOOKED", "IN_PROGRESS", "DONE", "CANCELLED"]


def assert_boarding_stay(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["kennel_id"])
    assert is_iso8601_timestamp(data["check_in_date"])
    assert is_iso8601_timestamp(data["check_out_date"])
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] >= 0
    assert isinstance(data["board_total_cents"], int) and data["board_total_cents"] >= 0
    assert data["status"] in ["RESERVED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"]


def assert_lab_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert data["order_type"] in ["BLOODWORK", "URINALYSIS", "DENTAL_XRAY",
                                  "CYTOLOGY", "BIOPSY"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ["ORDERED", "COLLECTED", "RESULTED", "CANCELLED"]


def assert_operatory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["cleanup_buffer_minutes"], int) and data["cleanup_buffer_minutes"] >= 0
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert data["status"] == "OPEN"


def assert_kennel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] == "OPEN"


def assert_invoice(data: dict):
    """Invoice is immutable: id + created_at only, no updated_at, no version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Invoice has no updated_at (immutable record)"
    assert "version" not in data, "Invoice has no version (immutable record)"
    assert is_valid_uuid(data["household_id"])
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["estimate_total_cents"], int)
    assert isinstance(data["actual_total_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["status"] == "FINALIZED"

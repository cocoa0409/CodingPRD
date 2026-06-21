"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract (§3).
Append-only records (VaccinationRecord, PackageRedemption, Certificate) carry only
id + created_at per PRD §2.4 — their assertions do NOT demand updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version, per PRD §2.4 (mutable resources)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def _assert_common_append_only(data: dict):
    """id + created_at only, per PRD §2.4 (append-only audit records)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_owner(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["phone"], str)


def assert_trainer(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["certified_levels"], list)
    assert isinstance(data["handles_private"], bool)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_dog(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["vaccination_posture"] in ("UNKNOWN", "COMPLIANT", "NONCOMPLIANT")
    assert data["highest_completed_level"] in ("NONE", "PUPPY", "BASIC", "INTERMEDIATE", "ADVANCED")
    assert data["intake_status"] in ("PENDING", "CLEARED", "FLAGGED")


def assert_behavioral_intake(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["dog_id"], str)
    assert isinstance(data["reactivity_score"], int)
    assert isinstance(data["bite_history"], bool)
    assert data["outcome"] in ("PENDING", "CLEARED", "FLAGGED")
    assert isinstance(data["requires_private_first"], bool)


def assert_class_series(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["title"], str)
    assert data["level"] in ("PUPPY", "BASIC", "INTERMEDIATE", "ADVANCED")
    assert data["modality"] in ("PRIVATE", "GROUP")
    assert isinstance(data["capacity"], int)
    assert isinstance(data["session_count"], int)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["credit_cost"], int)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "ARCHIVED")


def assert_class_session(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["series_id"], str)
    assert isinstance(data["trainer_id"], str)
    assert isinstance(data["sequence_index"], int)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["is_makeup_slot"], bool)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_enrollment(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["dog_id"], str)
    assert isinstance(data["series_id"], str)
    assert data["payment_method"] in ("CASH", "PACKAGE")
    assert data["status"] in (
        "PENDING_PREREQS", "ACTIVE", "WAITLISTED", "SUSPENDED", "GRADUATED", "WITHDRAWN")
    assert isinstance(data["sessions_attended"], int)
    assert isinstance(data["graduation_eligible"], bool)


def assert_package(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["owner_id"], str)
    assert data["tier"] in ("STARTER", "VALUE", "PRO")
    assert isinstance(data["credits_total"], int)
    assert isinstance(data["credits_consumed"], int)
    assert isinstance(data["credits_remaining"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "EXPIRED")
    assert_package_credit_invariant(data)


def assert_attendance_record(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["session_id"], str)
    assert data["state"] in (
        "EXPECTED", "PRESENT", "ABSENT", "MISSED_PROVIDER", "MAKEUP_PENDING", "MAKEUP_DONE")
    assert isinstance(data["makeup_eligible"], bool)


def assert_makeup_booking(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["attendance_id"], str)
    assert isinstance(data["makeup_session_id"], str)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "REJECTED", "CANCELLED")


def assert_vaccination_record(data: dict):
    _assert_common_append_only(data)
    assert isinstance(data["dog_id"], str)
    assert data["vaccine_type"] in ("RABIES", "DHPP", "BORDETELLA")
    assert isinstance(data["voided"], bool)


def assert_package_redemption(data: dict):
    _assert_common_append_only(data)
    assert isinstance(data["package_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert data["kind"] in ("DEBIT", "REVERSAL")
    assert isinstance(data["credits"], int)


def assert_certificate(data: dict):
    _assert_common_append_only(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["dog_id"], str)
    assert data["level"] in ("PUPPY", "BASIC", "INTERMEDIATE", "ADVANCED")
    assert isinstance(data["serial"], str) and len(data["serial"]) > 0


# ─── Domain invariants ──────────────────────────────────────────────────────────
def assert_package_credit_invariant(data: dict):
    """PRD §3.12: credits_remaining + credits_consumed == credits_total."""
    assert data["credits_remaining"] + data["credits_consumed"] == data["credits_total"], (
        f"credit invariant violated: remaining={data['credits_remaining']} + "
        f"consumed={data['credits_consumed']} != total={data['credits_total']}"
    )

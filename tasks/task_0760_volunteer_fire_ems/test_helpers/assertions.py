"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Every checker is keyed to the
PRD's exact field names.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def _assert_append_only_common(data: dict):
    """Append-only logs carry ONLY id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_member(data: dict):
    _assert_common(data)
    assert data["membership_status"] in {
        "PROBATIONARY", "ACTIVE", "LOA", "RETIRED", "EXPELLED"
    }, f"unexpected membership_status {data.get('membership_status')!r}"
    assert data["role_class"] in {
        "OFFICER", "PARAMEDIC", "EMT", "FIREFIGHTER", "PROBATIONARY"
    }
    assert isinstance(data["response_eligible"], bool)
    assert isinstance(data["points_ytd"], int)


def assert_certification(data: dict):
    _assert_common(data)
    assert data["status"] in {
        "PENDING", "CURRENT", "EXPIRING", "EXPIRED", "SUSPENDED", "REVOKED"
    }, f"unexpected cert status {data.get('status')!r}"
    assert data["cert_type"] in {
        "FIREFIGHTER_1", "EMT_BASIC", "PARAMEDIC", "HAZMAT", "DRIVER_OPERATOR", "CPR"
    }


def assert_apparatus(data: dict):
    _assert_common(data)
    assert data["posture"] in {"IN_SERVICE", "RESERVE", "OUT_OF_SERVICE"}


def assert_duty_shift(data: dict):
    _assert_common(data)
    assert data["status"] in {
        "DRAFT", "PUBLISHED", "SUSPENDED", "IN_PROGRESS", "COMPLETED", "CANCELLED"
    }
    assert data["staffing_status"] in {"UNDERSTAFFED", "STAFFED", "FULL"}


def assert_duty_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in {
        "ASSIGNED", "CHECKED_IN", "VERIFIED", "CANCELLED", "NO_SHOW"
    }


def assert_incident(data: dict):
    _assert_common(data)
    assert data["response_status"] in {"DISPATCHED", "ENROUTE", "ONSCENE", "CLEARED"}
    assert data["report_status"] in {"NONE", "DRAFT", "LOCKED", "AMENDED"}


def assert_turnout(data: dict):
    _assert_common(data)
    assert data["status"] in {"RESPONDED", "RELEASED", "VOIDED"}


def assert_campaign(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFT", "ACTIVE", "CLOSED"}
    assert data["raised_cents"] >= 0


def assert_donation(data: dict):
    _assert_common(data)
    assert data["status"] in {"POSTED", "REFUNDED"}


def assert_training_record(data: dict):
    _assert_append_only_common(data)
    assert "updated_at" not in data, "TrainingRecord is append-only: no updated_at"
    assert "version" not in data, "TrainingRecord is append-only: no version"


def assert_point_adjustment(data: dict):
    _assert_append_only_common(data)
    assert "updated_at" not in data, "PointAdjustment is append-only: no updated_at"
    assert "version" not in data, "PointAdjustment is append-only: no version"

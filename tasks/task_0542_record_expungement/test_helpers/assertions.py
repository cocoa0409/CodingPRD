"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_true(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _common_snapshot(data: dict):
    """For configuration/snapshot resources that carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "snapshot resources must not carry updated_at"
    assert "version" not in data, "snapshot resources must not carry version"


def assert_petitioner(data: dict):
    _common_true(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["annual_income_cents"], int)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["fee_paid_cents"], int) and data["fee_paid_cents"] >= 0
    assert isinstance(data["fee_refunded_cents"], int) and data["fee_refunded_cents"] >= 0


def assert_criminal_record(data: dict):
    _common_true(data)
    assert data["status"] in {"UNSCREENED", "ELIGIBLE", "INELIGIBLE", "SEALED"}
    assert data["offense_class"] in {
        "INFRACTION", "MISDEMEANOR", "FELONY_CLASS_C",
        "FELONY_CLASS_B", "FELONY_CLASS_A", "VIOLENT_FELONY",
    }
    assert data["disposition"] in {"CONVICTED", "DISMISSED", "ARREST_ONLY", "ACQUITTED"}


def assert_petition(data: dict):
    _common_true(data)
    assert data["status"] in {
        "DRAFT", "SCREENED", "FILED", "OBJECTION_REVIEW",
        "HEARING_SET", "GRANTED", "DENIED", "WITHDRAWN",
    }
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0


def assert_fee_waiver(data: dict):
    _common_true(data)
    assert data["status"] in {"REQUESTED", "GRANTED", "DENIED", "SUPERSEDED"}
    assert data["determination_basis"] in {"INCOME_UNDER_125", "OVER_THRESHOLD"}


def assert_agency_notification(data: dict):
    _common_true(data)
    assert data["status"] in {"PENDING", "SERVED", "OBJECTED", "CLEARED"}
    assert data["agency_type"] in {"DA", "ARRESTING_AGENCY", "STATE_REPOSITORY"}


def assert_hearing(data: dict):
    _common_true(data)
    assert data["status"] in {"SCHEDULED", "HELD", "VACATED", "SUPERSEDED"}


def assert_court_order(data: dict):
    _common_true(data)
    assert data["status"] in {"ENTERED", "DISTRIBUTED", "VACATED"}
    assert data["disposition"] in {"GRANTED", "DENIED"}


def assert_sealing_distribution(data: dict):
    _common_true(data)
    assert data["status"] in {"QUEUED", "SENT", "ACKNOWLEDGED", "FAILED", "CANCELLED"}
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_courtroom(data: dict):
    _common_snapshot(data)


def assert_judge(data: dict):
    _common_snapshot(data)


def assert_background_vendor(data: dict):
    _common_snapshot(data)
    assert isinstance(data["records_updated_count"], int) and data["records_updated_count"] >= 0


def assert_petition_item(data: dict):
    _common_snapshot(data)

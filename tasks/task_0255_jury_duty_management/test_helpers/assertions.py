"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates identity, timestamps, and field membership for a
resource returned by the API. Append-only rows (qualification response, check-in,
strike) are checked to carry id + created_at and to OMIT updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_SUMMONS_STATES = [
    "SUMMONED", "QUALIFIED_PENDING", "REPORTING", "SERVING", "RELEASED",
    "DEFERRED", "EXCUSED", "EXEMPT", "FAILED_TO_APPEAR",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only row must omit updated_at"
    assert "version" not in data, "append-only row must omit version"


def assert_service_term(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED"), f"bad status {data['status']!r}"
    assert isinstance(data["daily_pay_cents"], int) and data["daily_pay_cents"] >= 0
    assert isinstance(data["half_day_pay_cents"], int) and data["half_day_pay_cents"] >= 0
    assert data["full_day_hours"] > 0
    assert isinstance(data["mileage_rate_cents"], int) and data["mileage_rate_cents"] >= 0
    assert isinstance(data["pay_day_cap"], int) and data["pay_day_cap"] >= 1
    assert isinstance(data["fta_disqualify_threshold"], int) and data["fta_disqualify_threshold"] >= 1
    assert isinstance(data["pool_size"], int) and data["pool_size"] >= 0
    assert isinstance(data["summoned_count"], int) and data["summoned_count"] >= 0
    assert isinstance(data["draw_seq"], int) and data["draw_seq"] >= 0


def assert_juror(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["birth_year"], int)
    assert data["round_trip_miles"] >= 0
    assert data["qualification_status"] in ("PENDING", "QUALIFIED", "INELIGIBLE")
    assert isinstance(data["fta_strike_count"], int) and data["fta_strike_count"] >= 0
    assert isinstance(data["disqualified"], bool)
    assert isinstance(data["last_drawn_seq"], int) and data["last_drawn_seq"] >= 0


def assert_summons(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_term_id"])
    assert is_valid_uuid(data["juror_id"])
    assert isinstance(data["badge_number"], int) and data["badge_number"] >= 1
    assert data["status"] in _SUMMONS_STATES, f"bad summons status {data['status']!r}"
    assert isinstance(data["deferral_count"], int) and data["deferral_count"] >= 0
    assert isinstance(data["service_days"], int) and data["service_days"] >= 0


def assert_disposition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["summons_id"])
    assert data["kind"] in ("DEFER", "EXCUSE", "EXEMPT")
    assert data["decision"] in ("PENDING", "GRANTED", "DENIED")


def assert_trial(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_term_id"])
    assert isinstance(data["caption"], str) and len(data["caption"]) > 0
    assert isinstance(data["required_jurors"], int) and data["required_jurors"] >= 1
    assert data["status"] in ("SCHEDULED", "READY", "IN_TRIAL", "ADJOURNED")


def assert_panel(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_term_id"])
    assert is_valid_uuid(data["trial_id"])
    assert isinstance(data["target_size"], int) and data["target_size"] >= 1
    assert isinstance(data["seated_count"], int) and data["seated_count"] >= 0
    assert data["status"] in ("FORMING", "SEATED", "DISMISSED")
    assert data["seated_count"] <= data["target_size"], "seated_count must not exceed target_size"


def assert_panel_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["panel_id"])
    assert is_valid_uuid(data["summons_id"])
    assert isinstance(data["seat_index"], int) and data["seat_index"] >= 1
    assert data["status"] in ("SEATED", "EXCUSED_FROM_PANEL")


def assert_pay_voucher(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["summons_id"])
    assert data["variant"] in ("ESTIMATED", "FINAL")
    assert isinstance(data["paid_days"], int) and data["paid_days"] >= 0
    assert isinstance(data["attendance_cents"], int) and data["attendance_cents"] >= 0
    assert isinstance(data["mileage_cents"], int) and data["mileage_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["attendance_cents"] + data["mileage_cents"], (
        "total_cents must equal attendance_cents + mileage_cents"
    )


def assert_qualification_response(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["summons_id"])
    assert data["evaluated_status"] in ("QUALIFIED", "INELIGIBLE")


def assert_check_in(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["summons_id"])
    assert data["day_kind"] in ("FULL", "HALF")


def assert_strike(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["juror_id"])
    assert data["source"] == "FTA"

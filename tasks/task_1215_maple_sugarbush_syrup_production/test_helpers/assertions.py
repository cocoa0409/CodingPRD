"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in data, "append-only record must not carry updated_at"
        assert "version" not in data, "append-only record must not carry version"


def assert_season(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["opens_on"], str) and data["opens_on"]
    assert isinstance(data["closes_on"], str) and data["closes_on"]
    assert isinstance(data["planned_taps"], int) and data["planned_taps"] > 0
    assert data["status"] in ["PLANNED", "OPEN", "SUSPENDED", "CLOSED", "RECONCILED"]
    assert isinstance(data["taps_live"], int)
    assert isinstance(data["total_sap_gallons"], (int, float))
    assert isinstance(data["total_syrup_gallons"], (int, float))


def assert_sugarbush(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", "")), "season_id must be a valid UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["tap_capacity"], int) and data["tap_capacity"] > 0
    assert data["stand_type"] in ["OWNED", "LEASED"]
    assert data.get("active_lease_id") is None or isinstance(data["active_lease_id"], str)
    assert isinstance(data["organic_certified"], bool)
    assert isinstance(data["taps_set"], int)
    assert isinstance(data["taps_live"], int)
    assert data["status"] in ["PREP", "TAPPING", "LIVE", "SHUTDOWN"]


def assert_lease(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sugarbush_id", "")), "sugarbush_id must be a valid UUID"
    assert isinstance(data["landowner_name"], str) and data["landowner_name"]
    assert data["royalty_basis"] in ["PER_TAP", "SHARE_OF_SYRUP"]
    assert isinstance(data["term_start"], str) and data["term_start"]
    assert isinstance(data["term_end"], str) and data["term_end"]
    assert data["status"] in ["DRAFT", "PENDING_AUDIT", "ACTIVE", "TERMINATED", "EXPIRED"]


def assert_tap_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sugarbush_id", "")), "sugarbush_id must be a valid UUID"
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["tap_count"], int) and data["tap_count"] > 0
    assert data["vacuum_target_inhg"] > 0
    assert data.get("latest_vacuum_inhg") is None or isinstance(data["latest_vacuum_inhg"], (int, float))
    assert data["status"] in ["INSTALLING", "ACTIVE", "LEAK", "PULLED"]


def assert_vacuum_reading(data: dict):
    _assert_common(data, with_version=False)
    assert data["inhg"] >= 0
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"


def assert_weather_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", "")), "season_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("opens_at", "")), "opens_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("closes_at", "")), "closes_at must be ISO 8601"
    assert isinstance(data["forecast_min_f"], (int, float))
    assert isinstance(data["forecast_max_f"], (int, float))
    assert data["status"] in ["FORECAST", "OPEN", "CLOSED"]


def assert_crew_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", "")), "season_id must be a valid UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["crew_role"] in ["TAPPER", "BOILER", "GRADER"]
    assert isinstance(data["cert_organic_handler"], bool)
    assert data["status"] in ["HIRED", "ACTIVE", "RELEASED"]


def assert_sap_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sugarbush_id", "")), "sugarbush_id must be a valid UUID"
    assert is_valid_uuid(data.get("weather_window_id", "")), "weather_window_id must be a valid UUID"
    assert data["gallons_collected"] > 0
    assert 0.5 <= data["measured_brix"] <= 40.0
    assert is_iso8601_timestamp(data.get("collected_at", "")), "collected_at must be ISO 8601"
    assert data["gallons_remaining"] >= 0
    assert data["status"] in ["DRAFT", "CONFIRMED", "VOIDED"]


def assert_evaporator_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("season_id", "")), "season_id must be a valid UUID"
    assert isinstance(data["evaporator_capacity_gal"], int) and data["evaporator_capacity_gal"] > 0
    assert data["sap_gallons_in"] >= 0
    assert data["status"] in ["FILLING", "BOILING", "FINISHED", "CANCELLED"]


def assert_batch_intake(data: dict):
    _assert_common(data, with_version=False)
    assert data["gallons_drawn"] > 0
    assert isinstance(data["draw_sequence"], int)


def assert_syrup_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("batch_id", "")), "batch_id must be a valid UUID"
    assert is_valid_uuid(data.get("season_id", "")), "season_id must be a valid UUID"
    assert data["measured_gallons"] > 0
    assert data["finished_brix"] >= 66.0
    assert data.get("grade") is None or data["grade"] in [
        "GOLDEN", "AMBER", "DARK", "VERY_DARK", "PROCESSING",
    ]
    assert data["unpackaged_gallons"] >= 0
    assert isinstance(data["quality_hold_auto"], bool)
    assert data["status"] in ["UNGRADED", "GRADED", "HELD", "CONDEMNED", "EXHAUSTED"]


def assert_flavor_evaluation(data: dict):
    _assert_common(data, with_version=False)
    assert 0 <= data["flavor_score"] <= 100
    assert isinstance(data.get("defect_flags", []), list)
    assert is_iso8601_timestamp(data.get("evaluated_at", "")), "evaluated_at must be ISO 8601"


def assert_packaging_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("syrup_lot_id", "")), "syrup_lot_id must be a valid UUID"
    assert data["container_type"] in ["DRUM_55", "RETAIL_QUART", "RETAIL_PINT"]
    assert isinstance(data["units_planned"], int) and data["units_planned"] > 0
    assert data["status"] in ["PLANNED", "FILLED", "CANCELLED"]


def assert_cert_audit(data: dict):
    _assert_common(data)
    assert data["audit_type"] in ["ORGANIC", "WOODS"]
    assert isinstance(data["scheduled_for"], str) and data["scheduled_for"]
    assert data.get("result") is None or data["result"] in ["PASS", "FAIL"]
    assert data["status"] in ["SCHEDULED", "RECORDED"]


def assert_sap_conservation(sap_run: dict, drawn_outside_cancelled: float):
    """Sap conservation invariant (PRD §2.8): a run's gallons_remaining equals
    gallons_collected minus draws by batches in FILLING/BOILING/FINISHED."""
    remaining = sap_run["gallons_remaining"]
    collected = sap_run["gallons_collected"]
    assert abs((remaining + drawn_outside_cancelled) - collected) < 1e-9, (
        f"gallons_remaining {remaining} + live draws {drawn_outside_cancelled} "
        f"must equal gallons_collected {collected}"
    )


def assert_syrup_conservation(syrup_lot: dict, filled_gallons_total: float):
    """Syrup conservation invariant (PRD §2.8): unpackaged_gallons equals
    measured_gallons minus filled volume over FILLED packaging runs."""
    unpackaged = syrup_lot["unpackaged_gallons"]
    measured = syrup_lot["measured_gallons"]
    assert abs((unpackaged + filled_gallons_total) - measured) < 1e-9, (
        f"unpackaged_gallons {unpackaged} + filled {filled_gallons_total} "
        f"must equal measured_gallons {measured}"
    )

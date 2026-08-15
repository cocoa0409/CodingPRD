"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_same_instant(actual: str, expected: str):
    """Two ISO 8601 strings must denote the same instant.

    PRD pins instants (e.g., §2.5 "responds with the resulting current_utc",
    §3.8 "The response reports the window_start, the window_end") but never
    pins the serialized string form of these fields, so equality is judged on
    the parsed instant, not the characters.
    """
    def _parse(s):
        s = s.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    assert _parse(actual) == _parse(expected), (
        f"{actual!r} and {expected!r} are not the same instant"
    )


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["tax_exempt"], bool)


def assert_lane(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lane_code"], str) and data["lane_code"]
    assert isinstance(data["turn_days"], int) and data["turn_days"] >= 1
    assert isinstance(data["capacity_boards_per_day"], int) and data["capacity_boards_per_day"] >= 1
    assert data["premium_multiplier"] >= 1.0
    assert isinstance(data["active"], bool)


def assert_laminate_lot(data: dict):
    _assert_common_fields(data)
    assert data["material_code"] in ("FR4_TG135", "FR4_TG170", "ROGERS_4350")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["panels_total"], int) and data["panels_total"] >= 1
    assert isinstance(data["panels_reserved"], int)
    assert isinstance(data["panels_consumed"], int)
    assert data["status"] in ("RECEIVED", "QUALIFIED", "DEPLETED", "EXPIRED", "QUARANTINED")
    assert_lot_conservation(data)


def assert_lot_conservation(data: dict):
    """panels_available == panels_total - panels_reserved - panels_consumed (PRD §3.5)."""
    assert "panels_available" in data, "lot must expose panels_available"
    assert data["panels_available"] == (
        data["panels_total"] - data["panels_reserved"] - data["panels_consumed"]
    ), (
        f"conservation broken: total {data['panels_total']} != reserved "
        f"{data['panels_reserved']} + consumed {data['panels_consumed']} + available {data['panels_available']}"
    )


def assert_fab_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["service_lane"] in ("STANDARD", "QUICK_TURN")
    assert data["fab_status"] in (
        "QUOTED", "DFM_REVIEW", "AWAITING_LAMINATE", "RELEASED", "IN_PRODUCTION",
        "ON_HOLD", "AWAITING_ETEST", "COMPLETED", "SHIPPED", "CANCELLED",
    )
    assert data["quality_disposition"] in ("PENDING", "PASSED", "FAILED", "CONDITIONAL")
    assert isinstance(data["boards_scrapped"], int) and data["boards_scrapped"] >= 0
    assert isinstance(data["layer_count"], int) and data["layer_count"] in (2, 4, 6, 8)
    assert data["surface_finish"] in ("HASL", "OSP", "ENIG", "IMMERSION_SILVER", "HARD_GOLD")
    assert isinstance(data["quantity_boards"], int) and data["quantity_boards"] >= 1
    assert "laminate_lot_codes" in data and isinstance(data["laminate_lot_codes"], list)
    assert "provisional_total_cents" in data


def assert_stackup(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "LOCKED", "SUPERSEDED")
    assert data["total_thickness_mils"] > 0
    assert data["copper_weight_oz"] in (1, 2)
    assert isinstance(data["impedance_controlled"], bool)


def assert_spec_line(data: dict):
    _assert_common_fields(data)
    assert data["target_ohms"] > 0
    assert data["tolerance_plus_ohms"] >= 0
    assert data["tolerance_minus_ohms"] >= 0
    assert data["line_type"] in ("SINGLE_ENDED", "DIFFERENTIAL")
    assert isinstance(data["coupon_required"], bool)


def assert_panel_array(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "RELEASED", "SUPERSEDED", "CANCELLED")
    assert data["array_x"] >= 1 and data["array_y"] >= 1
    assert data["panel_width_mils"] > 0 and data["panel_height_mils"] > 0
    assert data["boards_per_panel"] == data["array_x"] * data["array_y"]


def assert_drill_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED", "CANCELLED")
    assert data["min_hole_mils"] > 0
    assert data["hole_count"] >= 1
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")
    assert data["panels_allocated"] >= 1


def assert_lane_slot_commitment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["committed_boards"], int) and data["committed_boards"] >= 0
    assert "ship_date" in data and "lane_id" in data


def assert_coupon(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("AWAITING_MEASURE", "PASSED", "FAILED", "CANCELLED")
    assert isinstance(data["retest_count"], int) and 0 <= data["retest_count"] <= 2


def assert_coupon_measurement(data: dict):
    _assert_append_only_fields(data)
    assert data["result"] in ("PASS", "FAIL")
    assert data["measured_ohms"] > 0
    assert is_iso8601_timestamp(data.get("measured_at", "")), "measured_at must be ISO 8601"


def assert_lab_booking(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")
    assert data["station"] == "MICROSECTION_A"
    assert data["ends_at"] > data["starts_at"]


def assert_etest_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED_PASS", "COMPLETED_FAIL", "CANCELLED")
    assert data["test_voltage"] > 0
    for counter in ("boards_tested", "boards_failed", "opens_found", "shorts_found"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_defect_record(data: dict):
    _assert_append_only_fields(data)
    assert data["defect_code"] in (
        "OPEN", "SHORT", "SPACING", "DRILL_BREAKOUT", "PLATING_VOID",
        "SOLDERMASK", "CONTAMINATION", "OVERETCH", "IMPEDANCE",
    )
    assert data["severity"] in ("COSMETIC", "MINOR", "MAJOR", "SCRAP")
    assert data["boards_affected"] >= 1
    assert data["source"] in ("AOI", "MANUAL", "ETEST")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID")
    assert data["actual_panels_run"] >= 1
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["retest_fees_cents"], int) and data["retest_fees_cents"] >= 0


def pareto_row_field(row: dict, *candidate_names: str):
    """Resolve a Pareto row field across PRD-faithful naming variants.

    PRD §3.8 pins the row contents (defect code, boards total, percentage share,
    running cumulative percentage, vital-few flag) but not the serialized key
    names, so lookup accepts the reasonable namings for each pinned value.
    """
    for name in candidate_names:
        if name in row:
            return row[name]
    raise AssertionError(
        f"Pareto row {row!r} carries none of the expected keys {candidate_names!r}"
    )

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_importer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ior_number"], str) and len(data["ior_number"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    # continuous_bond_id is nullable.
    assert data["continuous_bond_id"] is None or is_valid_uuid(
        data["continuous_bond_id"]
    )


def assert_bond(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["importer_id"])
    assert data["bond_type"] in ("CONTINUOUS", "SINGLE_ENTRY")
    assert isinstance(data["limit_cents"], int) and data["limit_cents"] >= 0
    assert isinstance(data["outstanding_liability_cents"], int)
    assert data["status"] in ("PENDING", "ACTIVE", "SATURATED", "TERMINATED")


def assert_isf(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["importer_id"])
    assert isinstance(data["bill_of_lading"], str) and len(data["bill_of_lading"]) > 0
    assert isinstance(data["data_element_count"], int)
    assert isinstance(data["late_filing"], bool)
    assert data["status"] in ("DRAFT", "FILED", "MATCHED", "CANCELLED")
    assert data["filed_at"] is None or is_iso8601_timestamp(data["filed_at"])


def assert_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["importer_id"])
    assert is_valid_uuid(data["bond_id"])
    assert data["entry_type"] in ("CONSUMPTION_01", "WAREHOUSE_21", "FTZ_06")
    assert isinstance(data["country_of_origin"], str)
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["total_duties_owed_cents"], int)
    assert data["final_total_cents"] is None or isinstance(
        data["final_total_cents"], int
    )
    assert data["status"] in (
        "DRAFT",
        "FILED",
        "HOLD_EXAM",
        "RELEASED",
        "LIQUIDATED",
        "CANCELLED",
    )


def assert_entry_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["entry_id"])
    assert isinstance(data["hts_code"], str)
    assert isinstance(data["customs_value_cents"], int)
    assert isinstance(data["assists_cents"], int)
    assert isinstance(data["quantity"], int)
    assert data["preference_claim"] in ("NONE", "USMCA")
    assert data["pga_flag"] in ("NONE", "FDA", "USDA")
    assert isinstance(data["dutiable_value_cents"], int)
    assert isinstance(data["line_duty_cents"], int)
    assert isinstance(data["preference_verified"], bool)


def assert_pga_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["entry_id"])
    assert data["agency"] in ("FDA", "USDA")
    assert data["decision"] in ("PENDING", "MAY_PROCEED", "HOLD", "REFUSED")


def assert_exam_slot(data: dict):
    _assert_common(data)
    assert data["station_code"] in ("CES_LAX", "CES_JFK")
    assert is_valid_uuid(data["entry_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("BOOKED", "RELEASED_SLOT", "CANCELLED_SLOT")


def assert_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["importer_id"])
    assert isinstance(data["period_month"], str)
    assert isinstance(data["statement_total_cents"], int)
    assert isinstance(data["entry_count"], int)
    assert data["status"] in ("OPEN", "SETTLED")


def assert_psc(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["entry_id"])
    assert data["filing_kind"] in ("PSC", "PROTEST")
    assert isinstance(data["corrected_value_delta_cents"], int)
    assert isinstance(data["adjustment_cents"], int)
    assert data["status"] in ("SUBMITTED", "GRANTED", "DENIED")

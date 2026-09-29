"""Entity-level assertion helpers for the draft beer line service API.

Each ``assert_<entity>`` helper checks the identity and timestamp discipline the
PRD declares for that entity: every mutable row carries an `id`, a `created_at`,
an `updated_at` and a `version`, while the two immutable evidence rows carry only
an `id` and a `created_at`.  The remaining helpers express recurring
domain invariants so tests can state intent in one line.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common metadata
# ---------------------------------------------------------------------------
def assert_mutable_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """A mutable row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), f"version must be an integer, got {row['version']!r}"
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_immutable_common_fields(row: Dict[str, Any]):
    """An immutable evidence row carries only id and created_at."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp, got {row['created_at']!r}"
    )
    assert "updated_at" not in row, "an immutable row must not carry updated_at"
    assert "version" not in row, "an immutable row must not carry version"


# ---------------------------------------------------------------------------
# Per-entity shape checks
# ---------------------------------------------------------------------------
def assert_service_account(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "venue_name",
        "status",
        "access_window_start_minute",
        "access_window_end_minute",
        "glycol_system_present",
        "billing_mode",
        "lines_out_of_service_count",
        "open_complaint_count",
        "suspended_reason",
    ):
        assert field in row, f"ServiceAccount must expose {field}"
    _assert_fields(row, expected, "ServiceAccount")


def assert_service_contract(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "account_id",
        "status",
        "cleaning_frequency_days",
        "contracted_line_count",
        "per_line_rate_cents",
        "visit_base_fee_cents",
        "effective_from",
        "funding_status",
        "frequency_multiplier",
    ):
        assert field in row, f"ServiceContract must expose {field}"
    _assert_fields(row, expected, "ServiceContract")


def assert_beer_line(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "account_id",
        "line_number",
        "run_length_feet",
        "vertical_rise_feet",
        "inner_diameter_inches",
        "beer_style_group",
        "average_daily_throughput_liters",
        "status",
        "compliance_flag",
        "days_overdue",
    ):
        assert field in row, f"BeerLine must expose {field}"
    _assert_fields(row, expected, "BeerLine")


def assert_technician(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in ("full_name", "certification_level", "caustic_certified", "status"):
        assert field in row, f"Technician must expose {field}"
    _assert_fields(row, expected, "Technician")


def assert_chemical_lot(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "chemical_type",
        "lot_code",
        "concentration_pct_stock",
        "liters_initial",
        "liters_remaining",
        "expires_on",
        "status",
    ):
        assert field in row, f"ChemicalLot must expose {field}"
    _assert_fields(row, expected, "ChemicalLot")


def assert_part_catalog_item(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "sku",
        "component_type",
        "unit_price_cents",
        "stock_on_hand",
        "brewer_funded_eligible",
    ):
        assert field in row, f"PartCatalogItem must expose {field}"
    _assert_fields(row, expected, "PartCatalogItem")


def assert_brewer_program(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "brewer_name",
        "funded_scope",
        "co_pay_bps",
        "funding_cap_cents",
        "consumed_cents",
        "remaining_cents",
        "status",
    ):
        assert field in row, f"BrewerProgram must expose {field}"
    _assert_fields(row, expected, "BrewerProgram")


def assert_service_visit(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "account_id",
        "technician_id",
        "visit_kind",
        "scheduled_date",
        "scheduled_start_minute",
        "scheduled_end_minute",
        "work_status",
        "verification_status",
        "settlement_state",
    ):
        assert field in row, f"ServiceVisit must expose {field}"
    _assert_fields(row, expected, "ServiceVisit")


def assert_cleaning_cycle(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "visit_id",
        "line_id",
        "chemical_lot_id",
        "chemical_type",
        "contact_minutes",
        "recirculation_temp_f",
        "concentrate_liters_used",
        "compliance_result",
        "record_status",
    ):
        assert field in row, f"CleaningCycle must expose {field}"
    _assert_fields(row, expected, "CleaningCycle")


def assert_balance_record(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "line_id",
        "visit_id",
        "measured_temp_f",
        "proposed_applied_psi",
        "proposed_co2_pct",
        "balance_state",
        "status",
    ):
        assert field in row, f"BalanceRecord must expose {field}"
    _assert_fields(row, expected, "BalanceRecord")


def assert_component_inspection(row: Dict[str, Any], **expected):
    assert_immutable_common_fields(row)
    for field in ("visit_id", "line_id", "component_type", "condition_grade", "action_taken"):
        assert field in row, f"ComponentInspection must expose {field}"
    _assert_fields(row, expected, "ComponentInspection")


def assert_quality_complaint(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "account_id",
        "line_id",
        "symptom",
        "reported_at",
        "status",
        "diagnostic_round",
        "reopen_count",
        "days_at_risk",
    ):
        assert field in row, f"QualityComplaint must expose {field}"
    _assert_fields(row, expected, "QualityComplaint")


def assert_glycol_loop(row: Dict[str, Any], **expected):
    assert_mutable_common_fields(row)
    for field in (
        "account_id",
        "glycol_pct",
        "pump_psi",
        "bath_temp_f",
        "last_serviced_at",
        "health_score",
        "status",
    ):
        assert field in row, f"GlycolLoop must expose {field}"
    _assert_fields(row, expected, "GlycolLoop")


def assert_cooler_reading(row: Dict[str, Any], **expected):
    assert_immutable_common_fields(row)
    for field in ("glycol_loop_id", "reading_at", "cooler_temp_f", "glycol_supply_temp_f", "source"):
        assert field in row, f"CoolerReading must expose {field}"
    _assert_fields(row, expected, "CoolerReading")


def _assert_fields(row: Dict[str, Any], expected: Dict[str, Any], label: str):
    for field, value in expected.items():
        assert field in row, f"{label} must expose {field}"
        assert row[field] == value, (
            f"{label}.{field}: expected {value!r}, got {row[field]!r}"
        )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_money_fields_zeroed(visit: Dict[str, Any]):
    """The four money fields a reversal zeroes."""
    for field in (
        "settled_charge_cents",
        "cleaning_subtotal_cents",
        "brewer_funded_cents",
        "account_due_cents",
    ):
        assert visit[field] == 0, f"{field} must be 0 after a reversal, got {visit[field]}"


def assert_program_ledger(program: Dict[str, Any], consumed: int, remaining: int, status: str):
    """A brewer programme's consumed, remaining and status read together."""
    assert program["consumed_cents"] == consumed, (
        f"consumed_cents: expected {consumed}, got {program['consumed_cents']}"
    )
    assert program["remaining_cents"] == remaining, (
        f"remaining_cents: expected {remaining}, got {program['remaining_cents']}"
    )
    assert program["status"] == status, (
        f"programme status: expected {status}, got {program['status']}"
    )


def assert_line_projection(
    line: Dict[str, Any],
    last_chemical_type: Optional[str] = None,
    last_cleaned_at: Optional[str] = None,
    next_due_at: Optional[str] = None,
    days_overdue: Optional[int] = None,
    compliance_flag: Optional[str] = None,
    status: Optional[str] = None,
):
    """The cleaning-due projection a line republishes after every cycle."""
    checks = {
        "last_chemical_type": last_chemical_type,
        "last_cleaned_at": last_cleaned_at,
        "next_due_at": next_due_at,
        "days_overdue": days_overdue,
        "compliance_flag": compliance_flag,
        "status": status,
    }
    for field, expected in checks.items():
        if expected is None:
            continue
        if field in ("last_cleaned_at", "next_due_at"):
            assert_instant(line[field], expected, label=f"BeerLine.{field}")
            continue
        assert line[field] == expected, (
            f"BeerLine.{field}: expected {expected!r}, got {line[field]!r}"
        )


def _normalise_instant(value: Any) -> Any:
    """Drop the optional fractional-second digits from an ISO 8601 UTC instant."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return value
    head = value[:-1]
    if "." in head:
        head = head.split(".", 1)[0]
    return head + "Z"


def assert_instant(actual: Any, expected: str, label: str = "instant"):
    """Two instants name the same second, whatever fractional digits are shown."""
    assert _normalise_instant(actual) == _normalise_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_liters(actual: float, expected: float):
    """Litre figures are carried to three decimal places."""
    assert round(float(actual), 3) == round(float(expected), 3), (
        f"Expected {expected} litres, got {actual}"
    )


def assert_pct(actual: float, expected: float):
    """Percentage figures are carried to three decimal places."""
    assert round(float(actual), 3) == round(float(expected), 3), (
        f"Expected {expected} per cent, got {actual}"
    )


def assert_psi(actual: float, expected: float):
    """Pressure figures are carried to two decimal places."""
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"Expected {expected} psi, got {actual}"
    )


def assert_score(actual: float, expected: float):
    """Health scores are carried to two decimal places."""
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"Expected a health score of {expected}, got {actual}"
    )


def assert_sorted_by_created_at(rows: list):
    """Collection reads come back oldest first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"Rows must be sorted by created_at ascending, got {stamps}"

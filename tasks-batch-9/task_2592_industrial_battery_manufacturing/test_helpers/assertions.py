"""Domain assertions for the battery manufacturing API.

These helpers exist so a test can state the outcome it cares about in one line
and get a readable failure message naming the field that disagreed.
"""

import datetime
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
)


# --- Envelope --------------------------------------------------------------
def assert_envelope(response, expected_response_type: str) -> Dict[str, Any]:
    """Assert the standard envelope shape and return the parsed body."""
    body = response.json()
    assert "meta" in body, f"response has no meta block: {body}"
    assert "data" in body, f"response has no data block: {body}"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), f"bad api_request_id: {meta}"
    assert meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_: {meta['api_request_id']}"
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), f"api_request_timestamp is not ISO-8601 UTC: {meta.get('api_request_timestamp')}"
    assert (
        body.get("response_type") == expected_response_type
    ), f"expected response_type {expected_response_type}, got {body.get('response_type')}"
    return body


def assert_single_resource_envelope(response) -> Dict[str, Any]:
    """A single-resource response carries no pagination fields at all."""
    body = assert_envelope(response, "object")
    for field in ("total_count", "limit", "offset", "has_more"):
        assert (
            field not in body["meta"]
        ), f"single-resource meta must omit {field}: {body['meta']}"
    return body["data"]


def assert_identity_fields(data: Dict[str, Any], expect_version: bool = True) -> None:
    """Every resource carries a UUID id and an ISO-8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id is not a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at is not ISO-8601: {data.get('created_at')}"
    if expect_version:
        assert isinstance(data.get("version"), int), f"version missing: {data}"
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at is not ISO-8601: {data.get('updated_at')}"


def assert_log_row_fields(data: Dict[str, Any]) -> None:
    """Append-only log rows carry only an identifier and a creation timestamp."""
    assert is_valid_uuid(data.get("id", "")), f"id is not a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at is not ISO-8601: {data.get('created_at')}"
    for field in ("updated_at", "version"):
        assert field not in data, f"log rows must not carry {field}: {data}"


# --- Numeric shape ---------------------------------------------------------
def assert_decimal_places(value: Any, places: int, label: str = "value") -> None:
    """Assert a numeric response field is quantised to `places` decimals."""
    assert value is not None, f"{label} is null"
    text = f"{value}"
    if "." in text:
        actual = len(text.split(".")[1])
        assert (
            actual <= places
        ), f"{label} carries {actual} decimals, expected at most {places}: {value}"
    rounded = round(float(value), places)
    assert (
        abs(float(value) - rounded) < 1e-9
    ), f"{label} is not quantised to {places} decimals: {value}"


def assert_whole_cents(value: Any, label: str = "amount") -> None:
    assert isinstance(value, int), f"{label} must be an integer number of cents: {value}"


def assert_close(actual: Any, expected: float, label: str, places: int = 4) -> None:
    assert actual is not None, f"{label} is null, expected {expected}"
    assert (
        abs(float(actual) - float(expected)) < 10 ** (-places) / 2
    ), f"{label}: expected {expected}, got {actual}"


# --- Plant -----------------------------------------------------------------
def _as_instant(text: str) -> datetime.datetime:
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(raw)


def assert_same_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC values denote the same instant.

    Instants are rendered "with exactly three fractional-second digits", so a
    stored `...:00.000Z` and the `...:00Z` literal a client supplied are the
    same instant written two ways; the requirements pin the instant, not the
    spelling.
    """
    assert actual is not None, f"{label} is null, expected {expected}"
    assert _as_instant(actual) == _as_instant(expected), (
        f"expected {label} {expected}, got {actual}"
    )


def assert_posture(plant: Dict[str, Any], expected: str) -> None:
    assert (
        plant.get("compliance_posture") == expected
    ), f"expected posture {expected}, got {plant.get('compliance_posture')}"


def assert_emission_ledger(
    ledger: Dict[str, Any],
    reserved_g: Optional[float] = None,
    consumed_g: Optional[float] = None,
    ratio: Optional[float] = None,
) -> None:
    if reserved_g is not None:
        assert_close(ledger.get("emission_reserved_g"), reserved_g, "emission_reserved_g", 2)
    if consumed_g is not None:
        assert_close(ledger.get("emission_consumed_g"), consumed_g, "emission_consumed_g", 2)
    if ratio is not None:
        assert_close(
            ledger.get("emission_utilization_ratio"),
            ratio,
            "emission_utilization_ratio",
            4,
        )


def assert_lead_balance(
    balance: Dict[str, Any],
    inventory_kg: Optional[float] = None,
    in_field_kg: Optional[float] = None,
    recycled_kg: Optional[float] = None,
    variance_kg: float = 0.000,
) -> None:
    if inventory_kg is not None:
        assert_close(balance.get("lead_inventory_kg"), inventory_kg, "lead_inventory_kg", 3)
    if in_field_kg is not None:
        assert_close(balance.get("lead_in_field_kg"), in_field_kg, "lead_in_field_kg", 3)
    if recycled_kg is not None:
        assert_close(balance.get("lead_recycled_kg"), recycled_kg, "lead_recycled_kg", 3)
    assert_close(
        balance.get("lead_mass_variance_kg"), variance_kg, "lead_mass_variance_kg", 3
    )


# --- Lot -------------------------------------------------------------------
def assert_lot_state(
    lot: Dict[str, Any],
    process_state: Optional[str] = None,
    env_hold_status: Optional[str] = None,
    hold_reason: Optional[str] = "__unchecked__",
) -> None:
    if process_state is not None:
        assert (
            lot.get("process_state") == process_state
        ), f"expected process_state {process_state}, got {lot.get('process_state')}"
    if env_hold_status is not None:
        assert (
            lot.get("env_hold_status") == env_hold_status
        ), f"expected env_hold_status {env_hold_status}, got {lot.get('env_hold_status')}"
    if hold_reason != "__unchecked__":
        assert (
            lot.get("hold_reason") == hold_reason
        ), f"expected hold_reason {hold_reason}, got {lot.get('hold_reason')}"


def assert_sampling_plan(
    lot: Dict[str, Any],
    sample_size: Optional[int] = None,
    acceptance_number: Optional[int] = None,
    revision: Optional[int] = None,
) -> None:
    if sample_size is not None:
        assert (
            lot.get("sample_size") == sample_size
        ), f"expected sample_size {sample_size}, got {lot.get('sample_size')}"
    if acceptance_number is not None:
        assert (
            lot.get("acceptance_number") == acceptance_number
        ), f"expected acceptance_number {acceptance_number}, got {lot.get('acceptance_number')}"
    if revision is not None:
        assert (
            lot.get("sampling_plan_revision") == revision
        ), f"expected sampling_plan_revision {revision}, got {lot.get('sampling_plan_revision')}"


def assert_lot_counters(
    lot: Dict[str, Any],
    completed: Optional[int] = None,
    failed: Optional[int] = None,
    passed_cycle_life: Optional[int] = None,
    retest_count: Optional[int] = None,
    failed_formation: Optional[int] = None,
) -> None:
    pairs = [
        ("completed_test_count", completed),
        ("failed_test_count", failed),
        ("passed_cycle_life_count", passed_cycle_life),
        ("retest_count", retest_count),
        ("failed_formation_count", failed_formation),
    ]
    for field, expected in pairs:
        if expected is not None:
            assert (
                lot.get(field) == expected
            ), f"expected {field} {expected}, got {lot.get(field)}"


# --- Assemblies ------------------------------------------------------------
def assert_assembly_axes(
    assembly: Dict[str, Any],
    torque_status: Optional[str] = None,
    insulation_status: Optional[str] = None,
    certification_status: Optional[str] = None,
    rework_count: Optional[int] = None,
) -> None:
    pairs = [
        ("torque_status", torque_status),
        ("insulation_status", insulation_status),
        ("certification_status", certification_status),
        ("rework_count", rework_count),
    ]
    for field, expected in pairs:
        if expected is not None:
            assert (
                assembly.get(field) == expected
            ), f"expected {field} {expected}, got {assembly.get(field)}"


# --- Formation runs --------------------------------------------------------
def assert_run_energy(
    run: Dict[str, Any],
    estimated_energy_kwh: Optional[float] = None,
    peak_hours: Optional[float] = None,
    offpeak_hours: Optional[float] = None,
    provisional_charge_cents: Optional[int] = None,
    reserved_emission_g: Optional[float] = None,
) -> None:
    if estimated_energy_kwh is not None:
        assert_close(
            run.get("estimated_energy_kwh"), estimated_energy_kwh, "estimated_energy_kwh", 2
        )
    if peak_hours is not None:
        assert_close(run.get("scheduled_peak_hours"), peak_hours, "scheduled_peak_hours", 4)
    if offpeak_hours is not None:
        assert_close(
            run.get("scheduled_offpeak_hours"),
            offpeak_hours,
            "scheduled_offpeak_hours",
            4,
        )
    if provisional_charge_cents is not None:
        assert_whole_cents(run.get("provisional_charge_cents"), "provisional_charge_cents")
        assert (
            run["provisional_charge_cents"] == provisional_charge_cents
        ), f"expected provisional_charge_cents {provisional_charge_cents}, got {run['provisional_charge_cents']}"
    if reserved_emission_g is not None:
        assert_close(
            run.get("reserved_emission_g"), reserved_emission_g, "reserved_emission_g", 2
        )


def assert_run_state(run: Dict[str, Any], expected: str) -> None:
    assert (
        run.get("run_state") == expected
    ), f"expected run_state {expected}, got {run.get('run_state')}"


# --- Ordering and pagination ----------------------------------------------
def assert_ordered_by(
    rows: List[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    values = [row.get(field) for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"rows are not ordered by {field}: {values}"


def assert_id_sequence(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [row.get("id") for row in rows]
    assert actual == expected_ids, f"expected id order {expected_ids}, got {actual}"


def created_at_then_id(rows: List[Dict[str, Any]]) -> List[str]:
    """The ids of `rows` in the default collection order of the requirements.

    "All other collections use `created_at` ascending with `id` ascending as the
    tiebreak." Rows minted under one logical instant therefore share a
    `created_at`, and the identifier decides — not the order they were written.
    """
    ordered = sorted(rows, key=lambda row: (row["created_at"], row["id"]))
    return [row["id"] for row in ordered]


def assert_row_absent(rows: List[Dict[str, Any]], row_id: str) -> None:
    assert row_id not in [
        row.get("id") for row in rows
    ], f"row {row_id} should not be listed"


def assert_row_count(response, expected: int) -> List[Dict[str, Any]]:
    data = get_success_data(response)
    assert isinstance(data, list), f"expected a list payload, got {type(data)}"
    assert len(data) == expected, f"expected {expected} rows, got {len(data)}"
    return data


# --- Units and core --------------------------------------------------------
def assert_unit_axes(
    unit: Dict[str, Any],
    warranty_status: Optional[str] = None,
    core_status: Optional[str] = None,
) -> None:
    if warranty_status is not None:
        assert (
            unit.get("warranty_status") == warranty_status
        ), f"expected warranty_status {warranty_status}, got {unit.get('warranty_status')}"
    if core_status is not None:
        assert (
            unit.get("core_status") == core_status
        ), f"expected core_status {core_status}, got {unit.get('core_status')}"


def assert_warranty_settlement(
    unit: Dict[str, Any], decision: str, credit_cents: int
) -> None:
    assert (
        unit.get("warranty_decision") == decision
    ), f"expected warranty_decision {decision}, got {unit.get('warranty_decision')}"
    assert_whole_cents(unit.get("warranty_credit_cents"), "warranty_credit_cents")
    assert (
        unit["warranty_credit_cents"] == credit_cents
    ), f"expected warranty_credit_cents {credit_cents}, got {unit['warranty_credit_cents']}"

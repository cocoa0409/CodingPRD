"""
Domain assertions for the Valve Manufacturing & Product Certification API.

These wrap the generic envelope validators with the entity-level invariants the
PRD states outright: the common server-managed property set (§2.4), the fixed
decimal scales (§2.6), the heat-lot mass balance (§3.2), the finding-count identity
(§3.6) and the money identity on a cancelled order (§3.8).
"""

from typing import Any, Dict, List, Optional

import pytest
import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import (
    FOUNDRY_ACTIVE_FLOOR,
    FOUNDRY_PROBATION_FLOOR,
    INDEX_DECIMALS,
    MASS_DECIMALS,
    PCT_DECIMALS,
    TORQUE_DECIMALS,
)
from .types import FoundryStatus


def _tolerance(decimals: int) -> float:
    return 0.5 * (10 ** -decimals)


def assert_decimal_equals(actual: Any, expected: float, decimals: int, label: str) -> None:
    """Assert a numeric field equals the expected value at its declared scale."""
    assert actual is not None, f"{label} is missing"
    assert float(actual) == pytest.approx(expected, abs=_tolerance(decimals) / 10), (
        f"{label}: expected {expected} at {decimals} decimal places, got {actual}"
    )


def assert_mass(actual: Any, expected: float, label: str) -> None:
    """Material masses are held to 3 decimal places."""
    assert_decimal_equals(actual, expected, MASS_DECIMALS, label)


def assert_torque(actual: Any, expected: float, label: str) -> None:
    """Torque figures are held to 1 decimal place."""
    assert_decimal_equals(actual, expected, TORQUE_DECIMALS, label)


def assert_percentage(actual: Any, expected: float, label: str) -> None:
    """Completeness percentages and the quality index are held to 2 decimal places."""
    assert_decimal_equals(actual, expected, PCT_DECIMALS, label)


# ─── Envelope shortcuts ───────────────────────────────


def assert_created(response: requests.Response) -> Dict[str, Any]:
    """Operations that mint a new resource return 201 Created."""
    return validate_success(response, 201)


def assert_ok(response: requests.Response) -> Dict[str, Any]:
    """Every operation that modifies an existing resource, and every read, returns 200 OK."""
    return validate_success(response, 200)


def assert_object_envelope(response: requests.Response, expected_status: int = 200) -> Dict[str, Any]:
    """Assert the envelope reports a single resource and return the resource."""
    data = validate_success(response, expected_status)
    body = response.json()
    assert body["response_type"] == "object", (
        f"Expected response_type 'object' for a single resource, got {body['response_type']!r}"
    )
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {body['meta']['api_request_id']!r}"
    )
    return data


# ─── Common server-managed properties (PRD §2.4) ──────


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the id/created_at/updated_at/version set every primary resource carries."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"id must be a server-minted UUID with no type prefix, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer, got {entity.get('version')!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_test_record(record: Dict[str, Any]) -> None:
    """A TestRecord carries id and created_at only — no updated_at and no version."""
    assert is_valid_uuid(record.get("id", "")), (
        f"test record id must be a UUID, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at", "")), (
        f"test record created_at must be ISO 8601, got {record.get('created_at')!r}"
    )
    assert "updated_at" not in record, "A test record has no updated_at field"
    assert "version" not in record, "A test record has no version field"


# ─── Entity-level invariants ──────────────────────────


def assert_foundry_band(foundry: Dict[str, Any], expected_index: float, expected_status: str) -> None:
    """The quality index and the status band it drives."""
    assert_decimal_equals(
        foundry.get("quality_index"), expected_index, INDEX_DECIMALS, "quality_index"
    )
    assert foundry.get("status") == expected_status, (
        f"Expected foundry status {expected_status}, got {foundry.get('status')!r}"
    )


def assert_index_band_consistent(foundry: Dict[str, Any]) -> None:
    """An index of 80 or above is ACTIVE, 60 up to but not including 80 is PROBATION,
    and anything below 60 is SUSPENDED."""
    index = float(foundry["quality_index"])
    if index >= FOUNDRY_ACTIVE_FLOOR:
        expected = FoundryStatus.ACTIVE
    elif index >= FOUNDRY_PROBATION_FLOOR:
        expected = FoundryStatus.PROBATION
    else:
        expected = FoundryStatus.SUSPENDED
    assert foundry["status"] == expected, (
        f"Index {index} should band to {expected}, got {foundry['status']!r}"
    )


def assert_lot_mass_balance(lot: Dict[str, Any]) -> None:
    """Received mass equals available plus committed plus scrapped."""
    received = float(lot["qty_received_kg"])
    available = float(lot["qty_available_kg"])
    committed = float(lot["qty_committed_kg"])
    scrapped = float(lot["qty_scrapped_kg"])
    assert available + committed + scrapped == pytest.approx(
        received, abs=_tolerance(MASS_DECIMALS)
    ), (
        f"Mass balance broken: available {available} + committed {committed} "
        f"+ scrapped {scrapped} != received {received}"
    )


def assert_unit_dimensions(
    unit: Dict[str, Any],
    build_status: Optional[str] = None,
    cert_status: Optional[str] = None,
    service_status: Optional[str] = None,
) -> None:
    """A unit carries three independent state dimensions rather than one status."""
    if build_status is not None:
        assert unit.get("build_status") == build_status, (
            f"Expected build_status {build_status}, got {unit.get('build_status')!r}"
        )
    if cert_status is not None:
        assert unit.get("cert_status") == cert_status, (
            f"Expected cert_status {cert_status}, got {unit.get('cert_status')!r}"
        )
    if service_status is not None:
        assert unit.get("service_status") == service_status, (
            f"Expected service_status {service_status}, got {unit.get('service_status')!r}"
        )


def assert_torque_envelope(
    package: Dict[str, Any],
    required_torque_nm: float,
    safety_margin_pct: float,
    sized_torque_nm: float,
) -> None:
    """The computed torque envelope of an actuator package."""
    assert_torque(package.get("required_torque_nm"), required_torque_nm, "required_torque_nm")
    assert_decimal_equals(
        package.get("safety_margin_pct"), safety_margin_pct, 2, "safety_margin_pct"
    )
    assert_torque(package.get("sized_torque_nm"), sized_torque_nm, "sized_torque_nm")


def assert_finding_identity(license_row: Dict[str, Any]) -> None:
    """total_major_raised equals the open, closed and waived major counts added together."""
    total = license_row["total_major_raised"]
    parts = (
        license_row["open_major_finding_count"]
        + license_row["closed_major_finding_count"]
        + license_row["waived_major_finding_count"]
    )
    assert total == parts, (
        f"Major finding identity broken: total_major_raised {total} != "
        f"open + closed + waived = {parts}"
    )


def assert_money_conservation(order: Dict[str, Any]) -> None:
    """The gross quote equals the net billable amount plus the credit issued."""
    gross = order["gross_quoted_cents"]
    net = order["net_billable_cents"]
    credit = order["credit_issued_cents"]
    assert isinstance(gross, int) and isinstance(net, int) and isinstance(credit, int), (
        "Money is integer cents throughout"
    )
    assert net + credit == gross, (
        f"Money identity broken: net {net} + credit {credit} != gross {gross}"
    )


def assert_emission_classes(
    unit: Dict[str, Any], provisional: Optional[str], final: Optional[str]
) -> None:
    """Fugitive-emission behaviour is computed twice and both answers are retained."""
    assert unit.get("provisional_emission_leak_class") == provisional, (
        f"Expected provisional_emission_leak_class {provisional!r}, "
        f"got {unit.get('provisional_emission_leak_class')!r}"
    )
    assert unit.get("final_emission_leak_class") == final, (
        f"Expected final_emission_leak_class {final!r}, "
        f"got {unit.get('final_emission_leak_class')!r}"
    )


def assert_list_contains_exactly(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing returned exactly the expected row identifiers, in order."""
    assert [row["id"] for row in rows] == expected_ids, (
        f"Expected rows {expected_ids}, got {[row.get('id') for row in rows]}"
    )

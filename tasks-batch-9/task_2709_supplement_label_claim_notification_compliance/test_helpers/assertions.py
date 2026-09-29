"""Domain assertions for the Supplement Label Claim Compliance API."""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    LOT_RELEASED,
    SUBSTANTIATION_APPROVED,
    SUBSTANTIATION_WITHDRAWN,
)


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """PRD §2.4: every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert not entity["id"].startswith(
        ("prod_", "ing_", "claim_", "panel_", "sup_", "lot_", "coa_", "aer_")
    ), "PRD §2.4: the id is a server-minted UUID with no type prefix"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_money(actual: Any, expected: float):
    """Two-decimal quantity comparison (PRD §2.8)."""
    assert actual is not None, "expected a numeric value, got None"
    assert not isinstance(actual, str), (
        f"expected a JSON number for a 2-decimal quantity, got the string {actual!r}"
    )
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"expected {expected}, got {actual}"
    )


def assert_lot_mass_identity(lot: Dict[str, Any]):
    """PRD §2.8: quarantined + released + rejected == quantity_kg, exactly."""
    total = (
        float(lot["quarantined_quantity_kg"])
        + float(lot["released_quantity_kg"])
        + float(lot["rejected_quantity_kg"])
    )
    assert total == pytest.approx(float(lot["quantity_kg"]), abs=0.01), (
        "PRD §2.8 lot mass identity violated: "
        f"{lot['quarantined_quantity_kg']} + {lot['released_quantity_kg']} + "
        f"{lot['rejected_quantity_kg']} != {lot['quantity_kg']}"
    )


def assert_supplier_ledger(supplier: Dict[str, Any], lots: List[Dict[str, Any]]):
    """PRD §2.8: total_released_kg == sum of released_quantity_kg over RELEASED lots."""
    expected = sum(
        float(lot["released_quantity_kg"])
        for lot in lots
        if lot["lot_status"] == LOT_RELEASED
    )
    assert_money(supplier["total_released_kg"], expected)


def assert_claim_ledger(product: Dict[str, Any], claims: List[Dict[str, Any]]):
    """PRD §2.8: both claim counters are literal counts."""
    active = sum(
        1 for c in claims if c["substantiation_status"] == SUBSTANTIATION_APPROVED
    )
    withdrawn = sum(
        1 for c in claims if c["substantiation_status"] == SUBSTANTIATION_WITHDRAWN
    )
    assert product["active_claim_count"] == active
    assert product["withdrawn_claim_count"] == withdrawn


def expected_risk_index(
    serious: int = 0, nonserious: int = 0, late: int = 0, rejected_coa: int = 0
) -> int:
    """PRD §2.9: base, then a surcharge chosen from the pre-surcharge base alone."""
    base = 10 + 20 * serious + 6 * nonserious + 15 * late + 8 * rejected_coa
    if base < 30:
        surcharge = 0
    elif base < 60:
        surcharge = 5
    else:
        surcharge = 12
    return min(base + surcharge, 100)


def assert_risk_index(product: Dict[str, Any], expected: int):
    assert product["compliance_risk_index"] == expected, (
        f"expected compliance_risk_index {expected}, "
        f"got {product['compliance_risk_index']}"
    )


def assert_posture(product: Dict[str, Any], expected: str):
    """PRD §2.9: requires_label_revision is the statement that posture is not OPEN."""
    assert product["label_posture"] == expected, (
        f"expected label_posture {expected}, got {product['label_posture']}"
    )
    assert product["requires_label_revision"] is (expected != "OPEN")


def assert_calendar_date(value: Any, expected: Optional[str] = None):
    """PRD §2.5: calendar dates are UTC dates in YYYY-MM-DD form."""
    assert isinstance(value, str), f"expected a YYYY-MM-DD string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"expected YYYY-MM-DD, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"expected {expected}, got {value}"


def assert_instant(value: Any, expected: Optional[str] = None):
    """PRD §2.5: instants are full ISO 8601 UTC timestamps."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 instant: {value!r}"
    if expected is not None:
        assert _normalize_instant(value) == _normalize_instant(expected), (
            f"expected instant {expected}, got {value}"
        )


def _normalize_instant(value: str) -> str:
    """Collapse ``Z``/``+00:00`` and optional millisecond precision."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[:-6]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text


def assert_warning_codes_sorted(codes: List[str]):
    """PRD §3.5: required_warning_codes is sorted in ascending lexicographic order."""
    assert codes == sorted(codes), f"required_warning_codes not sorted: {codes}"
    assert len(codes) == len(set(codes)), f"required_warning_codes has duplicates: {codes}"


def expected_panel_lines_allowed(panel_format: str, net_quantity_g: float) -> int:
    """PRD §3.5: floor division, then the upper cap, then the lower floor."""
    if panel_format == "LINEAR":
        return 8
    if panel_format == "STANDARD":
        value = int(net_quantity_g // 10) + 12
        value = min(value, 40)
        return max(value, 20)
    if panel_format == "SIMPLIFIED":
        value = int(net_quantity_g // 20) + 8
        value = min(value, 24)
        return max(value, 12)
    raise AssertionError(f"unknown panel_format {panel_format!r}")


def assert_panel_computed(
    panel: Dict[str, Any],
    required_warning_codes: List[str],
    panel_lines_required: int,
    panel_lines_allowed: int,
    panel_total_dv_coverage_pct: int,
):
    """PRD §3.5: validation persists all four computed panel figures."""
    assert panel["required_warning_codes"] == required_warning_codes
    assert_warning_codes_sorted(panel["required_warning_codes"])
    assert panel["panel_lines_required"] == panel_lines_required
    assert panel["panel_lines_allowed"] == panel_lines_allowed
    assert panel["panel_total_dv_coverage_pct"] == panel_total_dv_coverage_pct


def assert_score(actual: Any, expected: float):
    """PRD §2.8: substantiation scores are carried to two decimal places."""
    assert actual is not None, "expected a score, got None"
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"expected score {expected}, got {actual}"
    )


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"id {row_id} not present in the returned collection")

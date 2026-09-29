"""Domain assertion helpers built on the PRD's invariants."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _to_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """PRD 2.10: "Instant comparisons are made at second granularity", so an
    instant is compared as a point in time and not as a formatted string."""
    assert actual is not None, f"expected the instant {expected}, got null"
    assert is_iso8601_timestamp(actual), f"not an ISO-8601 instant: {actual}"
    assert _to_instant(actual) == _to_instant(expected), (
        f"instant mismatch: {actual} is not the same second as {expected}"
    )


def assert_versioned_common_fields(entity: Dict) -> None:
    """PRD 2.4: version-tracked entities expose id, created_at, updated_at,
    version."""
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_index_point_common_fields(entity: Dict) -> None:
    """PRD 2.4: CommodityIndexPoint "carries only id and created_at; it has no
    updated_at and no version field"."""
    assert is_valid_uuid(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"])
    assert "version" not in entity, "CommodityIndexPoint must expose no version"
    assert "updated_at" not in entity, "CommodityIndexPoint must expose no updated_at"


def assert_order_state(
    order: Dict,
    engineering_status: Optional[str] = None,
    fulfillment_status: Optional[str] = None,
    production_posture: Optional[str] = None,
    posture_reason_codes: Optional[List[str]] = None,
) -> None:
    """PRD 2.6: an order carries two independent status dimensions plus the
    derived production_posture and its sorted posture_reason_codes."""
    if engineering_status is not None:
        assert order["engineering_status"] == engineering_status
    if fulfillment_status is not None:
        assert order["fulfillment_status"] == fulfillment_status
    if production_posture is not None:
        assert order["production_posture"] == production_posture
    if posture_reason_codes is not None:
        assert order["posture_reason_codes"] == posture_reason_codes


def assert_reason_codes_sorted(order: Dict) -> None:
    """PRD 2.6: "posture_reason_codes is sorted ascending lexicographically"."""
    codes = order["posture_reason_codes"]
    assert codes == sorted(codes), f"reason codes not sorted ascending: {codes}"


def assert_component_buckets(
    component: Dict,
    quantity_on_hand: Optional[int] = None,
    quantity_available: Optional[int] = None,
    quantity_reserved: Optional[int] = None,
    quantity_committed: Optional[int] = None,
    quantity_consumed: Optional[int] = None,
) -> None:
    """Check the four unit buckets and quantity_available of PRD 2.9."""
    if quantity_on_hand is not None:
        assert component["quantity_on_hand"] == quantity_on_hand
    if quantity_available is not None:
        assert component["quantity_available"] == quantity_available
    if quantity_reserved is not None:
        assert component["quantity_reserved"] == quantity_reserved
    if quantity_committed is not None:
        assert component["quantity_committed"] == quantity_committed
    if quantity_consumed is not None:
        assert component["quantity_consumed"] == quantity_consumed


def assert_component_conservation(component: Dict, total_units: int) -> None:
    """PRD 2.9: "quantity_on_hand + quantity_consumed is conserved" and
    "quantity_on_hand always equals quantity_available + quantity_reserved +
    quantity_committed"."""
    assert component["quantity_on_hand"] + component["quantity_consumed"] == total_units
    assert component["quantity_on_hand"] == (
        component["quantity_available"]
        + component["quantity_reserved"]
        + component["quantity_committed"]
    )


def assert_net_contract_value(order: Dict) -> None:
    """PRD 2.9: "net_contract_value_cents equals contract_value_cents plus
    escalation_accepted_total_cents minus warranty_credit_total_cents"."""
    assert order["net_contract_value_cents"] == (
        order["contract_value_cents"]
        + order["escalation_accepted_total_cents"]
        - order["warranty_credit_total_cents"]
    )


def assert_bucket_allocation(
    claim: Dict, parts: int, labor: int, freight: int, consequential: int
) -> None:
    """PRD 3.9: bucket_allocation carries the keys PARTS, LABOR, FREIGHT and
    CONSEQUENTIAL, and credit_issued_cents is their sum."""
    allocation = claim["bucket_allocation"]
    assert allocation["PARTS"] == parts
    assert allocation["LABOR"] == labor
    assert allocation["FREIGHT"] == freight
    assert allocation["CONSEQUENTIAL"] == consequential
    assert claim["credit_issued_cents"] == parts + labor + freight + consequential


def assert_arc_flash_values(
    label: Dict,
    incident_energy_cal_cm2: float,
    ppe_category: int,
    arc_flash_boundary_mm: int,
    rating_text: Optional[str] = None,
) -> None:
    """PRD 3.6: incident_energy_cal_cm2 is rounded UP to one decimal,
    arc_flash_boundary_mm UP to a whole millimetre, and ppe_category is banded
    from the energy."""
    assert label["incident_energy_cal_cm2"] == pytest.approx(
        incident_energy_cal_cm2, abs=0.01
    )
    assert label["ppe_category"] == ppe_category
    assert label["arc_flash_boundary_mm"] == arc_flash_boundary_mm
    if rating_text is not None:
        assert label["rating_text"] == rating_text


def assert_arc_flash_unlabelable(label: Dict) -> None:
    """PRD 3.6: at or above 40.0 cal/cm2 the label "stays in DRAFT with no
    computed values"."""
    assert label["status"] == "DRAFT"
    assert label["incident_energy_cal_cm2"] is None
    assert label["ppe_category"] is None
    assert label["arc_flash_boundary_mm"] is None


def assert_quality_indices(
    supplier: Dict, trailing: float, lifetime: float
) -> None:
    """PRD 3.9: both index variants are rounded half up to two decimals and
    clamped into [0.00, 100.00]."""
    assert supplier["quality_index_trailing"] == pytest.approx(trailing, abs=0.01)
    assert supplier["quality_index_lifetime"] == pytest.approx(lifetime, abs=0.01)


def assert_storage_fee_breakdown(
    agreement: Dict,
    billable_days: int,
    storage_subtotal_cents: int,
    insurance_surcharge_cents: int,
    long_stay_discount_cents: int,
    total_fee_cents: int,
) -> None:
    """PRD 3.7: the six pinned steps of the site-storage fee computation."""
    assert agreement["billable_days"] == billable_days
    assert agreement["storage_subtotal_cents"] == storage_subtotal_cents
    assert agreement["insurance_surcharge_cents"] == insurance_surcharge_cents
    assert agreement["long_stay_discount_cents"] == long_stay_discount_cents
    assert agreement["total_fee_cents"] == total_fee_cents


def assert_pagination_defaults(meta: Dict, total_count: int) -> None:
    """PRD 2.3: limit defaults to 10 and offset defaults to 0."""
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == total_count
    assert meta["has_more"] is (total_count > 10)


def assert_punch_aggregates(
    job: Dict,
    open_punch_count: int,
    blocking_punch_count: int,
    completion_ratio_bp: int,
) -> None:
    """PRD 3.8: the three punch aggregates recomputed after every item change."""
    assert job["open_punch_count"] == open_punch_count
    assert job["blocking_punch_count"] == blocking_punch_count
    assert job["completion_ratio_bp"] == completion_ratio_bp


def assert_bay_scheduled_hours(bay: Dict, scheduled_hours_total: float) -> None:
    """PRD 2.9: scheduled_hours_total sums test_duration_hours over the tests
    occupying the bay."""
    assert bay["scheduled_hours_total"] == pytest.approx(
        scheduled_hours_total, abs=0.01
    )

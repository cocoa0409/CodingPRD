"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp
from .types import (
    BidSpecStatus, AwardStatus, PricingMode, PurchaseOrderStatus,
    PurchaseOrderPosture, POLineStatus, ShipmentKind, ShipmentStatus,
    InstallTaskStatus, DamageReportStatus, BackorderNoticeStatus,
    WarrantyClaimStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_district(data: dict):
    _assert_common(data, "District")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["annual_cap_cents"], int) and data["annual_cap_cents"] >= 1
    assert isinstance(data["extended_warranty_enrolled"], bool)


def assert_school_site(data: dict):
    _assert_common(data, "SchoolSite")
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["daily_crew_capacity"], int) and data["daily_crew_capacity"] >= 1


def assert_bid_spec(data: dict):
    _assert_common(data, "BidSpec")
    assert data["status"] in [s.value for s in BidSpecStatus]
    assert isinstance(data["spec_version"], int) and data["spec_version"] >= 1
    assert isinstance(data["delivery_window_start"], str)
    assert isinstance(data["delivery_window_end"], str)


def assert_spec_line(data: dict):
    _assert_common(data, "SpecLine")
    assert isinstance(data["manufacturer"], str) and len(data["manufacturer"]) > 0
    assert isinstance(data["model"], str) and len(data["model"]) > 0
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["max_unit_price_cents"], int)
    assert isinstance(data["remaining_qty"], int)


def assert_coop_agreement(data: dict):
    _assert_common(data, "CoopPriceAgreement")
    assert data["status"] == "ACTIVE"
    assert isinstance(data["contract_year"], int)
    assert isinstance(data["tier_table"], list) and len(data["tier_table"]) >= 1
    for row in data["tier_table"]:
        assert isinstance(row["min_qty"], int) and isinstance(row["unit_price_cents"], int)


def assert_award(data: dict):
    _assert_common(data, "Award")
    assert data["status"] in [s.value for s in AwardStatus]
    assert data["pricing_mode"] in [m.value for m in PricingMode]
    assert isinstance(data["awarded_spec_version"], int) and data["awarded_spec_version"] >= 1
    assert isinstance(data["install_rate_cents"], int)
    assert isinstance(data["warranty_years"], int) and data["warranty_years"] >= 1


def assert_purchase_order(data: dict):
    _assert_common(data, "PurchaseOrder")
    assert data["status"] in [s.value for s in PurchaseOrderStatus]
    assert data["posture"] in [p.value for p in PurchaseOrderPosture]
    assert isinstance(data["open_backorder_count"], int) and data["open_backorder_count"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0


def assert_po_line(data: dict):
    _assert_common(data, "POLine")
    assert data["status"] in [s.value for s in POLineStatus]
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] >= 1
    assert isinstance(data["computed_unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["delivered_qty"], int) and data["delivered_qty"] >= 0


def assert_shipment(data: dict):
    _assert_common(data, "Shipment")
    assert data["status"] in [s.value for s in ShipmentStatus]
    assert data["kind"] in [k.value for k in ShipmentKind]
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["lines"], list)


def assert_crew(data: dict):
    _assert_common(data, "Crew")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["booked_days"], int) and data["booked_days"] >= 0


def assert_install_task(data: dict):
    _assert_common(data, "InstallTask")
    assert data["status"] in [s.value for s in InstallTaskStatus]
    assert isinstance(data["crew_count"], int) and data["crew_count"] >= 1
    assert isinstance(data["crew_days"], int) and data["crew_days"] >= 1
    assert isinstance(data["start_date"], str) and isinstance(data["end_date"], str)


def assert_damage_report(data: dict):
    _assert_common(data, "DamageReport")
    assert data["status"] in [s.value for s in DamageReportStatus]
    assert isinstance(data["damaged_qty"], int) and data["damaged_qty"] >= 1
    assert isinstance(data["reported_date"], str)
    assert isinstance(data["replacement_deadline"], str)


def assert_backorder_notice(data: dict):
    _assert_common(data, "BackorderNotice")
    assert data["status"] in [s.value for s in BackorderNoticeStatus]
    assert isinstance(data["current_eta_date"], str)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common(data, "WarrantyClaim")
    assert data["status"] in [s.value for s in WarrantyClaimStatus]
    assert isinstance(data["parts_cost_cents"], int) and data["parts_cost_cents"] >= 1
    assert isinstance(data["appeal_count"], int) and 0 <= data["appeal_count"] <= 1
    assert isinstance(data["filed_date"], str)


def assert_spec_line_drawdown_invariant(spec_line: dict, active_ordered_qty: int):
    """PRD §2.10: qty == remaining_qty + summed ordered_qty of non-cancelled lines."""
    assert spec_line["qty"] == spec_line["remaining_qty"] + active_ordered_qty, (
        f"drawdown invariant broken: qty {spec_line['qty']} != remaining "
        f"{spec_line['remaining_qty']} + active {active_ordered_qty}"
    )


def assert_crew_booking_invariant(crew: dict, expected_booked_days: int):
    """PRD §2.10: booked_days == sum of crew_days over SCHEDULED/IN_PROGRESS tasks."""
    assert crew["booked_days"] == expected_booked_days, (
        f"crew booking ledger drifted: booked_days {crew['booked_days']} != {expected_booked_days}"
    )

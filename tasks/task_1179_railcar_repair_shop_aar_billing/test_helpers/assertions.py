"""Entity assertions and domain invariant checkers (PRD §2-§3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AuthStatus, BrcStatus, CarOwnerStatus, CauseCode, CounterBillStatus,
    DefectGroup, DefectStatus, ExecStatus, InspectionStatus, PartStatus,
    RepairLineStatus, ResponsibleParty, Routing, Severity, ShopPosture,
    SlotStatus, WarrantyClaimStatus, WheelsetStatus, RailcarStatus,
)


def _assert_common_fields(data: dict):
    """PRD §2.11: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_optional_timestamp(data: dict, field: str):
    if data.get(field) is not None:
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601 when present"


def assert_shop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["stalls"], int) and data["stalls"] >= 1
    assert isinstance(data["dwell_rate_cents_per_hour"], int)
    assert data["current_posture"] in [p.value for p in ShopPosture]


def assert_car_owner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["scac_code"], str) and data["scac_code"]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in [s.value for s in CarOwnerStatus]


def assert_handling_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["mark"], str) and data["mark"]
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_railcar(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["reporting_mark"], str) and data["reporting_mark"]
    assert isinstance(data["car_number"], str) and data["car_number"]
    assert is_valid_uuid(data.get("owner_id", "")), "owner_id must be a UUID"
    assert is_valid_uuid(data.get("handling_line_id", "")), "handling_line_id must be a UUID"
    assert is_iso8601_timestamp(data.get("arrived_at", "")), "arrived_at must be ISO 8601"
    _assert_optional_timestamp(data, "departed_at")
    assert data["status"] in [s.value for s in RailcarStatus]
    assert isinstance(data["shop_delay_hours"], (int, float))


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("railcar_id", "")), "railcar_id must be a UUID"
    assert data["status"] in [s.value for s in InspectionStatus]
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    _assert_optional_timestamp(data, "completed_at")
    assert isinstance(data["reopened_count"], int) and data["reopened_count"] >= 0


def assert_defect_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("inspection_id", "")), "inspection_id must be a UUID"
    assert isinstance(data["aar_defect_code"], str) and data["aar_defect_code"].startswith("AAR-")
    assert data["defect_group"] in [g.value for g in DefectGroup]
    assert data["cause_code"] in [c.value for c in CauseCode]
    assert data["severity"] in [s.value for s in Severity]
    assert data["status"] in [s.value for s in DefectStatus]


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("railcar_id", "")), "railcar_id must be a UUID"
    assert is_valid_uuid(data.get("inspection_id", "")), "inspection_id must be a UUID"
    assert data["routing"] in [r.value for r in Routing]
    assert data["auth_status"] in [s.value for s in AuthStatus]
    assert data["exec_status"] in [s.value for s in ExecStatus]
    if data.get("responsible_party") is not None:
        assert data["responsible_party"] in [p.value for p in ResponsibleParty]
    assert isinstance(data.get("estimate_total_cents", 0), int)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    _assert_optional_timestamp(data, "authorized_at")
    _assert_optional_timestamp(data, "completed_at")
    _assert_optional_timestamp(data, "qa_review_entered_at")


def assert_repair_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a UUID"
    assert is_valid_uuid(data.get("defect_finding_id", "")), "defect_finding_id must be a UUID"
    assert isinstance(data["job_code"], str) and data["job_code"]
    assert isinstance(data.get("estimate_labor_cents", 0), int)
    assert isinstance(data.get("estimate_material_cents", 0), int)
    assert isinstance(data.get("estimate_total_cents", 0), int)
    if data.get("responsible_party") is not None:
        assert data["responsible_party"] in [p.value for p in ResponsibleParty]
    if data.get("owner_pct") is not None:
        assert data["owner_pct"] in (0, 50, 100)
    assert data["status"] in [s.value for s in RepairLineStatus]


def assert_price_master_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_code"], str) and data["job_code"]
    assert isinstance(data["labor_rate_cents_per_hour"], int)
    assert isinstance(data["mobile_labor_rate_cents_per_hour"], int)
    assert isinstance(data["standard_labor_hours"], (int, float))
    assert isinstance(data["mobile_trip_surcharge_cents"], int)
    assert isinstance(data["mobile_eligible"], bool)
    assert isinstance(data["effective_from"], str) and data["effective_from"]
    assert isinstance(data["effective_to"], str) and data["effective_to"]


def assert_part_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["reorder_threshold"], int)
    assert data["status"] in [s.value for s in PartStatus]
    assert_part_quantity_invariant(data)


def assert_part_quantity_invariant(data: dict):
    """PRD §2.9: available_qty == on_hand_qty - reserved_qty, never negative."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty {data['available_qty']} != on_hand {data['on_hand_qty']} "
        f"- reserved {data['reserved_qty']}"
    )
    assert data["available_qty"] >= 0, "available_qty must never go negative"


def assert_wheelset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["flange_thickness_mm"], (int, float))
    assert isinstance(data["tread_wear_mm"], (int, float))
    assert data["status"] in [s.value for s in WheelsetStatus]


def assert_shop_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["stall_id"], str) and data["stall_id"]
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert data["status"] in [s.value for s in SlotStatus]


def assert_billing_repair_card(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a UUID"
    assert data["status"] in [s.value for s in BrcStatus]
    assert isinstance(data.get("submitted_total_cents", 0), int)
    assert isinstance(data.get("owner_total_cents", 0), int)
    assert isinstance(data.get("handling_line_total_cents", 0), int)
    assert isinstance(data.get("net_settled_cents", 0), int)
    assert isinstance(data.get("mobile_surcharge_cents", 0), int)
    _assert_optional_timestamp(data, "submitted_at")


def assert_brc_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("brc_id", "")), "brc_id must be a UUID"
    assert is_valid_uuid(data.get("repair_line_id", "")), "repair_line_id must be a UUID"
    assert isinstance(data["job_code"], str) and data["job_code"]
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["owner_share_cents"], int)
    assert isinstance(data["handling_share_cents"], int)
    assert isinstance(data["accepted_credit_cents"], int)
    assert isinstance(data["warranty_credit_cents"], int)


def assert_counter_bill(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("brc_id", "")), "brc_id must be a UUID"
    assert isinstance(data["items"], list) and data["items"]
    assert isinstance(data["total_countered_cents"], int)
    assert data["status"] in [s.value for s in CounterBillStatus]
    assert isinstance(data["filed_by_role"], str) and data["filed_by_role"]
    assert isinstance(data["filed_by_id"], str) and data["filed_by_id"]
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("repair_line_id", "")), "repair_line_id must be a UUID"
    assert data["failure_defect_group"] in [g.value for g in DefectGroup]
    assert isinstance(data["claimed_rework_cost_cents"], int)
    assert data["status"] in [s.value for s in WarrantyClaimStatus]
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
    assert isinstance(data["filed_by_id"], str) and data["filed_by_id"]


def assert_brc_money_conservation(brc: dict, accepted_credit_total: int):
    """PRD §3.7: net_settled_cents anchors the card as submitted minus credits."""
    assert brc["net_settled_cents"] == brc["submitted_total_cents"] - accepted_credit_total, (
        f"net_settled_cents {brc['net_settled_cents']} != submitted "
        f"{brc['submitted_total_cents']} - credits {accepted_credit_total}"
    )
    assert brc["owner_total_cents"] + brc["handling_line_total_cents"] == brc["submitted_total_cents"], (
        "owner_total_cents + handling_line_total_cents must equal submitted_total_cents"
    )

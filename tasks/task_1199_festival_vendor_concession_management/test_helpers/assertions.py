"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID without type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_festival(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNING", "APPLICATIONS_OPEN", "CURATED", "LIVE", "SETTLEMENT", "CLOSED"]
    assert isinstance(data["category_cap_per_category"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["status"] in ["APPROVED", "SUSPENDED"]
    assert isinstance(data["compliance_strikes"], int) and data["compliance_strikes"] >= 0


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "ACCEPTED",
                              "REJECTED", "WAITLISTED", "WITHDRAWN", "SUPERSEDED"]
    assert data["category"] in ["FOOD_HOT", "FOOD_COLD", "BEVERAGE_ALCOHOL", "BEVERAGE_NA",
                                "DESSERT", "MERCHANDISE"]
    assert data["fee_model"] in ["FLAT_FEE", "REVENUE_SHARE", "HYBRID"]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["reserved_power_amps"], int) and data["reserved_power_amps"] >= 0
    assert isinstance(data["reserved_water_hookups"], int) and data["reserved_water_hookups"] >= 0


def assert_booth(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "RESERVED", "ASSIGNED"]


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "CONFIRMED", "ACTIVE", "COMPLETED", "RELEASED", "FORFEITED"]
    assert data["utility_status"] in ["PENDING", "PROVISIONED"]
    assert isinstance(data["power_draw_amps"], int) and data["power_draw_amps"] >= 1


def assert_inspection(data: dict):
    # Immutable event: id + created_at only — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "InspectionRecord must not carry updated_at"
    assert "version" not in data, "InspectionRecord must not carry version"
    assert data["type"] in ["HEALTH_PREOPEN", "HEALTH_SPOT", "FIRE_SAFETY"]
    assert data["result"] in ["PASS", "CONDITIONAL_PASS", "FAIL"]
    assert data["status"] == "COMPLETED"


def assert_slot(data: dict):
    _assert_common(data)
    assert data["gate"] in ["GATE_A", "GATE_B", "GATE_C"]
    assert isinstance(data["reserved_vehicle_count"], int) and data["reserved_vehicle_count"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ["BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["vehicle_count"], int) and data["vehicle_count"] >= 1


def assert_transaction(data: dict):
    _assert_common(data)
    assert data["status"] in ["REPORTED", "SETTLED", "VOIDED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "RECONCILING", "DISPUTED", "FINALIZED", "PAID"]


def assert_fine(data: dict):
    _assert_common(data)
    assert data["type"] in ["WASTE_SORTING", "COMPOST_CONTAMINATION", "GREASE_DISPOSAL",
                            "HEALTH_VIOLATION", "NO_SHOW_PENALTY"]
    assert data["status"] in ["ISSUED", "ACKNOWLEDGED", "DISPUTED", "PAID", "WAIVED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_review(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "SCORED", "INVITED", "ACCEPTED", "DECLINED", "INELIGIBLE"]


def assert_settlement_conservation(gross: int, share: int, payout: int, balance_due: int, deduction: int):
    """PRD §3.6 conservation identity for the final settlement variant:
    gross + vendor_balance_due == festival_share + vendor_payout + deductions_applied."""
    assert gross + balance_due == share + payout + deduction, (
        f"conservation violated: {gross} + {balance_due} != {share} + {payout} + {deduction}"
    )

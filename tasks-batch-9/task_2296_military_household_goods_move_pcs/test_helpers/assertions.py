"""Entity assertions and domain invariant checkers for the household-goods move API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY_TOLERANCE = 0.005


def assert_common_fields(data: Dict[str, Any], entity_label: str = "entity") -> None:
    """Every record exposes a bare UUID id, both timestamps and an integer version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_service_member(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ServiceMember")
    assert isinstance(data["dod_id"], str) and len(data["dod_id"]) == 10, (
        f"dod_id must be exactly ten characters, got {data['dod_id']!r}"
    )
    assert 1 <= len(data["full_name"]) <= 120
    assert data["rank_code"] in [
        "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9",
        "W1", "W2", "W3", "W4", "W5",
        "O1", "O2", "O3", "O4", "O5", "O6",
    ]
    assert data["branch"] in [
        "ARMY", "NAVY", "AIR_FORCE", "MARINE_CORPS", "SPACE_FORCE", "COAST_GUARD",
    ]
    assert "@" in data["email"], f"email must contain an at-sign, got {data['email']!r}"
    assert 0 <= data["dependents_count"] <= 12
    assert isinstance(data["spouse_present"], bool)
    assert isinstance(data["active_shipment_count"], int)
    assert data["active_shipment_count"] >= 0


def assert_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "PcsOrder")
    assert is_valid_uuid(data["service_member_id"])
    assert 4 <= len(data["order_number"]) <= 32
    assert data["move_type"] in [
        "PCS_CONUS", "PCS_OCONUS", "SEPARATION", "RETIREMENT", "LOCAL",
    ]
    assert is_iso8601_timestamp(data["issue_date"])
    assert is_iso8601_timestamp(data["report_no_later_than_date"])
    assert data["report_no_later_than_date"] > data["issue_date"], (
        "report_no_later_than_date must fall strictly after issue_date"
    )
    assert_market_code(data["origin_market_code"])
    assert 0 < data["distance_miles"] <= 12000
    assert isinstance(data["is_dependent_restricted"], bool)
    assert isinstance(data["dependents_count_at_issue"], int)
    assert data["status"] in ["ISSUED", "AMENDED", "CLOSED"]
    assert 0 <= data["amendment_count"] <= 3


def assert_counseling_session(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CounselingSession")
    assert is_valid_uuid(data["order_id"])
    assert data["session_type"] in ["SELF_SERVICE", "VIRTUAL", "IN_PERSON"]
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert is_iso8601_timestamp(data["counseling_deadline_at"])
    assert isinstance(data["entitlement_briefed"], bool)
    assert isinstance(data["is_late_counseling"], bool)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_entitlement(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Entitlement")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["counseling_session_id"])
    assert data["dependent_status_effective"] in [
        "WITHOUT_DEPENDENTS", "WITH_DEPENDENTS",
    ]
    assert data["status"] in ["DRAFT", "AUTHORIZED", "SUSPENDED", "CLOSED"]
    for field in (
        "base_weight_allowance_lbs",
        "pro_gear_member_allowance_lbs",
        "pro_gear_spouse_allowance_lbs",
        "admin_weight_bump_lbs",
        "total_billable_cap_lbs",
        "charged_billable_weight_lbs",
        "pro_gear_excluded_total_lbs",
        "excess_weight_lbs",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole pound figure"
        assert data[field] >= 0, f"{field} must not be negative"
    for field in (
        "gross_excess_cost_usd",
        "excess_cost_waived_usd",
        "excess_cost_due_usd",
    ):
        assert_cost_precision(data[field])
        assert data[field] >= 0, f"{field} must not be negative"
    assert_excess_cost_conservation(data)


def assert_excess_cost_conservation(data: Dict[str, Any]) -> None:
    """The amount due plus the amount waived always equals the gross excess cost."""
    total = data["excess_cost_due_usd"] + data["excess_cost_waived_usd"]
    assert abs(total - data["gross_excess_cost_usd"]) < MONEY_TOLERANCE, (
        "excess_cost_due_usd plus excess_cost_waived_usd must equal "
        f"gross_excess_cost_usd; got {data['excess_cost_due_usd']} + "
        f"{data['excess_cost_waived_usd']} != {data['gross_excess_cost_usd']}"
    )


def assert_weight_ledger(data: Dict[str, Any]) -> None:
    """The computed weight-ledger read exposes every figure the PRD names."""
    for field in (
        "entitlement_id",
        "total_billable_cap_lbs",
        "charged_billable_weight_lbs",
        "pro_gear_excluded_total_lbs",
        "excess_weight_lbs",
        "excess_pct_over",
        "excess_rate_per_cwt",
        "admin_fee_usd",
        "gross_excess_cost_usd",
        "excess_cost_waived_usd",
        "excess_cost_due_usd",
        "contributing_shipment_count",
    ):
        assert field in data, f"weight ledger read must expose {field}"
    assert is_valid_uuid(data["entitlement_id"])
    assert isinstance(data["contributing_shipment_count"], int)
    for field in ("gross_excess_cost_usd", "excess_cost_due_usd", "admin_fee_usd"):
        assert_cost_precision(data[field])


def assert_moving_company(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "MovingCompany")
    assert isinstance(data["scac_code"], str) and len(data["scac_code"]) == 4
    assert data["scac_code"].isupper()
    assert isinstance(data["markets"], list) and len(data["markets"]) >= 1
    for market in data["markets"]:
        assert_market_code(market)
    assert data["status"] in ["ACTIVE", "PROBATION", "SUSPENDED"]
    assert 0 <= data["performance_score"] <= 100
    assert_cost_precision(data["performance_score"])
    assert isinstance(data["settled_claim_count"], int)
    assert_cost_precision(data["claim_settlement_total_usd"])


def assert_capacity_block(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CapacityBlock")
    assert is_valid_uuid(data["tsp_id"])
    assert_market_code(data["market_code"])
    assert is_iso8601_timestamp(data["week_start_date"])
    assert is_iso8601_timestamp(data["week_end_date"])
    assert isinstance(data["peak_season"], bool)
    assert data["total_capacity_lbs"] > 0
    assert 0 <= data["short_notice_reserve_pct"] <= 1
    assert 0 <= data["effective_reserve_pct"] <= 1
    assert data["status"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert_capacity_conservation(data)


def assert_capacity_conservation(data: Dict[str, Any]) -> None:
    """The two pools partition the block, and the two committed sums add to the total."""
    assert data["general_pool_lbs"] + data["short_notice_pool_lbs"] == data[
        "total_capacity_lbs"
    ], (
        "general_pool_lbs plus short_notice_pool_lbs must equal total_capacity_lbs; "
        f"got {data['general_pool_lbs']} + {data['short_notice_pool_lbs']} != "
        f"{data['total_capacity_lbs']}"
    )
    assert data["committed_general_lbs"] + data["committed_short_notice_lbs"] == data[
        "committed_lbs"
    ], (
        "committed_general_lbs plus committed_short_notice_lbs must equal "
        f"committed_lbs; got {data['committed_general_lbs']} + "
        f"{data['committed_short_notice_lbs']} != {data['committed_lbs']}"
    )
    assert data["committed_general_lbs"] >= 0
    assert data["committed_short_notice_lbs"] >= 0


def assert_shipment(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Shipment")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["entitlement_id"])
    assert is_valid_uuid(data["tsp_id"])
    assert data["shipment_method"] in ["HHG", "UB", "NTS", "PPM"]
    assert 4 <= len(data["shipment_code"]) <= 24
    assert_market_code(data["origin_market_code"])
    assert data["movement_status"] in [
        "AWARDED", "ON_HOLD", "SURVEYED", "PACKED", "PICKED_UP", "IN_SIT",
        "DELIVERED", "CANCELLED",
    ]
    assert data["weight_recon_status"] in [
        "PENDING", "ESTIMATED", "ACTUAL_RECORDED", "DISPUTED", "RECONCILED",
    ]
    assert data["billable_basis"] in ["NONE", "ESTIMATED", "ACTUAL"]
    assert isinstance(data["is_short_notice"], bool)
    assert isinstance(data["peak_season"], bool)
    assert isinstance(data["reweigh_required"], bool)
    assert is_iso8601_timestamp(data["spread_start_date"])
    assert is_iso8601_timestamp(data["spread_end_date"])
    assert data["spread_start_date"] <= data["spread_end_date"]
    assert data["transit_days_allowed"] >= 5
    assert data["billable_weight_lbs"] >= 0
    assert data["pro_gear_excluded_lbs"] >= 0


def assert_pro_gear_declaration(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ProGearDeclaration")
    assert is_valid_uuid(data["shipment_id"])
    assert data["owner"] in ["MEMBER", "SPOUSE"]
    assert 0 < data["claimed_weight_lbs"] <= 2500
    assert data["documentation_type"] in [
        "ITEMIZED_INVENTORY", "EMPLOYER_LETTER", "ORDERS_EXTRACT", "NONE",
    ]
    assert data["status"] in [
        "SUBMITTED", "VERIFIED", "PARTIALLY_VERIFIED", "REJECTED",
    ]
    assert 0 <= data["resubmission_count"] <= 2


def assert_sit_authorization(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "SitAuthorization")
    assert is_valid_uuid(data["shipment_id"])
    assert data["sit_type"] in ["ORIGIN", "DESTINATION"]
    assert is_iso8601_timestamp(data["entry_date"])
    assert 0 < data["requested_days"] <= 90
    assert data["authorized_days"] + data["extension_days"] <= 90, (
        "authorized_days plus extension_days may never exceed ninety days"
    )
    assert data["status"] in ["REQUESTED", "AUTHORIZED", "RELEASED"]
    for field in (
        "sit_base_cost_usd",
        "fuel_surcharge_usd",
        "sit_total_cost_usd",
        "member_liability_usd",
    ):
        assert_cost_precision(data[field])
        assert data[field] >= 0


def assert_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "LossDamageClaim")
    assert is_valid_uuid(data["shipment_id"])
    assert data["claim_type"] in ["LOSS", "DAMAGE", "BOTH"]
    assert is_iso8601_timestamp(data["notice_date"])
    assert data["settlement_basis"] in [
        "UNDETERMINED", "FULL_REPLACEMENT_VALUE", "DEPRECIATED_VALUE",
    ]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "SETTLED", "DENIED",
    ]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    assert 0 <= data["info_request_count"] <= 3
    assert_cost_precision(data["claimed_total_usd"])
    assert_cost_precision(data["settlement_total_usd"])
    assert data["settlement_total_usd"] <= 100000.00 + MONEY_TOLERANCE, (
        "settlement_total_usd may never exceed the hundred-thousand-dollar cap"
    )


def assert_claim_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ClaimItem")
    assert is_valid_uuid(data["claim_id"])
    assert data["category"] in [
        "ELECTRONICS", "FURNITURE", "APPLIANCE", "CLOTHING", "OTHER",
    ]
    assert data["replacement_cost_usd"] > 0
    assert_cost_precision(data["replacement_cost_usd"])
    assert 0 <= data["age_years"] <= 60
    assert isinstance(data["high_value_inventory_documented"], bool)
    assert data["disposition"] in ["PENDING", "ALLOWED", "DENIED"]
    assert_cost_precision(data["item_settlement_usd"])


def assert_ppm_submission(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "PpmSubmission")
    assert is_valid_uuid(data["shipment_id"])
    assert isinstance(data["trip_tickets"], list) and len(data["trip_tickets"]) >= 1
    assert data["elected_basis"] in [
        "AUTO", "INCENTIVE_BASIS", "ACTUAL_EXPENSE_BASIS",
    ]
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED"]
    for field in (
        "documented_expenses_usd",
        "advance_paid_usd",
        "gcc_usd",
        "incentive_usd",
        "reimbursement_usd",
        "net_payable_usd",
        "debt_owed_usd",
        "taxable_amount_usd",
    ):
        assert_cost_precision(data[field])
        assert data[field] >= 0, f"{field} must not be negative"


def assert_notification(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Notification")
    assert is_valid_uuid(data["shipment_id"])
    assert data["notification_type"] in [
        "PACK_DATE_CONFIRMED", "PICKUP_CONFIRMED", "SIT_ENTRY",
        "WEIGHT_RECON_COMPLETE", "CLAIM_ACK",
    ]
    assert is_iso8601_timestamp(data["trigger_event_at"])
    assert is_iso8601_timestamp(data["due_by"])
    assert data["sla_hours"] in [24, 72, 120, 168]
    assert data["status"] in ["PENDING", "SENT", "LATE"]
    if data["channel"] is not None:
        assert data["channel"] in ["EMAIL", "SMS", "PORTAL"]
    assert data["hours_late"] >= 0


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def assert_market_code(value: str) -> None:
    """A market code is `MKT-` followed by exactly three uppercase letters."""
    assert isinstance(value, str) and len(value) == 7, (
        f"market code must be seven characters, got {value!r}"
    )
    assert value.startswith("MKT-"), f"market code must start with MKT-, got {value!r}"
    assert value[4:].isalpha() and value[4:].isupper(), (
        f"market code must end with three uppercase letters, got {value!r}"
    )


def assert_shipment_dimensions(
    data: Dict[str, Any],
    movement_status: Optional[str] = None,
    weight_recon_status: Optional[str] = None,
) -> None:
    """Assert either or both of a shipment's two independent status dimensions."""
    if movement_status is not None:
        assert data["movement_status"] == movement_status, (
            f"Expected movement_status {movement_status}, "
            f"got {data['movement_status']}"
        )
    if weight_recon_status is not None:
        assert data["weight_recon_status"] == weight_recon_status, (
            f"Expected weight_recon_status {weight_recon_status}, "
            f"got {data['weight_recon_status']}"
        )


def assert_money(actual: float, expected: float, label: str = "amount") -> None:
    assert abs(actual - expected) < MONEY_TOLERANCE, (
        f"Expected {label} {expected:.2f}, got {actual}"
    )

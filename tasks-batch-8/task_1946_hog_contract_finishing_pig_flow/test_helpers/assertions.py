"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """System-managed fields every primary resource carries (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["county"], str) and data["county"]
    assert data["site_status"] in ("ACTIVE", "SUSPENDED", "DECOMMISSIONED")
    assert isinstance(data["total_capacity_head"], int)
    assert data["total_capacity_head"] >= 0


def assert_grower(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["grower_code"], str) and data["grower_code"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["grower_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["grower_id"])
    assert is_valid_uuid(data["site_id"])
    for money_field in (
        "base_pay_cents_per_head", "bonus_cap_cents_per_head", "feed_budget_lbs_per_head",
    ):
        assert isinstance(data[money_field], int) and data[money_field] >= 0
    for pct_field in (
        "structural_owner_pct", "equipment_owner_pct", "routine_owner_pct",
    ):
        assert isinstance(data[pct_field], int), f"{pct_field} must be int"
        assert 0 <= data[pct_field] <= 100, f"{pct_field} must be in 0..100"
    assert data["contract_status"] in ("DRAFT", "ACTIVE", "TERMINATED", "EXPIRED")


def assert_barn(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["barn_code"], str) and data["barn_code"]
    assert isinstance(data["capacity_head"], int) and data["capacity_head"] >= 1
    assert isinstance(data["floor_space_sqft"], int) and data["floor_space_sqft"] >= 0
    assert data["barn_status"] in (
        "AVAILABLE", "OCCUPIED", "WASH_REQUIRED", "WASHING", "DOWNTIME",
        "OUT_OF_SERVICE",
    )
    assert isinstance(data["wash_required"], bool)


def assert_pig_group(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["barn_id"])
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["head_placed"], int) and data["head_placed"] >= 1
    assert data["group_status"] in (
        "SCHEDULED", "PLACED", "MARKETING", "CLOSED", "CANCELLED",
    )
    assert data["current_phase"] in ("STARTER", "GROWER", "FINISHER_1", "FINISHER_2")
    for counter in (
        "mortality_total", "cull_total", "head_marketed", "head_unaccounted",
        "head_current", "total_live_weight_lbs", "cumulative_feed_lbs",
        "pending_deductions_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter


def assert_feed_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["group_id"])
    assert data["phase"] in ("STARTER", "GROWER", "FINISHER_1", "FINISHER_2")
    assert isinstance(data["quantity_lbs"], int) and data["quantity_lbs"] >= 1
    assert data["order_status"] in (
        "REQUESTED", "SCHEDULED", "DELIVERED", "SHORTED", "CANCELLED",
    )
    assert isinstance(data["over_phase_plan"], bool)


def assert_mortality_report(data: dict):
    """Append-only event shape (PRD §2.5): id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "mortality reports must not carry updated_at"
    assert "version" not in data, "mortality reports must not carry version"
    assert isinstance(data["mortality_count"], int) and data["mortality_count"] >= 0
    assert isinstance(data["cull_count"], int) and data["cull_count"] >= 0
    assert data["reason_code"] in ("DISEASE", "INJURY", "STRESS", "OTHER")


def assert_packer_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["plant_code"], str) and data["plant_code"]
    assert data["shift"] in ("AM", "PM")
    assert isinstance(data["capacity_head"], int) and data["capacity_head"] >= 1
    assert data["max_weight_lbs"] >= data["min_weight_lbs"]
    assert isinstance(data["reserved_head"], int) and data["reserved_head"] >= 0
    assert data["slot_status"] in ("OPEN", "FULL", "CLOSED")


def assert_truck_wash(data: dict):
    _assert_common(data)
    assert isinstance(data["truck_code"], str) and data["truck_code"]
    assert data["wash_type"] in ("FULL_DISINFECT", "WASH_ONLY")
    assert data["wash_status"] in ("RECORDED", "VERIFIED", "REJECTED")
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


def assert_market_load(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["group_id"])
    assert is_valid_uuid(data["slot_id"])
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert data["load_status"] in (
        "SCHEDULED", "DISPATCHED", "DELIVERED", "REJECTED_AT_PLANT", "CANCELLED",
    )


def assert_barn_wash(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["barn_id"])
    assert data["wash_type"] in ("FULL_DISINFECT", "WASH_ONLY")
    assert data["wash_status"] in ("RECORDED", "VERIFIED", "REJECTED")
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


def assert_manure_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["plan_year"], int)
    assert data["plan_status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED",
    )
    for counter in ("n_applied_lbs", "p_applied_lbs", "lagoon_available_gal"):
        assert isinstance(data[counter], int), counter


def assert_manure_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["gallons"], int) and data["gallons"] >= 1
    assert isinstance(data["n_lbs"], int) and data["n_lbs"] >= 0
    assert isinstance(data["p_lbs"], int) and data["p_lbs"] >= 0
    assert data["application_status"] in ("RECORDED", "CONFIRMED", "VOIDED")


def assert_maintenance_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["barn_id"])
    assert data["category"] in ("STRUCTURAL", "EQUIPMENT", "ROUTINE", "EMERGENCY")
    assert data["ticket_status"] in (
        "OPEN", "QUOTED", "APPROVED", "IN_PROGRESS", "COMPLETED", "REJECTED",
        "CANCELLED",
    )


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["group_id"])
    assert is_valid_uuid(data["contract_id"])
    for money in (
        "base_pay_cents", "bonus_cents", "deductions_cents", "adjustment_cents",
        "total_pay_cents",
    ):
        assert isinstance(data[money], int), money
    assert data["settlement_status"] in ("FINALIZED", "DISPUTED", "APPROVED", "PAID")


def assert_head_reconciliation_pre_close(group: dict):
    """PRD §3.4: before close, head_placed == head_current + mortality_total
    + cull_total + head_marketed."""
    total = (
        group["head_current"] + group["mortality_total"] + group["cull_total"]
        + group["head_marketed"]
    )
    assert group["head_placed"] == total, (
        f"pre-close head invariant broken: placed {group['head_placed']} != {total}"
    )


def assert_head_reconciliation_post_close(group: dict):
    """PRD §3.4: after close, head_placed == mortality_total + cull_total
    + head_marketed + head_unaccounted."""
    total = (
        group["mortality_total"] + group["cull_total"] + group["head_marketed"]
        + group["head_unaccounted"]
    )
    assert group["head_placed"] == total, (
        f"post-close head invariant broken: placed {group['head_placed']} != {total}"
    )


def assert_settlement_pay_invariants(settlement: dict):
    """PRD §3.8: total_pay_cents == base + bonus + adjustment - deductions."""
    expected = (
        settlement["base_pay_cents"] + settlement["bonus_cents"]
        + settlement["adjustment_cents"] - settlement["deductions_cents"]
    )
    assert settlement["total_pay_cents"] == expected, (
        f"total_pay_cents {settlement['total_pay_cents']} != {expected}"
    )


def assert_ticket_split_invariants(ticket: dict):
    """PRD §3.7: owner + grower shares always sum back to the quoted cost."""
    total = ticket["owner_share_cents"] + ticket["grower_share_cents"]
    assert ticket["cost_cents"] == total, (
        f"cost split does not conserve: {ticket['owner_share_cents']} + "
        f"{ticket['grower_share_cents']} != {ticket['cost_cents']}"
    )

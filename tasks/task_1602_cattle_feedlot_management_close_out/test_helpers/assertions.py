"""Entity assertions and domain invariant checkers.

Field-level checks for the entities that tests read back. These validate the
fixed envelope-facing contract: identifier shape, timestamp shape, status
membership, and the presence of PRD-named fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_owner(data: dict):
    _assert_common_fields(data, "Owner")
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0, (
        "outstanding_balance_cents never falls below zero"
    )


def assert_pen(data: dict):
    _assert_common_fields(data, "Pen")
    assert isinstance(data["pen_code"], str) and data["pen_code"]
    assert isinstance(data["capacity_head"], int) and data["capacity_head"] > 0
    assert data["status"] in ("EMPTY", "OCCUPIED", "MAINTENANCE")
    assert isinstance(data["current_occupancy_head"], int)
    assert data["current_occupancy_head"] >= 0


def assert_lot(data: dict):
    _assert_common_fields(data, "Lot")
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert data["sex_class"] in ("STEER", "HEIFER")
    assert isinstance(data["head_count_in"], int) and data["head_count_in"] > 0
    assert isinstance(data["in_weight_total_lbs"], int)
    assert data["in_weight_total_lbs"] > 0
    assert isinstance(data["purchase_cost_cents"], int)
    assert data["purchase_cost_cents"] >= 0
    assert isinstance(data["arrival_date"], str)
    assert isinstance(data["commingle_allowed"], bool)
    assert data["status"] in ("OPEN", "MARKETED", "SHIPPED", "CLOSED_OUT", "SETTLED")
    assert isinstance(data["head_count_current"], int)
    assert data["head_count_current"] >= 0
    assert isinstance(data["head_shipped"], int)
    assert isinstance(data["total_deaths"], int) and data["total_deaths"] >= 0
    for acc in ("total_feed_cost_cents", "total_health_cost_cents",
                "total_death_loss_cents", "total_hedge_pnl_cents",
                "insurance_credit_pending_cents"):
        assert isinstance(data[acc], int), f"Lot.{acc} must be an integer"


def assert_lot_head_conservation(data: dict):
    """The lot's head conservation invariant must hold at every read."""
    assert data["head_count_in"] == (
        data["head_count_current"] + data["total_deaths"] + data["head_shipped"]
    ), (
        "head_count_in must equal head_count_current + total_deaths + head_shipped"
    )


def assert_ration(data: dict):
    _assert_common_fields(data, "Ration")
    assert isinstance(data["ration_name"], str) and data["ration_name"]
    assert isinstance(data["step_level"], int) and data["step_level"] >= 1
    assert isinstance(data["cost_per_ton_cents"], int)
    assert data["cost_per_ton_cents"] > 0


def assert_pen_assignment(data: dict):
    _assert_common_fields(data, "PenAssignment")
    assert isinstance(data["pen_id"], str) and data["pen_id"]
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["head_count"], int) and data["head_count"] >= 0
    assert isinstance(data["start_date"], str)
    assert data["end_date"] is None or isinstance(data["end_date"], str)
    assert data["status"] in ("ACTIVE", "ENDED")


def assert_ration_assignment(data: dict):
    _assert_common_fields(data, "RationAssignment")
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["ration_id"], str) and data["ration_id"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_feed_call(data: dict):
    """FeedCall is an immutable event record: id + created_at only as common
    fields; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "FeedCall.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "FeedCall.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "FeedCall must not carry updated_at"
    assert "version" not in data, "FeedCall must not carry version"
    assert isinstance(data["pen_id"], str) and data["pen_id"]
    assert isinstance(data["call_date"], str)
    assert isinstance(data["ration_id"], str) and data["ration_id"]
    assert isinstance(data["qty_lbs_per_head"], (int, float))
    assert isinstance(data["total_qty_lbs"], int)
    assert isinstance(data["total_cost_cents"], int)


def assert_health_event(data: dict):
    _assert_common_fields(data, "HealthEvent")
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["treatment_date"], str)
    assert isinstance(data["drug_product"], str) and data["drug_product"]
    assert isinstance(data["withdrawal_days"], int) and data["withdrawal_days"] >= 0
    assert isinstance(data["head_treated"], int) and data["head_treated"] >= 1
    assert isinstance(data["treatment_cost_cents"], int)
    assert data["treatment_cost_cents"] >= 0
    assert isinstance(data["withdrawal_end_date"], str)
    assert data["status"] in ("WITHDRAWAL_ACTIVE", "CLEARED")


def assert_death_loss(data: dict):
    _assert_common_fields(data, "DeathLoss")
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["loss_date"], str)
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert isinstance(data["cause"], str) and data["cause"]
    assert isinstance(data["insured"], bool)
    assert isinstance(data["loss_value_cents"], int)
    assert isinstance(data["allocations"], list)
    for alloc in data["allocations"]:
        assert isinstance(alloc["assignment_id"], str)
        assert isinstance(alloc["head_count"], int)
    assert data["status"] in ("RECORDED", "VOIDED")


def assert_insurance_claim(data: dict):
    _assert_common_fields(data, "InsuranceClaim")
    assert isinstance(data["death_loss_id"], str) and data["death_loss_id"]
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0
    assert (data["approved_amount_cents"] is None
            or isinstance(data["approved_amount_cents"], int))
    assert data["status"] in ("UNDER_REVIEW", "APPROVED", "DENIED", "PAID")
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_hedge_position(data: dict):
    _assert_common_fields(data, "HedgePosition")
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["contract_month"], str)
    assert data["side"] in ("SHORT", "LONG")
    assert isinstance(data["quantity_contracts"], int)
    assert data["quantity_contracts"] >= 1
    assert isinstance(data["entry_price_cents_per_cwt"], int)
    assert data["entry_price_cents_per_cwt"] > 0
    assert (data["exit_price_cents_per_cwt"] is None
            or isinstance(data["exit_price_cents_per_cwt"], int))
    assert (data["realized_pnl_cents"] is None
            or isinstance(data["realized_pnl_cents"], int))
    assert data["status"] in ("OPEN", "OFFSET", "EXPIRED")


def assert_close_out(data: dict):
    _assert_common_fields(data, "CloseOut")
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert data["pricing_basis"] in ("PER_CARCASS", "LOT_AVERAGE")
    assert isinstance(data["grid_base_price_cents_per_cwt"], int)
    assert data["grid_base_price_cents_per_cwt"] > 0
    assert data["carcass_records"] is None or isinstance(data["carcass_records"], list)
    assert data["status"] in ("DRAFT", "CONFIRMED", "SUPERSEDED")


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    for line in ("feed_cents", "yardage_cents", "health_cents",
                 "death_loss_cents", "insurance_credit_cents", "total_cents",
                 "amount_paid_cents"):
        assert isinstance(data[line], int), f"Invoice.{line} must be an integer"
    assert isinstance(data["yardage_head_days"], int)
    assert data["status"] in ("OPEN", "PAID", "VOID")

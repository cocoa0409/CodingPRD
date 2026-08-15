"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every resource carries id (UUID) + created_at, and (except Payment)
    updated_at + integer version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["prepaid_balance_cents"], int)
    assert data["priority_class"] in ("STANDARD", "PRIORITY_CONTRACT")
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")


def assert_grain_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["commodity"] in ("CORN", "SOYBEAN", "WHEAT")
    assert isinstance(data["gross_weight_lbs"], int)
    assert isinstance(data["tare_weight_lbs"], int)
    assert isinstance(data["wet_net_weight_lbs"], int)
    assert data["wet_net_weight_lbs"] == data["gross_weight_lbs"] - data["tare_weight_lbs"]
    assert isinstance(data["target_moisture_pct"], (int, float))
    assert data["status"] in (
        "RECEIVED", "TESTED", "QUEUED", "DRYING", "DRIED",
        "DAMAGE_HOLD", "STORED", "LOADED_OUT", "BLENDED_OUT",
    )
    assert data["ownership"] in ("GROWER_HELD", "ELEVATOR_HELD")


def assert_moisture_test(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["sample_moisture_pct"], (int, float))
    assert 0 < data["sample_moisture_pct"] < 60
    assert data["method"] in ("PROBE", "OVEN_REFERENCE")
    assert data["status"] in ("PRELIMINARY", "CERTIFIED", "DISPUTED", "SUPERSEDED")
    assert isinstance(data["tested_by_user_id"], str)


def assert_charge_schedule(data: dict):
    _assert_common_fields(data)
    assert data["commodity"] in ("CORN", "SOYBEAN", "WHEAT")
    for field in (
        "t1_max_moisture_pct", "t2_max_moisture_pct", "fm_threshold_pct",
        "fm_surcharge_pct", "energy_t1_limit_therms", "est_therms_per_hour",
        "est_point_factor",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    for field in (
        "rate_t1_cents_per_pt_bu", "rate_t2_cents_per_pt_bu",
        "rate_t3_cents_per_pt_bu", "min_charge_cents",
        "energy_t1_rate_cents_per_therm", "energy_t2_rate_cents_per_therm",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)


def assert_dryer_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_code"], str) and len(data["unit_code"]) > 0
    for field in (
        "daily_capacity_bushels", "standard_class_cap_bushels",
        "throughput_bu_per_hour", "cooldown_minutes",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_queue_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["window_date"], str)
    assert isinstance(data["requested_bushels"], int) and data["requested_bushels"] > 0
    assert data["priority_class"] in ("STANDARD", "PRIORITY_CONTRACT")
    assert data["status"] in (
        "PENDING", "CONFIRMED", "PREEMPTED", "CONSUMED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["preemption_count"], int)


def assert_dryer_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("queue_ticket_id", ""))
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED", "CANCELLED")


def assert_blend_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("high_moisture_lot_id", ""))
    assert is_valid_uuid(data.get("low_moisture_lot_id", ""))
    assert isinstance(data["target_moisture_pct"], (int, float))
    assert data["status"] in ("DRAFT", "APPROVED", "EXECUTED", "CANCELLED")
    assert isinstance(data["created_by_user_id"], str)


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("dryer_run_id", ""))
    assert data["damage_type"] in (
        "HEAT_DAMAGE", "STRESS_CRACKING", "MOLD_CONTAMINATION", "EXCESS_SHRINK",
    )
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "ASSESSED", "DENIED", "APPEALED", "PAID", "WITHDRAWN",
    )
    assert isinstance(data["filed_by_user_id"], str)


def assert_storage_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["daily_rate_cents_per_bu"], (int, float))
    assert isinstance(data["min_days"], int)
    assert data["status"] in ("RESERVED", "ACTIVE", "CLOSED", "DEFAULTED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert line["line_type"] in ("DRYING", "ENERGY", "STORAGE")
        assert isinstance(line["ref_id"], str)
        assert isinstance(line["amount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")


def assert_payment(data: dict):
    """Payment is an immutable ledger entry: id + created_at only from the
    common set; updated_at and version are absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["direction"] in ("APPLICATION", "REVERSAL")


def assert_invoice_balances(invoice: dict):
    """Domain invariant: amount_due never exceeds total, never negative."""
    assert 0 <= invoice["amount_due_cents"] <= invoice["total_cents"]


def assert_customer_ledger_invariants(customer: dict):
    """Domain invariant: prepaid balance is never negative."""
    assert customer["prepaid_balance_cents"] >= 0
    assert customer["credit_limit_cents"] >= 0

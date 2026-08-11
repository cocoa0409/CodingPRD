"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4 common fields carried by every primary resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_number(value, name):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{name} must be numeric, got {value!r}"
    )


def assert_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["base_price_cents_per_ton"], int)
    assert data["status"] in ("OPEN", "CLOSED", "SETTLING", "SETTLED")


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["member_code"], str) and data["member_code"]
    _assert_number(data["haul_distance_miles"], "haul_distance_miles")
    assert data["haul_distance_miles"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["net_ledger_cents"], int)
    _assert_number(data["deterioration_loss_lbs"], "deterioration_loss_lbs")


def assert_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    _assert_number(data["booking_capacity_tons"], "booking_capacity_tons")
    assert data["booking_capacity_tons"] > 0
    for field in ("booked_tons", "received_tons", "stored_tons"):
        _assert_number(data[field], field)
        assert data[field] >= 0


def assert_pile(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    _assert_number(data["capacity_tons"], "capacity_tons")
    assert data["capacity_tons"] > 0
    assert data["fill_status"] in ("FILLING", "SEALED", "RECLAIMING", "EMPTY")
    assert data["condition_status"] in ("SOUND", "DETERIORATING", "LOSS_DECLARED")
    _assert_number(data["stored_lbs"], "stored_lbs")
    _assert_number(data["sealed_stored_lbs"], "sealed_stored_lbs")
    assert data["sealed_at"] is None or is_iso8601_timestamp(data["sealed_at"])
    assert data["reclaim_started_at"] is None or is_iso8601_timestamp(data["reclaim_started_at"])


def assert_booking(data: dict):
    _assert_common_fields(data)
    for field in ("member_id", "station_id", "campaign_id"):
        assert is_valid_uuid(data[field]), f"{field} must be a valid UUID"
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])
    _assert_number(data["estimated_tons"], "estimated_tons")
    assert data["estimated_tons"] > 0
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "WAITLISTED", "IN_USE", "COMPLETED", "CANCELLED",
    )


def assert_ticket(data: dict):
    _assert_common_fields(data)
    for field in ("booking_id", "member_id", "station_id"):
        assert is_valid_uuid(data[field]), f"{field} must be a valid UUID"
    assert data["status"] in (
        "CREATED", "WEIGHED", "REWEIGHING", "SAMPLED",
        "ACCEPTED", "CREDITED", "REJECTED", "VOIDED",
    )
    for field in ("gross_weight_lbs", "tare_weight_lbs", "net_weight_lbs",
                  "provisional_trash_pct", "provisional_sugar_pct",
                  "provisional_factor", "provisional_adjusted_net_tons",
                  "final_trash_pct", "final_sugar_pct", "final_factor",
                  "adjusted_net_tons_final", "adjusted_net_lbs_final"):
        assert data[field] is None or isinstance(data[field], (int, float)), field
    assert data["provisional_value_cents"] is None or isinstance(
        data["provisional_value_cents"], int)


def assert_sample(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["ticket_id"])
    assert data["sample_type"] in ("STATION_QUICK", "LAB_VERIFY")
    assert data["status"] in ("COLLECTED", "RESULT_RECORDED", "VERIFIED")
    assert data["sugar_pct"] is None or isinstance(data["sugar_pct"], (int, float))
    assert data["trash_pct"] is None or isinstance(data["trash_pct"], (int, float))
    assert data["recorded_by_user_id"] is None or isinstance(data["recorded_by_user_id"], str)


def assert_pile_allocation(data: dict):
    _assert_common_fields(data)
    for field in ("ticket_id", "pile_id", "member_id"):
        assert is_valid_uuid(data[field]), f"{field} must be a valid UUID"
    _assert_number(data["allocated_lbs"], "allocated_lbs")
    _assert_number(data["remaining_lbs"], "remaining_lbs")
    assert data["status"] in ("ACTIVE", "DEPLETED")


def assert_loss_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["pile_id"])
    assert data["method"] in ("TABLE_RATE", "RESURVEY")
    assert is_iso8601_timestamp(data["survey_at"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("DRAFT", "CONFIRMED", "ALLOCATED")
    for field in ("measured_remaining_lbs", "loss_lbs", "unallocated_lbs"):
        assert data[field] is None or isinstance(data[field], (int, float)), field


def assert_pool(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["campaign_id"])
    assert data["status"] in ("OPEN", "ACCRUING", "CLOSED", "SETTLED")
    assert isinstance(data["accrued_provisional_cents"], int)
    for field in ("estimated_pool_value_cents", "gross_pool_value_cents"):
        assert data[field] is None or isinstance(data[field], int), field
    assert data["final_price_cents_per_lb"] is None or isinstance(
        data["final_price_cents_per_lb"], (int, float))


def assert_installment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["pool_id"])
    _assert_number(data["pct_of_estimated"], "pct_of_estimated")
    assert isinstance(data["target_amount_cents"], int)
    assert isinstance(data["distributed_amount_cents"], int)
    assert data["status"] in ("SCHEDULED", "ISSUED")


def assert_ledger_entry(data: dict):
    """PRD §2.4: a ledger entry carries only id and created_at as common fields;
    updated_at and version are absent (append-only event log)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["pool_id"])
    assert data["kind"] in ("ADVANCE_CREDIT", "FINAL_SETTLEMENT", "TRANSPORT_CREDIT", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert data["installment_id"] is None or is_valid_uuid(data["installment_id"])
    assert data["settlement_id"] is None or is_valid_uuid(data["settlement_id"])
    assert data["reversal_of_id"] is None or is_valid_uuid(data["reversal_of_id"])


def assert_settlement(data: dict):
    _assert_common_fields(data)
    for field in ("member_id", "campaign_id", "pool_id"):
        assert is_valid_uuid(data[field]), f"{field} must be a valid UUID"
    _assert_number(data["sugar_lbs"], "sugar_lbs")
    _assert_number(data["price_cents_per_lb"], "price_cents_per_lb")
    for field in ("gross_entitlement_cents", "advances_posted_cents",
                  "transport_credit_cents", "final_payment_cents", "total_payment_cents"):
        assert isinstance(data[field], int), field
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "ACKNOWLEDGED", "PAID")


def assert_station_tonnage_invariants(station: dict):
    """PRD §2.8 derived aggregates are never negative and booked tonnage never
    exceeds the station's booking capacity."""
    assert station["booked_tons"] >= 0
    assert station["received_tons"] >= 0
    assert station["stored_tons"] >= 0
    assert station["booked_tons"] <= station["booking_capacity_tons"] + 1e-9

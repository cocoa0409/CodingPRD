"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CampaignStatus,
    CartStatus,
    ClaimStatus,
    CreditStatus,
    DeliveryStatus,
    FacilityStatus,
    GivebackEventStatus,
    InspectionResult,
    RouteStatus,
    ServiceModel,
    SubscriptionStatus,
    SurgeBookingStatus,
    SurgeEventStatus,
    TicketStatus,
    Weekday,
    ZoneStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def _assert_evidentiary_fields(data: dict):
    """Inspections and credits carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_service_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["service_model"] in {m.value for m in ServiceModel}
    assert isinstance(data["season_start_date"], str)
    assert isinstance(data["season_end_date"], str)
    assert isinstance(data["base_seasonal_fee_cents"], int)
    assert isinstance(data["universal_flat_credit_cents"], int)
    assert isinstance(data["max_strikes_per_season"], int)
    assert data["status"] in {s.value for s in ZoneStatus}


def assert_household(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert is_valid_uuid(data.get("zone_id", ""))
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["compost_entitlement_gallons"], (int, float))


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("household_id", ""))
    assert isinstance(data["season_year"], int)
    assert data["service_model"] in {m.value for m in ServiceModel}
    assert data["status"] in {s.value for s in SubscriptionStatus}
    for field in ("base_fee_cents", "cart_fees_cents", "surcharge_cents", "total_due_cents", "paid_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["strikes_this_season"], int)
    assert data.get("suspended_reason") in (None, "CONTAMINATION_STRIKES")


def assert_cart(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("household_id", ""))
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert data["size_gallons"] in (35, 64, 96)
    assert data["status"] in {s.value for s in CartStatus}
    assert isinstance(data["surcharge_cents"], int)


def assert_collection_route(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", ""))
    assert data["weekday"] in {d.value for d in Weekday}
    assert isinstance(data["max_stops"], int)
    assert isinstance(data["max_tonnage_lbs"], int)
    assert data["status"] in {s.value for s in RouteStatus}


def assert_pickup_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data["service_date"], str)
    assert data["status"] in {s.value for s in TicketStatus}


def assert_contamination_inspection(data: dict):
    _assert_evidentiary_fields(data)
    assert "updated_at" not in data, "inspections are immutable records without updated_at"
    assert "version" not in data, "inspections are immutable records without version"
    assert is_valid_uuid(data.get("pickup_ticket_id", ""))
    assert data["result"] in {r.value for r in InspectionResult}
    assert isinstance(data["violation_codes"], list)
    assert isinstance(data.get("inspector_user_id"), str)


def assert_surge_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", ""))
    assert data["event_type"] in ("LEAF_SURGE", "HOLIDAY_TREE")
    assert isinstance(data["capacity_slots"], int)
    assert isinstance(data["reserved_slots"], int)
    assert data["status"] in {s.value for s in SurgeEventStatus}
    assert_surge_event_slot_invariant(data)


def assert_surge_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("surge_event_id", ""))
    assert is_valid_uuid(data.get("household_id", ""))
    assert isinstance(data["quantity_bundles"], int)
    assert data["status"] in {s.value for s in SurgeBookingStatus}


def assert_processing_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["daily_receiving_capacity_lbs"], int)
    assert isinstance(data["safety_contamination_item_limit"], int)
    assert data["status"] in {s.value for s in FacilityStatus}
    assert isinstance(data["season_accepted_lbs"], int)


def assert_facility_delivery(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data["delivery_date"], str)
    assert data["status"] in {s.value for s in DeliveryStatus}
    assert isinstance(data["accepted_weight_lbs"], int)


def assert_compost_giveback_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", ""))
    assert isinstance(data["event_date"], str)
    assert isinstance(data["per_household_cap_gallons"], int)
    assert isinstance(data["initial_inventory_gallons"], int)
    assert isinstance(data["remaining_gallons"], int)
    assert data["status"] in {s.value for s in GivebackEventStatus}
    assert 0 <= data["remaining_gallons"] <= data["initial_inventory_gallons"]


def assert_compost_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("giveback_event_id", ""))
    assert is_valid_uuid(data.get("household_id", ""))
    assert isinstance(data["gallons"], int) and data["gallons"] >= 1
    assert data["status"] in {s.value for s in ClaimStatus}


def assert_service_credit(data: dict):
    _assert_evidentiary_fields(data)
    assert "updated_at" not in data, "credits are immutable records without updated_at"
    assert "version" not in data, "credits are immutable records without version"
    assert is_valid_uuid(data.get("household_id", ""))
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("missed_pickup_ticket_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {s.value for s in CreditStatus}


def assert_outreach_campaign(data: dict):
    _assert_common_fields(data)
    assert data["channel"] in ("MAIL", "DOOR_TAG", "EMAIL", "SOCIAL")
    assert data["topic"] in ("ACCEPTABLE_MATERIALS", "SEASON_START", "CONTAMINATION_PREVENTION", "COMPOST_GIVEBACK")
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["audience_size"], int)
    assert isinstance(data["cost_per_impression_cents"], int)
    assert data["status"] in {s.value for s in CampaignStatus}


# --- Domain invariants ---

def assert_surge_event_slot_invariant(data: dict):
    """reserved_slots never exceeds capacity_slots and is never negative."""
    assert 0 <= data["reserved_slots"] <= data["capacity_slots"]


def assert_subscription_money_invariants(data: dict):
    """total_due_cents is always the sum of its three components."""
    assert data["total_due_cents"] == (
        data["base_fee_cents"] + data["cart_fees_cents"] + data["surcharge_cents"]
    ), "total_due_cents must equal base + cart fees + surcharge"
    assert data["paid_cents"] >= 0

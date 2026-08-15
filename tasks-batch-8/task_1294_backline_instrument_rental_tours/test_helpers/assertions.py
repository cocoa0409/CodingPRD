"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict, context: str):
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{context}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{context}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{context}: version must be an integer"


def assert_artist(data: dict):
    _assert_common(data, "Artist")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["tier"] in ["STANDARD", "PREMIUM", "PLATINUM"]
    assert isinstance(data["deposit_credit_cents"], int)
    assert isinstance(data["deposit_waived"], bool)
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100


def assert_tour(data: dict):
    _assert_common(data, "Tour")
    assert data["status"] in ["DRAFT", "ACTIVE", "COMPLETED", "CANCELLED"]
    assert isinstance(data["name"], str)
    assert isinstance(data["stop_count"], int)


def assert_tour_stop(data: dict):
    _assert_common(data, "TourStop")
    assert data["status"] in ["PLANNED", "GEAR_STAGED", "SHOW_READY", "LOADED_OUT", "SETTLED", "CANCELLED"]
    assert isinstance(data["rider_revision"], int)


def assert_rider_line(data: dict):
    _assert_common(data, "RiderLine")
    assert data["status"] in ["REQUESTED", "SOURCED", "SUBSTITUTION_PENDING", "APPROVED",
                              "FULFILLED", "SHORTED", "CANCELLED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_gear_model(data: dict):
    _assert_common(data, "GearModel")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ["GUITAR", "BASS", "DRUMS", "KEYS", "AMP", "PA", "BACKLINE_MISC"]
    assert data["weight_class"] in ["HAND_CARRY", "STANDARD", "HEAVY", "OVERSIZE"]
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["replacement_value_cents"], int)


def assert_gear_unit(data: dict):
    _assert_common(data, "GearUnit")
    assert data["status"] in ["AVAILABLE", "RESERVED", "OUT_ON_RENTAL", "IN_TRANSIT",
                              "MAINTENANCE", "QUARANTINED", "RETIRED"]
    assert isinstance(data["condition_score"], int)
    assert 0 <= data["condition_score"] <= 100
    assert isinstance(data["rental_days_since_service"], int)
    assert isinstance(data["flight_case_required"], bool)


def assert_reservation_line(data: dict):
    _assert_common(data, "ReservationLine")
    assert data["status"] in ["DRAFT", "SOURCED", "DISPATCHED", "DELIVERED", "RETURNED",
                              "INSPECTED", "SETTLED", "CANCELLED"]
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert isinstance(data["is_cross_rental"], bool)


def assert_shipment(data: dict):
    _assert_common(data, "Shipment")
    assert data["status"] in ["PLANNED", "LOADING", "IN_TRANSIT", "DELIVERED", "CLOSED", "CANCELLED"]
    assert isinstance(data["capacity_kg"], int)
    assert isinstance(data["booked_weight_kg"], int)
    assert isinstance(data["tech_labor_minutes"], int)


def assert_shipment_line(data: dict):
    _assert_common(data, "ShipmentLine")
    assert data["status"] in ["BOOKED", "LOADED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["weight_kg"], int)
    assert isinstance(data["labor_minutes"], int)


def assert_flight_case(data: dict):
    _assert_common(data, "FlightCase")
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "IN_TRANSIT", "MAINTENANCE", "RETIRED"]
    assert data["size_class"] in ["SMALL", "MEDIUM", "LARGE", "TRUNK"]


def assert_partner_vendor(data: dict):
    _assert_common(data, "PartnerVendor")
    assert data["status"] in ["PENDING", "APPROVED", "SUSPENDED"]
    assert isinstance(data["commission_bps"], int)
    assert 0 <= data["commission_bps"] <= 3000
    assert isinstance(data["city_codes"], list)


def assert_cross_rental_request(data: dict):
    _assert_common(data, "CrossRentalRequest")
    assert data["status"] in ["REQUESTED", "ACCEPTED", "REJECTED", "FULFILLED", "SETTLED", "CANCELLED"]
    assert isinstance(data["vendor_rate_cents_per_day"], int)


def assert_maintenance_ticket(data: dict):
    _assert_common(data, "MaintenanceTicket")
    assert data["status"] in ["OPEN", "IN_PROGRESS", "AWAITING_PARTS", "COMPLETED", "CANCELLED"]
    assert data["opened_reason"] in ["SCHEDULED_CYCLE", "DAMAGE_REPAIR",
                                     "CONDITION_THRESHOLD", "POST_FLIGHT_INSPECTION"]


def assert_damage_claim(data: dict):
    _assert_common(data, "DamageClaim")
    assert data["status"] in ["FILED", "ASSESSED", "CHARGED", "DISPUTED", "WAIVED", "PAID"]
    assert data["assessed_severity"] in ["COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS"]
    assert isinstance(data["repair_estimate_cents"], int)
    assert isinstance(data["filed_by_user_id"], str)


def assert_deposit_invariant(artist_balance: int, held_sum: int, conserved_total: int):
    """Domain invariant: artist balance plus deposits held on non-terminal
    reservations stays constant across source/cancel pairs."""
    assert artist_balance + held_sum == conserved_total, (
        f"deposit invariant violated: balance {artist_balance} + held {held_sum} "
        f"!= conserved {conserved_total}"
    )

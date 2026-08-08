"""Drop-off chain of custody and the booking transitions around it: location-open
dependency, seal uniqueness, tamper detection, and invalid transitions.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, seal_entry,
    setup_reserved_booking, setup_stored_booking,
)


# --- Drop-off requires the referenced location to be OPEN ----------------------

def test_dropoff_on_suspended_location_rejected(api):
    """PRD §3.4: "if the location is no longer `OPEN` the drop-off is rejected with
    `ERR_LOCATION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/dropoff_requires_location_open
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-13")
    get_success_data(api.set_location_status(
        ctx["location"]["id"], {"to_status": "SUSPENDED"}, ctx["host_headers"]))
    seals = [seal_entry(bags[0]["id"], "K0")]
    resp = api.dropoff_booking(booking["id"], {"seals": seals}, ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_LOCATION_NOT_OPEN.value)


def test_dropoff_on_suspended_location_leaves_booking_reserved(api):
    """PRD §3.4: "When the traveler arrives, the host that owns the booking's location
    receives the bags, transitioning the booking `RESERVED → STORED`."
    PRD §3.4: "if the location is no longer `OPEN` the drop-off is rejected with
    `ERR_LOCATION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/dropoff_requires_location_open
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-13")
    get_success_data(api.set_location_status(
        ctx["location"]["id"], {"to_status": "SUSPENDED"}, ctx["host_headers"]))
    api.dropoff_booking(booking["id"], {"seals": [seal_entry(bags[0]["id"], "K0")]}, ctx["host_headers"])
    after = get_success_data(api.get_booking(booking["id"], ctx["host_headers"]))
    assert after["status"] == "RESERVED"


# --- Seal uniqueness and tamper detection -------------------------------------

def test_dropoff_duplicate_seal_returns_error(api):
    """PRD §3.4: "No supplied `seal_code` may duplicate the seal of another already-sealed
    bag at the same location; a collision is rejected with `ERR_DUPLICATE_SEAL`."

    Design: Corner/validations/dropoff_duplicate_seal_returns_error
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100},
              {"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-11")
    seals = [seal_entry(bags[0]["id"], "DUP"), seal_entry(bags[1]["id"], "DUP")]
    resp = api.dropoff_booking(booking["id"], {"seals": seals}, ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEAL.value)


def test_pickup_seal_tamper_returns_error(api):
    """PRD §3.6: "when supplied, every presented `seal_code` must match the value recorded
    for that bag at drop-off, and any mismatch is rejected with `ERR_SEAL_TAMPERED`."

    Design: Corner/validations/pickup_seal_tamper_returns_error
    """
    ctx, booking, bags = setup_stored_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        seal_codes=["GOOD"], check_in_date="2026-06-10", check_out_date="2026-06-11")
    resp = api.pickup_booking(
        booking["id"], {"presented_seals": [{"bag_id": bags[0]["id"], "seal_code": "TAMPERED"}]},
        ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_SEAL_TAMPERED.value)
    after = get_success_data(api.get_booking(booking["id"], ctx["host_headers"]))
    assert after["status"] == "STORED"


# --- Invalid booking transitions ----------------------------------------------

def test_cancel_after_dropoff_returns_cancel_not_allowed(api):
    """PRD §3.3: "an attempt to cancel a booking that has already been dropped off or has
    reached a terminal state is rejected with `ERR_CANCEL_NOT_ALLOWED`."

    Design: Corner/state_machines/cancel_after_dropoff_returns_cancel_not_allowed
    """
    ctx, booking, bags = setup_stored_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-12")
    resp = api.cancel_booking(booking["id"], ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_CANCEL_NOT_ALLOWED.value)


def test_pickup_from_reserved_returns_invalid_state(api):
    """PRD §3.6: "The owning host returns the bags at pickup, transitioning the booking to
    `COMPLETED` from either `STORED` or `OVERDUE`."
    PRD §2.8: "the resource, and any referenced location, is in a state that permits the
    operation (`ERR_INVALID_STATE`, `ERR_LOCATION_NOT_OPEN`, `ERR_CANCEL_NOT_ALLOWED`,
    `ERR_HOST_SUSPENDED`, `ERR_LOCATION_HAS_ACTIVE_BOOKINGS`)."

    Design: Corner/state_machines/pickup_from_reserved_returns_invalid_state
    """
    ctx, booking, bags = setup_reserved_booking(
        api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0,
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
        check_in_date="2026-06-10", check_out_date="2026-06-12")
    resp = api.pickup_booking(booking["id"], {}, ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

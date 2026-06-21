"""State-machine branching and transitive-cascade tests across Reservation,
GarmentUnit, PartyOrder, and Catalog."""
from test_helpers import (
    validate_success,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_picked_up_reservation, return_reservation,
    create_party, make_customer_headers,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import create_reservation_payload

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}
ONTIME_RESV = {
    "event_date_iso": "2026-09-04T00:00:00Z",
    "pickup_window_start_iso": "2026-09-01T09:00:00Z",
    "return_window_end_iso": "2026-09-03T17:00:00Z",
}


def test_on_time_return_routes_returned_no_late_fee(api):
    """PRD §3.7: "If the `returned_at_iso` is on or before the reservation's `return_window_end_iso`, the reservation follows the on-time branch from `PICKED_UP` to `RETURNED`."
    PRD §3.7: "on the on-time branch `late_days` is forced to 0."

    Design: Difficulty/non_linear_state_machine/reservation_branching_fork_join_pickedup_to_returned_or_overdue
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux E2"}, reservation_overrides=ONTIME_RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "CLEAN")

    assert settlement["late_days"] == 0
    assert settlement["late_fee_cents"] == 0
    after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert after["status"] == "RETURNED", "on-time branch goes to RETURNED, not OVERDUE"


def test_confirm_reserves_unit(api):
    """PRD §3.4: "The chosen unit is pinned to the reservation by writing its identifier into `garment_unit_id`, and that unit transitions from `AVAILABLE` to `RESERVED`."

    Design: Difficulty/non_linear_state_machine/garment_unit_cyclic_available_reserved_available
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux F"})
    unit = create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")
    validate_success(confirm(resv["id"]), 200)

    after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert after["status"] == "RESERVED", "confirm reserves the unit"


def test_cancel_confirmed_releases_unit_back_to_available(api):
    """PRD §3.9: "on success the allocated unit is released from `RESERVED` back to `AVAILABLE`, any `REQUESTED` alteration on the reservation is moved to `CANCELLED".

    Design: Difficulty/non_linear_state_machine/garment_unit_cyclic_available_reserved_available
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux F2"})
    unit = create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M")
    validate_success(confirm(resv["id"]), 200)

    cancelled = validate_success(api_client.cancel_reservation(resv["id"], CLERK), 200)
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert after["status"] == "AVAILABLE", "cancel cycles the unit back to AVAILABLE"


def test_party_dissolve_cascades_member_cancel_then_unit_release(api):
    """PRD §3.9: "Dissolving moves the `posture` from `FORMING` to the terminal `DISSOLVED` and cascades over the membership: every `PENDING` member reservation is cancelled, and each member that was `CONFIRMED` releases its allocated unit from `RESERVED` back to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/party_dissolve_cascades_member_cancel_then_unit_release
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux G"})
    unit = create_unit(catalog["id"], "M")
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])
    # required 2 so the party stays FORMING after the single confirm (dissolve allowed).
    party = create_party(coordinator["id"], required_member_count=2,
                         event_date_iso="2026-09-06T00:00:00Z")
    resv = validate_success(api_client.create_reservation(
        create_reservation_payload(coordinator["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-06T00:00:00Z",
                                   party_order_id=party["id"]),
        coord_headers), 201)
    validate_success(confirm(resv["id"], expected_party_order_version=party["version"]), 200)

    dissolved = validate_success(api_client.dissolve_party_order(party["id"], coord_headers), 200)
    assert dissolved["posture"] == "DISSOLVED"

    resv_after = validate_success(api_client.get_reservation(resv["id"], CLERK), 200)
    assert resv_after["status"] == "CANCELLED", "hop 2: member cancelled by dissolve"
    unit_after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert unit_after["status"] == "AVAILABLE", "hop 3: unit released by the member cancellation"


def test_lost_return_cascades_unit_retire_then_catalog_recount(api):
    """PRD §3.7: "the unit is automatically retired — carried to `RETIRED` — when its `damage_strike_count` reaches 2 or more, or whenever the disposition was `LOST`."
    PRD §3.7: "A unit auto-retired in this way has its owning catalog's `active_unit_count` recomputed downward."

    Design: Difficulty/transitive_cascade/lost_return_cascades_unit_retire_then_catalog_recount
    """
    catalog, unit, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux H"}, reservation_overrides=ONTIME_RESV)
    return_reservation(resv["id"], "2026-09-03T12:00:00Z", "LOST")

    unit_after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert unit_after["status"] == "RETIRED", "hop 1: LOST -> retire"
    catalog_after = validate_success(api_client.get_catalog(catalog["id"], CLERK), 200)
    assert catalog_after["active_unit_count"] == 0, "hop 2: recount after retire (was 1)"

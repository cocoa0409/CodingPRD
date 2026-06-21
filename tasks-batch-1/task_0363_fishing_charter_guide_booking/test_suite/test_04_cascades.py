"""Transitive cascade chains: a charter cancel rippling Charter -> Booking ->
AddOnLine, and a sail rippling Charter -> NO_SHOW booking -> AddOnLine void.
Covers the difficulty-design transitive-cascade instances rooted in §3.8 of the
PRD.
"""
from test_helpers import (
    validate_success,
    make_captain_headers,
    pin_clock,
    create_marina,
    create_dock_slot,
    create_boat,
    create_captain,
    create_customer,
    create_charter,
    create_booking,
    pay_deposit,
    add_on_line,
    reserve_slot,
    assign_captain,
    current_charter_version,
    api_client,
)
from test_helpers.fixtures import FLEET_MANAGER


# ===========================================================================
# Difficulty: transitive_cascade / charter_cancel_to_booking_cancel_to_addon_void
# ===========================================================================

def _scheduled_charter_with_confirmed_booking_and_addon(name):
    pin_clock("2026-10-01T00:00:00Z")
    marina = create_marina(name=name)
    slot = create_dock_slot(marina["id"], slot_label="E1")
    boat = create_boat(marina["id"], name=name + "boat")
    captain = create_captain(marina["id"])
    customer = create_customer()
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2026-10-10T12:00:00Z",
                             return_at="2026-10-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=2)
    pay_deposit(booking["id"], customer["id"], 5000)
    line = add_on_line(booking["id"], customer["id"], "COOLER_ICE", 2)
    api_client.schedule_charter(charter["id"], FLEET_MANAGER)
    return charter["id"], booking["id"], line["id"]


def test_charter_cancel_cascades_booking_to_cancelled(api):
    """PRD §3.8: "Cancelling cascades: every non-terminal booking is cancelled to
    `CANCELLED` with a refund computed per the cancellation rule below."

    Cancelling the charter mutates its booking to CANCELLED (hop 1 of the depth-3
    chain).

    Design: Difficulty/transitive_cascade/charter_cancel_to_booking_cancel_to_addon_void
    """
    ch_id, bk_id, line_id = _scheduled_charter_with_confirmed_booking_and_addon("Casc Marina")
    res = api.cancel_charter(ch_id, FLEET_MANAGER)
    charter = validate_success(res, expected_status=200)
    assert charter["status"] == "CANCELLED"
    booking = validate_success(api.get_booking(bk_id, FLEET_MANAGER), 200)
    assert booking["status"] == "CANCELLED", booking["status"]


def test_charter_cancel_cascades_addon_to_voided(api):
    """PRD §3.8: "every add-on line on those bookings (whether `PENDING` or
    `FULFILLED`) is voided to `VOIDED`."

    The booking's cancellation in turn voids its add-on line to VOIDED (hop 2 of
    the depth-3 chain).

    Design: Difficulty/transitive_cascade/charter_cancel_to_booking_cancel_to_addon_void
    """
    ch_id, bk_id, line_id = _scheduled_charter_with_confirmed_booking_and_addon("Casc Marina 2")
    api.cancel_charter(ch_id, FLEET_MANAGER)
    line = validate_success(api.get_add_on_line(line_id, FLEET_MANAGER), 200)
    assert line["status"] == "VOIDED", line["status"]


# ===========================================================================
# Difficulty: transitive_cascade / charter_sail_to_noshow_to_addon_void
# ===========================================================================

def _sailed_charter_with_unpaid_booking_and_addon(name):
    pin_clock("2026-10-10T11:00:00Z")
    marina = create_marina(name=name)
    slot = create_dock_slot(marina["id"], slot_label="F1")
    boat = create_boat(marina["id"], name=name + "boat")
    captain = create_captain(marina["id"])
    cust_paid = create_customer()
    cust_unpaid = create_customer()
    charter = create_charter(marina["id"], boat["id"],
                             depart_at="2026-10-10T12:00:00Z",
                             return_at="2026-10-10T16:00:00Z")
    assign_captain(charter["id"], captain["id"])
    reserve_slot(slot["id"], charter["id"])
    bk_paid = create_booking(charter["id"], cust_paid["id"], party_size=1)
    pay_deposit(bk_paid["id"], cust_paid["id"], 2500)
    bk_unpaid = create_booking(charter["id"], cust_unpaid["id"], party_size=1)
    line = add_on_line(bk_unpaid["id"], cust_unpaid["id"], "BAIT", 2)
    api_client.schedule_charter(charter["id"], FLEET_MANAGER)
    pin_clock("2026-10-10T12:00:00Z")
    api_client.sail_charter(charter["id"], make_captain_headers(captain["id"]))
    return charter["id"], bk_paid["id"], bk_unpaid["id"], line["id"]


def test_sail_drops_unpaid_reservation_to_no_show(api):
    """PRD §3.8: "every booking still in `RESERVED` whose `deposit_paid_cents` is
    0 is dropped to `NO_SHOW` ... and every booking in `RESERVED` or `CONFIRMED`
    whose `deposit_paid_cents` is greater than 0 is kept and set to `CONFIRMED`."

    The unpaid RESERVED booking becomes NO_SHOW; the paid one stays CONFIRMED.

    Design: Difficulty/transitive_cascade/charter_sail_to_noshow_to_addon_void
    """
    ch_id, bk_paid, bk_unpaid, line_id = _sailed_charter_with_unpaid_booking_and_addon("NoShow Marina")
    unpaid = validate_success(api.get_booking(bk_unpaid, FLEET_MANAGER), 200)
    paid = validate_success(api.get_booking(bk_paid, FLEET_MANAGER), 200)
    assert unpaid["status"] == "NO_SHOW", unpaid["status"]
    assert paid["status"] == "CONFIRMED", paid["status"]


def test_no_show_voids_its_addon_lines(api):
    """PRD §3.8: "A booking turning into a no-show releases its seats ... and voids
    its add-on lines to `VOIDED`."

    The NO_SHOW booking's add-on line is voided to VOIDED (the second hop driven by
    the no-show, not by the sail call directly).

    Design: Difficulty/transitive_cascade/charter_sail_to_noshow_to_addon_void
    """
    ch_id, bk_paid, bk_unpaid, line_id = _sailed_charter_with_unpaid_booking_and_addon("NoShow Marina 2")
    line = validate_success(api.get_add_on_line(line_id, FLEET_MANAGER), 200)
    assert line["status"] == "VOIDED", line["status"]

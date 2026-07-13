"""Composite setup helpers.

Each test runs against a freshly launched server (empty DB, logical clock at the
2026-05-01T00:00:00Z startup default), so every helper builds its preconditions
from scratch using only PRD-declared endpoints. Setup calls use get_success_data()
(lenient 2xx validator) so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from .factories import (
    create_member_payload, create_attraction_payload, create_prize_item_payload,
    create_party_package_payload, create_room_payload, create_game_card_payload,
    reload_payload, game_play_payload, redemption_payload,
    create_party_booking_payload, issue_wristband_payload,
    create_reconciliation_payload, count_reconciliation_payload, unique_email,
)

MANAGER = TEST_USERS["manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------------- #
# Primitives                                                                    #
# --------------------------------------------------------------------------- #
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, MANAGER))


def create_member(api, email=None, full_name="Host", promo_opt_in=None):
    payload = create_member_payload(email=email or unique_email(), full_name=full_name,
                                    promo_opt_in=promo_opt_in)
    return get_success_data(api.create_member(payload, CASHIER))


def create_attraction(api, chip_cost_cents=100, points_award=10, name="Racer"):
    return get_success_data(api.create_attraction(
        create_attraction_payload(name=name, chip_cost_cents=chip_cost_cents,
                                  points_award=points_award), MANAGER))


def create_prize(api, points_price=500, stock_qty=100, name="Teddy"):
    return get_success_data(api.create_prize_item(
        create_prize_item_payload(name=name, points_price=points_price,
                                  stock_qty=stock_qty), MANAGER))


def create_room(api, capacity=20, hourly_rate_cents=8_000, name="Room"):
    return get_success_data(api.create_room(
        create_room_payload(name=name, capacity=capacity,
                            hourly_rate_cents=hourly_rate_cents), MANAGER))


def create_package(api, base_price_cents=20_000, included_guests=10, included_hours=2,
                   included_chip_cents=1_000, tier="GOLD", combo_value_cents=3_000, name="Gold"):
    return get_success_data(api.create_party_package(
        create_party_package_payload(
            name=name, base_price_cents=base_price_cents, included_guests=included_guests,
            included_hours=included_hours, included_chip_cents=included_chip_cents,
            tier=tier, combo_value_cents=combo_value_cents), MANAGER))


def issue_card(api, owner_member_id=None):
    return get_success_data(api.create_game_card(
        create_game_card_payload(owner_member_id=owner_member_id), CASHIER))


def activate_card(api, card_id):
    return get_success_data(api.activate_game_card(card_id, CASHIER))


def reload_card(api, card_id, amount_cents):
    return get_success_data(api.reload_game_card(card_id, reload_payload(amount_cents), CASHIER))


def freeze_card(api, card_id):
    return get_success_data(api.freeze_game_card(card_id, MANAGER))


def close_card(api, card_id):
    return get_success_data(api.close_game_card(card_id, MANAGER))


def get_card(api, card_id):
    return get_success_data(api.get_game_card(card_id, CASHIER))


def get_card_ledger(api, card_id):
    return get_success_data(api.get_card_ledger(card_id, CASHIER, params={"limit": 100}))


def play(api, card_id, attraction_id, headers=None):
    return get_success_data(api.create_game_play(
        game_play_payload(card_id, attraction_id), headers or ATTENDANT))


def reserve_redemption(api, card_id, prize_id, quantity, expected_version, headers=None):
    return get_success_data(api.create_redemption(
        redemption_payload(card_id, prize_id, quantity, expected_version), headers or ATTENDANT))


def create_booking(api, room_id, package_id, host_id, start_at, end_at, guest_count):
    return get_success_data(api.create_party_booking(
        create_party_booking_payload(room_id, package_id, host_id, start_at, end_at, guest_count),
        COORDINATOR))


def confirm_booking(api, booking_id):
    return get_success_data(api.confirm_party_booking(booking_id, COORDINATOR))


def revert_booking(api, booking_id):
    return get_success_data(api.revert_party_booking(booking_id, COORDINATOR))


def check_in_booking(api, booking_id):
    return get_success_data(api.check_in_party_booking(booking_id, CASHIER))


def complete_booking(api, booking_id):
    return get_success_data(api.complete_party_booking(booking_id, COORDINATOR))


def cancel_booking(api, booking_id):
    return get_success_data(api.cancel_party_booking(booking_id, COORDINATOR))


def issue_extra_wristband(api, booking_id, expected_booking_version, card_id=None):
    return get_success_data(api.issue_wristband(
        booking_id, issue_wristband_payload(expected_booking_version, card_id), CASHIER))


def get_booking(api, booking_id):
    return get_success_data(api.get_party_booking(booking_id, COORDINATOR))


def list_booking_wristbands(api, booking_id):
    return get_success_data(api.list_wristbands(CASHIER, params={"booking_id": booking_id, "limit": 100}))


def open_reconciliation(api, business_day):
    return get_success_data(api.create_reconciliation(
        create_reconciliation_payload(business_day), MANAGER))


def count_reconciliation(api, reconciliation_id, chip_cents, prize_units):
    return get_success_data(api.count_reconciliation(
        reconciliation_id, count_reconciliation_payload(chip_cents, prize_units), MANAGER))


# --------------------------------------------------------------------------- #
# Composite: cards funded with e-ticket points                                  #
# --------------------------------------------------------------------------- #
def setup_funded_points_card(api, plays=1, points_award=1_000, chip_cost=100, member_id=None):
    """Create an ACTIVE owned card holding `points_award * plays` e-ticket points.

    Reloads only `chip_cost * plays` cents (far below the 50,000-cent SILVER
    threshold), so the owner stays tier NONE and the gameplay multiplier is 1.0 —
    each play therefore awards exactly `points_award` points. Returns a dict with
    card_id, attraction_id, member_id, version (card version after the plays), and
    points (total accrued).
    """
    attraction = create_attraction(api, chip_cost_cents=chip_cost, points_award=points_award)
    if member_id is None:
        member_id = create_member(api)["id"]
    card = activate_card(api, issue_card(api, owner_member_id=member_id)["id"])
    reload_card(api, card["id"], chip_cost * plays)
    for _ in range(plays):
        play(api, card["id"], attraction["id"])
    card = get_card(api, card["id"])
    return {
        "card_id": card["id"],
        "attraction_id": attraction["id"],
        "member_id": member_id,
        "version": card["version"],
        "points": points_award * plays,
    }


def setup_reserved_redemption(api, prize_price=500, stock_qty=100, quantity=2, plays=2,
                              points_award=1_000):
    """A card funded via `plays` plays holding one RESERVED redemption of `quantity`
    units against a prize priced `prize_price`. Returns card_id, prize_id,
    redemption_id, attraction_id, member_id, and points_hold."""
    prize = create_prize(api, points_price=prize_price, stock_qty=stock_qty)
    funded = setup_funded_points_card(api, plays=plays, points_award=points_award)
    redemption = reserve_redemption(api, funded["card_id"], prize["id"], quantity, funded["version"])
    return {
        "card_id": funded["card_id"],
        "prize_id": prize["id"],
        "redemption_id": redemption["id"],
        "attraction_id": funded["attraction_id"],
        "member_id": funded["member_id"],
        "points_hold": redemption["points_hold"],
    }


# --------------------------------------------------------------------------- #
# Composite: party bookings                                                     #
# --------------------------------------------------------------------------- #
def setup_confirmed_booking(api, guest_count=2, capacity=20, hourly_rate_cents=8_000,
                            included_chip_cents=1_000, included_guests=10, included_hours=2,
                            base_price_cents=20_000, start_at="2026-05-01T14:00:00Z",
                            end_at="2026-05-01T16:00:00Z", clock="2026-05-01T10:00:00Z",
                            room_name="Room"):
    """Active room + package + host + a CONFIRMED booking (confirm cascade fired:
    `guest_count` ISSUED wristbands, each linked to a fresh ACTIVE card granted
    `included_chip_cents` bonus). Returns a dict: room, package, host, booking
    (post-confirm), wristbands, card_ids."""
    if clock:
        set_clock(api, clock)
    room = create_room(api, capacity=capacity, hourly_rate_cents=hourly_rate_cents, name=room_name)
    package = create_package(api, base_price_cents=base_price_cents, included_guests=included_guests,
                             included_hours=included_hours, included_chip_cents=included_chip_cents)
    host = create_member(api)
    booking = create_booking(api, room["id"], package["id"], host["id"], start_at, end_at, guest_count)
    confirm_booking(api, booking["id"])
    booking = get_booking(api, booking["id"])
    wristbands = list_booking_wristbands(api, booking["id"])
    return {
        "room": room,
        "package": package,
        "host": host,
        "booking": booking,
        "wristbands": wristbands,
        "card_ids": [w["card_id"] for w in wristbands],
    }


def setup_completed_booking(api, guest_count=2, start_at="2026-05-01T14:00:00Z",
                            end_at="2026-05-01T16:00:00Z"):
    """A booking driven all the way to COMPLETED (confirm -> check-in -> complete),
    using clock 14:30 inside the window. Returns the booking dict (post-complete)."""
    ctx = setup_confirmed_booking(api, guest_count=guest_count, start_at=start_at, end_at=end_at,
                                  clock="2026-05-01T10:00:00Z")
    bid = ctx["booking"]["id"]
    set_clock(api, "2026-05-01T14:30:00Z")
    check_in_booking(api, bid)
    booking = complete_booking(api, bid)
    ctx["booking"] = booking
    return ctx

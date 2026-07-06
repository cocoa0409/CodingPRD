"""Validation rules and validation-precedence conflicts on confirm/ticket/admit."""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_venue_attraction_slot, preload_slot_to_demand_ratio,
    create_venue, create_attraction, create_pricing_rule, create_time_slot,
    create_guest, create_reservation, add_ticket, confirm_reservation,
    create_held_reservation_with_ticket, get_slot_version,
    create_pass_product, issue_pass, set_clock,
    confirm_payload, weather_payload, create_ticket_payload,
    TEST_USERS,
)

BOX = TEST_USERS["box_office_headers"]
OPS = TEST_USERS["ops_headers"]


# ─── Single-failure validations (corner queue) ────────────────────────────

def test_ticket_age_below_minimum_rejected(api):
    """PRD 3.5: "The bearer's guest_age must be at least the attraction's min_age,
    failing which the ticket is rejected with ERR_AGE_BELOW_MINIMUM".

    Adding a ticket with guest_age 10 to an attraction whose min_age is 13 is rejected
    ERR_AGE_BELOW_MINIMUM.

    Design: Corner/validations/ticket_age_below_minimum_returns_age_error
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"], min_age=13)
    slot = create_time_slot(attraction["id"])
    guest = create_guest()
    reservation = create_reservation(venue["id"], guest["id"])

    res = api.add_ticket(reservation["id"],
                         create_ticket_payload(slot["id"], guest_age=10, max_scare_level=1, tier="GA"),
                         BOX)
    validate_error(res, "ERR_AGE_BELOW_MINIMUM")


def test_ticket_venue_mismatch_rejected_on_confirm(api):
    """PRD 3.5: "every such slot must belong to an attraction whose venue_id matches
    the reservation's venue_id, or the ticket is rejected with
    ERR_TICKET_VENUE_MISMATCH."

    A reservation in venue V1 carrying a ticket whose slot belongs to an attraction in
    venue V2 fails with ERR_TICKET_VENUE_MISMATCH.

    Design: Corner/validations/ticket_venue_mismatch_returns_error
    """
    v1 = create_venue(name="V1")
    v2 = create_venue(name="V2")
    att2 = create_attraction(v2["id"], name="Crypt2")
    create_pricing_rule(att2["id"])
    slot2 = create_time_slot(att2["id"])
    guest = create_guest()
    reservation = create_reservation(v1["id"], guest["id"])
    # The mismatch may surface on ticket-add or on confirm; assert it on confirm
    # per the design recipe, falling through if the add already rejects it.
    add_res = api.add_ticket(reservation["id"],
                             create_ticket_payload(slot2["id"], tier="GA"), BOX)
    if add_res.status_code >= 400:
        validate_error(add_res, "ERR_TICKET_VENUE_MISMATCH")
        return
    slot_v = slot2["version"]
    res = api.confirm_reservation(reservation["id"], confirm_payload(slot_v), BOX)
    validate_error(res, "ERR_TICKET_VENUE_MISMATCH")


def test_pass_not_owned_rejected_on_confirm(api):
    """PRD 3.6: "the pass's guest_id must equal the reservation's guest_id, or it is
    rejected with ERR_PASS_NOT_OWNED."

    Confirming a reservation owned by guest GB that applies guest GA's pass fails with
    ERR_PASS_NOT_OWNED.

    Design: Corner/validations/pass_not_owned_returns_error
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    product = create_pass_product(venue["id"], kind="SEASON", price_cents=5000,
                                  discount_pct=10, max_redemptions=5)
    ga = create_guest(full_name="GA", email="ga@x.com")
    gb = create_guest(full_name="GB", email="gb@x.com")
    pass_ = issue_pass(product["id"], ga["id"])
    reservation = create_reservation(venue["id"], gb["id"], pass_id=pass_["id"])
    add_ticket(reservation["id"], slot["id"], tier="GA")

    slot_v = get_slot_version(slot["id"])
    res = api.confirm_reservation(reservation["id"], confirm_payload(slot_v), BOX)
    validate_error(res, "ERR_PASS_NOT_OWNED")


def test_slot_capacity_exceeded_rejected_on_confirm(api):
    """PRD 3.6: "the confirmation checks that the slot's reserved_count plus its
    admitted_count plus the new party members landing on that slot does not exceed the
    slot's capacity; a confirmation that would push a slot past its capacity is
    rejected with ERR_SLOT_CAPACITY_EXCEEDED."

    A slot of capacity 2 already at reserved_count 2 rejects a confirm of one more
    ticket with ERR_SLOT_CAPACITY_EXCEEDED.

    Design: Corner/validations/slot_capacity_exceeded_aggregate
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 2})
    seed_guest = create_guest(full_name="Seed", email="seed@x.com")
    seed_res = create_reservation(venue["id"], seed_guest["id"])
    add_ticket(seed_res["id"], slot["id"], tier="GA")
    add_ticket(seed_res["id"], slot["id"], tier="GA")
    confirm_reservation(seed_res["id"], slot["id"])

    guest = create_guest(full_name="Over", email="over@x.com")
    reservation = create_reservation(venue["id"], guest["id"])
    add_ticket(reservation["id"], slot["id"], tier="GA")
    slot_v = get_slot_version(slot["id"])
    res = api.confirm_reservation(reservation["id"], confirm_payload(slot_v), BOX)
    validate_error(res, "ERR_SLOT_CAPACITY_EXCEEDED")


def test_pass_exhausted_rejected_on_second_confirm(api):
    """PRD 3.6: "the pass must be ACTIVE with redemptions_used still below the
    product's max_redemptions, or the confirmation is rejected with
    ERR_PASS_EXHAUSTED".

    A SEASON pass with max_redemptions 1, already redeemed once (now EXHAUSTED),
    rejects a second confirm with ERR_PASS_EXHAUSTED.

    Design: Corner/validations/pass_exhausted_returns_error
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 10})
    product = create_pass_product(venue["id"], kind="SEASON", price_cents=5000,
                                  discount_pct=10, max_redemptions=1)
    guest = create_guest(full_name="Holder", email="h@x.com")
    pass_ = issue_pass(product["id"], guest["id"])

    r1 = create_reservation(venue["id"], guest["id"], pass_id=pass_["id"])
    add_ticket(r1["id"], slot["id"], tier="GA")
    confirm_reservation(r1["id"], slot["id"])

    r2 = create_reservation(venue["id"], guest["id"], pass_id=pass_["id"])
    add_ticket(r2["id"], slot["id"], tier="GA")
    slot_v = get_slot_version(slot["id"])
    res = api.confirm_reservation(r2["id"], confirm_payload(slot_v), BOX)
    validate_error(res, "ERR_PASS_EXHAUSTED")


def test_confirm_already_reserved_rejected(api):
    """PRD 3.6: "Box-office staff or the guest confirm a HELD reservation ... the
    request advances the reservation from HELD to RESERVED." PRD 2.11: "the
    requirement that the target be in a legal state for the requested transition
    (ERR_INVALID_STATE)."

    Re-confirming a reservation already in entry_status RESERVED is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/confirm_already_reserved_returns_invalid_state
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_held_reservation_with_ticket(venue["id"], slot["id"])
    confirm_reservation(reservation["id"], slot["id"])

    slot_v = get_slot_version(slot["id"])
    res = api.confirm_reservation(reservation["id"], confirm_payload(slot_v), BOX)
    validate_error(res, "ERR_INVALID_STATE")


def test_confirm_empty_reservation_rejected(api):
    """PRD 3.6: "Box-office staff or the guest confirm a HELD reservation, which must
    hold at least one ticket — a confirmation against a reservation with zero tickets
    is rejected with ERR_EMPTY_RESERVATION."

    Confirming a HELD reservation with no tickets is rejected ERR_EMPTY_RESERVATION.

    Design: Corner/state_machines/confirm_empty_reservation_returns_empty_reservation
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest = create_guest()
    reservation = create_reservation(venue["id"], guest["id"])

    slot_v = slot["version"]
    res = api.confirm_reservation(reservation["id"], confirm_payload(slot_v), BOX)
    validate_error(res, "ERR_EMPTY_RESERVATION")


def test_capacity_over_throughput_rejected_on_slot_create(api):
    """PRD 3.2: "At creation the slot's capacity must not exceed the parent
    attraction's throughput_per_slot; a slot whose capacity is larger is rejected with
    ERR_CAPACITY_OVER_THROUGHPUT."

    Creating a slot of capacity 20 on an attraction with throughput_per_slot 10 is
    rejected ERR_CAPACITY_OVER_THROUGHPUT.

    Design: Corner/entities/time_slot_capacity_over_throughput_rejected
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"], throughput_per_slot=10)
    from test_helpers import create_time_slot_payload
    res = api.create_time_slot(attraction["id"], create_time_slot_payload(capacity=20), OPS)
    validate_error(res, "ERR_CAPACITY_OVER_THROUGHPUT")


def test_revoke_already_revoked_waiver_rejected(api):
    """PRD 3.3: "A guest or an operations manager may instead deliberately end a
    waiver early by revoking it, which moves a still-SIGNED waiver to the terminal
    REVOKED state". PRD 2.11: "the requirement that the target be in a legal state for
    the requested transition (ERR_INVALID_STATE)."

    Revoking a waiver already in the terminal REVOKED state is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/revoke_already_revoked_waiver_returns_invalid_state
    """
    from test_helpers import create_waiver_payload, revoke_payload, make_guest_headers
    guest = create_guest()
    gh = make_guest_headers(guest["id"])
    waiver = get_success_data(
        api.create_waiver(guest["id"], create_waiver_payload(max_scare_level=5), gh)
    )
    validate_success(api.revoke_waiver(waiver["id"], revoke_payload(waiver["version"]), gh), 200)

    res = api.revoke_waiver(waiver["id"], revoke_payload(waiver["version"]), gh)
    validate_error(res, "ERR_INVALID_STATE")


def test_restricted_state_blocks_vip_ticket_add(api):
    """PRD 3.5: "Adding a VIP ticket is blocked when the venue's operational_state is
    RESTRICTED or SHUTDOWN." PRD 3.9: "every such block surfaces as ERR_SALES_BLOCKED."

    Under operational_state RESTRICTED (weather ADVISORY) a VIP ticket add is rejected
    ERR_SALES_BLOCKED.

    Design: Corner/cross_cutting/restricted_blocks_vip_ticket_add
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    slot = create_time_slot(attraction["id"])
    validate_success(
        api.set_weather(venue["id"], weather_payload("ADVISORY", venue["version"]), OPS), 200
    )
    guest = create_guest()
    reservation = create_reservation(venue["id"], guest["id"])

    res = api.add_ticket(reservation["id"],
                         create_ticket_payload(slot["id"], tier="VIP"), BOX)
    validate_error(res, "ERR_SALES_BLOCKED")

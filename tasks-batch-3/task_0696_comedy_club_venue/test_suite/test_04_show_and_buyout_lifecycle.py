"""Show state machine, private buyouts, and cross-entity state dependencies.

Translates difficulty instances (cross_entity_state_dependency) plus the show
and private-event corner instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_venue, create_draft_show,
    setup_ga_show_on_sale, setup_table_show_on_sale,
    create_table_reservation_assigned,
    setup_private_held, setup_settled_show,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]


# ---------------------------------------------------------------------------
# Corner B — state_machines: initial state / publish precondition / terminal
# ---------------------------------------------------------------------------
def test_initial_state_show_is_draft(api):
    """PRD §3.1: "Within an open venue, a `Booker` programs a **Show** in `DRAFT`".
    PRD §2.5: "A show's `is_private` flag reads true exactly while a `PrivateEvent`
    in `HELD` or `CONFIRMED` status references it, and reverts to false once no
    such buyout remains."

    Design: Corner/state_machines/initial_state_show_is_draft
    """
    venue = create_venue(name="Init Venue")
    show = validate_success(
        api.create_show(venue["id"], {
            "title": "Init Night", "starts_at": "2026-05-07T03:00:00Z",
            "ends_at": "2026-05-07T05:00:00Z",
        }, BOOKER),
        expected_status=201,
    )
    assert show["status"] == "DRAFT", f"new show must be DRAFT, got {show['status']}"
    assert show["is_private"] is False, f"new show is_private must be False, got {show['is_private']}"


def test_publish_requires_section_and_tier(api):
    """PRD §3.1: "a `Booker` may do so only when the show already has at least one
    seating section and at least one ticket tier, when no `PrivateEvent` in
    `HELD` or `CONFIRMED` references the show, and when the venue's `posture` is
    not `CLOSED`".

    Design: Corner/state_machines/publish_requires_section_and_tier
    """
    venue = create_venue(name="Pub Venue")
    show = create_draft_show(venue["id"], title="Pub Night",
                             starts_at="2026-05-08T03:00:00Z", ends_at="2026-05-08T05:00:00Z")
    resp = api.publish_show(venue["id"], show["id"], BOOKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_terminal_settled_show_rejects_cancel(api):
    """PRD §3.1: "Cancelling a show is a `Booker` action permitted from `DRAFT`,
    `ON_SALE`, `PRIVATE_HELD`, or `SOLD_OUT` — but not once the show is `SETTLING`
    or `SETTLED`."

    Design: Corner/state_machines/terminal_settled_show_rejects_cancel
    """
    sc = setup_settled_show(
        ends_after_iso="2026-05-09T06:00:00Z",
        show_overrides={"title": "Term Night", "starts_at": "2026-05-09T03:00:00Z",
                        "ends_at": "2026-05-09T05:00:00Z"},
    )
    assert sc["show"]["status"] == "SETTLED", "precondition: show is SETTLED"
    resp = api.cancel_show(sc["venue"]["id"], sc["show"]["id"], BOOKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_private_event_held_moves_show_to_private_held(api):
    """PRD §3.11: "Creating it starts the buyout `HELD`, computes its
    `deposit_cents` ... and as a system consequence moves the show from `DRAFT` to
    `PRIVATE_HELD` (so `is_private` reads true and public reservation creation is
    blocked)."

    Design: Corner/state_machines/private_event_held_moves_show_to_private_held
    """
    venue = create_venue(name="Priv Venue")
    show = create_draft_show(venue["id"], title="Priv Night",
                             starts_at="2026-05-10T03:00:00Z", ends_at="2026-05-10T05:00:00Z")
    validate_success(
        api.create_private_event(
            {"show_id": show["id"], "client_name": "Gamma", "buyout_fee_cents": 300000},
            BOOKER,
        ),
        expected_status=201,
    )
    after = validate_success(api.get_show(show["id"], BOOKER))
    assert after["status"] == "PRIVATE_HELD", \
        f"buyout must move show to PRIVATE_HELD, got {after['status']}"
    assert after["is_private"] is True, \
        f"is_private must read true, got {after['is_private']}"


def test_buyout_cancel_reverts_show_to_on_sale(api):
    """PRD §3.11: "A `Booker` may cancel a buyout from `HELD` or `CONFIRMED`;
    cancellation moves `status` to `CANCELLED`, retains the `deposit_cents` (it is
    non-refundable even on cancellation), and — if this was the only `HELD` or
    `CONFIRMED` buyout on the show — moves the show from `PRIVATE_HELD` back to
    `ON_SALE` with `is_private` reverting to false."

    Design: Corner/state_machines/buyout_cancel_reverts_show_to_on_sale
    """
    ctx = setup_private_held(buyout_fee_cents=400000, deposit_pct=0.25,
                             show_overrides={"title": "Revert Night",
                                             "starts_at": "2026-05-11T03:00:00Z",
                                             "ends_at": "2026-05-11T05:00:00Z"})
    pe = ctx["private_event"]
    assert pe["deposit_cents"] == 100000, "precondition: deposit 0.25*400000 == 100000"
    cancelled = validate_success(api.cancel_private_event(pe["id"], BOOKER))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    assert cancelled["deposit_cents"] == 100000, \
        f"deposit must be retained at 100000, got {cancelled['deposit_cents']}"
    show = validate_success(api.get_show(ctx["show"]["id"], BOOKER))
    assert show["status"] == "ON_SALE", \
        f"show must revert to ON_SALE, got {show['status']}"


# ---------------------------------------------------------------------------
# Difficulty A — cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_seat_rejected_once_show_cancelled(api):
    """PRD §3.6: "Seating a party advances its `booking_status` from `BOOKED` to
    `SEATED` ... this is a `FloorManager` action available only on a `TABLE`-section
    reservation that already holds a table, while its show is `ON_SALE` or
    `SOLD_OUT`."
    PRD §2.6: "then, that the target resource is in a legal state for the
    operation (`ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/reservation_seat_requires_show_on_sale
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "CrossA Night", "starts_at": "2026-04-12T03:00:00Z",
                        "ends_at": "2026-04-12T05:00:00Z"},
    )
    res = create_table_reservation_assigned(sc, patron_id="patron-hh", party_size=2)
    # Cancelling the show cancels the reservation and takes the show out of ON_SALE.
    validate_success(api.cancel_show(sc["venue"]["id"], sc["show"]["id"], BOOKER))
    resp = api.seat_reservation(res["id"], FLOOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_buyout_rejected_after_cancel_reverts_show(api):
    """PRD §3.11: "A `Booker` confirms a held buyout while the underlying show is
    `PRIVATE_HELD`, moving `status` to `CONFIRMED`".
    PRD §2.6: "then, that the target resource is in a legal state for the
    operation (`ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/private_event_confirm_requires_show_private_held
    """
    venue = create_venue(name="CrossB Venue")
    show = create_draft_show(venue["id"], title="CrossB Night",
                             starts_at="2026-04-13T03:00:00Z", ends_at="2026-04-13T05:00:00Z")
    # Need a section+tier so a later revert to ON_SALE is meaningful, mirroring the design.
    section = validate_success(
        api.create_section(venue["id"], show["id"], {"kind": "GA", "label": "Standing", "ga_capacity": 100}, BOOKER),
        expected_status=201,
    )
    validate_success(
        api.create_tier(venue["id"], show["id"], {"section_id": section["id"], "name": "GA", "price_cents": 4500}, BOOKER),
        expected_status=201,
    )
    pe = validate_success(
        api.create_private_event(
            {"show_id": show["id"], "client_name": "Beta Corp", "buyout_fee_cents": 400000},
            BOOKER,
        ),
        expected_status=201,
    )
    validate_success(api.cancel_private_event(pe["id"], BOOKER))
    resp = api.confirm_private_event(pe["id"], BOOKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_seat_after_show_cancel_reservation_already_cancelled(api):
    """PRD §3.8: "Every reservation for the show whose `booking_status` is
    `BOOKED`, `SEATED`, or `CHECKED_IN` is moved to `CANCELLED`".
    PRD §2.6: "then, that the target resource is in a legal state for the
    operation (`ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/reservation_seat_requires_show_on_sale
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "CrossA2 Night", "starts_at": "2026-04-12T03:00:00Z",
                        "ends_at": "2026-04-12T05:00:00Z"},
    )
    res = create_table_reservation_assigned(sc, patron_id="patron-hh2", party_size=2)
    validate_success(api.cancel_show(sc["venue"]["id"], sc["show"]["id"], BOOKER))
    # The cascade already moved the reservation to CANCELLED; the seat attempt
    # therefore acts on a reservation that is not in a seatable state.
    reread = validate_success(api.get_reservation(res["id"], FLOOR))
    assert reread["booking_status"] == "CANCELLED", \
        f"show cancel must cascade reservation to CANCELLED, got {reread['booking_status']}"
    resp = api.seat_reservation(res["id"], FLOOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_buyout_after_revert_show_now_on_sale(api):
    """PRD §3.11: "A `Booker` confirms a held buyout while the underlying show is
    `PRIVATE_HELD`, moving `status` to `CONFIRMED` while the show stays
    `PRIVATE_HELD` and excluded from public sale."
    PRD §3.11: "moves the show from `PRIVATE_HELD` back to `ON_SALE` with
    `is_private` reverting to false."

    Design: Difficulty/cross_entity_state_dependency/private_event_confirm_requires_show_private_held
    """
    ctx = setup_private_held(
        buyout_fee_cents=400000,
        show_overrides={"title": "CrossB2 Night", "starts_at": "2026-04-13T03:00:00Z",
                        "ends_at": "2026-04-13T05:00:00Z"},
    )
    pe = ctx["private_event"]
    validate_success(api.cancel_private_event(pe["id"], BOOKER))
    # The show has reverted to ON_SALE (no longer PRIVATE_HELD), so confirm fails.
    show = validate_success(api.get_show(ctx["show"]["id"], BOOKER))
    assert show["status"] == "ON_SALE", \
        f"cancel must revert show to ON_SALE, got {show['status']}"
    resp = api.confirm_private_event(pe["id"], BOOKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Difficulty A — transitive_cascade / show_cancel_cascade_depth3_to_server
# ---------------------------------------------------------------------------
def test_show_cancel_cascades_reservation_and_table_release(api):
    """PRD §3.8: "Every reservation for the show whose `booking_status` is
    `BOOKED`, `SEATED`, or `CHECKED_IN` is moved to `CANCELLED`, each computing a
    full refund into `refunded_cents` with no cancellation fee deducted ... Each
    such cancelled reservation that held a `SeatTable` releases it back to
    `AVAILABLE`."

    Design: Difficulty/transitive_cascade/show_cancel_cascade_depth3_to_server
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "Cascade Night", "starts_at": "2026-04-07T03:00:00Z",
                        "ends_at": "2026-04-07T05:00:00Z"},
        server_overrides={"name": "Frank", "max_tables": 4},
    )
    res = create_table_reservation_assigned(sc, patron_id="patron-ee", party_size=2)
    cancelled_show = validate_success(api.cancel_show(sc["venue"]["id"], sc["show"]["id"], BOOKER))
    assert cancelled_show["status"] == "CANCELLED", \
        f"show must be CANCELLED, got {cancelled_show['status']}"
    res_after = validate_success(api.get_reservation(res["id"], FLOOR))
    assert res_after["booking_status"] == "CANCELLED", \
        f"reservation must cascade to CANCELLED, got {res_after['booking_status']}"
    table = validate_success(api.get_table(sc["table"]["id"], FLOOR))
    assert table["status"] == "AVAILABLE", \
        f"held table must release to AVAILABLE, got {table['status']}"


def test_show_cancel_cascade_full_refund_no_fee(api):
    """PRD §3.8: "Every reservation for the show whose `booking_status` is
    `BOOKED`, `SEATED`, or `CHECKED_IN` is moved to `CANCELLED`, each computing a
    full refund into `refunded_cents` with no cancellation fee deducted — the
    patron is made whole on the recoverable base — and each advancing
    `settlement_status` to `REFUNDED`."

    Design: Difficulty/transitive_cascade/show_cancel_cascade_depth3_to_server
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "Cascade2 Night", "starts_at": "2026-04-07T03:00:00Z",
                        "ends_at": "2026-04-07T05:00:00Z"},
        server_overrides={"name": "Frank", "max_tables": 4},
    )
    res = create_table_reservation_assigned(sc, patron_id="patron-ee2", party_size=2)
    # Collect the ticket so there is a recoverable base (4500*2 == 9000).
    paid = validate_success(api.collect_ticket(res["id"], BOX_OFFICE))
    assert paid["ticket_charge_cents"] == 9000, "precondition: base 9000 collected"
    validate_success(api.cancel_show(sc["venue"]["id"], sc["show"]["id"], BOOKER))
    res_after = validate_success(api.get_reservation(res["id"], FLOOR))
    assert res_after["booking_status"] == "CANCELLED", \
        f"reservation must cascade to CANCELLED, got {res_after['booking_status']}"
    # Show-cancel deducts no cancellation fee: full base of 9000 refunded.
    assert res_after["refunded_cents"] == 9000, \
        f"show-cancel must refund the full base 9000 (no fee), got {res_after['refunded_cents']}"
    assert res_after["settlement_status"] == "REFUNDED", \
        f"expected REFUNDED, got {res_after['settlement_status']}"

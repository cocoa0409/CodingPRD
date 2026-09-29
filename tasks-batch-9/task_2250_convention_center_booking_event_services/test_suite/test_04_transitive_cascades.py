"""Multi-level cascades fired by a sweep, by finalization and by termination."""

from test_helpers import (
    ANALYST_ONE,
    ANALYST_TWO,
    BALLROOM_B,
    HALL_A,
    NATIONAL_WIDGET_ASSOCIATION,
    RIVERBEND_ROTARY,
    SALES_MANAGER,
    SPARKLECLEAN_EXCLUSIVE,
    VENUE_ADMIN,
    ApiClient,
    append_line_item,
    approve_service_order,
    assert_fields,
    assert_money_cents,
    assert_settlement_money,
    close_booking,
    confirm_definite,
    confirm_first_option,
    countersign_license,
    create_booking,
    draft_license,
    execute_license,
    get_success_data,
    issue_license,
    issue_settlement,
    make_analyst_headers,
    open_settlement,
    open_show,
    order_service,
    pay_deposit,
    place_hold,
    publish_window,
    read_booking,
    read_client,
    read_hold,
    read_license,
    read_service_order,
    read_settlement,
    read_space,
    register_client,
    register_space,
    register_vendor,
    set_clock,
    validate_success,
)

CONVENTION_DATES = {
    "move_in_start_date": "2028-05-10",
    "show_start_date": "2028-05-14",
    "show_end_date": "2028-05-17",
    "move_out_end_date": "2028-05-19",
}


def _lapsed_challenge_world(api: ApiClient):
    """A challenged rank-1 local hold whose deadline has passed by one second."""
    publish_window(api, "CITYWIDE_CONVENTION")
    publish_window(api, "LOCAL_EVENT")
    space = register_space(api, **dict(BALLROOM_B))
    vendor = register_vendor(api, **dict(SPARKLECLEAN_EXCLUSIVE))

    rotary = register_client(api, **dict(RIVERBEND_ROTARY))
    widget = register_client(api, **dict(NATIONAL_WIDGET_ASSOCIATION))
    pay_deposit(api, rotary["id"], 2000000)

    rotary_booking = create_booking(
        api,
        rotary["id"],
        space["id"],
        event_name="Riverbend Charity Gala",
        event_class="LOCAL_EVENT",
        **CONVENTION_DATES,
    )
    rotary_hold = place_hold(api, rotary_booking["id"])
    rotary_license = draft_license(api, rotary_booking["id"])
    issue_license(api, rotary_license["id"])
    rotary_order = order_service(api, rotary_booking["id"], vendor["id"], "CLEANING", 2000)
    approve_service_order(api, rotary_order["id"])

    widget_booking = create_booking(
        api,
        widget["id"],
        space["id"],
        event_name="National Widget Convention",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **CONVENTION_DATES,
    )
    widget_hold = place_hold(api, widget_booking["id"])

    get_success_data(
        api.challenge_hold(
            rotary_hold["id"], challenger_hold_id=widget_hold["id"], headers=SALES_MANAGER
        )
    )
    set_clock(api, "2026-08-04T00:00:01Z")

    return {
        "space": space,
        "rotary": rotary,
        "rotary_booking": rotary_booking,
        "rotary_hold": rotary_hold,
        "rotary_license": rotary_license,
        "rotary_order": rotary_order,
        "widget_hold": widget_hold,
    }


def test_hold_sweep_releases_the_lapsed_challenge_and_its_booking(api: ApiClient):
    """One lapsed challenge releases the hold, which releases the booking behind it.

    PRD: "Every hold whose `status` is `CHALLENGED` and whose
    `challenge_deadline_utc` has strictly passed moves `CHALLENGED → RELEASED`;
    every hold whose `status` is `ACTIVE` and whose `release_deadline_utc` has
    strictly passed likewise moves to `RELEASED`."
    PRD: "The sweep reports four counters: `expired_challenge_count`,
    `released_hold_count`, `promoted_hold_count` and `released_booking_count`."

    Design: Difficulty/transitive_cascade/expired_challenge_sweep_cascades_hold_release_to_booking_license_and_service_order
    """
    world = _lapsed_challenge_world(api)

    response = api.run_hold_sweep(headers=VENUE_ADMIN)
    counters = validate_success(response, expected_status=200)
    assert_fields(
        counters,
        expired_challenge_count=1,
        released_hold_count=1,
        promoted_hold_count=1,
        released_booking_count=1,
    )

    assert_fields(read_hold(api, world["rotary_hold"]["id"]), status="RELEASED")
    assert_fields(
        read_booking(api, world["rotary_booking"]["id"]), status="RELEASED", hold_count=0
    )


def test_hold_sweep_release_reaches_the_license_the_order_and_both_ledgers(api: ApiClient):
    """The same sweep voids the license, refunds escrow, cancels the order and re-ranks.

    PRD: "the booking's license agreement, if its `status` is `DRAFT` or `ISSUED`,
    moves to `VOIDED`, its `deposit_held_cents` returning to the client's
    `credit_balance_cents` and then being set to 0; every service order on the
    booking whose `approval_status` is `PENDING_APPROVAL` or `APPROVED` moves to
    `CANCELLED` with its `billing_status` moved to `VOID`; the space's
    `committed_space_days` decreases by this booking's `space_days_committed`; and
    `order_posture` is recomputed to `LOCKED`."
    PRD: "For a lapsed challenge specifically, the hold named by
    `challenged_by_hold_id` is promoted by the ranking rule and every hold below it
    on the space shifts up one position."

    Design: Difficulty/transitive_cascade/expired_challenge_sweep_cascades_hold_release_to_booking_license_and_service_order
    """
    world = _lapsed_challenge_world(api)

    api.run_hold_sweep(headers=VENUE_ADMIN)

    license_row = read_license(api, world["rotary_license"]["id"])
    assert_fields(license_row, status="VOIDED")
    assert_money_cents(license_row["deposit_held_cents"], 0, "deposit_held_cents")
    assert_money_cents(
        read_client(api, world["rotary"]["id"])["credit_balance_cents"], 2000000, "credit_balance_cents"
    )

    assert_fields(
        read_service_order(api, world["rotary_order"]["id"]),
        approval_status="CANCELLED",
        billing_status="VOID",
    )
    assert_fields(read_hold(api, world["widget_hold"]["id"]), hold_rank=1)
    assert read_space(api, world["space"]["id"])["committed_space_days"] == 10


def _finalizable_convention_settlement(api: ApiClient):
    """A closed Hall A convention with an issued settlement and a live sibling booking."""
    publish_window(api, "CITYWIDE_CONVENTION")
    hall = register_space(api, **dict(HALL_A))
    ballroom = register_space(api, **dict(BALLROOM_B))
    client = register_client(api, **dict(NATIONAL_WIDGET_ASSOCIATION))
    pay_deposit(api, client["id"], 8000000)

    booking = create_booking(
        api,
        client["id"],
        hall["id"],
        event_name="National Widget Convention",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **CONVENTION_DATES,
    )
    sibling = create_booking(
        api,
        client["id"],
        ballroom["id"],
        event_name="National Widget Fall Council",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=2600,
        move_in_start_date="2028-09-05",
        show_start_date="2028-09-08",
        show_end_date="2028-09-10",
        move_out_end_date="2028-09-12",
    )

    hold = place_hold(api, booking["id"])
    confirm_first_option(api, hold["id"])
    license_row = execute_license(api, booking["id"], client["id"])
    confirm_definite(api, booking["id"])

    open_show(api, booking["id"], at_utc="2028-05-10T08:00:00Z")
    close_booking(api, booking["id"], at_utc="2028-05-20T09:00:00Z")

    settlement = open_settlement(api, booking["id"], basis="CONTRACTED", analyst_id=ANALYST_ONE)
    append_line_item(
        api, settlement["id"], "RENTAL", 25200000, memo="contracted rental", analyst_id=ANALYST_ONE
    )
    issue_settlement(api, settlement["id"], analyst_id=ANALYST_ONE)
    set_clock(api, "2028-05-30T10:00:00Z")

    return {
        "client": client,
        "booking": booking,
        "sibling": sibling,
        "license": license_row,
        "settlement": settlement,
    }


def test_finalization_settles_the_booking_and_applies_the_escrowed_deposit(api: ApiClient):
    """Finalizing moves escrow onto the settlement and drives the booking to SETTLED.

    PRD: "`deposit_applied_cents` is set to the license's `deposit_held_cents` for
    this booking, and that field is then set to 0, moving the escrowed money onto
    the settlement and preserving the monetary invariant of §2.9."
    PRD: "`grand_total_cents` is recomputed as `line_subtotal_cents` plus
    `facility_service_fee_cents` less `deposit_applied_cents`."
    PRD: "Then the booking moves `CLOSED → SETTLED`, which increases the client's
    `outstanding_balance_cents` by this settlement's `grand_total_cents`."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascades_client_standing_into_sibling_booking_order_lock
    """
    world = _finalizable_convention_settlement(api)

    response = api.finalize_settlement(
        world["settlement"]["id"], headers=make_analyst_headers(ANALYST_TWO)
    )
    validate_success(response, expected_status=200)

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="FINAL")
    assert_settlement_money(
        settlement,
        line_subtotal_cents=25200000,
        facility_service_fee_cents=1386000,
        deposit_applied_cents=6300000,
        grand_total_cents=20286000,
    )
    assert_fields(read_booking(api, world["booking"]["id"]), status="SETTLED")
    assert_money_cents(
        read_license(api, world["license"]["id"])["deposit_held_cents"], 0, "deposit_held_cents"
    )


def test_finalization_restricts_the_client_and_locks_its_other_booking(api: ApiClient):
    """The settled total restricts the client's standing and locks the sibling booking.

    PRD: "That increase re-runs the standing calculation of §3.1, which may move the
    client's `booking_standing` from `GOOD` to `HOLD_RESTRICTED`."
    PRD: "And a `HOLD_RESTRICTED` standing in turn recomputes `order_posture` to
    `LOCKED` on every *other* booking of the same client whose `status` is
    `TENTATIVE`, `DEFINITE`, `IN_HOUSE` or `CLOSED` — so one unpaid settlement
    freezes event services across that licensee's entire forward calendar."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascades_client_standing_into_sibling_booking_order_lock
    """
    world = _finalizable_convention_settlement(api)

    api.finalize_settlement(world["settlement"]["id"], headers=make_analyst_headers(ANALYST_TWO))

    client = read_client(api, world["client"]["id"])
    assert_money_cents(client["outstanding_balance_cents"], 20286000, "outstanding_balance_cents")
    assert_money_cents(client["credit_balance_cents"], 1700000, "credit_balance_cents")
    assert_fields(client, booking_standing="HOLD_RESTRICTED")

    assert_fields(read_booking(api, world["sibling"]["id"]), order_posture="LOCKED")


def _executed_convention_license(api: ApiClient):
    """A Hall A convention booking whose license is EXECUTED and whose hold is CONFIRMED."""
    publish_window(api, "CITYWIDE_CONVENTION")
    hall = register_space(api, **dict(HALL_A))
    client = register_client(api, **dict(NATIONAL_WIDGET_ASSOCIATION))
    pay_deposit(api, client["id"], 8000000)

    booking = create_booking(
        api,
        client["id"],
        hall["id"],
        event_name="National Widget Convention",
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **CONVENTION_DATES,
    )
    hold = place_hold(api, booking["id"])
    confirm_first_option(api, hold["id"])
    license_row = draft_license(api, booking["id"])
    issue_license(api, license_row["id"])
    countersign_license(api, license_row["id"], client["id"])

    return {"space": hall, "client": client, "booking": booking, "hold": hold, "license": license_row}


def test_termination_returns_the_escrowed_deposit_to_the_client(api: ApiClient):
    """Terminating an executed license restores the full deposit credit.

    PRD: "**Termination** is the deliberate counterpart, reserved to a
    `VenueAdmin`, driving `EXECUTED → TERMINATED`."
    PRD: "Terminating sets `deposit_held_cents` to 0 and returns the prior amount to
    the client's `credit_balance_cents`, restoring the monetary invariant, and then
    drives the booking to `RELEASED` — which decrements the space's
    `committed_space_days` by the booking's `space_days_committed` and releases every
    hold on the booking whose `status` is `ACTIVE`, `CHALLENGED` or `CONFIRMED`,
    restoring the capacity invariant."

    Design: Difficulty/transitive_cascade/license_termination_cascades_booking_release_hold_release_and_space_day_reversal
    """
    world = _executed_convention_license(api)

    response = api.terminate_license(world["license"]["id"], headers=VENUE_ADMIN)
    validate_success(response, expected_status=200)

    license_row = read_license(api, world["license"]["id"])
    assert_fields(license_row, status="TERMINATED")
    assert_money_cents(license_row["deposit_held_cents"], 0, "deposit_held_cents")
    assert_money_cents(
        read_client(api, world["client"]["id"])["credit_balance_cents"], 8000000, "credit_balance_cents"
    )


def test_termination_reverses_the_space_day_ledger_but_not_the_booking_record(api: ApiClient):
    """The space counter falls to zero while the booking keeps its own committed day count.

    PRD: "`space_days_committed` is the inclusive number of days from
    `move_in_start_date` through `move_out_end_date` — the difference in calendar
    days plus one — and the named space's `committed_space_days` rises by exactly
    that figure."
    PRD: "`SpaceUnit.committed_space_days` is the sum of `space_days_committed` over
    the bookings placed on that space or on any of its descendant spaces whose
    `status` is one of `TENTATIVE`, `DEFINITE`, `IN_HOUSE`, `CLOSED` or `SETTLED`."

    Design: Difficulty/transitive_cascade/license_termination_cascades_booking_release_hold_release_and_space_day_reversal
    """
    world = _executed_convention_license(api)

    api.terminate_license(world["license"]["id"], headers=VENUE_ADMIN)

    booking = read_booking(api, world["booking"]["id"])
    assert_fields(booking, status="RELEASED", hold_count=0, space_days_committed=10)
    assert_fields(read_hold(api, world["hold"]["id"]), status="RELEASED")
    assert read_space(api, world["space"]["id"])["committed_space_days"] == 0

"""Money, space-days and crew-hours must each return to balance after a reversal."""

from test_helpers import (
    EVENT_SERVICES,
    HALL_A,
    MEETING_ROOM_301,
    NATIONAL_WIDGET_ASSOCIATION,
    SALES_MANAGER,
    SEIU_LOCAL_3,
    VENUE_ADMIN,
    ApiClient,
    assert_crew_hours,
    assert_fields,
    assert_money_cents,
    confirm_first_option,
    countersign_license,
    create_booking,
    draft_license,
    issue_license,
    pay_deposit,
    place_hold,
    publish_window,
    read_booking,
    read_client,
    read_labor_call,
    read_license,
    read_space,
    read_union_jurisdiction,
    register_client,
    register_space,
    register_union_local,
    schedule_labor_call,
    setup_event_lifecycle,
    validate_paginated,
    validate_success,
)

CONVENTION_DATES = {
    "event_name": "National Widget Convention",
    "move_in_start_date": "2028-05-10",
    "show_start_date": "2028-05-14",
    "show_end_date": "2028-05-17",
    "move_out_end_date": "2028-05-19",
}

FALL_COUNCIL_DATES = {
    "event_name": "National Widget Fall Council",
    "move_in_start_date": "2028-09-05",
    "show_start_date": "2028-09-08",
    "show_end_date": "2028-09-10",
    "move_out_end_date": "2028-09-12",
}


def _escrowed_convention_license(api: ApiClient):
    """A Hall A convention license holding 6,300,000 cents of the client's 8,000,000."""
    publish_window(api, "CITYWIDE_CONVENTION")
    hall = register_space(api, **dict(HALL_A))
    client = register_client(api, **dict(NATIONAL_WIDGET_ASSOCIATION))
    pay_deposit(api, client["id"], 8000000)

    booking = create_booking(
        api,
        client["id"],
        hall["id"],
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **CONVENTION_DATES,
    )
    hold = place_hold(api, booking["id"])
    confirm_first_option(api, hold["id"])
    license_row = draft_license(api, booking["id"])
    issue_license(api, license_row["id"])
    countersign_license(api, license_row["id"], client["id"])

    return {"client": client, "booking": booking, "license": license_row}


def test_termination_zeroes_escrow_without_touching_the_pinned_contract_figures(api: ApiClient):
    """The discounted rental and the required deposit survive; only the escrow drains.

    PRD: "Terminating sets `deposit_held_cents` to 0 and returns the prior amount to
    the client's `credit_balance_cents`, restoring the monetary invariant, and then
    drives the booking to `RELEASED` — which decrements the space's
    `committed_space_days` by the booking's `space_days_committed` and releases every
    hold on the booking whose `status` is `ACTIVE`, `CHALLENGED` or `CONFIRMED`,
    restoring the capacity invariant."
    PRD: "`contracted_rental_cents` is `gross_rental_cents` multiplied by one minus
    the class's `rental_discount_pct`, rounded half up to whole cents."
    PRD: "`deposit_required_cents` is `contracted_rental_cents` multiplied by one
    quarter, rounded half up to whole cents."

    Design: Difficulty/compensating_invariant/deposit_escrow_conservation_holds_across_license_issue_and_termination
    """
    world = _escrowed_convention_license(api)

    escrowed = read_license(api, world["license"]["id"])
    assert_money_cents(escrowed["deposit_held_cents"], 6300000, "deposit_held_cents")

    validate_success(
        api.terminate_license(world["license"]["id"], headers=VENUE_ADMIN), expected_status=200
    )

    license_row = read_license(api, world["license"]["id"])
    assert_fields(license_row, status="TERMINATED")
    assert_money_cents(license_row["contracted_rental_cents"], 25200000, "contracted_rental_cents")
    assert_money_cents(license_row["deposit_required_cents"], 6300000, "deposit_required_cents")
    assert_money_cents(license_row["deposit_held_cents"], 0, "deposit_held_cents")


def test_deposit_money_is_neither_created_nor_destroyed_by_the_cycle(api: ApiClient):
    """Credit plus escrow plus applied deposits equals the lifetime total at the end.

    PRD: "Money moves between the two but is never created or destroyed by a state
    transition: issuing a license moves the deposit out of the client's credit
    balance and into escrow, voiding or terminating a license moves it back, and
    finalizing a settlement moves it out of escrow and onto the settlement as
    `deposit_applied_cents`."
    PRD: "`total_deposits_paid_cents` is therefore a historical fact while
    `credit_balance_cents` is a live balance; the two diverge the moment a license is
    issued."

    Design: Difficulty/compensating_invariant/deposit_escrow_conservation_holds_across_license_issue_and_termination
    """
    world = _escrowed_convention_license(api)

    api.terminate_license(world["license"]["id"], headers=VENUE_ADMIN)

    client = read_client(api, world["client"]["id"])
    license_row = read_license(api, world["license"]["id"])
    assert_money_cents(client["credit_balance_cents"], 8000000, "credit_balance_cents")
    assert_money_cents(client["total_deposits_paid_cents"], 8000000, "total_deposits_paid_cents")

    settlements, _meta = validate_paginated(
        api.list_settlements(headers=VENUE_ADMIN, booking_id=world["booking"]["id"])
    )
    assert settlements == [], f"expected no settlements for the booking, got {settlements}"

    applied = sum(row["deposit_applied_cents"] for row in settlements)
    assert (
        client["credit_balance_cents"] + license_row["deposit_held_cents"] + applied
        == client["total_deposits_paid_cents"]
    ), "credit plus escrow plus applied deposits must equal the lifetime deposits paid"


def _two_hall_bookings(api: ApiClient):
    """Two Hall A bookings committing 10 and 8 space-days with no holds placed."""
    publish_window(api, "CITYWIDE_CONVENTION")
    hall = register_space(api, **dict(HALL_A))
    client = register_client(api, **dict(NATIONAL_WIDGET_ASSOCIATION))

    keep = create_booking(
        api,
        client["id"],
        hall["id"],
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=3000,
        **CONVENTION_DATES,
    )
    drop = create_booking(
        api,
        client["id"],
        hall["id"],
        event_class="CITYWIDE_CONVENTION",
        projected_room_nights=2600,
        **FALL_COUNCIL_DATES,
    )
    return {"space": hall, "keep": keep, "drop": drop}


def test_releasing_one_booking_leaves_the_other_booking_untouched(api: ApiClient):
    """The released booking keeps its own historical eight days and the survivor its ten.

    PRD: "`space_days_committed` is the inclusive number of days from
    `move_in_start_date` through `move_out_end_date` — the difference in calendar
    days plus one — and the named space's `committed_space_days` rises by exactly
    that figure."
    PRD: "**Releasing** a booking, which a `SalesManager` may do from `TENTATIVE` and
    a `VenueAdmin` may do from `DEFINITE`, drives `TENTATIVE → RELEASED` or
    `DEFINITE → RELEASED`; both require that no settlement yet exists for the
    booking, and an attempt on a booking that already has one is refused with
    `ERR_SETTLEMENT_ALREADY_EXISTS`."

    Design: Difficulty/compensating_invariant/space_day_capacity_ledger_reverses_only_the_released_booking_share
    """
    world = _two_hall_bookings(api)

    validate_success(
        api.release_booking(world["drop"]["id"], headers=SALES_MANAGER), expected_status=200
    )

    assert_fields(read_booking(api, world["drop"]["id"]), status="RELEASED", space_days_committed=8)
    assert_fields(read_booking(api, world["keep"]["id"]), status="TENTATIVE", space_days_committed=10)


def test_space_day_ledger_falls_by_exactly_the_released_share(api: ApiClient):
    """The hall's counter moves from eighteen to exactly ten, not to zero.

    PRD: "`SpaceUnit.committed_space_days` is the sum of `space_days_committed` over
    the bookings placed on that space or on any of its descendant spaces whose
    `status` is one of `TENTATIVE`, `DEFINITE`, `IN_HOUSE`, `CLOSED` or `SETTLED`."
    PRD: "It rises when a booking is created and falls by the same amount when that
    booking leaves the set — that is, when it reaches `RELEASED` or `CANCELLED`."

    Design: Difficulty/compensating_invariant/space_day_capacity_ledger_reverses_only_the_released_booking_share
    """
    world = _two_hall_bookings(api)

    assert read_space(api, world["space"]["id"])["committed_space_days"] == 18

    api.release_booking(world["drop"]["id"], headers=SALES_MANAGER)

    assert read_space(api, world["space"]["id"])["committed_space_days"] == 10


def _scheduled_cleaning_call(api: ApiClient):
    """A 3-crew cleaning call from 06:00 to 10:30 committing 13.5 crew-hours."""
    world = setup_event_lifecycle(
        api,
        "in_house",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )
    local = register_union_local(api, **dict(SEIU_LOCAL_3))
    call = schedule_labor_call(
        api, world["booking"]["id"], local["id"], "CLEANING", "2027-03-01", 6.0, 10.5, 3
    )
    world["local"] = local
    world["labor_call"] = call
    return world


def test_cancelling_a_call_zeroes_its_billed_hours_but_keeps_its_estimate(api: ApiClient):
    """Cancellation drops billed_hours to zero while the recorded estimate stands.

    PRD: "**Cancelling** drives `SCHEDULED → CANCELLED` or `DISPATCHED →
    CANCELLED`, and in both cases it decreases the local's `committed_crew_hours` by
    the call's current `billed_hours` and then sets `billed_hours` to 0, restoring
    the capacity invariant exactly."
    PRD: "The estimate prices every hour at straight time and never applies the
    overtime multiplier, no matter where the scheduled hours fall relative to the
    straight-time window."

    Design: Difficulty/compensating_invariant/union_committed_crew_hours_return_to_zero_after_labor_call_cancellation
    """
    world = _scheduled_cleaning_call(api)

    scheduled = read_labor_call(api, world["labor_call"]["id"])
    assert_crew_hours(scheduled["billed_hours"], 13.5)

    validate_success(
        api.cancel_labor_call(world["labor_call"]["id"], headers=EVENT_SERVICES),
        expected_status=200,
    )

    call = read_labor_call(api, world["labor_call"]["id"])
    assert_fields(call, status="CANCELLED")
    assert_crew_hours(call["billed_hours"], 0.0)
    assert_money_cents(call["estimated_charge_cents"], 128696, "estimated_charge_cents")


def test_cancelled_call_returns_the_local_to_zero_committed_crew_hours(api: ApiClient):
    """The local's aggregate falls back to 0.0 while the booking stays in house.

    PRD: "The local's `committed_crew_hours` is the sum of `billed_hours` over its
    calls whose `status` is `SCHEDULED`, `DISPATCHED` or `ACTUALIZED`, and cancelled
    calls contribute nothing."
    PRD: "The derived `committed_crew_hours` counter initializes to 0."

    Design: Difficulty/compensating_invariant/union_committed_crew_hours_return_to_zero_after_labor_call_cancellation
    """
    world = _scheduled_cleaning_call(api)

    assert_crew_hours(
        read_union_jurisdiction(api, world["local"]["id"])["committed_crew_hours"], 13.5
    )

    api.cancel_labor_call(world["labor_call"]["id"], headers=EVENT_SERVICES)

    assert_crew_hours(
        read_union_jurisdiction(api, world["local"]["id"])["committed_crew_hours"], 0.0
    )
    assert_fields(read_booking(api, world["booking"]["id"]), status="IN_HOUSE")

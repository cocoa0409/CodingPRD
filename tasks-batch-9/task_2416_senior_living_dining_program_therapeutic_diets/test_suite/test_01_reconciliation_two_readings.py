"""Meal-count reconciliation: the two readings, the fee waterfall and its tier."""
from test_helpers import (
    BILLING_SPECIALIST,
    assert_reconciliation_waterfall,
    create_reconciliation,
    create_reservation,
    issue_and_serve_ticket,
    issue_ticket,
    read_reservation,
    read_resident,
    seat_reservation,
    serve_ticket,
    setup_dining_program,
    setup_published_menu_cycle,
    tickets_for_reservation,
    validate_success,
    void_ticket,
)


def _riverbend_period_day():
    """A community whose single day mixes one never-seated reservation and one walk-in."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Riverbend",
        care_levels=["ASSISTED_LIVING", "MEMORY_CARE"],
        venue_name="Riverbend Main Dining",
        seat_capacity=20,
        resident_name="Ada Lin",
        baseline_weight_kg=78.0,
    )
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "DINNER",
        "2026-08-10T18:00:00Z",
        party_size=1,
    )
    issue_and_serve_ticket(
        program["venue"]["id"],
        "RESIDENT",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )
    program["reservation"] = reservation
    return program


def test_ledger_and_census_readings_diverge_over_the_same_period(api):
    """A never-seated DINNER reservation prices into the census only while a walk-in
    RESIDENT LUNCH ticket prices into the ledger only, so the same single-day period
    reports 650 against 800 and a negative variance.

    PRD: "A walk-in `RESIDENT` ticket with no `reservation_id` raises the ledger only. A
    reservation that was booked but never seated raises the census only, because the census
    charges the transfer rate whether or not a ticket was ever issued."

    Design: Difficulty/dual_variant_calc/meal_count_ledger_vs_census_billing
    """
    program = _riverbend_period_day()

    response = api.create_reconciliation(
        {
            "community_id": program["community"]["id"],
            "period_start_date": "2026-08-10",
            "period_end_date": "2026-08-10",
        },
        BILLING_SPECIALIST,
    )
    reconciliation = validate_success(response, 201)

    assert reconciliation["ticket_ledger_total_cents"] == 650
    assert reconciliation["census_projection_total_cents"] == 800
    assert reconciliation["variance_cents"] == -150
    assert reconciliation["pre_fee_base_cents"] == 650
    assert reconciliation["administrative_fee_cents"] == 39
    assert reconciliation["net_billable_total_cents"] == 689
    assert_reconciliation_waterfall(reconciliation)


def test_both_meal_count_maps_are_zero_filled_and_the_reservation_stays_reserved(api):
    """Each reading counts its own single row under `RESIDENT` with `GUEST` and `TAKEOUT`
    zero-filled, and the reservation that fed the census is still `RESERVED`.

    PRD: "`ledger_meal_counts` is the count of those tickets grouped by `ticket_type` with all
    three keys — `RESIDENT`, `GUEST` and `TAKEOUT` — always present and zero-filled."

    Design: Difficulty/dual_variant_calc/meal_count_ledger_vs_census_billing
    """
    program = _riverbend_period_day()

    reconciliation = create_reconciliation(
        program["community"]["id"], "2026-08-10", "2026-08-10"
    )

    assert reconciliation["ledger_meal_counts"] == {
        "RESIDENT": 1,
        "GUEST": 0,
        "TAKEOUT": 0,
    }
    assert reconciliation["census_meal_counts"] == {
        "RESIDENT": 1,
        "GUEST": 0,
        "TAKEOUT": 0,
    }
    assert read_reservation(program["reservation"]["id"])["status"] == "RESERVED"


def _northgate_ledger_of_3386():
    """Three unsponsored GUEST BREAKFAST tickets plus one walk-in RESIDENT LUNCH."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Northgate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Northgate Main Dining",
        seat_capacity=30,
        resident_name="Dee Marsh",
        baseline_weight_kg=66.0,
    )
    guests = []
    for _ in range(3):
        ticket = issue_ticket(
            program["venue"]["id"], "GUEST", "2026-08-10", "BREAKFAST"
        )
        serve_ticket(ticket["id"])
        guests.append(ticket)
    issue_and_serve_ticket(
        program["venue"]["id"],
        "RESIDENT",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )
    program["guest_tickets"] = guests
    return program


def test_administrative_fee_tier_is_keyed_on_the_pre_fee_base(api):
    """With a pre-fee base of 3386 the small tier applies, giving a fee of 203 and a net of
    3589 — not the 152 and 3538 that keying the tier on the net total would produce.

    PRD: "Step four selects the administrative fee tier **from `pre_fee_base_cents`**: the tier
    is small when `pre_fee_base_cents` is at most 3500, mid when it is at most 20000, and large
    above that."

    Design: Difficulty/combinatorial_formula/net_billable_fee_tier_keyed_on_pre_fee_base
    """
    program = _northgate_ledger_of_3386()

    response = api.create_reconciliation(
        {
            "community_id": program["community"]["id"],
            "period_start_date": "2026-08-10",
            "period_end_date": "2026-08-10",
        },
        BILLING_SPECIALIST,
    )
    reconciliation = validate_success(response, 201)

    assert reconciliation["ticket_ledger_total_cents"] == 3386
    assert reconciliation["void_credit_cents"] == 0
    assert reconciliation["pre_fee_base_cents"] == 3386
    assert reconciliation["administrative_fee_cents"] == 203
    assert reconciliation["administrative_fee_cents"] != 152
    assert reconciliation["net_billable_total_cents"] == 3589
    assert reconciliation["net_billable_total_cents"] != 3538


def test_unsponsored_guest_breakfast_prices_912_and_only_tickets_feed_the_census(api):
    """An unsponsored `GUEST` ticket takes no discount, so it bills 912; the census reading
    picks up the three guest tickets and nothing else, leaving a variance of 650.

    PRD: "A ticket is **sponsorship-eligible** when its `ticket_type` is `GUEST` or `TAKEOUT`,
    its `resident_id` is not null, and that resident's `dining_status` is `ACTIVE`."

    Design: Difficulty/combinatorial_formula/net_billable_fee_tier_keyed_on_pre_fee_base
    """
    program = _northgate_ledger_of_3386()

    assert program["guest_tickets"][0]["billed_amount_cents"] == 912

    reconciliation = create_reconciliation(
        program["community"]["id"], "2026-08-10", "2026-08-10"
    )

    assert reconciliation["census_projection_total_cents"] == 2736
    assert reconciliation["variance_cents"] == 650
    assert reconciliation["ledger_meal_counts"] == {
        "RESIDENT": 1,
        "GUEST": 3,
        "TAKEOUT": 0,
    }


def _ashgrove_served_day():
    """A community whose only served meal sits outside the reconciled period."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Ashgrove",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Ashgrove Main Dining",
        seat_capacity=10,
        resident_name="Nora Fielding",
        baseline_weight_kg=64.0,
    )
    setup_published_menu_cycle(
        program["community"]["id"],
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-16",
        items=[{"item_code": "REG-COD", "name": "Baked Cod"}],
    )
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:00:00Z",
        party_size=1,
    )
    seat_reservation(reservation["id"])
    tickets = tickets_for_reservation(reservation["id"])
    serve_ticket(tickets[0]["id"])
    return program


def test_empty_period_reports_zero_totals_and_zero_filled_counts(api):
    """A period holding no ticket and no reservation reconciles to zeros throughout the
    waterfall rather than to nulls or absent keys.

    PRD: "Step three computes `pre_fee_base_cents` as the gross figure minus the void credit,
    floored at 0."

    Design: Difficulty/boundary_precision_check/empty_period_reconciliation_zero_and_empty_counts
    """
    program = _ashgrove_served_day()

    response = api.create_reconciliation(
        {
            "community_id": program["community"]["id"],
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-08-05",
        },
        BILLING_SPECIALIST,
    )
    reconciliation = validate_success(response, 201)

    assert reconciliation["ticket_ledger_total_cents"] == 0
    assert reconciliation["census_projection_total_cents"] == 0
    assert reconciliation["variance_cents"] == 0
    assert reconciliation["void_credit_cents"] == 0
    assert reconciliation["pre_fee_base_cents"] == 0
    assert reconciliation["administrative_fee_cents"] == 0
    assert reconciliation["net_billable_total_cents"] == 0
    assert reconciliation["status"] == "RECONCILED"


def test_empty_period_still_carries_all_three_count_keys(api):
    """Both count maps are present and zero-filled even when the period matched nothing.

    PRD: "`census_meal_counts` reports the count of those reservations under the `RESIDENT`
    key, and the counts of the guest-and-takeout ticket set split into the `GUEST` and
    `TAKEOUT` keys."

    Design: Difficulty/boundary_precision_check/empty_period_reconciliation_zero_and_empty_counts
    """
    program = _ashgrove_served_day()

    reconciliation = create_reconciliation(
        program["community"]["id"], "2026-08-01", "2026-08-05"
    )

    assert reconciliation["ledger_meal_counts"] == {
        "RESIDENT": 0,
        "GUEST": 0,
        "TAKEOUT": 0,
    }
    assert reconciliation["census_meal_counts"] == {
        "RESIDENT": 0,
        "GUEST": 0,
        "TAKEOUT": 0,
    }
    assert_reconciliation_waterfall(reconciliation)


def _talloak_sponsored_guest_lunch():
    """A sponsored GUEST LUNCH ticket, served but never billed by a finalized period."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Talloak",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Talloak Main Dining",
        seat_capacity=10,
        resident_name="Ulla Berenson",
        baseline_weight_kg=59.0,
    )
    ticket = issue_ticket(
        program["venue"]["id"],
        "GUEST",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )
    served = serve_ticket(ticket["id"])
    program["ticket"] = served
    return program


def test_void_returns_the_sponsorship_balance_to_its_starting_value(api):
    """Issuing the sponsored guest meal raises the balance to 1173 and voiding it returns the
    balance to 0, conserving the charged amount across `billed` and `voided`.

    PRD: "The void copies the ticket's current `billed_amount_cents` into
    `voided_amount_cents` and then forces `billed_amount_cents` to 0, so the amount that was
    charged remains visible for audit while the live charge disappears."

    Design: Difficulty/compensating_invariant/community_billable_cents_issue_then_void
    """
    program = _talloak_sponsored_guest_lunch()
    assert program["community"]["guest_meal_sponsor_cap_cents"] == 20000
    assert program["ticket"]["billed_amount_cents"] == 1173
    assert program["ticket"]["status"] == "SERVED"
    assert (
        read_resident(program["resident"]["id"])["guest_meal_charge_balance_cents"]
        == 1173
    )

    response = api.void_meal_ticket(
        program["ticket"]["id"], {"void_reason": "guest never arrived"}, BILLING_SPECIALIST
    )
    voided = validate_success(response)

    assert voided["status"] == "VOIDED"
    assert voided["billed_amount_cents"] == 0
    assert voided["voided_amount_cents"] == 1173
    assert voided["billed_reconciliation_id"] is None
    assert (
        read_resident(program["resident"]["id"])["guest_meal_charge_balance_cents"] == 0
    )


def test_voiding_a_never_billed_ticket_raises_no_chargeback_credit(api):
    """The first reconciliation bills 1173 with a fee of 70; after the void a fresh
    reconciliation of the same period reads zero everywhere, including the void credit, because
    the ticket had never been billed.

    PRD: "Because the credit term is restricted to tickets a prior reconciliation already
    billed, voiding a never-billed ticket simply removes it from the first term without adding
    a credit."

    Design: Difficulty/compensating_invariant/community_billable_cents_issue_then_void
    """
    program = _talloak_sponsored_guest_lunch()
    first = create_reconciliation(program["community"]["id"], "2026-08-10", "2026-08-10")
    assert first["ticket_ledger_total_cents"] == 1173
    assert first["census_projection_total_cents"] == 1173
    assert first["variance_cents"] == 0
    assert first["pre_fee_base_cents"] == 1173
    assert first["administrative_fee_cents"] == 70
    assert first["net_billable_total_cents"] == 1243

    void_ticket(program["ticket"]["id"], "guest never arrived")

    second = create_reconciliation(
        program["community"]["id"], "2026-08-10", "2026-08-10"
    )
    assert second["ticket_ledger_total_cents"] == 0
    assert second["census_projection_total_cents"] == 0
    assert second["variance_cents"] == 0
    assert second["void_credit_cents"] == 0
    assert second["pre_fee_base_cents"] == 0
    assert second["administrative_fee_cents"] == 0
    assert second["net_billable_total_cents"] == 0

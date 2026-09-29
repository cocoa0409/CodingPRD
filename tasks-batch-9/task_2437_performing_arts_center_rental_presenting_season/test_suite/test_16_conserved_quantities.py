"""Two quantities that must still balance after a cancellation has moved their
individual terms: the capital reserve, which returns to exactly where it started,
and a tier's seat count, whose three claims move by different amounts.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    attach_education_program,
    book_presented_engagement,
    cancel,
    clear_presented_rider,
    confirm,
    create_subscription_package,
    negotiate_and_accept_fee,
    open_reserve_balance,
    put_on_sale,
    read_engagement,
    read_price_tier,
    register_artist,
    register_hall,
    sell_subscription_orders,
    sell_tickets,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

RESERVE_OPENING_CENTS = 10_000_000


def _draft_presented_engagement_with_two_funded_programs() -> dict:
    """A draft presented engagement carrying two funded education programs, one
    capped by its allowance and one funded at exactly what it asked for, drawn
    against a ten-million-cent reserve."""
    open_reserve_balance(RESERVE_OPENING_CENTS,
                        memo="FY27 capital and community programming reserve")
    space = register_hall()
    artist = register_artist(legal_name="Marrow & Vine Theatre",
                            agency_name="Northline Artists",
                            guarantee_floor_cents=100_000,
                            historical_sell_through_pct=0.60,
                            min_days_between_engagements=0)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Marrow & Vine: Company Season",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    matinee = attach_education_program(engagement["id"],
                                     program_type="STUDENT_MATINEE",
                                     participant_capacity=200,
                                     subsidy_requested_cents=1_000_000)
    masterclass = attach_education_program(engagement["id"],
                                          program_type="MASTERCLASS",
                                          participant_capacity=100,
                                          subsidy_requested_cents=250_000)
    return {"engagement": engagement, "matinee": matinee,
            "masterclass": masterclass}


def _two_on_sale_engagements_sharing_a_subscription_package() -> dict:
    """Two presented engagements on sale in one hall, spanned by a three-order
    subscription package, the first also carrying a thirty-seat single sale."""
    space = register_hall()
    first_artist = register_artist(legal_name="Kestrel String Trio",
                                  agency_name="Northline Artists",
                                  guarantee_floor_cents=100_000,
                                  historical_sell_through_pct=0.75,
                                  min_days_between_engagements=2)
    second_artist = register_artist(legal_name="Bellwether Jazz Orchestra",
                                   agency_name="Southgate Booking",
                                   guarantee_floor_cents=100_000,
                                   historical_sell_through_pct=0.70,
                                   min_days_between_engagements=2)
    first = book_presented_engagement(
        space["id"], first_artist["id"], title="Kestrel String Trio",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    second = book_presented_engagement(
        space["id"], second_artist["id"], title="Bellwether Jazz Orchestra",
        load_in_start_utc="2026-10-05T08:00:00Z",
        performance_start_utc="2026-10-06T19:00:00Z",
        performance_end_utc="2026-10-06T22:00:00Z",
        load_out_end_utc="2026-10-07T02:00:00Z")
    clear_presented_rider(first["id"], first_artist["id"],
                          submitted_rigging_kg=1_000, requested_power_amps=200,
                          requested_dmx_universes=1)
    clear_presented_rider(second["id"], second_artist["id"],
                          submitted_rigging_kg=1_500, requested_power_amps=250,
                          requested_dmx_universes=2)
    first_tier = add_price_tier(first["id"], tier_name="ORCH",
                               seats_allocated=100, base_price_cents=7_000,
                               price_ceiling_cents=9_000,
                               dynamic_pricing_enabled=False,
                               subscription_eligible=True)
    second_tier = add_price_tier(second["id"], tier_name="ORCH",
                                seats_allocated=200, base_price_cents=12_000,
                                price_ceiling_cents=15_000,
                                dynamic_pricing_enabled=False,
                                subscription_eligible=True)
    negotiate_and_accept_fee(first["id"], first_artist["id"], 300_000, 0.10)
    first_assessed = assess_risk(first["id"])
    assert first_assessed["projected_gross_cents"] == 525_000
    assert first_assessed["risk_score"] == 38
    assert first_assessed["financial_clearance"] == "CLEARED"
    confirm(first["id"])
    put_on_sale(first["id"])

    negotiate_and_accept_fee(second["id"], second_artist["id"], 400_000, 0.10)
    second_assessed = assess_risk(second["id"])
    assert second_assessed["projected_gross_cents"] == 1_680_000
    assert second_assessed["risk_score"] == 23
    assert second_assessed["financial_clearance"] == "CLEARED"
    confirm(second["id"])
    put_on_sale(second["id"])

    single_sale = sell_tickets(first_tier["id"], 30, "WEB")
    assert single_sale["gross_cents"] == 210_000
    package = create_subscription_package([first["id"], second["id"]])
    sold = sell_subscription_orders(package["id"], 3)
    return {"first": first, "second": second, "first_tier": first_tier,
            "second_tier": second_tier, "single_sale": single_sale,
            "package": package, "sold_package": sold}


class TestReserveBalanceConservedAcrossDrawsAndRefunds:

    def test_each_funded_program_debits_the_reserve_by_its_approved_subsidy(self):
        """The matinee asks for more than its allowance and is funded at the
        allowance; the masterclass asks for less than its own and is funded at what
        it asked for. Each approval debits the reserve immediately and the second
        draw reads the balance the first one left, so the two entries step down in
        sequence rather than both measuring from the opening balance.

        PRD: "When the guard passes, the program is created in `FUNDED` status and
        a reserve entry of type `EDUCATION_SUBSIDY_DRAW` is appended, carrying
        `amount_cents` equal to the approved subsidy negated, the causing
        `engagement_id`, and a recomputed `balance_after_cents`."

        Design: Difficulty/compensating_invariant/reserve_balance_conserved_across_subsidy_draws_and_cancellation_refunds
        """
        scenario = _draft_presented_engagement_with_two_funded_programs()
        assert scenario["matinee"]["status"] == "FUNDED"
        assert scenario["matinee"]["subsidy_approved_cents"] == 700_000
        assert scenario["masterclass"]["status"] == "FUNDED"
        assert scenario["masterclass"]["subsidy_approved_cents"] == 250_000

        caused, caused_meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(
                scenario["engagement"]["id"], FINANCE))
        assert caused_meta["total_count"] == 2
        assert [entry["entry_type"] for entry in caused] == \
            ["EDUCATION_SUBSIDY_DRAW", "EDUCATION_SUBSIDY_DRAW"]
        assert [entry["amount_cents"] for entry in caused] == [-700_000, -250_000]
        assert [entry["balance_after_cents"] for entry in caused] == \
            [9_300_000, 9_050_000]

        whole_ledger, ledger_meta = validate_paginated(
            api_client.list_reserve_ledger_entries(ADMIN, {"limit": 100}))
        assert ledger_meta["total_count"] == 3
        assert whole_ledger[0]["entry_type"] == "OPENING_BALANCE"
        assert whole_ledger[0]["engagement_id"] is None
        assert whole_ledger[0]["balance_after_cents"] == RESERVE_OPENING_CENTS

    def test_cancelling_refunds_both_subsidies_and_the_balance_returns_exactly(self):
        """Cancelling before confirmation gives every drawn cent back, one credit
        per program in the order the programs were created, and the running balance
        climbs back through the mirror image of the two draws to exactly the opening
        figure. The programs keep their approved amounts on the way to their
        terminal state — the refund lives in the ledger, not by erasing history.

        PRD: "one reserve entry of type `EDUCATION_SUBSIDY_REFUND` is appended per
        program, carrying `amount_cents` equal to that program's
        `subsidy_approved_cents` as a positive credit, appended in the programs'
        `created_at` ascending order, each entry recomputing `balance_after_cents`
        in turn."

        Design: Difficulty/compensating_invariant/reserve_balance_conserved_across_subsidy_draws_and_cancellation_refunds
        """
        scenario = _draft_presented_engagement_with_two_funded_programs()
        engagement_id = scenario["engagement"]["id"]

        cancelled = cancel(engagement_id, DIRECTOR,
                           reason="Company visa denied")
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 0

        programs, programs_meta = validate_paginated(
            api_client.list_engagement_education_programs(engagement_id,
                                                         DIRECTOR))
        assert programs_meta["total_count"] == 2
        by_id = {program["id"]: program for program in programs}
        matinee_after = by_id[scenario["matinee"]["id"]]
        masterclass_after = by_id[scenario["masterclass"]["id"]]
        assert matinee_after["status"] == "CANCELLED_WITH_ENGAGEMENT"
        assert matinee_after["subsidy_approved_cents"] == 700_000
        assert masterclass_after["status"] == "CANCELLED_WITH_ENGAGEMENT"
        assert masterclass_after["subsidy_approved_cents"] == 250_000

        caused, caused_meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(engagement_id,
                                                              FINANCE))
        assert caused_meta["total_count"] == 4
        assert [entry["entry_type"] for entry in caused] == [
            "EDUCATION_SUBSIDY_DRAW", "EDUCATION_SUBSIDY_DRAW",
            "EDUCATION_SUBSIDY_REFUND", "EDUCATION_SUBSIDY_REFUND"]
        assert [entry["amount_cents"] for entry in caused] == [
            -700_000, -250_000, 700_000, 250_000]
        assert [entry["balance_after_cents"] for entry in caused] == [
            9_300_000, 9_050_000, 9_750_000, 10_000_000]
        assert caused[-1]["balance_after_cents"] == RESERVE_OPENING_CENTS


class TestSeatConservationAcrossRefundsAndSubscriptionHolds:

    def test_the_seat_identity_still_closes_when_only_the_single_sales_refund(self):
        """The cancellation returns the thirty single-sale seats to availability but
        deliberately leaves the six subscription-held seats where they are, so the
        three terms of the seat identity move by different amounts and the identity
        still closes at a hundred. The refunded sale keeps its historical gross even
        though the tier's own single-sale revenue is reversed.

        PRD: "That is deliberate, and it is what keeps the seat identity intact
        after cancellation — `seats_allocated` still equals `available_qty` plus
        `sold_qty` plus `subscription_held_qty` once the refunded single sales have
        released their seats."

        Design: Difficulty/compensating_invariant/price_tier_seat_conservation_across_sales_subscription_holds_and_refunds
        """
        scenario = _two_on_sale_engagements_sharing_a_subscription_package()
        first_id = scenario["first"]["id"]

        before = read_price_tier(scenario["first_tier"]["id"])
        assert before["sold_qty"] == 30
        assert before["subscription_held_qty"] == 6
        assert before["available_qty"] == 64

        cancelled = cancel(first_id, DIRECTOR, reason="Violist injured on tour")
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["ticketing_status"] == "CLOSED"
        assert cancelled["cancellation_fee_cents"] == 120_000

        after = read_price_tier(scenario["first_tier"]["id"])
        assert after["seats_allocated"] == 100
        assert after["sold_qty"] == 0
        assert after["subscription_held_qty"] == 6
        assert after["available_qty"] == 94
        assert after["seats_allocated"] == (after["available_qty"]
                                           + after["sold_qty"]
                                           + after["subscription_held_qty"])
        assert after["status"] == "CLOSED"
        assert after["gross_cents"] == 0
        assert after["subscription_revenue_cents"] == 110_529

        sales, sales_meta = validate_paginated(api_client.list_tier_ticket_sales(
            scenario["first_tier"]["id"], BOX_OFFICE))
        assert sales_meta["total_count"] == 1
        assert sales[0]["status"] == "REFUNDED"
        assert sales[0]["gross_cents"] == 210_000

        assert read_engagement(first_id)["realized_gross_cents"] == 110_529

    def test_the_package_price_stays_whole_and_the_sibling_keeps_its_seats(self):
        """The truncated per-order shares would have lost a cent, so the remainder
        goes to the earliest engagement's tier and three orders book exactly three
        times the package price across the two houses. Cancelling one member of the
        package leaves the other's seats, revenue and dimensions entirely alone.

        PRD: "so a remainder is computed as `package_price_cents` less the sum of
        the truncated allocations, and the whole remainder is added to the
        **first** tier in the pinned ordering — never spread, never given to the
        largest tier."

        Design: Difficulty/compensating_invariant/price_tier_seat_conservation_across_sales_subscription_holds_and_refunds
        """
        scenario = _two_on_sale_engagements_sharing_a_subscription_package()
        first_id = scenario["first"]["id"]
        second_id = scenario["second"]["id"]

        allocation = scenario["package"]["allocation_map"]
        assert allocation[first_id] == 36_843
        assert allocation[second_id] == 63_157
        assert allocation[first_id] + allocation[second_id] == 100_000
        assert scenario["sold_package"]["sold_count"] == 3

        cancel(first_id, DIRECTOR, reason="Violist injured on tour")

        first_tier_after = read_price_tier(scenario["first_tier"]["id"])
        second_tier_after = read_price_tier(scenario["second_tier"]["id"])
        assert first_tier_after["subscription_revenue_cents"] == 110_529
        assert second_tier_after["subscription_revenue_cents"] == 189_471
        assert (first_tier_after["subscription_revenue_cents"]
                + second_tier_after["subscription_revenue_cents"]) == 300_000

        assert second_tier_after["seats_allocated"] == 200
        assert second_tier_after["sold_qty"] == 0
        assert second_tier_after["subscription_held_qty"] == 6
        assert second_tier_after["available_qty"] == 194
        assert second_tier_after["status"] == "ACTIVE"

        sibling = read_engagement(second_id)
        assert sibling["lifecycle_status"] == "CONFIRMED"
        assert sibling["ticketing_status"] == "ON_SALE"
        assert sibling["realized_gross_cents"] == 189_471

        statement = validate_success(
            api_client.get_box_office_statement(second_id, BOX_OFFICE))
        assert statement["subscription_held_qty_total"] == 6
        assert statement["subscription_revenue_cents"] == 189_471

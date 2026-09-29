"""Two multi-hop cascades where a later hop consumes an earlier hop's output: the
cancellation that releases commitments before recomputing the deposit that
depended on them, and the finalization that appends to the capital reserve before
paying the artist.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    attach_education_program,
    book_presented_engagement,
    book_rental_engagement,
    call_crew,
    cancel,
    clear_presented_rider,
    clear_rider,
    confirm,
    finalize_settlement_as,
    make_rental_client_contact_headers,
    negotiate_and_accept_fee,
    open_reserve_balance,
    open_settlement,
    put_on_sale,
    read_engagement,
    reconcile_expenses,
    record_deposit,
    register_artist,
    register_equipment_item,
    register_hall,
    register_rental_client,
    register_union_department,
    report_hours,
    reserve_equipment_line,
    review_rider,
    sell_tickets,
    set_clock,
    submit_rider,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

CASCADE_CONTROLLER_USER_ID = "user-finance-7"


def _confirmed_rental_with_labor_and_equipment_committed() -> dict:
    """A CONFIRMED two-performance-day rental whose deposit requirement climbed
    from 300,000 to 430,000 as a crew call and a gap-covering equipment line were
    committed, with 430,000 actually on hand."""
    space = register_hall()
    client = register_rental_client(org_name="Harbor Ballet Academy",
                                   contact_email="rentals@harborballet.example",
                                   credit_rating="A",
                                   outstanding_balance_cents=10_000)
    department = register_union_department(department="STAGEHANDS",
                                          roster_size=30,
                                          straight_hourly_rate_cents=5_000)
    item = register_equipment_item(category="POWER_DISTRO",
                                   model_name="400A Company Switch Cart",
                                   on_hand_qty=5, daily_rate_cents=25_000,
                                   replacement_value_cents=4_000_000)
    engagement = book_rental_engagement(
        space["id"], client["id"], title="Harbor Ballet: Nutcracker Rental",
        performance_day_count=2, load_in_day_count=1)
    assert engagement["facility_fee_cents"] == 1_200_000
    assert engagement["deposit_required_cents"] == 300_000

    call = call_crew(engagement["id"], department["id"], crew_size=4,
                     call_start_utc="2026-10-01T08:00:00Z",
                     call_end_utc="2026-10-01T14:00:00Z")
    assert call["estimated_cost_cents"] == 120_000
    assert read_engagement(engagement["id"])["deposit_required_cents"] == 330_000

    rider = submit_rider(engagement["id"],
                         make_rental_client_contact_headers(client["id"]),
                         submitted_rigging_kg=3_000, requested_power_amps=500,
                         requested_dmx_universes=2)
    reviewed = review_rider(rider["id"])
    assert reviewed["review_status"] == "GAP_IDENTIFIED"
    line = reserve_equipment_line(rider["id"], item["id"],
                                  covers_gap="POWER_SHORTFALL", qty=2,
                                  rental_days=2)
    cleared = clear_rider(rider["id"])
    assert cleared["additional_equipment_cost_cents"] == 100_000

    paid = record_deposit(engagement["id"], 430_000)
    assert paid["deposit_required_cents"] == 430_000
    assert paid["deposit_paid_cents"] == 430_000

    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 10
    assert assessed["financial_clearance"] == "CLEARED"
    confirmed = confirm(engagement["id"], RENTAL_MANAGER)
    assert confirmed["lifecycle_status"] == "CONFIRMED"
    return {"client": client, "engagement": engagement, "item": item,
            "rider": rider, "call": call, "line": line}


def _reconciled_presented_settlement_over_a_used_reserve() -> dict:
    """A presented night reconciled to a 83,700-cent reserve contribution, sitting
    on a ledger that already holds an opening balance and an education draw."""
    space = register_hall()
    open_reserve_balance(8_000_000,
                         memo="FY27 capital and equipment reserve opening balance")
    artist = register_artist(legal_name="Aurora Chamber Players",
                            agency_name="Northline Artists",
                            guarantee_floor_cents=1_000_000,
                            historical_sell_through_pct=0.80)
    department = register_union_department(roster_size=20,
                                          straight_hourly_rate_cents=5_000)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Aurora Chamber Players in Recital",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    program = attach_education_program(engagement["id"],
                                      program_type="STUDENT_MATINEE",
                                      participant_capacity=200,
                                      subsidy_requested_cents=1_000_000)
    assert program["status"] == "FUNDED"
    assert program["subsidy_approved_cents"] == 700_000

    clear_presented_rider(engagement["id"], artist["id"],
                          submitted_rigging_kg=3_000, requested_power_amps=300,
                          requested_dmx_universes=2)
    tier = add_price_tier(engagement["id"], tier_name="ORCH",
                          seats_allocated=500, base_price_cents=8_000,
                          price_ceiling_cents=12_000,
                          dynamic_pricing_enabled=False,
                          subscription_eligible=False)
    negotiate_and_accept_fee(engagement["id"], artist["id"], 1_500_000, 0.10)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 33
    assert assessed["financial_clearance"] == "CLEARED"
    confirm(engagement["id"])
    put_on_sale(engagement["id"])
    sell_tickets(tier["id"], 300, "WINDOW")
    call = call_crew(engagement["id"], department["id"], crew_size=4,
                     call_start_utc="2026-10-01T08:00:00Z",
                     call_end_utc="2026-10-01T14:00:00Z")
    worked = report_hours(call["id"], 6, True)
    assert worked["status"] == "WORKED"
    set_clock("2026-10-03T00:00:00Z")
    settlement = open_settlement(engagement["id"])
    settlement = reconcile_expenses(settlement["id"], 180_000)
    assert settlement["reserve_contribution_cents"] == 83_700
    assert settlement["amount_payable_to_artist_cents"] == 1_566_000
    return {"artist": artist, "engagement": engagement, "program": program,
            "call": call, "settlement": settlement}


class TestCancellationReverseCascade:

    def test_the_deposit_is_recomputed_only_after_the_commitments_are_released(self):
        """Cancelling a confirmed rental cancels the crew call, releases the
        equipment line and zeroes both equipment aggregates before the deposit
        requirement is rebuilt, so the requirement falls all the way back to the
        bare facility fee's quarter. A requirement of 430,000 would mean it was
        never rebuilt, 400,000 that it was rebuilt from the pre-release equipment
        cost and 330,000 that the cancelled call still counted.

        PRD: "`labor_estimate_total_cents` re-derived over the calls whose
        `status` is `ESTIMATED`, `WORKED` or `RECONCILED`, and
        `deposit_required_cents` recomputed exactly once after both of those
        inputs settle, for a rental engagement only."

        Design: Difficulty/transitive_cascade/engagement_cancel_reverse_cascade_to_deposit_and_client_balance
        """
        scenario = _confirmed_rental_with_labor_and_equipment_committed()
        engagement_id = scenario["engagement"]["id"]

        cancelled = cancel(engagement_id,
                           reason="Client withdrew the production",
                           cancelled_by_client=True)
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["ticketing_status"] == "CLOSED"

        calls, calls_meta = validate_paginated(
            api_client.list_engagement_labor_calls(engagement_id, TECH_DIRECTOR))
        assert calls_meta["total_count"] == 1
        assert calls[0]["status"] == "CANCELLED"

        lines, lines_meta = validate_paginated(
            api_client.list_rider_equipment_lines(scenario["rider"]["id"],
                                                  TECH_DIRECTOR))
        assert lines_meta["total_count"] == 1
        assert lines[0]["status"] == "RELEASED"
        item_after = validate_success(
            api_client.get_equipment_item(scenario["item"]["id"], ADMIN))
        assert item_after["reserved_qty"] == 0

        rider_after = validate_success(
            api_client.get_tech_rider(scenario["rider"]["id"], TECH_DIRECTOR))
        assert rider_after["review_status"] == "CLEARED"
        assert rider_after["additional_equipment_cost_cents"] == 0

        after = read_engagement(engagement_id)
        assert after["labor_estimate_total_cents"] == 0
        assert after["additional_equipment_cost_cents"] == 0
        assert after["deposit_required_cents"] == 300_000

    def test_the_retained_fee_reaches_the_client_ledger_net_of_the_deposit(self):
        """The last hop leaves the engagement altogether. Two months out the
        center retains forty percent of the hall billing, and because 430,000 was
        already banked the client is billed only the 50,000 difference on top of
        the 10,000 it already owed. The deposit ledger itself is not rewritten.

        PRD: "for a rental engagement the client's `outstanding_balance_cents` is
        increased by the engagement's `cancellation_fee_cents` less its
        `deposit_paid_cents`; where the deposit already on hand exceeds the
        retained fee the result is negative, and the client is credited rather
        than billed."

        Design: Difficulty/transitive_cascade/engagement_cancel_reverse_cascade_to_deposit_and_client_balance
        """
        scenario = _confirmed_rental_with_labor_and_equipment_committed()
        engagement_id = scenario["engagement"]["id"]

        cancelled = cancel(engagement_id,
                           reason="Client withdrew the production",
                           cancelled_by_client=True)
        assert cancelled["cancellation_fee_cents"] == 480_000
        assert cancelled["deposit_paid_cents"] == 430_000

        client_after = validate_success(api_client.get_rental_client(
            scenario["client"]["id"], FINANCE))
        assert client_after["outstanding_balance_cents"] == 60_000

        after = read_engagement(engagement_id)
        assert after["deposit_paid_cents"] == 430_000
        assert after["cancellation_fee_cents"] == 480_000
        assert after["lifecycle_status"] == "CANCELLED"


class TestFinalizationForwardCascade:

    def test_finalizing_settles_the_booking_reconciles_the_crew_and_pays_the_agency(self):
        """One finalization moves four things in order: the settlement closes
        under the acting controller's name, the booking reaches its terminal state
        carrying the realized margin, the worked call is promoted to its own
        terminal state, and the guarantee plus the overage share lands on the
        artist's lifetime payout counter.

        PRD: "Because that contribution posted, the counterparty ledger moves
        next: for a presented engagement the artist's
        `lifetime_guarantee_paid_cents` increases by the settlement's
        `amount_payable_to_artist_cents`"

        Design: Difficulty/transitive_cascade/settlement_finalize_forward_cascade_into_reserve_and_artist_ledger
        """
        scenario = _reconciled_presented_settlement_over_a_used_reserve()
        engagement_id = scenario["engagement"]["id"]

        finalized = finalize_settlement_as(scenario["settlement"]["id"],
                                           CASCADE_CONTROLLER_USER_ID)
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_by_user_id"] == CASCADE_CONTROLLER_USER_ID

        after = read_engagement(engagement_id)
        assert after["lifecycle_status"] == "SETTLED"
        assert after["realized_margin_cents"] == 534_000

        calls, calls_meta = validate_paginated(
            api_client.list_engagement_labor_calls(engagement_id, FINANCE))
        assert calls_meta["total_count"] == 1
        assert calls[0]["status"] == "RECONCILED"

        artist_after = validate_success(
            api_client.get_artist(scenario["artist"]["id"], DIRECTOR))
        assert artist_after["lifetime_guarantee_paid_cents"] == 1_566_000

        settlements, settlements_meta = validate_paginated(
            api_client.list_engagement_settlements(engagement_id, FINANCE))
        assert settlements_meta["total_count"] == 1
        assert settlements[0]["status"] == "FINALIZED"

    def test_the_contribution_stacks_on_the_balance_the_education_draw_left(self):
        """The reserve is append-only and its running balance accumulates: the
        contribution lands on top of an opening credit and an education debit, so
        it reads 7,383,700 rather than 83,700. The funded program is untouched —
        only cancellation refunds a subsidy.

        PRD: "Because the settlement produced a reserve contribution, a reserve
        entry of type `SETTLEMENT_CONTRIBUTION` is appended with `amount_cents`
        equal to the settlement's `reserve_contribution_cents` and a recomputed
        `balance_after_cents`."

        Design: Difficulty/transitive_cascade/settlement_finalize_forward_cascade_into_reserve_and_artist_ledger
        """
        scenario = _reconciled_presented_settlement_over_a_used_reserve()
        engagement_id = scenario["engagement"]["id"]

        finalize_settlement_as(scenario["settlement"]["id"],
                               CASCADE_CONTROLLER_USER_ID)

        entries, entries_meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(engagement_id,
                                                              FINANCE))
        assert entries_meta["total_count"] == 2
        draw, contribution = entries
        assert draw["entry_type"] == "EDUCATION_SUBSIDY_DRAW"
        assert draw["amount_cents"] == -700_000
        assert draw["balance_after_cents"] == 7_300_000
        assert contribution["entry_type"] == "SETTLEMENT_CONTRIBUTION"
        assert contribution["amount_cents"] == 83_700
        assert contribution["balance_after_cents"] == 7_383_700

        programs, programs_meta = validate_paginated(
            api_client.list_engagement_education_programs(engagement_id,
                                                         DIRECTOR))
        assert programs_meta["total_count"] == 1
        assert programs[0]["status"] == "FUNDED"
        assert programs[0]["subsidy_approved_cents"] == 700_000

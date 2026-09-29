"""Two named calculations that answer differently depending on which variant the
caller stands in: a labor call's estimate against its actual reckoning, and an
engagement's forward-looking margin against the one settled after the fact.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    call_crew,
    clear_presented_rider,
    clear_rental_rider,
    confirm,
    finalize_settlement_as,
    negotiate_and_accept_fee,
    open_settlement,
    put_on_sale,
    read_engagement,
    read_price_tier,
    reconcile_expenses,
    record_deposit,
    register_artist,
    register_hall,
    register_rental_client,
    register_union_department,
    report_hours,
    sell_tickets,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

FINALIZING_CONTROLLER_USER_ID = "user-finance-1"


def _confirmed_rental_with_a_ten_hour_crew_of_six() -> dict:
    """A CONFIRMED rental engagement carrying one ESTIMATED ten-hour call for a
    crew of six, so hours may be reported against it."""
    space = register_hall()
    client = register_rental_client(credit_rating="A",
                                    outstanding_balance_cents=0)
    department = register_union_department(
        department="STAGEHANDS", roster_size=20,
        straight_hourly_rate_cents=5_000, overtime_multiplier=1.5,
        doubletime_multiplier=2.0, call_minimum_hours=4,
        meal_penalty_cents=3_500)
    engagement = book_rental_engagement(space["id"], client["id"],
                                        title="Meridian Dance: Northbound")
    assert engagement["facility_fee_cents"] == 700_000
    call = call_crew(engagement["id"], department["id"], crew_size=6,
                     call_start_utc="2026-10-01T08:00:00Z",
                     call_end_utc="2026-10-01T18:00:00Z")
    clear_rental_rider(engagement["id"], client["id"],
                       submitted_rigging_kg=3_000, requested_power_amps=300,
                       requested_dmx_universes=2)
    record_deposit(engagement["id"], 257_500)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 10
    assert assessed["financial_clearance"] == "CLEARED"
    confirmed = confirm(engagement["id"], RENTAL_MANAGER)
    assert confirmed["lifecycle_status"] == "CONFIRMED"
    return {"engagement": engagement, "call": call, "department": department}


def _presented_night_reconciled_at_three_hundred_seats(
        sale_channel: str = "WEB") -> dict:
    """A presented engagement carried from projection to a reconciled
    settlement: 500 seats offered at 8,000, 300 of them sold, one worked call
    and 180,000 of reconciled marketing."""
    space = register_hall()
    artist = register_artist(legal_name="Aurora Chamber Players",
                            agency_name="Northline Artists",
                            guarantee_floor_cents=1_000_000,
                            historical_sell_through_pct=0.80)
    department = register_union_department(roster_size=20,
                                          straight_hourly_rate_cents=5_000)
    engagement = book_presented_engagement(
        space["id"], artist["id"],
        title="Aurora Chamber Players in Recital",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    clear_presented_rider(engagement["id"], artist["id"],
                          submitted_rigging_kg=3_000, requested_power_amps=300,
                          requested_dmx_universes=2)
    tier = add_price_tier(engagement["id"], tier_name="ORCH",
                          seats_allocated=500, base_price_cents=8_000,
                          price_ceiling_cents=12_000,
                          dynamic_pricing_enabled=False,
                          subscription_eligible=True)
    negotiate_and_accept_fee(engagement["id"], artist["id"], 1_500_000, 0.10)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 33
    assert assessed["financial_clearance"] == "CLEARED"
    confirm(engagement["id"])
    on_sale = put_on_sale(engagement["id"])
    sell_tickets(tier["id"], 300, sale_channel)
    call = call_crew(engagement["id"], department["id"], crew_size=4,
                     call_start_utc="2026-10-01T08:00:00Z",
                     call_end_utc="2026-10-01T14:00:00Z")
    worked = report_hours(call["id"], 6, True)
    assert worked["actual_cost_cents"] == 120_000
    set_clock("2026-10-03T00:00:00Z")
    settlement = open_settlement(engagement["id"])
    settlement = reconcile_expenses(settlement["id"], 180_000)
    return {
        "space": space,
        "artist": artist,
        "engagement": engagement,
        "tier": tier,
        "call": call,
        "on_sale": on_sale,
        "settlement": settlement,
    }


class TestLaborCallEstimateVersusActual:

    def test_the_actual_reckoning_exceeds_the_estimate_by_the_meal_penalty_alone(self):
        """The call is scheduled for ten hours and worked for ten hours, so both
        variants tier the same hour count into the same bands. The only surviving
        difference is the penalty the actual variant charges for the break that
        was never taken: 3,500 a head across a crew of six.

        PRD: "for two calls of identical duration, the actual cost exceeds the
        estimate by exactly `meal_penalty_cents` multiplied by `crew_size` when a
        break was skipped, and equals it otherwise."

        Design: Difficulty/dual_variant_calc/labor_call_estimate_vs_actual_meal_penalty_divergence
        """
        scenario = _confirmed_rental_with_a_ten_hour_crew_of_six()
        call = scenario["call"]
        assert call["status"] == "ESTIMATED"
        assert call["scheduled_hours"] == pytest.approx(10, abs=0.01)
        assert call["estimated_cost_cents"] == 330_000
        assert call["actual_cost_cents"] == 0

        worked = validate_success(api_client.report_labor_hours(
            call["id"], {"actual_hours": 10, "meal_break_taken": False},
            TECH_DIRECTOR))
        assert worked["status"] == "WORKED"
        assert worked["actual_hours"] == pytest.approx(10, abs=0.01)
        assert worked["meal_break_taken"] is False
        assert worked["actual_cost_cents"] == 351_000
        assert worked["estimated_cost_cents"] == 330_000
        assert worked["actual_cost_cents"] - worked["estimated_cost_cents"] == \
            3_500 * 6

    def test_the_estimate_aggregate_and_the_deposit_ignore_the_actual_figure(self):
        """The engagement's labor aggregate and the deposit it feeds are built
        from the estimate variant, so a worked cost of 351,000 leaves both
        standing at the 330,000 estimate. The actual variant is written once:
        a second report against the worked call is refused.

        PRD: "`Engagement.labor_estimate_total_cents` is re-derived as the sum of
        `estimated_cost_cents` over the engagement's calls whose `status` is
        `ESTIMATED`, `WORKED` or `RECONCILED`"

        Design: Difficulty/dual_variant_calc/labor_call_estimate_vs_actual_meal_penalty_divergence
        """
        scenario = _confirmed_rental_with_a_ten_hour_crew_of_six()
        engagement_id = scenario["engagement"]["id"]
        call = scenario["call"]

        before = read_engagement(engagement_id)
        assert before["labor_estimate_total_cents"] == 330_000
        assert before["deposit_required_cents"] == 257_500
        assert before["deposit_paid_cents"] == 257_500

        worked = report_hours(call["id"], 10, False)
        assert worked["actual_cost_cents"] == 351_000

        after = read_engagement(engagement_id)
        assert after["labor_estimate_total_cents"] == 330_000
        assert after["deposit_required_cents"] == 257_500
        assert after["deposit_paid_cents"] == 257_500

        drawn, meta = validate_paginated(api_client.list_department_labor_calls(
            scenario["department"]["id"], TECH_DIRECTOR))
        assert meta["total_count"] == 1
        assert drawn[0]["id"] == call["id"]
        assert drawn[0]["actual_cost_cents"] == 351_000

        validate_error(api_client.report_labor_hours(
            call["id"], {"actual_hours": 10, "meal_break_taken": False},
            TECH_DIRECTOR), "ERR_LABOR_CALL_INVALID_STATE")
        assert read_engagement(engagement_id)["labor_estimate_total_cents"] == \
            330_000


class TestProjectedVersusRealizedMargin:

    def test_the_realized_margin_lands_beside_the_projection_it_diverges_from(self):
        """The projection was taken from 500 allocated seats at an 0.80
        historical sell-through against a flat marketing allowance; the realized
        reckoning reads 300 actual sales, the artist's overage share, the labor
        the projection never saw and the marketing actually reconciled. Both
        figures survive on the engagement, so the 916,000 divergence is readable
        in one row.

        PRD: "it uses actual sales rather than historical sell-through, and it
        uses the reconciled marketing figure rather than the flat allowance, so
        the two variants diverge whenever real sell-through differs from
        historical sell-through or reconciled marketing differs from $2,500."

        Design: Difficulty/dual_variant_calc/engagement_margin_projected_vs_realized_input_set_divergence
        """
        scenario = _presented_night_reconciled_at_three_hundred_seats()
        assert scenario["on_sale"]["projected_gross_cents"] == 3_200_000
        assert scenario["on_sale"]["projected_margin_cents"] == 1_450_000
        assert scenario["settlement"]["artist_share_cents"] == 66_000
        assert scenario["settlement"]["actual_labor_cents"] == 120_000
        assert scenario["settlement"]["actual_marketing_cents"] == 180_000

        finalized = finalize_settlement_as(scenario["settlement"]["id"],
                                           FINALIZING_CONTROLLER_USER_ID)
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_by_user_id"] == FINALIZING_CONTROLLER_USER_ID

        after = read_engagement(scenario["engagement"]["id"])
        assert after["projected_gross_cents"] == 3_200_000
        assert after["projected_margin_cents"] == 1_450_000
        assert after["realized_gross_cents"] == 2_400_000
        assert after["realized_margin_cents"] == 534_000
        assert after["projected_margin_cents"] - after["realized_margin_cents"] \
            == 916_000

    def test_finalizing_the_realized_variant_closes_the_house_and_pays_the_artist(self):
        """Writing the realized margin is one step of a cascade: the booking
        reaches its terminal state with the box office closed behind it, the
        worked call is reconciled, the guarantee plus the overage share lands on
        the artist's lifetime total, and the center's share of the night is swept
        into the reserve as a single entry.

        PRD: "Every labor call of the engagement whose `status` is `WORKED` is
        then moved to the terminal `RECONCILED`, each incrementing its own
        `version` by 1."

        Design: Difficulty/dual_variant_calc/engagement_margin_projected_vs_realized_input_set_divergence
        """
        scenario = _presented_night_reconciled_at_three_hundred_seats()
        engagement_id = scenario["engagement"]["id"]

        finalized = finalize_settlement_as(scenario["settlement"]["id"],
                                           FINALIZING_CONTROLLER_USER_ID)
        assert finalized["reserve_contribution_cents"] == 83_700
        assert finalized["amount_payable_to_artist_cents"] == 1_566_000

        after = read_engagement(engagement_id)
        assert after["lifecycle_status"] == "SETTLED"
        assert after["ticketing_status"] == "CLOSED"

        tier_after = read_price_tier(scenario["tier"]["id"])
        assert tier_after["status"] == "CLOSED"
        assert tier_after["sold_qty"] == 300
        assert tier_after["gross_cents"] == 2_400_000

        calls, calls_meta = validate_paginated(
            api_client.list_engagement_labor_calls(engagement_id, FINANCE))
        assert calls_meta["total_count"] == 1
        assert calls[0]["status"] == "RECONCILED"

        artist_after = validate_success(
            api_client.get_artist(scenario["artist"]["id"], DIRECTOR))
        assert artist_after["lifetime_guarantee_paid_cents"] == 1_566_000

        entries, entries_meta = validate_paginated(
            api_client.list_engagement_reserve_ledger_entries(engagement_id,
                                                              FINANCE))
        assert entries_meta["total_count"] == 1
        assert entries[0]["entry_type"] == "SETTLEMENT_CONTRIBUTION"
        assert entries[0]["amount_cents"] == 83_700
        assert entries[0]["balance_after_cents"] == 83_700

"""Two calculations whose answer depends on the order in which rounding,
aggregation and capping are combined: the per-component labor rounding that
precedes the crew multiplication, and the settlement waterfall whose every step
consumes the previous step's output.
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
    clear_rental_rider,
    clear_rider,
    confirm,
    make_artist_representative_headers,
    negotiate_and_accept_fee,
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

RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


def _confirmed_rental_with_an_odd_electrics_rate() -> dict:
    """A CONFIRMED rental engagement and an ELECTRICS card at 4,445 cents an
    hour — a rate whose overtime component lands on a half cent."""
    space = register_hall()
    client = register_rental_client(org_name="Copper Street Brass",
                                    contact_email="ops@copperstreet.example",
                                    credit_rating="A",
                                    outstanding_balance_cents=0)
    department = register_union_department(
        department="ELECTRICS", roster_size=12,
        straight_hourly_rate_cents=4_445, overtime_multiplier=1.5,
        doubletime_multiplier=2.0, call_minimum_hours=4,
        meal_penalty_cents=3_500)
    engagement = book_rental_engagement(space["id"], client["id"],
                                        title="Copper Street Brass")
    assert engagement["facility_fee_cents"] == 700_000
    assert engagement["deposit_required_cents"] == 175_000
    clear_rental_rider(engagement["id"], client["id"],
                       submitted_rigging_kg=2_000, requested_power_amps=200,
                       requested_dmx_universes=2)
    record_deposit(engagement["id"], 175_000)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 10
    assert assessed["financial_clearance"] == "CLEARED"
    confirm(engagement["id"], RENTAL_MANAGER)
    return {"engagement": engagement, "department": department}


def _presented_settlement_awaiting_reconciliation() -> dict:
    """A performed presented engagement whose eligible expenses will exceed the
    reimbursement cap: 400 seats sold at 10,000, a crew of twenty for five hours
    and 100,000 of gap-covering equipment."""
    space = register_hall()
    artist = register_artist(legal_name="Vela Theatre Collective",
                            agency_name="Southgate Booking",
                            guarantee_floor_cents=1_000_000,
                            historical_sell_through_pct=0.80)
    department = register_union_department(roster_size=20,
                                          straight_hourly_rate_cents=5_000)
    item = register_equipment_item(category="POWER_DISTRO",
                                   model_name="400A Company Switch Cart",
                                   on_hand_qty=5, daily_rate_cents=25_000,
                                   replacement_value_cents=4_000_000)
    engagement = book_presented_engagement(
        space["id"], artist["id"], title="Vela Theatre: The Long Room",
        load_in_start_utc="2026-10-01T08:00:00Z",
        performance_start_utc="2026-10-02T19:00:00Z",
        performance_end_utc="2026-10-02T22:00:00Z",
        load_out_end_utc="2026-10-03T02:00:00Z")
    rider = submit_rider(engagement["id"],
                         make_artist_representative_headers(artist["id"]),
                         submitted_rigging_kg=3_000, requested_power_amps=500,
                         requested_dmx_universes=2)
    reviewed = review_rider(rider["id"])
    assert reviewed["capability_gaps"] == ["POWER_SHORTFALL"]
    reserve_equipment_line(rider["id"], item["id"],
                           covers_gap="POWER_SHORTFALL", qty=2, rental_days=2)
    cleared = clear_rider(rider["id"])
    assert cleared["additional_equipment_cost_cents"] == 100_000
    tier = add_price_tier(engagement["id"], tier_name="ORCH",
                          seats_allocated=500, base_price_cents=10_000,
                          price_ceiling_cents=15_000,
                          dynamic_pricing_enabled=False,
                          subscription_eligible=False)
    negotiate_and_accept_fee(engagement["id"], artist["id"], 2_000_000, 0.15)
    assessed = assess_risk(engagement["id"])
    assert assessed["risk_score"] == 34
    assert assessed["financial_clearance"] == "CLEARED"
    confirm(engagement["id"])
    put_on_sale(engagement["id"])
    sell_tickets(tier["id"], 400, "WEB")
    call = call_crew(engagement["id"], department["id"], crew_size=20,
                     call_start_utc="2026-10-01T08:00:00Z",
                     call_end_utc="2026-10-01T13:00:00Z")
    report_hours(call["id"], 5, True)
    set_clock("2026-10-03T00:00:00Z")
    settlement = open_settlement(engagement["id"])
    return {
        "artist": artist,
        "engagement": engagement,
        "tier": tier,
        "item": item,
        "call": call,
        "settlement": settlement,
    }


class TestLaborRoundingBeforeCrewMultiplication:

    def test_each_rate_component_is_rounded_before_the_crew_multiplier_lands(self):
        """A ten-and-a-half-hour call on a 4,445-cent rate splits into eight
        straight hours and two and a half overtime hours, and the overtime
        component falls on a half cent. Rounding that component first and only
        then multiplying by a crew of three gives 156,687; summing the unrounded
        components and rounding after the multiplication gives 156,686.

        PRD: "each of those three products is rounded half up to a whole cent
        **before** the three are added together."

        Design: Difficulty/combinatorial_formula/labor_cost_round_per_component_then_multiply_by_crew
        """
        scenario = _confirmed_rental_with_an_odd_electrics_rate()
        engagement_id = scenario["engagement"]["id"]

        call = validate_success(api_client.create_labor_call(
            engagement_id,
            {"union_department_id": scenario["department"]["id"],
             "crew_size": 3,
             "call_start_utc": "2026-10-01T08:00:00Z",
             "call_end_utc": "2026-10-01T18:30:00Z"},
            TECH_DIRECTOR), expected_status=201)
        assert call["status"] == "ESTIMATED"
        assert call["scheduled_hours"] == pytest.approx(10.5, abs=0.01)
        assert call["estimated_cost_cents"] == 156_687

        after = read_engagement(engagement_id)
        assert after["labor_estimate_total_cents"] == 156_687
        assert after["deposit_required_cents"] == 214_200
        assert after["deposit_paid_cents"] == 175_000

    def test_the_meal_penalty_sits_inside_the_per_crew_member_subtotal(self):
        """The same call worked in full with no break carries the penalty inside
        the per-head subtotal, so the crew multiplier applies to it too:
        (52,229 + 3,500) times three. Adding the penalty once after the crew
        multiplication would stop 10,500 short.

        PRD: "That per-crew-member subtotal, plus any meal penalty, is then
        multiplied by `crew_size` to give the call's cost."

        Design: Difficulty/combinatorial_formula/labor_cost_round_per_component_then_multiply_by_crew
        """
        scenario = _confirmed_rental_with_an_odd_electrics_rate()
        call = call_crew(scenario["engagement"]["id"],
                         scenario["department"]["id"], crew_size=3,
                         call_start_utc="2026-10-01T08:00:00Z",
                         call_end_utc="2026-10-01T18:30:00Z")
        assert call["estimated_cost_cents"] == 156_687

        worked = report_hours(call["id"], 10.5, False)
        assert worked["status"] == "WORKED"
        assert worked["actual_cost_cents"] == 167_187
        assert worked["actual_cost_cents"] - worked["estimated_cost_cents"] == \
            3_500 * 3
        assert read_engagement(scenario["engagement"]["id"])[
            "labor_estimate_total_cents"] == 156_687


class TestSettlementWaterfallEvaluationOrder:

    def test_the_capped_expense_pool_is_what_reduces_the_artist_overage(self):
        """Nine hundred thousand of marketing plus a hundred thousand of
        equipment is a million of eligible spend against a six-hundred-thousand
        cap, and it is the capped figure that the overage subtracts: a fifteen
        percent share of 1,320,000 rather than of the uncapped 920,000. Labor
        never enters the reimbursable pool but is still deducted from the
        center's net.

        PRD: "writes `reimbursable_expenses_cents` as the smaller of that pool
        and the cap."

        Design: Difficulty/combinatorial_formula/settlement_presented_split_pinned_evaluation_order
        """
        scenario = _presented_settlement_awaiting_reconciliation()

        reconciled = reconcile_expenses(scenario["settlement"]["id"], 900_000)
        assert reconciled["status"] == "EXPENSES_RECONCILED"
        assert reconciled["box_office_gross_cents"] == 4_000_000
        assert reconciled["restoration_fees_cents"] == 80_000
        assert reconciled["adjusted_gross_cents"] == 3_920_000
        assert reconciled["reimbursable_expense_cap_cents"] == 600_000
        assert reconciled["reimbursable_expenses_cents"] == 600_000
        assert reconciled["artist_share_cents"] == 198_000
        assert reconciled["actual_labor_cents"] == 500_000
        assert reconciled["actual_equipment_cents"] == 100_000
        assert reconciled["net_to_center_cents"] == 622_000

    def test_the_reserve_contribution_is_never_subtracted_back_out_of_the_net(self):
        """The reserve percentage is chosen from the center's net position and
        the whole restoration take is added to it, but the resulting contribution
        is not an expense: the net it was derived from still reads 622,000 both
        in the reconciliation response and on the stored settlement.

        PRD: "the reserve contribution is derived from the net position but is
        never treated as an expense and is never subtracted back out of
        `net_to_center_cents`."

        Design: Difficulty/combinatorial_formula/settlement_presented_split_pinned_evaluation_order
        """
        scenario = _presented_settlement_awaiting_reconciliation()

        reconciled = reconcile_expenses(scenario["settlement"]["id"], 900_000)
        assert reconciled["net_to_center_cents"] == 622_000
        assert reconciled["reserve_contribution_cents"] == 111_100
        assert reconciled["amount_payable_to_artist_cents"] == 2_198_000
        assert reconciled["balance_due_from_client_cents"] == 0

        stored, meta = validate_paginated(api_client.list_engagement_settlements(
            scenario["engagement"]["id"], FINANCE))
        assert meta["total_count"] == 1
        assert stored[0]["net_to_center_cents"] == 622_000
        assert stored[0]["reserve_contribution_cents"] == 111_100
        assert stored[0]["status"] == "EXPENSES_RECONCILED"

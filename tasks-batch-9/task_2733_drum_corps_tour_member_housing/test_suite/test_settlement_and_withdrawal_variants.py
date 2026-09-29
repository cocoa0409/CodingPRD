"""Two calculations that each carry two variants on one entity.

A show settlement holds both an optimistic projection and the circuit's certified
outcome; a departing member's obligation is struck by one of two ladders chosen
solely by where the withdrawal date falls relative to the departure date.
"""

from test_helpers import (
    assert_all_nulls,
    assert_member,
    assert_show_settlement,
    factories as f,
    fixtures as fx,
)

SHOW_STOP = {
    "venue_name": "Allen Stadium",
    "city": "Allen",
    "state_code": "TX",
    "arrive_at": "2027-06-20T14:00:00Z",
    "depart_at": "2027-06-20T23:30:00Z",
    "show_start_at": "2027-06-20T20:00:00Z",
    "travel_miles_from_previous": 0,
    "uniform_trunks": 0,
    "instrument_cases": 0,
    "prop_units": 0,
    "truck_count": 1,
    "rehearsal_minutes": 0,
    "heat_index_f": 80,
}

CERTIFIED_LINES = [
    f.prize_adjustment_line(40000, "2027-06-25T09:00:00Z"),
    f.sanction_line(250000, "2027-06-26T09:00:00Z"),
    f.sanction_line(200000, "2027-06-27T09:00:00Z"),
    f.rebate_line(60000, "2027-06-28T09:00:00Z"),
]


def test_provisional_variant_is_struck_from_the_corps_own_projection(api):
    """Opening a draft prices the show off projected_placement alone.

    PRD: "`provisional_prize_cents` is the prize pool multiplied by the share
    belonging to `projected_placement`, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/settlement_provisional_forward_versus_circuit_final_net
    """
    season = fx.create_season(api)
    built = fx.draft_settlement_on_show(api, season["id"], 1200000, 800000, 3, **SHOW_STOP)
    settlement = built["settlement"]

    assert_show_settlement(
        settlement,
        appearance_fee_cents=1200000,
        prize_pool_cents=800000,
        projected_placement=3,
        provisional_prize_cents=128000,
        provisional_gross_cents=1328000,
        provisional_circuit_fee_cents=53120,
        provisional_net_cents=1274880,
        remittance_line_count=0,
        status="DRAFT",
        prepared_by_user_id="bm-anna",
    )
    assert_all_nulls(
        settlement,
        "final_placement",
        "finalized_by_user_id",
        "final_prize_cents",
        "final_gross_cents",
        "final_circuit_fee_cents",
        "sanctions_charged_cents",
        "rebate_applied_cents",
        "final_net_cents",
        "variance_cents",
    )
    assert built["stop"]["settlement_state"] == "PENDING"
    assert fx.get_season(api, season["id"])["tour_revenue_cents"] == 0


def test_certified_variant_replays_the_remittance_advice_on_the_same_row(api):
    """Finalization re-prices on the certified placement and replays the lines.

    PRD: "For each `SANCTION_FEE` line, a per-line cap is computed as fifteen
    percent of the running net **as it stands at that moment**, rounded half up;
    the amount actually charged is the smaller of the line's `amount_cents` and
    that cap; the running net is reduced by the charged amount; and
    `sanctions_charged_cents` accumulates it."

    Design: Difficulty/dual_variant_calc/settlement_provisional_forward_versus_circuit_final_net
    """
    season = fx.create_season(api)
    built = fx.draft_settlement_on_show(api, season["id"], 1200000, 800000, 3, **SHOW_STOP)
    settlement = built["settlement"]

    fx.set_clock(api, "2027-06-30T00:00:00Z")
    finalized = fx.finalize_settlement(api, settlement["id"], 2, CERTIFIED_LINES)

    assert_show_settlement(
        finalized,
        final_placement=2,
        final_prize_cents=176000,
        final_gross_cents=1416000,
        final_circuit_fee_cents=56640,
        sanctions_charged_cents=377222,
        rebate_applied_cents=56640,
        final_net_cents=1038778,
        variance_cents=-236102,
        remittance_line_count=4,
        status="FINALIZED",
        finalized_by_user_id="bm-brett",
        prepared_by_user_id="bm-anna",
    )
    assert finalized["provisional_net_cents"] == 1274880
    assert fx.get_stop(api, built["stop"]["id"])["settlement_state"] == "SETTLED"
    assert fx.get_season(api, season["id"])["tour_revenue_cents"] == 1038778


def test_both_variants_survive_side_by_side_after_finalization(api):
    """A finalized settlement still reports the projection it opened with.

    PRD: "`variance_cents` is the final net less the provisional net — a negative
    variance being the ordinary outcome when the circuit's certified placement is
    worse than the projection or the sanctions bite."

    Design: Difficulty/dual_variant_calc/settlement_provisional_forward_versus_circuit_final_net
    """
    season = fx.create_season(api)
    built = fx.draft_settlement_on_show(api, season["id"], 1200000, 800000, 3, **SHOW_STOP)
    fx.set_clock(api, "2027-06-30T00:00:00Z")
    fx.finalize_settlement(api, built["settlement"]["id"], 2, CERTIFIED_LINES)

    stored = fx.get_settlement(api, built["settlement"]["id"])
    assert stored["provisional_prize_cents"] == 128000
    assert stored["provisional_gross_cents"] == 1328000
    assert stored["provisional_circuit_fee_cents"] == 53120
    assert stored["provisional_net_cents"] == 1274880
    assert stored["final_net_cents"] == 1038778
    assert stored["variance_cents"] == stored["final_net_cents"] - stored["provisional_net_cents"]


def _extended_six_member(api, season_id, date_of_birth, section):
    built = fx.contracted_member(
        api,
        season_id,
        tuition_amount_cents=399900,
        payment_plan_type="EXTENDED_6",
        date_of_birth=date_of_birth,
        section=section,
    )
    assert built["member"]["tuition_charged_cents"] == 399900
    return built["member"]


def test_withdrawing_the_day_before_departure_takes_the_prorated_branch(api):
    """One day short of departure prorates the spring window then adds the fee.

    PRD: "The tuition component is the contracted tuition multiplied by days
    completed and divided by the length of the spring window, rounded half up to
    a whole cent."

    Design: Difficulty/dual_variant_calc/withdrawal_prorated_spring_versus_liquidated_ladder_obligation
    """
    season = fx.create_season(api)
    member = _extended_six_member(api, season["id"], "2005-03-04", "BRASS")

    fx.set_clock(api, "2027-06-11T12:00:00Z")
    withdrawn = fx.withdraw_member(api, member["id"], "2027-06-11")

    assert_member(
        withdrawn,
        withdrawal_date="2027-06-11",
        withdrawal_obligation_basis="PRORATED_SPRING",
        withdrawal_obligation_cents=402782,
        tuition_charged_cents=402782,
        tuition_paid_cents=0,
        tuition_balance_cents=402782,
        refund_due_cents=0,
        membership_status="WITHDRAWN",
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 402782


def test_withdrawing_on_the_departure_date_takes_the_liquidated_branch(api):
    """The first day of tour abandons proration for the zero-week rung.

    PRD: "zero completed weeks charge seventy-five percent, one completed week
    charges eighty-five percent, two charge ninety-two percent, three charge
    ninety-seven percent, and four or more charge the full hundred percent — any
    week number above four is treated as four."

    Design: Difficulty/dual_variant_calc/withdrawal_prorated_spring_versus_liquidated_ladder_obligation
    """
    season = fx.create_season(api)
    member = _extended_six_member(api, season["id"], "2004-11-22", "PERCUSSION")

    fx.set_clock(api, "2027-06-12T12:00:00Z")
    withdrawn = fx.withdraw_member(api, member["id"], "2027-06-12")

    assert_member(
        withdrawn,
        withdrawal_date="2027-06-12",
        withdrawal_obligation_basis="LIQUIDATED_LADDER",
        withdrawal_obligation_cents=314925,
        tuition_charged_cents=314925,
        tuition_paid_cents=0,
        tuition_balance_cents=314925,
        refund_due_cents=0,
        membership_status="WITHDRAWN",
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 314925


def test_one_day_apart_the_two_branches_diverge_by_a_fixed_delta(api):
    """Identical contracts a day apart owe 87857 cents differently.

    PRD: "The discontinuity at the departure date is deliberate and steep: the
    identical contract owes very nearly all of its tuition on the last day before
    departure but only seventy-five percent plus the admin fee on the first day of
    tour."

    Design: Difficulty/dual_variant_calc/withdrawal_prorated_spring_versus_liquidated_ladder_obligation
    """
    season = fx.create_season(api)
    avery = _extended_six_member(api, season["id"], "2005-03-04", "BRASS")
    blake = _extended_six_member(api, season["id"], "2004-11-22", "PERCUSSION")

    fx.set_clock(api, "2027-06-11T12:00:00Z")
    prorated = fx.withdraw_member(api, avery["id"], "2027-06-11")
    fx.set_clock(api, "2027-06-12T12:00:00Z")
    laddered = fx.withdraw_member(api, blake["id"], "2027-06-12")

    assert prorated["withdrawal_obligation_basis"] == "PRORATED_SPRING"
    assert laddered["withdrawal_obligation_basis"] == "LIQUIDATED_LADDER"
    assert (
        prorated["withdrawal_obligation_cents"]
        - laddered["withdrawal_obligation_cents"]
        == 87857
    )
    assert fx.get_season(api, season["id"])["tuition_charged_cents"] == 717707

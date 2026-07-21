"""Session bill composition: provisional vs final, the nested min/max/discount
formula, and the F&B-minimum equality boundary."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_table, create_membership, grant_loyalty,
    create_seated_reservation, add_fnb, set_clock,
)

STAFF = TEST_USERS["staff_headers"]


# ─── Difficulty/dual_variant_calc/session_bill_provisional_vs_final ─────────
def test_provisional_bill_measures_table_time_to_current_clock(api):
    """PRD §3.3: "At any moment while a reservation is `SEATED`, reading it returns
    a live `provisional_bill_total_cents` — a running estimate evaluated against the
    current logical clock at read time. This provisional figure mirrors the final bill
    formula below, except that elapsed table time is measured from `seated_at` to the
    current logical clock rather than to a close time; for a reservation that is not
    `SEATED`, `provisional_bill_total_cents` is zero."
    PRD §3.3: "That duration is divided into 30-minute blocks, and any started block
    counts as a full block — the number of blocks is the elapsed minutes divided by 30
    and rounded up to the next whole block."

    Design: Difficulty/dual_variant_calc/session_bill_provisional_vs_final
    """
    table = create_table(api, seats=6, half_hour_rate_cents=500, day_pass_cents=6000,
                         cover_fee_cents=300, min_spend_cents=2000, zone="MAIN")
    member = create_membership(api, email="prov1@x.com", full_name="Prov One")
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=4,
        start_at="2026-07-02T18:00:00Z", end_at="2026-07-02T20:00:00Z",
        seated_at="2026-07-02T18:00:00Z", booking_clock="2026-07-02T17:00:00Z",
    )
    add_fnb(api, resv["id"], 1500)
    set_clock(api, "2026-07-02T19:00:00Z")

    data = validate_success(api.get_reservation(resv["id"], STAFF))
    # time 1000 (60min->2 blocks*500) + cover 1200 (4*300) + fnb 1500 + shortfall 500
    assert data["provisional_bill_total_cents"] == 4200, \
        f"expected provisional 4200, got {data['provisional_bill_total_cents']}"


def test_final_bill_measures_table_time_to_closed_at_and_diverges(api):
    """PRD §3.3: "On a successful close, `closed_at` is stamped with the current logical
    clock and the bill is computed component by component"
    PRD §3.3: "`bill_total_cents` is the discounted gaming amount plus `fnb_subtotal_cents`
    plus `minimum_shortfall_cents`. Before a session is closed, `bill_total_cents` is zero."

    Design: Difficulty/dual_variant_calc/session_bill_provisional_vs_final
    """
    table = create_table(api, seats=6, half_hour_rate_cents=500, day_pass_cents=6000,
                         cover_fee_cents=300, min_spend_cents=2000, zone="MAIN")
    member = create_membership(api, email="fin1@x.com", full_name="Fin One")
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=4,
        start_at="2026-07-02T18:00:00Z", end_at="2026-07-02T20:00:00Z",
        seated_at="2026-07-02T18:00:00Z", booking_clock="2026-07-02T17:00:00Z",
    )
    add_fnb(api, resv["id"], 1500)

    set_clock(api, "2026-07-02T19:00:00Z")
    prov = validate_success(api.get_reservation(resv["id"], STAFF))["provisional_bill_total_cents"]

    set_clock(api, "2026-07-02T20:00:00Z")
    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    # time 2000 (120min->4 blocks*500) + cover 1200 + fnb 1500 + shortfall 500
    assert closed["bill_total_cents"] == 5200, \
        f"expected final bill 5200, got {closed['bill_total_cents']}"
    assert prov == 4200 and closed["bill_total_cents"] != prov, \
        "final bill must diverge from the provisional estimate"


# ─── Difficulty/combinatorial_formula/session_bill_nonlinear_composition_mode_a ─
def test_bill_applies_daypass_cap_cover_silver_discount_and_shortfall(api):
    """PRD §3.3: "The raw time charge is that block count multiplied by the table's
    `half_hour_rate_cents`, and the final `time_charge_cents` is the smaller of that
    raw charge and the table's `day_pass_cents` cap."
    PRD §3.3: "`cover_charge_cents` is the `party_size` multiplied by the table's
    `cover_fee_cents`."
    PRD §3.3: "`BRONZE` earns no discount, `SILVER` earns 10 percent, and `GOLD` earns
    20 percent. `member_discount_cents` is that percentage of the gaming subtotal,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/session_bill_nonlinear_composition_mode_a
    """
    table = create_table(api, seats=8, half_hour_rate_cents=500, day_pass_cents=3000,
                         cover_fee_cents=400, min_spend_cents=5000, zone="MAIN")
    member = create_membership(api, email="silver@x.com", full_name="M Two")
    grant_loyalty(api, member["id"], 500, "signup bonus")  # -> lifetime 500 -> SILVER
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=6,
        start_at="2026-07-03T18:00:00Z", end_at="2026-07-03T23:00:00Z",
        seated_at="2026-07-03T18:00:00Z", booking_clock="2026-07-03T18:00:00Z",
    )
    add_fnb(api, resv["id"], 2000, "Pizza night")
    set_clock(api, "2026-07-03T22:00:00Z")

    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    assert closed["time_charge_cents"] == 3000, "240min->8 blocks*500=4000 capped at day_pass 3000"
    assert closed["cover_charge_cents"] == 2400, "6*400"
    assert closed["member_discount_cents"] == 540, "round_half_up((3000+2400)*0.10)"
    assert closed["minimum_shortfall_cents"] == 3000, "max(0, 5000-2000)"


def test_bill_total_composes_all_components(api):
    """PRD §3.3: "`minimum_shortfall_cents` is the amount by which the table's
    `min_spend_cents` exceeds `fnb_subtotal_cents`, or zero if food-and-beverage
    spending already met the minimum."
    PRD §3.3: "`bill_total_cents` is the discounted gaming amount plus `fnb_subtotal_cents`
    plus `minimum_shortfall_cents`."

    Design: Difficulty/combinatorial_formula/session_bill_nonlinear_composition_mode_a
    """
    table = create_table(api, seats=8, half_hour_rate_cents=500, day_pass_cents=3000,
                         cover_fee_cents=400, min_spend_cents=5000, zone="MAIN")
    member = create_membership(api, email="silver2@x.com", full_name="M Two B")
    grant_loyalty(api, member["id"], 500, "signup bonus")
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=6,
        start_at="2026-07-03T18:00:00Z", end_at="2026-07-03T23:00:00Z",
        seated_at="2026-07-03T18:00:00Z", booking_clock="2026-07-03T18:00:00Z",
    )
    add_fnb(api, resv["id"], 2000, "Pizza night")
    set_clock(api, "2026-07-03T22:00:00Z")

    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    # (5400 - 540) + 2000 + 3000
    assert closed["bill_total_cents"] == 9860, \
        f"expected bill 9860, got {closed['bill_total_cents']}"


# ─── Difficulty/boundary_precision_check/fnb_minimum_exact_equality_zero_shortfall ─
def test_fnb_exactly_meets_minimum_yields_zero_shortfall(api):
    """PRD §3.3: "`minimum_shortfall_cents` is the amount by which the table's
    `min_spend_cents` exceeds `fnb_subtotal_cents`, or zero if food-and-beverage
    spending already met the minimum."

    Design: Difficulty/boundary_precision_check/fnb_minimum_exact_equality_zero_shortfall
    """
    table = create_table(api, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=2000, zone="MAIN")
    resv = create_seated_reservation(
        api, table_id=table["id"], party_size=2,
        start_at="2026-07-08T18:00:00Z", end_at="2026-07-08T19:00:00Z",
        seated_at="2026-07-08T18:00:00Z", booking_clock="2026-07-08T18:00:00Z",
    )
    add_fnb(api, resv["id"], 2000, "Dinner")
    set_clock(api, "2026-07-08T19:00:00Z")

    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    assert closed["minimum_shortfall_cents"] == 0, "fnb 2000 == min_spend 2000, no shortfall"


def test_bill_total_when_minimum_exactly_met(api):
    """PRD §3.3: "`fnb_subtotal_cents` is the sum of `total_cents` across all non-`VOID`
    food-and-beverage orders on the reservation."
    PRD §3.3: "`bill_total_cents` is the discounted gaming amount plus `fnb_subtotal_cents`
    plus `minimum_shortfall_cents`."

    Design: Difficulty/boundary_precision_check/fnb_minimum_exact_equality_zero_shortfall
    """
    table = create_table(api, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=2000, zone="MAIN")
    resv = create_seated_reservation(
        api, table_id=table["id"], party_size=2,
        start_at="2026-07-08T18:00:00Z", end_at="2026-07-08T19:00:00Z",
        seated_at="2026-07-08T18:00:00Z", booking_clock="2026-07-08T18:00:00Z",
    )
    add_fnb(api, resv["id"], 2000, "Dinner")
    set_clock(api, "2026-07-08T19:00:00Z")

    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    # gaming 0 + fnb 2000 + shortfall 0
    assert closed["bill_total_cents"] == 2000, \
        f"expected bill 2000, got {closed['bill_total_cents']}"

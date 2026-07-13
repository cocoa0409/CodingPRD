"""Occupancy fee (estimated vs. final variants), the tiered min-cap, the
per-component surcharge rounding order, and first-offense penalty."""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    ZONE_CAP_CENTS,
    fixtures,
)

REVIEWER_1 = TEST_USERS["reviewer_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_estimated_fee_computed_at_issue(api):
    """PRD §3.4: "In the **estimated variant** computed at issuance, the duration
    uses the permit's `requested_start_date` through `requested_end_date` window
    and the result is stored as `estimated_fee_cents`."
    PRD §3.4: "The fee is computed by multiplying the daily rate by the area
    factor and by the duration in days, rounding that product half-up to a whole
    cent, adding the zone's base component, and then taking the smaller of that
    sum and the zone's cap."

    Design: Difficulty/dual_variant_calc/occupancy_estimated_vs_final_overstay_on_permit
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="COMMERCIAL", obstruction_type="LANE",
        requested_start_date="2026-04-01", requested_end_date="2026-04-11",
        posted_cents=80000,
    )
    assert ctx["permit"]["estimated_fee_cents"] == 40000


def test_final_fee_reflects_overstay_at_closeout(api):
    """PRD §3.9: "The final variant uses the same tiered formula as the estimated
    variant but measures the true occupancy window: its duration in whole days
    runs from the permit's `actual_start_date` (the date of the first lane-closure
    activation) to its `actual_end_date`. Because the true window can exceed the
    requested one, an overstay yields a strictly larger fee than the estimate."

    Design: Difficulty/dual_variant_calc/occupancy_estimated_vs_final_overstay_on_permit
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="COMMERCIAL", obstruction_type="LANE",
        requested_start_date="2026-04-01", requested_end_date="2026-04-11",
        posted_cents=80000,
    )
    closure = fixtures.create_closure(
        api, ctx["permit_id"], ctx["seg_id"], ctx["app_id"],
        start_date="2026-04-01", end_date="2026-04-11",
    )
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    fixtures.activate_closure(api, closure["id"], ctx["app_id"])
    fixtures.request_restoration(api, closure["id"], ctx["app_id"], 10000)
    fixtures.sign_off(api, closure["id"], "PASS", 25000)
    fixtures.set_clock(api, "2026-04-14T00:00:00Z")
    closed = get_success_data(api.close_out_permit(ctx["permit_id"], REVIEWER_1))
    assert closed["final_fee_cents"] == 49000


def test_occupancy_fee_clamped_to_arterial_cap(api):
    """PRD §3.4: "The fee is computed by multiplying the daily rate by the area
    factor and by the duration in days, rounding that product half-up to a whole
    cent, adding the zone's base component, and then taking the smaller of that
    sum and the zone's cap."

    Design: Difficulty/combinatorial_formula/occupancy_tiered_rate_with_min_cap_mode_a
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="ARTERIAL", obstruction_type="FULL_ROAD",
        requested_start_date="2026-04-01", requested_end_date="2026-07-04",
        posted_cents=2000000, block_label="Grand 1",
        tcp_requires_flaggers=True, tcp_flagger_count=2,
    )
    assert ctx["permit"]["estimated_fee_cents"] == 1000000


def test_occupancy_cap_is_strictly_below_uncapped_raw(api):
    """PRD §3.4: "a fee cap of 200000 cents for `RESIDENTIAL`, 500000 cents for
    `COMMERCIAL`, and 1000000 cents for `ARTERIAL`."
    PRD §3.4: "The fee is computed by multiplying the daily rate by the area
    factor and by the duration in days, rounding that product half-up to a whole
    cent, adding the zone's base component, and then taking the smaller of that
    sum and the zone's cap."

    Design: Difficulty/combinatorial_formula/occupancy_tiered_rate_with_min_cap_mode_a
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="ARTERIAL", obstruction_type="FULL_ROAD",
        requested_start_date="2026-04-01", requested_end_date="2026-07-04",
        posted_cents=2000000, block_label="Grand 1",
        tcp_requires_flaggers=True, tcp_flagger_count=2,
    )
    # raw = base 20000 + round(3000 * 3.5 * 94) = 20000 + 987000 = 1007000 > cap
    raw_uncapped = 20000 + round(3000 * 3.5 * 94)
    fee = ctx["permit"]["estimated_fee_cents"]
    assert fee == ZONE_CAP_CENTS["ARTERIAL"]
    assert fee < raw_uncapped


def test_surcharge_rounded_per_component(api):
    """PRD §3.4: "The municipal surcharge is 7.25 percent applied per component:
    for each of the three components, multiply the component by 0.0725, round that
    product half-up to a whole cent, and then sum the three rounded results — the
    surcharge is deliberately rounded per line item and never on the aggregate."

    Design: Difficulty/combinatorial_formula/total_charge_surcharge_rounding_order_mode_b
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="ARTERIAL", obstruction_type="FULL_ROAD",
        requested_start_date="2026-04-01", requested_end_date="2026-04-03",
        posted_cents=82000, block_label="Grand 2",
        tcp_requires_flaggers=True, tcp_flagger_count=1,
    )
    assert ctx["permit"]["surcharge_cents"] == 3807


def test_total_charge_sums_components_plus_surcharge(api):
    """PRD §3.4: "The **total permit charge** is computed at issuance from three
    components: the estimated occupancy fee just computed, a fixed
    traffic-control-plan review fee of 7500 cents, and a fixed inspection fee of
    4000 cents."
    PRD §3.4: "The `total_charge_cents` is the sum of the three components plus
    `surcharge_cents`."

    Design: Difficulty/combinatorial_formula/total_charge_surcharge_rounding_order_mode_b
    """
    ctx = fixtures.setup_issued_permit(
        api, zone_class="ARTERIAL", obstruction_type="FULL_ROAD",
        requested_start_date="2026-04-01", requested_end_date="2026-04-03",
        posted_cents=82000, block_label="Grand 2",
        tcp_requires_flaggers=True, tcp_flagger_count=1,
    )
    assert ctx["permit"]["estimated_fee_cents"] == 41000
    assert ctx["permit"]["total_charge_cents"] == 56307


def test_first_violation_penalty_is_base(api):
    """PRD §3.8: "The penalty is a base of 15000 cents scaled by one plus 0.5
    times that prior count; that scaled product is rounded half-up to a whole
    cent and then capped at a maximum of 100000 cents — the penalty is the smaller
    of the rounded escalated product and 100000 cents."

    Design: Corner/calculations/penalty_first_offense_value
    """
    ctx = fixtures.setup_issued_permit(api)
    notice = get_success_data(
        api.create_violation(ctx["permit_id"], {"violation_type": "TCP_VIOLATION"}, OFFICER)
    )
    assert notice["penalty_cents"] == 15000

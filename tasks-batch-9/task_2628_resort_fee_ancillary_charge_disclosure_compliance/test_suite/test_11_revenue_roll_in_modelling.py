"""Roll-in projections: the two variants and the post-roll-in commission tier."""
from test_helpers import (
    COMMISSION_TIER_2_BPS,
    COMMISSION_TIER_3_BPS,
    TIER_BOUNDARY_ROOM_RATE_CENTS,
    assert_revenue_impact_model,
    create_revenue_impact_model_payload,
    setup_published_program,
    validate_success,
)
from test_helpers.fixtures import REVENUE


def _model(api, env, **overrides):
    payload = create_revenue_impact_model_payload(
        env["property"]["id"], env["program"]["id"], **overrides
    )
    return validate_success(
        api.create_revenue_impact_model(payload, REVENUE), expected_status=201
    )


def test_rate_parity_keeps_the_pre_tax_rate_whole_and_the_guest_pays_more(api):
    """Rolling two fees in at rate parity costs 226 cents of net revenue.

    PRD 3.9: "The `variant` is `RATE_PARITY`, where the operator moves the fee
    into the rate and keeps the pre-tax rate whole so the guest's tax base rises
    and the guest pays more". The worked reference pins every figure: "the
    baseline is an ADR of 29900, a tier of 1800 basis points, a commission of
    5382, retained taxable fees of 3738 ... a tax of 4501, a guest total of
    38789 and a net revenue of 28906. Under `RATE_PARITY` the rolled amount is
    2145, `modeled_adr_cents` is 32045, `applied_commission_bps` is 1800, the
    commission is 5768, ... the tax is 4609, the guest total is 39057 and the
    net revenue is 28680, giving deltas of plus 2145 on ADR, plus 386 on
    commission, plus 108 on tax, plus 268 on guest total and **minus 226** on
    net revenue."

    Design: Difficulty/dual_variant_calc/revenue_roll_in_rate_parity_versus_tax_absorbed_net_revenue
    """
    env = setup_published_program()

    model = _model(api, env, scenario="PARTIAL_ROLL_IN", variant="RATE_PARITY")

    assert_revenue_impact_model(model)
    assert model["baseline_adr_cents"] == 29900
    assert model["baseline_commission_cents"] == 5382
    assert model["baseline_tax_cents"] == 4501
    assert model["baseline_guest_total_cents"] == 38789
    assert model["baseline_net_revenue_cents"] == 28906

    assert model["modeled_adr_cents"] == 32045
    assert model["applied_commission_bps"] == COMMISSION_TIER_2_BPS
    assert model["modeled_commission_cents"] == 5768
    assert model["modeled_tax_cents"] == 4609
    assert model["modeled_guest_total_cents"] == 39057
    assert model["modeled_net_revenue_cents"] == 28680

    assert model["modeled_adr_delta_cents"] == 2145
    assert model["modeled_commission_delta_cents"] == 386
    assert model["modeled_tax_delta_cents"] == 108
    assert model["modeled_guest_total_delta_cents"] == 268
    assert model["modeled_net_revenue_delta_cents"] == -226


def test_tax_absorbed_back_solves_the_rate_and_costs_far_more_net_revenue(api):
    """The same roll-in set absorbed into the tax loses 3610 cents, not 226.

    PRD 3.9: "or `TAX_ABSORBED`, where the operator holds the guest's
    tax-inclusive number constant and back-solves the rate." The reference
    continues: "Under `TAX_ABSORBED` the same inputs give a `modeled_adr_cents`
    of 28263, `applied_commission_bps` of 1800, a commission of 5087, ... a tax
    of 4065, a guest total of 34448 and a net revenue of 25296, giving deltas of
    minus 1637 on ADR, minus 295 on commission, minus 436 on tax, minus 4341 on
    guest total and **minus 3610** on net revenue."

    Design: Difficulty/dual_variant_calc/revenue_roll_in_rate_parity_versus_tax_absorbed_net_revenue
    """
    env = setup_published_program()

    parity = _model(api, env, scenario="PARTIAL_ROLL_IN", variant="RATE_PARITY")
    absorbed = _model(api, env, scenario="PARTIAL_ROLL_IN", variant="TAX_ABSORBED")

    # The baseline is identical under both variants.
    for field in (
        "baseline_adr_cents",
        "baseline_commission_cents",
        "baseline_tax_cents",
        "baseline_guest_total_cents",
        "baseline_net_revenue_cents",
    ):
        assert absorbed[field] == parity[field], field

    assert absorbed["modeled_adr_cents"] == 28263
    assert absorbed["modeled_adr_cents"] < parity["modeled_adr_cents"]
    assert absorbed["applied_commission_bps"] == COMMISSION_TIER_2_BPS
    assert absorbed["modeled_commission_cents"] == 5087
    assert absorbed["modeled_tax_cents"] == 4065
    assert absorbed["modeled_guest_total_cents"] == 34448
    assert absorbed["modeled_net_revenue_cents"] == 25296

    assert absorbed["modeled_adr_delta_cents"] == -1637
    assert absorbed["modeled_commission_delta_cents"] == -295
    assert absorbed["modeled_tax_delta_cents"] == -436
    assert absorbed["modeled_guest_total_delta_cents"] == -4341
    assert absorbed["modeled_net_revenue_delta_cents"] == -3610
    assert absorbed["modeled_net_revenue_delta_cents"] != parity[
        "modeled_net_revenue_delta_cents"
    ]


def test_partial_roll_in_at_the_tier_ceiling_still_pays_the_middle_tier(api):
    """A modelled ADR of exactly 34999 keeps the 1800 basis-point tier.

    PRD 3.9: "Step M3 sets `applied_commission_bps` to the tier selected by
    `modeled_adr_cents` under the same three thresholds". PRD 3.9 also states
    the boundary exactly: "The commission-tier boundary is exact and is keyed on
    the **modelled** ADR. With the same roll-in set under `RATE_PARITY`, a
    `base_room_rate_cents` of 32854 produces a `modeled_adr_cents` of 34999, an
    `applied_commission_bps` of 1800 and a `modeled_commission_cents` of 6300".

    Design: Difficulty/combinatorial_formula/roll_in_commission_tier_keyed_on_post_roll_in_adr_not_baseline
    """
    env = setup_published_program(
        property_overrides={"base_room_rate_cents": TIER_BOUNDARY_ROOM_RATE_CENTS}
    )

    model = _model(api, env, scenario="PARTIAL_ROLL_IN", variant="RATE_PARITY")

    assert model["baseline_adr_cents"] == TIER_BOUNDARY_ROOM_RATE_CENTS
    assert model["baseline_commission_cents"] == 5914
    assert model["baseline_tax_cents"] == 4926
    assert model["baseline_guest_total_cents"] == 42389
    assert model["baseline_net_revenue_cents"] == 31549

    assert model["modeled_adr_cents"] == 34999
    assert model["applied_commission_bps"] == COMMISSION_TIER_2_BPS
    assert model["modeled_commission_cents"] == 6300
    assert model["modeled_tax_cents"] == 5034
    assert model["modeled_guest_total_cents"] == 42658
    assert model["modeled_net_revenue_cents"] == 31324

    assert model["modeled_adr_delta_cents"] == 2145
    assert model["modeled_commission_delta_cents"] == 386
    assert model["modeled_tax_delta_cents"] == 108
    assert model["modeled_guest_total_delta_cents"] == 269
    assert model["modeled_net_revenue_delta_cents"] == -225


def test_full_roll_in_crosses_the_tier_because_the_modelled_adr_crosses_it(api):
    """Rolling every fee in lifts the ADR to 37463 and the tier to 2100.

    PRD 3.9: "The order matters because step M2 changes the ADR, step M3's
    commission **tier** is keyed on the ADR that M2 produced, and step M4
    re-derives every `PERCENT_OF_ROOM` fee against that same new ADR;
    evaluating commission before the roll-in, or holding a percent fee at its
    baseline value, yields different integers." Step B2 fixes the thresholds:
    "1500 basis points when the ADR is at most 19999, 1800 basis points when it
    is at most 34999, and 2100 basis points otherwise".

    Design: Difficulty/combinatorial_formula/roll_in_commission_tier_keyed_on_post_roll_in_adr_not_baseline
    """
    env = setup_published_program(
        property_overrides={"base_room_rate_cents": TIER_BOUNDARY_ROOM_RATE_CENTS}
    )

    model = _model(
        api,
        env,
        scenario="FULL_ROLL_IN",
        variant="RATE_PARITY",
        roll_in_fee_codes=["RESORT", "DESTINATION", "WIFI_PREMIUM"],
    )

    # The baseline ADR sits inside the middle tier; only the modelled ADR leaves it.
    assert model["baseline_adr_cents"] == TIER_BOUNDARY_ROOM_RATE_CENTS
    assert model["baseline_commission_cents"] == 5914

    assert model["modeled_adr_cents"] == 37463
    assert model["applied_commission_bps"] == COMMISSION_TIER_3_BPS
    assert model["modeled_commission_cents"] == 7867
    # 6743 is what keying the tier on the baseline ADR would have produced.
    assert model["modeled_commission_cents"] != 6743
    assert model["modeled_tax_cents"] == 5013
    assert model["modeled_guest_total_cents"] == 42476
    assert model["modeled_net_revenue_cents"] == 29596

    assert model["modeled_adr_delta_cents"] == 4609
    assert model["modeled_commission_delta_cents"] == 1953
    assert model["modeled_tax_delta_cents"] == 87
    assert model["modeled_guest_total_delta_cents"] == 87
    assert model["modeled_net_revenue_delta_cents"] == -1953

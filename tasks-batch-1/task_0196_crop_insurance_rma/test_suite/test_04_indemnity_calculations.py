"""Dual-variant indemnity and prevented-planting indemnity calculations.

Covers the yield-protection vs revenue-protection methodology (PRD §3.7), the
prevented-planting indemnity (PRD §3.8), and the zero-loss boundary. All expected
cent figures are the pre-computed literals from the design indices.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_submitted_loss_claim, setup_submitted_pp_claim,
)


def test_yp_and_rp_indemnity_differ_on_identical_loss(api):
    """PRD §3.7: "For a revenue-protection election, the loss is measured in revenue
    rather than bushels, which is why the same physical shortfall can produce a larger
    indemnity than the yield-protection path."
    PRD §3.7: "For a yield-protection election (plan_type of YP), the loss is measured
    purely in bushels and priced at the projected price; the harvest price is ignored
    entirely."
    PRD §3.7: "for RP, the revenue price is the greater of the projected price and the
    harvest price (so the producer captures harvest-price upside)"

    Design: Difficulty/dual_variant_calc/dual_variant_yp_vs_rp_indemnity_same_loss
    """
    # YP: guar_bu=135/ac; ptc_per_acre=100; (135-100)*4 = 140/ac; *100ac*1*100 = 1400000
    yp = setup_submitted_loss_claim(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                    acres=100, share=1, production_to_count_bu=10000,
                                    publish_harvest=5.20)
    yp_res = validate_success(api.approve_loss_claim(yp["claim"]["id"], yp["adj_headers"]), 200)
    assert yp_res["indemnity_cents"] == 1400000, yp_res["indemnity_cents"]

    # RP: rev guar 135*max(4,5.20)=135*5.20=702/ac; calc rev 100*5.20=520/ac;
    #     (702-520)=182/ac; *100ac*1*100 = 1820000
    rp = setup_submitted_loss_claim(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                    acres=100, share=1, production_to_count_bu=10000,
                                    publish_harvest=5.20)
    rp_res = validate_success(api.approve_loss_claim(rp["claim"]["id"], rp["adj_headers"]), 200)
    assert rp_res["indemnity_cents"] == 1820000, rp_res["indemnity_cents"]

    assert rp_res["indemnity_cents"] != yp_res["indemnity_cents"]


def test_yp_ignores_harvest_price_entirely(api):
    """PRD §3.7: "For a yield-protection election (plan_type of YP), the loss is measured
    purely in bushels and priced at the projected price; the harvest price is ignored
    entirely."

    Design: Difficulty/dual_variant_calc/dual_variant_yp_vs_rp_indemnity_same_loss
    """
    # Same YP inputs as the paired test but with a different (higher) published harvest
    # price (9.99). YP must ignore harvest entirely -> indemnity unchanged at 1400000.
    yp = setup_submitted_loss_claim(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                    acres=100, share=1, production_to_count_bu=10000,
                                    publish_harvest=9.99)
    res = validate_success(api.approve_loss_claim(yp["claim"]["id"], yp["adj_headers"]), 200)
    # YP per-acre = (135-100)*4.00 = 140; *100ac*1*100 = 1400000, harvest 9.99 irrelevant.
    assert res["indemnity_cents"] == 1400000, res["indemnity_cents"]


def test_loss_indemnity_differs_from_prevented_planting_indemnity(api):
    """PRD §3.7: "the per-acre indemnity is the shortfall of guaranteed yield below
    production made — that is, the guaranteed yield per acre minus the production per
    acre, but never less than zero — multiplied by the program's projected_price."
    PRD §3.8: "The prevented-planting indemnity per acre in cents is the election's
    dollar_liability_per_acre_cents multiplied by the program's pp_coverage_factor,
    rounded to a whole number of cents; the per-acre figure is rounded first."

    Design: Difficulty/dual_variant_calc/dual_variant_lossclaim_indemnity_vs_pp_indemnity
    """
    # 100-ac unit; report 60 planted + 40 prevented. The loss claim is UNDER_REVIEW
    # and the unit is ACTIVE after setup.
    ctx = setup_submitted_loss_claim(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     acres=100, share=1, production_to_count_bu=6000,
                                     publish_harvest=5.20, planted_acres=60, prevented_acres=40,
                                     clock="2026-06-01T00:00:00Z")
    # File and submit a PP claim on the SAME unit BEFORE approving the loss claim, so the
    # unit keeps an open (UNDER_REVIEW) claim when the loss claim is approved. PRD §3.6
    # settles the unit to SETTLED only "when ... no other claim on that unit is still in
    # DRAFT or UNDER_REVIEW"; with the PP claim still open, approving the loss claim leaves
    # the unit ACTIVE so the PP claim can run to approval too.
    pp = get_success_data(api.create_pp_claim(
        {"unit_id": ctx["unit"]["id"], "claimed_prevented_acres": 40, "cause": "EXCESS_MOISTURE"},
        ctx["sa_headers"]))
    api.submit_pp_claim(pp["id"], ctx["sa_headers"])

    # YP: guar_bu=135/ac; ptc_per_acre=6000/100=60; (135-60)*4=300/ac; *100ac*1*100 = 3000000
    loss_res = validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert loss_res["indemnity_cents"] == 3000000, loss_res["indemnity_cents"]

    # PP on the SAME unit: claim 40 prevented ac. liability 54000c/ac * 0.60 = 32400c/ac;
    #   * 40 ac * 1 = 1296000c
    pp_res = validate_success(api.approve_pp_claim(pp["id"], ctx["adj_headers"]), 200)
    assert pp_res["pp_indemnity_cents"] == 1296000, pp_res["pp_indemnity_cents"]

    assert pp_res["pp_indemnity_cents"] != loss_res["indemnity_cents"]


def test_prevented_planting_indemnity_independent_of_production(api):
    """PRD §3.8: "The prevented-planting indemnity per acre in cents is the election's
    dollar_liability_per_acre_cents multiplied by the program's pp_coverage_factor,
    rounded to a whole number of cents; the per-acre figure is rounded first. The claim's
    pp_indemnity_cents is then that rounded per-acre amount multiplied by the
    claimed_prevented_acres and the unit's share, rounded again to a whole number of cents."

    Design: Difficulty/dual_variant_calc/dual_variant_lossclaim_indemnity_vs_pp_indemnity
    """
    # The PP indemnity is a function only of liability, pp_factor, prevented acres, and
    # share — never of production_to_count_bu (which lives in the LossClaim domain). A unit
    # reporting 60 planted + 40 prevented, with a 40-ac PP claim, yields the same
    # 1296000c as in the paired test regardless of any production figure.
    ctx = setup_submitted_pp_claim(coverage_level=0.75, acres=100, share=1,
                                   planted_acres=60, prevented_acres=40,
                                   claimed_prevented_acres=40, cause="EXCESS_MOISTURE")
    # liability 54000c/ac * 0.60 = 32400c/ac; * 40 ac * 1 = 1296000c
    res = validate_success(api.approve_pp_claim(ctx["pp_claim"]["id"], ctx["adj_headers"]), 200)
    assert res["pp_indemnity_cents"] == 1296000, res["pp_indemnity_cents"]


def test_indemnity_zero_when_production_meets_guarantee(api):
    """PRD §3.7: "the guaranteed yield per acre minus the production per acre, but never
    less than zero — multiplied by the program's projected_price."
    PRD §3.6: "computes and sets its indemnity_cents by the methodology of §3.7 (which
    is required to be at least zero)"

    Design: Difficulty/boundary_precision_check/boundary_no_loss_indemnity_zero_when_production_meets_guarantee
    """
    # guar_bu=135/ac -> 13500 bu over 100 ac. ptc=13500 exactly meets -> max(0,135-135)=0.
    ctx = setup_submitted_loss_claim(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     acres=100, share=1, production_to_count_bu=13500,
                                     publish_harvest=5.20)
    res = validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert res["status"] == "APPROVED"
    assert res["indemnity_cents"] == 0, res["indemnity_cents"]


def test_indemnity_zero_boundary_one_bushel_short_pays(api):
    """PRD §3.7: "the guaranteed yield per acre minus the production per acre, but never
    less than zero — multiplied by the program's projected_price."

    Design: Difficulty/boundary_precision_check/boundary_no_loss_indemnity_zero_when_production_meets_guarantee
    """
    # ptc=13499 (1 bu short of the 13500-bu guarantee): guar_bu=135/ac, ptc_per_acre=134.99;
    #   (135-134.99)*4 = 0.04/ac; *100ac*1*100 = 400c.
    ctx = setup_submitted_loss_claim(plan_type="YP", aph_yield=180, coverage_level=0.75,
                                     acres=100, share=1, production_to_count_bu=13499,
                                     publish_harvest=5.20)
    res = validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert res["status"] == "APPROVED"
    assert res["indemnity_cents"] == 400, res["indemnity_cents"]


def test_rp_hpe_indemnity_excludes_harvest_upside(api):
    """PRD §3.7: "for RP_HPE, the revenue price is the projected price alone, excluding
    harvest-price upside. In both revenue variants the calculated revenue still uses the
    harvest price."

    Design: Corner/calculations/rp_hpe_indemnity_excludes_harvest_upside
    """
    # RP_HPE: rev guar 135*4.00=540/ac; calc rev 100*5.20=520/ac; (540-520)=20/ac;
    #   *100ac*1*100 = 200000
    ctx = setup_submitted_loss_claim(plan_type="RP_HPE", aph_yield=180, coverage_level=0.75,
                                     acres=100, share=1, production_to_count_bu=10000,
                                     publish_harvest=5.20)
    res = validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert res["indemnity_cents"] == 200000, res["indemnity_cents"]


def test_rp_indemnity_uses_projected_when_harvest_below_projected(api):
    """PRD §3.7: "for RP, the revenue price is the greater of the projected price and the
    harvest price (so the producer captures harvest-price upside)"

    Design: Corner/calculations/rp_indemnity_uses_projected_when_harvest_below_projected
    """
    # RP, harvest 3.00 < projected 4.00: rev guar 135*max(4,3)=540/ac; calc rev 100*3.00=300/ac;
    #   (540-300)=240/ac; *100ac*1*100 = 2400000
    ctx = setup_submitted_loss_claim(plan_type="RP", aph_yield=180, coverage_level=0.75,
                                     acres=100, share=1, production_to_count_bu=10000,
                                     publish_harvest=3.00)
    res = validate_success(api.approve_loss_claim(ctx["claim"]["id"], ctx["adj_headers"]), 200)
    assert res["indemnity_cents"] == 2400000, res["indemnity_cents"]


def test_prevented_planting_indemnity_correct_result(api):
    """PRD §3.8: "The prevented-planting indemnity per acre in cents is the election's
    dollar_liability_per_acre_cents multiplied by the program's pp_coverage_factor,
    rounded to a whole number of cents; the per-acre figure is rounded first. The claim's
    pp_indemnity_cents is then that rounded per-acre amount multiplied by the
    claimed_prevented_acres and the unit's share, rounded again to a whole number of cents."

    Design: Corner/calculations/prevented_planting_indemnity_correct_result
    """
    # liability 54000c/ac * 0.60 = 32400c/ac; * 30 prevented ac * 1 = 972000c
    ctx = setup_submitted_pp_claim(coverage_level=0.75, acres=100, share=1,
                                   planted_acres=0, prevented_acres=30,
                                   claimed_prevented_acres=30, cause="FLOOD")
    res = validate_success(api.approve_pp_claim(ctx["pp_claim"]["id"], ctx["adj_headers"]), 200)
    assert res["pp_indemnity_cents"] == 972000, res["pp_indemnity_cents"]

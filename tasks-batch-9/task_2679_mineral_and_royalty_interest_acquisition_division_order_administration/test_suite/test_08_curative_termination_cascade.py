"""A curative termination: three hops back out of the acquisition pipeline."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.test_users import MANAGER_HEADERS

TWO_LARGE_DEFECTS = [
    {"defect_type": "OVERCONVEYANCE", "affected_nma": 20.0000, "description": "Overconveyance across half the interest"},
    {"defect_type": "MISSING_HEIR", "affected_nma": 12.0000, "description": "Three unlocated heirs of the 1988 estate"},
]


def test_uncured_defects_above_the_basket_move_the_price(api):
    """Both defects sweep to UNCURED and their net values enter the waterfall.

    PRD: "For each one in turn, its `allocated_value` and `net_defect_value` are
    recomputed by the two rules stated earlier in this subsection, and the running
    total accumulates as the previous running total plus that defect's
    `net_defect_value`, rounded half-up to cents at each addition."

    Design: Difficulty/transitive_cascade/curative_termination_cascades_psa_to_interest_to_offer_and_valuation
    """
    world = fx.psa_with_defects_ready(api, TWO_LARGE_DEFECTS)

    fx.close_curative(api, world["psa"]["id"])

    first = fx.read_defect(api, world["defects"][0]["id"])
    second = fx.read_defect(api, world["defects"][1]["id"])
    assert_money(first["net_defect_value"], "21500.00", "net_defect_value of the 20-acre defect")
    assert first["defect_status"] == "UNCURED"
    assert_money(second["net_defect_value"], "11900.00", "net_defect_value of the 12-acre defect")
    assert second["defect_status"] == "UNCURED"


def test_adjustment_above_the_termination_ceiling_terminates_the_agreement(api):
    """An adjustment of 17400.00 exceeds the 9600.00 ceiling, so the deal dies.

    PRD: "If the adjustment is strictly greater than that ceiling, the curative
    dimension moves `CURATIVE_OPEN → CURATIVE_TERMINATED` instead."

    Design: Difficulty/transitive_cascade/curative_termination_cascades_psa_to_interest_to_offer_and_valuation
    """
    world = fx.psa_with_defects_ready(api, TWO_LARGE_DEFECTS)

    psa = fx.close_curative(api, world["psa"]["id"])

    assert_money(psa["defect_adjustment_amount"], "17400.00", "defect_adjustment_amount")
    assert_money(psa["adjusted_purchase_price"], "30600.00", "adjusted_purchase_price")
    assert psa["curative_status"] == "CURATIVE_TERMINATED"
    assert psa["psa_status"] == "TERMINATED"
    assert psa["funding_status"] == "UNFUNDED"


def test_termination_reverts_the_interest_and_voids_its_offer_and_valuation(api):
    """Hops two and three: PROSPECT again, with a voided offer and a stale price.

    PRD: "Caused by that second hop rather than by the close itself, the third hop
    reaches two more rows: the offer letter of that interest whose `offer_status`
    is `ACCEPTED` is driven `ACCEPTED → VOIDED`, and the valuation of that
    interest whose `valuation_status` is `CURRENT` is driven `CURRENT → STALE`."

    Design: Difficulty/transitive_cascade/curative_termination_cascades_psa_to_interest_to_offer_and_valuation
    """
    world = fx.psa_with_defects_ready(api, TWO_LARGE_DEFECTS)

    fx.close_curative(api, world["psa"]["id"])

    assert fx.read_interest(api, world["interest"]["id"])["interest_status"] == "PROSPECT"
    assert fx.read_offer(api, world["offer"]["id"])["offer_status"] == "VOIDED"
    valuation = validate_success(
        api.get_valuation(world["valuation"]["id"], MANAGER_HEADERS)
    )
    assert valuation["valuation_status"] == "STALE"

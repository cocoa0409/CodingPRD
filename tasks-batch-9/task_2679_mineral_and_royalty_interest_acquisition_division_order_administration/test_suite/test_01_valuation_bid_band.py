"""Decline-curve valuation: the pdp-only and risked-upside variants of one dataset."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money, assert_rate
from test_helpers.test_users import MANAGER_HEADERS, MANAGER_USER_ID, make_headers
from test_helpers.constants import ROLE_ACQUISITION_MANAGER


def _interest_on_certified_tract(api):
    tract = fx.create_certified_tract(api)
    owner = fx.create_owner(api)
    interest = fx.create_interest(api, tract["id"], owner["id"])
    return tract, owner, interest


def test_valuation_pdp_only_variant_sets_the_walk_away_bid_floor(api):
    """The pdp-only variant of the bid band is pdp_pv haircut by the burden.

    PRD: "The `bid_floor` is `pdp_pv` multiplied by that haircut, rounded
    half-up to cents; this is the proved-developed-producing-only variant, the
    walk-away number below which the firm will not bid."

    Design: Difficulty/dual_variant_calc/valuation_bid_band_pdp_only_versus_risked_upside
    """
    _tract, _owner, interest = _interest_on_certified_tract(api)

    response = api.create_valuation(
        interest["id"],
        f.valuation_payload(
            current_monthly_net_revenue=1200.00,
            annual_decline_rate=0.18,
            undeveloped_net_acres=20.0000,
        ),
        make_headers(MANAGER_USER_ID, ROLE_ACQUISITION_MANAGER),
    )
    valuation = validate_success(response, 201)

    assert_money(valuation["pdp_pv"], "39589.70", "pdp_pv")
    assert_money(valuation["bid_floor"], "37115.34", "bid_floor")


def test_valuation_risked_upside_variant_sets_the_max_bid(api):
    """The risked-upside variant adds undeveloped_pv before the same haircut.

    PRD: "For identical valuation inputs, the two variants differ by exactly
    `undeveloped_pv` multiplied by the haircut, rounded half-up to cents — which
    is to say the entire difference between the floor and the ceiling of the band
    is the risked value of undeveloped acreage."

    Design: Difficulty/dual_variant_calc/valuation_bid_band_pdp_only_versus_risked_upside
    """
    _tract, _owner, interest = _interest_on_certified_tract(api)

    response = api.create_valuation(
        interest["id"],
        f.valuation_payload(
            current_monthly_net_revenue=1200.00,
            annual_decline_rate=0.18,
            undeveloped_net_acres=20.0000,
        ),
        make_headers(MANAGER_USER_ID, ROLE_ACQUISITION_MANAGER),
    )
    valuation = validate_success(response, 201)

    assert_money(valuation["undeveloped_pv"], "19440.00", "undeveloped_pv")
    assert_money(valuation["max_bid"], "55340.34", "max_bid")
    assert_money(
        float(valuation["max_bid"]) - float(valuation["bid_floor"]),
        "18225.00",
        "max_bid less bid_floor",
    )


def test_valuation_copies_the_tract_tier_and_becomes_the_current_valuation(api):
    """The filed valuation copies the tract's tier and is pointed at by the interest.

    PRD: "Filing a valuation sets its `valuation_status` to `CURRENT` and stamps
    `approved_by_user_id` with the filing manager's `X-User-ID` — the counterparty
    for the segregation-of-duties check of §2.6."

    Design: Difficulty/dual_variant_calc/valuation_bid_band_pdp_only_versus_risked_upside
    """
    _tract, _owner, interest = _interest_on_certified_tract(api)

    response = api.create_valuation(
        interest["id"],
        f.valuation_payload(),
        make_headers(MANAGER_USER_ID, ROLE_ACQUISITION_MANAGER),
    )
    valuation = validate_success(response, 201)

    assert valuation["operator_activity_tier"] == "HIGH"
    assert valuation["valuation_status"] == "CURRENT"
    assert valuation["approved_by_user_id"] == MANAGER_USER_ID
    assert_rate(valuation["annual_decline_rate"], "0.180000", "annual_decline_rate")

    reread = validate_success(api.get_mineral_interest(interest["id"], MANAGER_HEADERS))
    assert reread["current_valuation_id"] == valuation["id"]

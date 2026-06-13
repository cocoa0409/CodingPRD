"""Combinatorial formulas: marginal-band surety premium and the jointly-keyed
(result, condition_code) compliance check-in weight.
"""
from test_helpers import (
    validate_success,
    setup_active_surety_bond, setup_active_bond_with_active_gps,
    TEST_USERS,
)

RECOVERY = TEST_USERS["recovery_agent_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/surety_premium_marginal_tier_banding
# ---------------------------------------------------------------------------
def test_surety_premium_marginal_banding_3m_face(api):
    """PRD 3.2: "Each band is priced at its own effective rate, which is the
    greater of the negotiated `premium_rate_bps` and that band's statutory floor —
    a floor of 1000 basis points on the first band, 800 basis points on the second,
    and 600 basis points on the third."

    Face 3,000,000c at 1000 bps: band1 1,000,000*1000 + band2 2,000,000*max(1000,800)=1000
    -> (1,000,000,000 + 2,000,000,000)/10000 == 300000, above the 10,000 minimum.

    Design: Difficulty/combinatorial_formula/surety_premium_marginal_tier_banding
    """
    scen = setup_active_surety_bond(bail_amount_cents=3_000_000, liability_share_cents=3_000_000,
                                    collateral_value_cents=750_000)
    assert scen["bond"]["premium_cents"] == 300000, scen["bond"]["premium_cents"]
    assert scen["bond"]["coverage_status"] == "ACTIVE"


def test_surety_premium_second_band_floor_distinct_from_flat(api):
    """PRD 3.2: "The premium before the minimum is the sum across the three bands
    of each band's face amount multiplied by its effective basis-point rate, that
    total divided by 10,000; the three bands are summed as exact integer products
    before the single division, and the result is rounded half up to whole cents
    at that final step only."

    Face 6,000,000c at 600 bps: band1 1,000,000*max(600,1000)=1000;
    band2 4,000,000*max(600,800)=800; band3 1,000,000*max(600,600)=600 ->
    (1,000,000,000 + 3,200,000,000 + 600,000,000)/10000 == 480000.

    Design: Difficulty/combinatorial_formula/surety_premium_marginal_tier_banding
    """
    scen = setup_active_surety_bond(bail_amount_cents=6_000_000, premium_rate_bps=600,
                                    liability_share_cents=6_000_000, collateral_value_cents=1_500_000)
    assert scen["bond"]["premium_cents"] == 480000, scen["bond"]["premium_cents"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/compliance_score_weight_joint_result_and_condition
# ---------------------------------------------------------------------------
def test_checkin_weight_gps_fail_is_five(api):
    """PRD 3.8: "A `FAIL` contributes a base weight of 2, plus an additional 3
    points when the failing condition is `GPS`, so that a GPS failure carries a
    weight of 5 while any other failure carries a weight of 2."

    Design: Difficulty/combinatorial_formula/compliance_score_weight_joint_result_and_condition
    """
    scen = setup_active_bond_with_active_gps(condition_codes=["GPS", "DRUG_TEST", "CURFEW"])
    ci = validate_success(
        api.create_check_in(scen["def_id"], {"bond_id": scen["bond_id"], "condition_code": "GPS", "result": "FAIL"}, RECOVERY),
        expected_status=201,
    )
    assert ci["weight"] == 5, ci["weight"]


def test_checkin_weight_drug_fail_is_two_and_curfew_missed_is_one(api):
    """PRD 3.8: "A `MISSED` contributes a weight of 1. A `FAIL` contributes a base
    weight of 2, plus an additional 3 points when the failing condition is `GPS`,
    so that a GPS failure carries a weight of 5 while any other failure carries a
    weight of 2."

    DRUG_TEST + FAIL == 2 (non-GPS fail); CURFEW + MISSED == 1.

    Design: Difficulty/combinatorial_formula/compliance_score_weight_joint_result_and_condition
    """
    scen = setup_active_bond_with_active_gps(condition_codes=["GPS", "DRUG_TEST", "CURFEW"])
    drug = validate_success(
        api.create_check_in(scen["def_id"], {"bond_id": scen["bond_id"], "condition_code": "DRUG_TEST", "result": "FAIL"}, RECOVERY),
        expected_status=201,
    )
    assert drug["weight"] == 2, drug["weight"]
    curfew = validate_success(
        api.create_check_in(scen["def_id"], {"bond_id": scen["bond_id"], "condition_code": "CURFEW", "result": "MISSED"}, RECOVERY),
        expected_status=201,
    )
    assert curfew["weight"] == 1, curfew["weight"]

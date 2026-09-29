"""Disproportionate share eligibility right at the fifteen-percent boundary."""

from test_helpers import assert_money_equals, assert_ucc_data_set
from test_helpers.fixtures import add_ucc_data_set, new_scenario


def test_rounding_each_fraction_first_lands_exactly_on_the_threshold(api):
    """Two fractions of 7495/100000 each round to 0.0750 and add to exactly
    0.1500, which qualifies for disproportionate share.

    PRD 3.7: "`dsh_patient_percentage` is the sum of those two **already-rounded** fractions, itself rounded half up to four decimal places — rounding each fraction first and then adding is normative, because summing the raw quotients and rounding once produces a different four-decimal value right at the eligibility boundary."

    Design: Difficulty/boundary_precision_check/dsh_patient_percentage_exactly_at_eligibility_threshold
    """
    scenario = new_scenario(api)

    data_set = add_ucc_data_set(api, scenario)

    assert_ucc_data_set(data_set)
    assert data_set["medicaid_fraction"] == 0.0750
    assert data_set["ssi_fraction"] == 0.0750
    assert data_set["dsh_patient_percentage"] == 0.1500
    assert data_set["dsh_patient_percentage"] != 0.1499
    assert data_set["dsh_eligible"] is True


def test_uncompensated_care_cost_rounds_its_two_terms_separately(api):
    """With no allocation yet the snapshot ratio is zero, so only the bad-debt
    term survives: 6500000 cents of cost and 1300000 of payment.

    PRD 3.7: "`uncompensated_care_cost_cents` is the sum of two separately rounded terms: `charity_care_charges_cents` multiplied by that snapshot ratio, rounded half up to a whole cent, plus `non_medicare_bad_debt_cents` multiplied by 0.65 — sixty-five percent of non-Medicare bad debt is allowable — rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/dsh_patient_percentage_exactly_at_eligibility_threshold
    """
    scenario = new_scenario(api)

    data_set = add_ucc_data_set(api, scenario)

    assert data_set["cost_to_charge_ratio"] == 0.000000
    assert_money_equals(
        data_set["uncompensated_care_cost_cents"], 6500000, "uncompensated_care_cost_cents"
    )
    assert_money_equals(data_set["ucc_payment_cents"], 1300000, "ucc_payment_cents")
    assert data_set["recompute_required"] is False

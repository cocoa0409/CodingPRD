"""Household income certification: the two methodologies and the 80.0 edge."""

import pytest

from test_helpers import (
    api_client,
    assert_ami_percent_precision,
    assert_applicant,
    validate_success,
)
from test_helpers.fixtures import INTAKE, build_applicant

# Identical household economics; only `income_calc_method` differs between the
# two rows.
SHARED_HOUSEHOLD = {
    "full_name": "Ramona Vela",
    "household_size": 4,
    "wage_income_cents": 7_150_000,
    "benefit_income_cents": 0,
    "actual_asset_income_cents": 0,
    "household_assets_cents": 20_000_000,
    "dependents_count": 1,
    "elderly_household": False,
}


def _certify(applicant_id):
    return validate_success(api_client.verify_income(applicant_id, INTAKE), 200)


class TestMethodologyDivergence:
    """One household record, two methodologies, opposite program decisions."""

    def test_part_5_annual_imputes_asset_income_and_lands_over_income(
        self, program_year
    ):
        """Part 5 counts gross income and imputes asset income at the passbook rate.

        PRD: "Under `PART_5_ANNUAL`, gross income from all sources counts, and
        asset income is imputed. When `household_assets_cents` is strictly
        greater than five thousand dollars — that is, strictly greater than
        500,000 cents — the imputed figure is `household_assets_cents`
        multiplied by the passbook savings rate of four tenths of one percent,
        rounded half up to whole cents, and the asset income used is the greater
        of that imputed figure and `actual_asset_income_cents`."

        Design: Difficulty/dual_variant_calc/part5_vs_irs1040_income_certification_diverges_across_the_eligibility_band
        """
        applicant = build_applicant(
            program_year["id"], income_calc_method="PART_5_ANNUAL", **SHARED_HOUSEHOLD
        )

        certified = _certify(applicant["id"])

        assert_applicant(certified)
        assert certified["income_limit_cents"] == 9_000_000, (
            "A four-person household carries the 1.00 adjustment factor, so the "
            f"limit is the area median itself, got {certified['income_limit_cents']}"
        )
        assert certified["annual_income_cents"] == 7_230_000, (
            "Wages 7,150,000 plus the imputed 80,000 of asset income should give "
            f"7,230,000, got {certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == pytest.approx(80.3, abs=0.01)
        assert_ami_percent_precision(certified["ami_percent"])
        assert certified["income_category"] == "OVER_INCOME"
        assert certified["eligibility_status"] == "INELIGIBLE"
        assert certified["verified_by_user_id"] == "is-1"

    def test_irs_1040_adjusted_drops_the_imputation_and_stays_income_eligible(
        self, program_year
    ):
        """The adjusted-gross methodology never imputes and subtracts deductions.

        PRD: "Under `IRS_1040_ADJUSTED`, `benefit_income_cents` is excluded
        entirely, asset income is never imputed and only
        `actual_asset_income_cents` counts, and deductions are subtracted."

        Design: Difficulty/dual_variant_calc/part5_vs_irs1040_income_certification_diverges_across_the_eligibility_band
        """
        applicant = build_applicant(
            program_year["id"],
            income_calc_method="IRS_1040_ADJUSTED",
            **SHARED_HOUSEHOLD,
        )

        certified = _certify(applicant["id"])

        assert certified["income_limit_cents"] == 9_000_000
        assert certified["annual_income_cents"] == 7_102_000, (
            "Wages 7,150,000 less the single 48,000 dependent deduction should "
            f"give 7,102,000, got {certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == pytest.approx(78.9, abs=0.01)
        assert certified["income_category"] == "LOW"
        assert certified["eligibility_status"] == "INCOME_VERIFIED"
        assert certified["verified_by_user_id"] == "is-1"

    def test_the_two_methodologies_separate_by_the_imputation_and_the_deduction(
        self, program_year
    ):
        """The same declarations certify 128,000 cents apart across the band.

        PRD: "Annual income is then determined by the household's declared
        methodology, and the two methodologies genuinely disagree on the same
        household record."

        Design: Difficulty/dual_variant_calc/part5_vs_irs1040_income_certification_diverges_across_the_eligibility_band
        """
        part5 = build_applicant(
            program_year["id"], income_calc_method="PART_5_ANNUAL", **SHARED_HOUSEHOLD
        )
        irs = build_applicant(
            program_year["id"],
            income_calc_method="IRS_1040_ADJUSTED",
            **SHARED_HOUSEHOLD,
        )

        certified_part5 = _certify(part5["id"])
        certified_irs = _certify(irs["id"])

        gap = (
            certified_part5["annual_income_cents"]
            - certified_irs["annual_income_cents"]
        )
        assert gap == 128_000, (
            "The 80,000 imputation plus the 48,000 deduction should separate the "
            f"two certifications by 128,000 cents, got {gap}"
        )
        assert certified_part5["income_category"] == "OVER_INCOME"
        assert certified_irs["income_category"] == "LOW"
        assert certified_part5["eligibility_status"] == "INELIGIBLE"
        assert certified_irs["eligibility_status"] == "INCOME_VERIFIED"


class TestEightyPercentBand:
    """The `LOW` to `OVER_INCOME` edge is inclusive at 80.0 percent."""

    def _edge_household(self, program_year_id, wage_income_cents):
        return build_applicant(
            program_year_id,
            full_name="Edge Case",
            household_size=4,
            income_calc_method="PART_5_ANNUAL",
            wage_income_cents=wage_income_cents,
            benefit_income_cents=0,
            actual_asset_income_cents=0,
            household_assets_cents=5_000_000,
            dependents_count=0,
            elderly_household=False,
        )

    def test_ami_percent_of_exactly_eighty_point_zero_certifies_as_low(
        self, program_year
    ):
        """Exactly 80.0 percent of the adjusted limit is still an assisted band.

        PRD: "The band is read off that rounded percentage: at or below 30.0
        percent the `income_category` is `EXTREMELY_LOW`; above 30.0 and at or
        below 50.0 it is `VERY_LOW`; above 50.0 and at or below 80.0 it is
        `LOW`; above 80.0 it is `OVER_INCOME`."

        Design: Difficulty/boundary_precision_check/ami_percent_of_exactly_eighty_point_zero_is_still_income_eligible
        """
        applicant = self._edge_household(program_year["id"], 7_180_000)

        certified = _certify(applicant["id"])

        assert certified["annual_income_cents"] == 7_200_000, (
            "Wages 7,180,000 plus 20,000 of imputed asset income should give "
            f"7,200,000, got {certified['annual_income_cents']}"
        )
        assert certified["ami_percent"] == pytest.approx(80.0, abs=0.01)
        assert certified["income_category"] == "LOW"
        assert certified["eligibility_status"] == "INCOME_VERIFIED"

    def test_ami_percent_of_eighty_point_one_certifies_as_over_income(
        self, program_year
    ):
        """Five thousand cents more wage income rounds to 80.1 and is over income.

        PRD: "With both figures in hand, `ami_percent` is one hundred
        multiplied by `annual_income_cents` divided by `income_limit_cents`,
        rounded half up to one decimal place."

        Design: Difficulty/boundary_precision_check/ami_percent_of_exactly_eighty_point_zero_is_still_income_eligible
        """
        applicant = self._edge_household(program_year["id"], 7_185_000)

        certified = _certify(applicant["id"])

        assert certified["annual_income_cents"] == 7_205_000
        assert certified["ami_percent"] == pytest.approx(80.1, abs=0.01), (
            "A raw 80.0555 percent rounds half up to 80.1, got "
            f"{certified['ami_percent']}"
        )
        assert certified["income_category"] == "OVER_INCOME"
        assert certified["eligibility_status"] == "INELIGIBLE"

    def test_both_edge_households_share_one_limit_and_one_imputed_asset_figure(
        self, program_year
    ):
        """The 5,000-cent input gap is the only thing separating the two rows.

        PRD: "`income_limit_cents` is the program year's
        `ami_median_income_cents` multiplied by the adjustment factor for the
        household size, rounded half up to whole cents."

        Design: Difficulty/boundary_precision_check/ami_percent_of_exactly_eighty_point_zero_is_still_income_eligible
        """
        at_edge = self._edge_household(program_year["id"], 7_180_000)
        over_edge = self._edge_household(program_year["id"], 7_185_000)

        certified_at_edge = _certify(at_edge["id"])
        certified_over_edge = _certify(over_edge["id"])

        assert certified_at_edge["income_limit_cents"] == 9_000_000
        assert certified_over_edge["income_limit_cents"] == 9_000_000
        imputed_at_edge = (
            certified_at_edge["annual_income_cents"] - 7_180_000
        )
        imputed_over_edge = (
            certified_over_edge["annual_income_cents"] - 7_185_000
        )
        assert imputed_at_edge == 20_000, (
            "Assets of 5,000,000 cents impute 20,000 at four tenths of one "
            f"percent, got {imputed_at_edge}"
        )
        assert imputed_over_edge == 20_000
        assert (
            certified_over_edge["annual_income_cents"]
            - certified_at_edge["annual_income_cents"]
            == 5_000
        )


def test_certification_answers_two_hundred_for_an_over_income_household(
    program_year,
):
    """Over-income households are certified and recorded, never refused.

    PRD: "Over-income households are not refused at certification time — they
    are recorded and then blocked at application intake with
    `ERR_APPLICANT_OVER_INCOME`."

    Design: Difficulty/dual_variant_calc/part5_vs_irs1040_income_certification_diverges_across_the_eligibility_band
    """
    applicant = build_applicant(
        program_year["id"], income_calc_method="PART_5_ANNUAL", **SHARED_HOUSEHOLD
    )
    assert applicant["eligibility_status"] == "APPLIED"

    response = api_client.verify_income(applicant["id"], INTAKE)

    certified = validate_success(response, 200)
    assert certified["eligibility_status"] == "INELIGIBLE"
    assert certified["version"] == applicant["version"] + 1, (
        "Certification advances the household version by one, got "
        f"{certified['version']} from {applicant['version']}"
    )

"""MAGI and countable-asset calculations, including FEDERAL vs STATE
rule variants.

Exercises PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_income,
    decide_application,
    get_applicant,
    get_application,
    setup_basic_household,
    setup_eligible_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# Annualization — PRD §3.2
# ===========================================================================
class TestMagiAnnualization:

    @pytest.mark.parametrize("frequency,gross_amount,expected_magi", [
        ("ANNUAL", 20_000.00, 20_000.00),
        ("MONTHLY", 1_000.00, 12_000.00),
        ("BIWEEKLY", 500.00, 13_000.00),
        ("WEEKLY", 200.00, 10_400.00),
    ])
    def test_wage_annualization_per_frequency(
            self, api, intake_worker_headers,
            frequency, gross_amount, expected_magi):
        """PRD §3.2: "when the frequency is ANNUAL the annualized amount
        is the gross_amount itself; when it is MONTHLY the gross amount
        is multiplied by twelve; when it is BIWEEKLY the gross amount
        is multiplied by twenty-six; when it is WEEKLY the gross amount
        is multiplied by fifty-two."

        Claim: a single WAGES IncomeRecord at the given frequency
        annualizes to the expected magi_income.
        """
        _sp, household, [applicant] = setup_basic_household()
        add_income(
            household=household, applicant=applicant,
            source_type="WAGES", gross_amount=gross_amount,
            frequency=frequency,
        )
        a = get_applicant(household["id"], applicant["id"])
        assert float(a["magi_income"]) == pytest.approx(expected_magi), (
            f"frequency={frequency!r} gross={gross_amount} must annualize "
            f"to {expected_magi}; got magi_income={a['magi_income']}"
        )


# ===========================================================================
# MAGI countable sources — PRD §3.2
# ===========================================================================
class TestMagiCountableSourceTypes:

    @pytest.mark.parametrize("source_type", [
        "WAGES", "SELF_EMPLOYMENT", "INTEREST", "DIVIDENDS",
        "CAPITAL_GAINS", "UNEMPLOYMENT", "OTHER",
    ])
    def test_countable_sources_contribute_to_magi(
            self, api, intake_worker_headers, source_type):
        """PRD §3.2: "the countable set for MAGI is WAGES,
        SELF_EMPLOYMENT, INTEREST, DIVIDENDS, CAPITAL_GAINS,
        UNEMPLOYMENT, and OTHER."

        Claim: a single $10,000 ANNUAL record from this source_type
        produces magi_income=10000.00.
        """
        _sp, household, [applicant] = setup_basic_household()
        add_income(
            household=household, applicant=applicant,
            source_type=source_type, gross_amount=10_000.00,
            frequency="ANNUAL",
        )
        a = get_applicant(household["id"], applicant["id"])
        assert float(a["magi_income"]) == pytest.approx(10_000.00), (
            f"{source_type} must contribute to MAGI per PRD §3.2; "
            f"got magi_income={a['magi_income']}"
        )

    @pytest.mark.parametrize("source_type", [
        "CHILD_SUPPORT", "TANF", "SSI",
    ])
    def test_excluded_sources_do_not_contribute_to_magi(
            self, api, intake_worker_headers, source_type):
        """PRD §3.2: "CHILD_SUPPORT, TANF, and SSI are never countable
        for MAGI."

        Claim: a $10,000 ANNUAL record from this source produces
        magi_income=0.
        """
        _sp, household, [applicant] = setup_basic_household()
        add_income(
            household=household, applicant=applicant,
            source_type=source_type, gross_amount=10_000.00,
            frequency="ANNUAL",
        )
        a = get_applicant(household["id"], applicant["id"])
        assert float(a["magi_income"]) == pytest.approx(0.0), (
            f"{source_type} must NOT contribute to MAGI per PRD §3.2; "
            f"got magi_income={a['magi_income']}"
        )

    def test_social_security_countable_for_primary(
            self, api, intake_worker_headers):
        """PRD §3.2: "SOCIAL_SECURITY is countable only when the owning
        applicant's dependent_status is PRIMARY — a dependent's Social
        Security benefits are excluded from MAGI under federal rule."

        Claim: SOCIAL_SECURITY on a PRIMARY applicant contributes;
        SOCIAL_SECURITY on a DEPENDENT does not.

        # difficulty: combinatorial_formula/magi_per_applicant_conditional_inputs
        """
        # PRIMARY case.
        _sp, household, [a1] = setup_basic_household(applicants=[
            {"dependent_status": "PRIMARY"},
        ])
        add_income(
            household=household, applicant=a1,
            source_type="SOCIAL_SECURITY", gross_amount=10_000.00,
            frequency="ANNUAL",
        )
        a1_refreshed = get_applicant(household["id"], a1["id"])
        assert float(a1_refreshed["magi_income"]) == pytest.approx(10_000.00), (
            "SOCIAL_SECURITY on PRIMARY must count toward MAGI per PRD §3.2"
        )

    def test_social_security_excluded_for_dependent(
            self, api, intake_worker_headers):
        """PRD §3.2: "SOCIAL_SECURITY is countable only when the owning
        applicant's dependent_status is PRIMARY — a dependent's Social
        Security benefits are excluded from MAGI under federal rule."

        Claim: SOCIAL_SECURITY on a DEPENDENT contributes 0 to MAGI.

        # difficulty: combinatorial_formula/magi_per_applicant_conditional_inputs
        """
        _sp, household, applicants = setup_basic_household(applicants=[
            {"dependent_status": "PRIMARY"},
            {"dependent_status": "DEPENDENT"},
        ])
        dependent = applicants[1]
        add_income(
            household=household, applicant=dependent,
            source_type="SOCIAL_SECURITY", gross_amount=10_000.00,
            frequency="ANNUAL",
        )
        d = get_applicant(household["id"], dependent["id"])
        assert float(d["magi_income"]) == pytest.approx(0.0), (
            "SOCIAL_SECURITY on a DEPENDENT must NOT count toward MAGI "
            f"per PRD §3.2; got magi_income={d['magi_income']}"
        )


# ===========================================================================
# FEDERAL vs STATE total_magi — PRD §3.2
# ===========================================================================
class TestTotalMagiVariants:

    def test_federal_variant_skips_state_disregard(
            self, api, intake_worker_headers):
        """PRD §3.2: "Under the FEDERAL variant (the standard MAGI
        variant), total_magi is the sum of magi_income over all
        Applicants in the household whose dependent_status is not
        EXCLUDED, with no state disregard applied."

        Claim: with state_disregard=2000 and a $20,000 income,
        FEDERAL snapshot_magi = 20000 (disregard NOT applied).

        # difficulty: dual_variant_calc/magi_federal_vs_state_disregard
        """
        # Build household with state_disregard=2000 and a single
        # applicant earning $20,000 annually.
        _sp, household, [_a], application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
                "state_disregard_amount": 2000.00,
            },
            rule_variant="FEDERAL",
            applicants=[{"dependent_status": "PRIMARY"}],
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 20_000.00, "frequency": "ANNUAL"},
            ],
        )
        assert float(application["snapshot_magi"]) == pytest.approx(20_000.00), (
            "FEDERAL variant must NOT subtract state_disregard per PRD §3.2; "
            f"got snapshot_magi={application['snapshot_magi']}"
        )

    def test_state_variant_subtracts_state_disregard(
            self, api, intake_worker_headers):
        """PRD §3.2: "Under the STATE variant (the state-adjusted MAGI
        variant), total_magi is the maximum of zero and the same sum
        minus the household's StatePolicy.state_disregard_amount."

        Claim: with state_disregard=2000 and $20,000 income, STATE
        snapshot_magi = 18000 (disregard applied).

        # difficulty: dual_variant_calc/magi_federal_vs_state_disregard
        """
        _sp, household, [_a], application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
                "state_disregard_amount": 2000.00,
            },
            rule_variant="STATE",
            applicants=[{"dependent_status": "PRIMARY"}],
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 20_000.00, "frequency": "ANNUAL"},
            ],
        )
        assert float(application["snapshot_magi"]) == pytest.approx(18_000.00), (
            "STATE variant must subtract state_disregard per PRD §3.2; "
            f"got snapshot_magi={application['snapshot_magi']}"
        )

    def test_state_variant_floors_at_zero(self, api, intake_worker_headers):
        """PRD §3.2: "the maximum of zero and the same sum minus the
        household's StatePolicy.state_disregard_amount — that is, the
        state disregard is subtracted but the result is floored at zero
        so that the household's MAGI never becomes negative."

        Claim: with state_disregard=50000 and only $20,000 income, STATE
        snapshot_magi = 0 (not negative).
        """
        _sp, household, [_a], application = setup_eligible_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
                "state_disregard_amount": 50_000.00,
            },
            rule_variant="STATE",
            applicants=[{"dependent_status": "PRIMARY"}],
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 20_000.00, "frequency": "ANNUAL"},
            ],
        )
        assert float(application["snapshot_magi"]) == pytest.approx(0.0), (
            "STATE variant must floor total_magi at zero per PRD §3.2; "
            f"got snapshot_magi={application['snapshot_magi']}"
        )


# ===========================================================================
# Countable assets — PRD §3.2
# ===========================================================================
class TestCountableAssets:

    def test_federal_exempt_set_only(self, api, intake_worker_headers):
        """PRD §3.2: "Under the federal exempt set, only
        PRIMARY_RESIDENCE, RETIREMENT, and LIFE_INSURANCE are exempt;
        every other asset type contributes its full market_value (so a
        CHECKING balance of, for example, five thousand dollars
        contributes five thousand dollars in full)."

        Claim: FEDERAL variant counts a $5,000 CHECKING balance and a
        $20,000 VEHICLE in full (=$25,000), but exempts the
        $100,000 PRIMARY_RESIDENCE.

        # difficulty: dual_variant_calc/asset_federal_vs_state_exempt_set
        """
        _sp, household, [_a], application = setup_eligible_application(
            state_policy_kwargs={
                "asset_test_applies": True,
                "asset_limit_per_member": 100_000.00,
                "state_exempt_asset_types": ["VEHICLE"],
                "magi_income_limit_pct": 138.0,
            },
            rule_variant="FEDERAL",
            program="NON_MAGI_DISABILITY",
            applicants=[{"dependent_status": "PRIMARY",
                         "is_disabled": True}],
            assets=[
                {"applicant_index": 0, "asset_type": "PRIMARY_RESIDENCE",
                 "market_value": 100_000.00},
                {"applicant_index": 0, "asset_type": "VEHICLE",
                 "market_value": 20_000.00},
                {"applicant_index": 0, "asset_type": "CHECKING",
                 "market_value": 5_000.00},
            ],
        )
        # PRIMARY_RESIDENCE (federal exempt) = 0; VEHICLE = 20000 (state
        # exempts but FEDERAL variant ignores state exempt set);
        # CHECKING = 5000. Total = 25000.
        assert float(application["snapshot_countable_assets"]) == pytest.approx(
            25_000.00
        ), (
            "FEDERAL variant must count VEHICLE at full market_value "
            "even when state exempts it, per PRD §3.2; got "
            f"snapshot_countable_assets="
            f"{application['snapshot_countable_assets']}"
        )

    def test_state_exempt_set_includes_state_additions(
            self, api, intake_worker_headers):
        """PRD §3.2: "Under the state exempt set, the exempt set is the
        federal exempt set unioned with the state's
        state_exempt_asset_types; an asset whose type appears in either
        set contributes zero, while every other type contributes its
        full market_value (so if the state exempts VEHICLE, a
        twenty-thousand-dollar vehicle contributes zero instead of
        twenty thousand)."

        Claim: STATE variant with state_exempt={VEHICLE} counts
        $5,000 CHECKING only; PRIMARY_RESIDENCE and VEHICLE both = 0.

        # difficulty: dual_variant_calc/asset_federal_vs_state_exempt_set
        """
        _sp, household, [_a], application = setup_eligible_application(
            state_policy_kwargs={
                "asset_test_applies": True,
                "asset_limit_per_member": 100_000.00,
                "state_exempt_asset_types": ["VEHICLE"],
                "magi_income_limit_pct": 138.0,
            },
            rule_variant="STATE",
            program="NON_MAGI_DISABILITY",
            applicants=[{"dependent_status": "PRIMARY",
                         "is_disabled": True}],
            assets=[
                {"applicant_index": 0, "asset_type": "PRIMARY_RESIDENCE",
                 "market_value": 100_000.00},
                {"applicant_index": 0, "asset_type": "VEHICLE",
                 "market_value": 20_000.00},
                {"applicant_index": 0, "asset_type": "CHECKING",
                 "market_value": 5_000.00},
            ],
        )
        assert float(application["snapshot_countable_assets"]) == pytest.approx(
            5_000.00
        ), (
            "STATE variant must exempt VEHICLE when state declares it "
            "exempt per PRD §3.2; got snapshot_countable_assets="
            f"{application['snapshot_countable_assets']}"
        )

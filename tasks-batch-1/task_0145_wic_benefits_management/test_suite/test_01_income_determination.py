"""Income determination: dual-variant annualization, FPG limit, eligibility
boundary, and the adjunctive short-circuit.

These tests exercise PRD §3.3 (Income Determination) end to end. Setup builds a
DRAFT application with attached income records, then runs determine-income.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_agency,
    create_household,
    create_participant,
    create_application_with_income,
    make_cpa_headers,
    CLERK,
)


class TestDualVariantAnnualization:
    def test_average_all_diverges_from_annualize_recent(self, api):
        """PRD §3.3: "Under the AVERAGE_ALL method, the system first selects all
        income records whose pay_frequency equals the most recent record's
        frequency, takes the arithmetic mean of their gross_amount_cents, rounds
        that mean to whole cents using round-half-up, then annualizes the averaged
        cents amount at the most recent record's frequency and rounds the annual
        figure half-up to two decimal places."
        PRD §3.3: "The boundary is inclusive: an income exactly equal to the limit
        is eligible."

        Design: Difficulty/dual_variant_calc/income_recent_vs_average_diverges
        """
        agency = create_agency(caseload_cap=50)
        hh = create_household(agency["id"], household_size=3, pregnancy_count=0,
                              adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Child One", ssn_last4="1001",
                               category="CHILD")
        app = create_application_with_income(
            p["id"], [(300000, "MONTHLY"), (350000, "MONTHLY")],
            income_method="AVERAGE_ALL",
        )
        data = validate_success(api.determine_income(app["id"], CLERK))
        # mean(3000, 3500) = 3250.00/mo -> *12 = 39000.00 (vs RECENT's 42000.00)
        assert data["annual_income_determined"] == 39000.00, (
            f"AVERAGE_ALL expected 39000.00, got {data['annual_income_determined']}"
        )
        # adjusted size 3 -> FPG 25820 * 1.85 = 47767.00
        assert data["income_limit"] == 47767.00, (
            f"income_limit expected 47767.00, got {data['income_limit']}"
        )
        assert data["income_eligible"] is True

    def test_annualize_recent_uses_highest_sequence_only(self, api):
        """PRD §3.3: "Under the ANNUALIZE_RECENT method, the system annualizes
        only that highest-sequence record, ignoring all earlier records, and
        rounds the result half-up to two decimal places."
        PRD §3.3: "The most recent income record is the one with the highest
        sequence_index — never the most recently created id."

        Design: Difficulty/dual_variant_calc/income_recent_vs_average_diverges
        """
        agency = create_agency(caseload_cap=50)
        hh = create_household(agency["id"], household_size=3, pregnancy_count=0,
                              adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Child One R", ssn_last4="1011",
                               category="CHILD")
        app = create_application_with_income(
            p["id"], [(300000, "MONTHLY"), (350000, "MONTHLY")],
            income_method="ANNUALIZE_RECENT",
        )
        data = validate_success(api.determine_income(app["id"], CLERK))
        # highest-sequence record is 3500/mo -> *12 = 42000.00
        assert data["annual_income_determined"] == 42000.00, (
            f"ANNUALIZE_RECENT expected 42000.00, got {data['annual_income_determined']}"
        )
        assert data["income_limit"] == 47767.00
        assert data["income_eligible"] is True


class TestEligibilityBoundary:
    def test_income_exactly_equal_to_limit_is_eligible(self, api):
        """PRD §3.3: "the application's income_eligible flag is set true when the
        household's adjunctive_program is anything other than NONE, or when
        annual_income_determined is less than or equal to income_limit. The
        boundary is inclusive: an income exactly equal to the limit is eligible."

        Design: Difficulty/boundary_precision_check/income_equals_limit_is_eligible
        """
        agency = create_agency(caseload_cap=50)
        hh = create_household(agency["id"], household_size=1, pregnancy_count=0,
                              adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Preg Six", ssn_last4="2006",
                               category="PREGNANT")
        # FPG[1]=15060 * 1.85 = 27861.00; an ANNUAL record of exactly $27,861
        app = create_application_with_income(
            p["id"], [(2786100, "ANNUAL")], income_method="ANNUALIZE_RECENT",
        )
        data = validate_success(api.determine_income(app["id"], CLERK))
        assert data["annual_income_determined"] == 27861.00
        assert data["income_limit"] == 27861.00
        assert data["income_eligible"] is True, "income == limit must be eligible (inclusive)"

    def test_income_one_cent_above_limit_is_ineligible(self, api):
        """PRD §3.3: "the application's income_eligible flag is set true when the
        household's adjunctive_program is anything other than NONE, or when
        annual_income_determined is less than or equal to income_limit. The
        boundary is inclusive: an income exactly equal to the limit is eligible."

        Design: Difficulty/boundary_precision_check/income_equals_limit_is_eligible
        """
        agency = create_agency(caseload_cap=50)
        hh = create_household(agency["id"], household_size=1, pregnancy_count=0,
                              adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Preg Six Up", ssn_last4="2016",
                               category="PREGNANT")
        # one dollar above the size-1 limit of 27861.00
        app = create_application_with_income(
            p["id"], [(2786200, "ANNUAL")], income_method="ANNUALIZE_RECENT",
        )
        data = validate_success(api.determine_income(app["id"], CLERK))
        assert data["annual_income_determined"] == 27862.00
        assert data["income_limit"] == 27861.00
        assert data["income_eligible"] is False, "income above limit must be ineligible"

    def test_income_above_limit_without_adjunctive_is_ineligible(self, api):
        """PRD §3.3: "the application's income_eligible flag is set true when the
        household's adjunctive_program is anything other than NONE, or when
        annual_income_determined is less than or equal to income_limit."
        PRD §3.5: "the application's income_eligible must be true (otherwise
        ERR_INCOME_INELIGIBLE)".

        Design: Corner/calculations/income_ineligible_no_adjunctive_blocks_approval
        """
        agency = create_agency(caseload_cap=25)
        hh = create_household(agency["id"], household_size=1, pregnancy_count=0,
                              adjunctive_program="NONE")
        p = create_participant(hh["id"], full_name="Over Income", ssn_last4="4443",
                               category="PREGNANT")
        # MONTHLY $2500 -> annual 30000.00 > limit 27861.00
        app = create_application_with_income(
            p["id"], [(250000, "MONTHLY")], income_method="ANNUALIZE_RECENT",
        )
        data = validate_success(api.determine_income(app["id"], CLERK))
        assert data["annual_income_determined"] == 30000.00
        assert data["income_eligible"] is False
        # risk-eligible (high priority) so the approve gate is the income gate
        validate_success(api.assess_risk(app["id"], ["GEST_DIABETES"],
                                         make_cpa_headers("cpa-1")))
        resp = api.approve_application(app["id"], make_cpa_headers("cpa-1"))
        validate_error(resp, ApiErrorId.ERR_INCOME_INELIGIBLE.value)


class TestAdjunctiveShortCircuit:
    def test_adjunctive_program_overrides_numeric_income_test(self, api):
        """PRD §3.3: "Adjunctive enrollment short-circuits the income comparison
        entirely."
        PRD §3.3: "the application's income_eligible flag is set true when the
        household's adjunctive_program is anything other than NONE, or when
        annual_income_determined is less than or equal to income_limit."

        Design: Corner/calculations/adjunctive_program_overrides_income_test
        """
        agency = create_agency(caseload_cap=25)
        hh = create_household(agency["id"], household_size=1, pregnancy_count=0,
                              adjunctive_program="SNAP")
        p = create_participant(hh["id"], full_name="SNAP High", ssn_last4="4444",
                               category="CHILD")
        # MONTHLY $5000 -> annual 60000.00, far above the size-1 limit
        app = create_application_with_income(
            p["id"], [(500000, "MONTHLY")], income_method="ANNUALIZE_RECENT",
        )
        data = validate_success(api.determine_income(app["id"], CLERK))
        assert data["annual_income_determined"] == 60000.00
        assert data["income_eligible"] is True, "SNAP household must be income-eligible"


def test_determine_income_without_records_rejected(api):
    """PRD §3.3: "The application must be in DRAFT (otherwise ERR_INVALID_STATE)
    and at least one income record must already be attached (otherwise
    ERR_NO_INCOME_RECORDS)."

    Design: Corner/state_machines/determine_income_without_records_rejected
    """
    agency = create_agency(caseload_cap=25)
    hh = create_household(agency["id"], household_size=2, adjunctive_program="NONE")
    p = create_participant(hh["id"], full_name="No Inc", ssn_last4="5554", category="CHILD")
    app = validate_success(api.create_application({"participant_id": p["id"]}, CLERK), 201)
    resp = api.determine_income(app["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_NO_INCOME_RECORDS.value)

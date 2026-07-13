"""Calculation-focused tests: dual-variant project cost, weighted person confidence,
milestone invoice combinatorics, per-milestone billable rounding, and DNA bands."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    make_researcher_headers, make_client_headers, TEST_USERS,
    create_active_project, create_completed_search, create_person, add_citation,
    setup_person_under_review, setup_verified_person, log_time_data,
    setup_ready_milestone, create_milestone, create_submitted_deliverable,
    api_client,
)
from test_helpers.factories import create_dna_payload

PM = TEST_USERS["project_manager_headers"]


# ==========================================================================
# dual_variant_calc / project_cost_estimate_vs_actual_divergence
# ==========================================================================
class TestProjectCostDualVariant:
    def _setup(self):
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=150000, budget_hours=2,
            target_person_count=1)
        # One COMPLETED search estimated at 5 hours -> feeds the estimate variant.
        create_completed_search(project["id"], researcher["id"], estimated_hours=5,
                                repository_name="State Archive", search_terms="Smith 1880",
                                result_summary="Found census entry")
        # One ACTIVE billable 3-hour time entry -> feeds the actual variant.
        log_time_data(project["id"], researcher["id"], hours=3, billable=True)
        return get_success_data(api_client.get_project(project["id"], PM))

    def test_estimated_cost_uses_planned_search_hours(self):
        """PRD §3.2: "The **estimated** variant, `estimated_cost_cents`, is
        forward-looking: it sums the `estimated_hours` of every record search on
        the project that has not been cancelled (those in `PENDING`, `COMPLETED`,
        or `NO_RESULTS`), subtracts `budget_hours` to obtain the projected overage,
        treats any negative result as zero overage, rounds that overage figure up
        to the next whole hour, multiplies by 8000 cents, and adds the product to
        `package_price_cents`."

        Design: Difficulty/dual_variant_calc/project_cost_estimate_vs_actual_divergence
        """
        project = self._setup()
        assert project["estimated_cost_cents"] == 174000, (
            f"expected 150000 + ceil(5-2)*8000 = 174000, got {project['estimated_cost_cents']}")

    def test_actual_cost_uses_logged_hours_and_diverges_from_estimate(self):
        """PRD §3.2: "The **actual** variant, `actual_cost_cents`, accounts logged
        work instead: it sums the `hours` of the project's `ACTIVE` billable time
        entries in chronological order of creation, subtracts `budget_hours`, floors
        the overage at zero, rounds it up to the next whole hour, multiplies by 8000
        cents, and adds the product to `package_price_cents`."
        PRD §3.2: "The two variants differ only in their inclusion set — planned
        searches versus logged hours — and never borrow from one another."

        Design: Difficulty/dual_variant_calc/project_cost_estimate_vs_actual_divergence
        """
        project = self._setup()
        assert project["actual_cost_cents"] == 158000, (
            f"expected 150000 + ceil(3-2)*8000 = 158000, got {project['actual_cost_cents']}")
        assert project["estimated_cost_cents"] != project["actual_cost_cents"], (
            "estimate and actual variants must diverge for this project")


# ==========================================================================
# dual_variant_calc / person_confidence_provisional_vs_verified_divergence
# ==========================================================================
class TestPersonConfidenceDualVariant:
    def _setup(self):
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=10)
        person = create_person(project["id"], researcher["id"], full_name="John Smith")
        search = create_completed_search(project["id"], researcher["id"], search_terms="Smith")
        # Citation A: PRIMARY, VERIFIED. Citation B: SECONDARY, UNVERIFIED.
        add_citation(search["id"], person["id"], researcher["id"], quality="PRIMARY",
                     source_type="VITAL_RECORD", citation_text="Birth record", verify=True)
        add_citation(search["id"], person["id"], researcher["id"], quality="SECONDARY",
                     source_type="CENSUS", citation_text="Census", verify=False)
        return get_success_data(api_client.get_person(person["id"], PM))

    def test_provisional_confidence_counts_all_non_disputed(self):
        """PRD §3.4: "The provisional figure, `provisional_confidence`, sums the
        points of every citation for the person that is not `DISPUTED` (that is,
        `UNVERIFIED` and `VERIFIED` citations alike)."
        PRD §3.4: "a `PRIMARY` citation is worth 3 points, a `SECONDARY` citation 2
        points, and an `INDIRECT` citation 1 point — and the point total is divided
        by 6, capped at 1.00, and rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/person_confidence_provisional_vs_verified_divergence
        """
        person = self._setup()
        assert person["provisional_confidence"] == pytest.approx(0.83, abs=0.001), (
            f"expected (3+2)/6 -> 0.83, got {person['provisional_confidence']}")

    def test_confidence_score_counts_only_verified(self):
        """PRD §3.4: "The authoritative figure, `confidence_score`, sums the points
        of only the person's `VERIFIED` citations."

        Design: Difficulty/dual_variant_calc/person_confidence_provisional_vs_verified_divergence
        """
        person = self._setup()
        assert person["confidence_score"] == pytest.approx(0.50, abs=0.001), (
            f"expected 3/6 -> 0.50, got {person['confidence_score']}")


# ==========================================================================
# combinatorial_formula / milestone_invoice_amount_tier_surcharge_cap_mode_a
# ==========================================================================
class TestMilestoneInvoiceCombinatorics:
    def _invoice(self):
        client, researcher, project = create_active_project(
            client_tier="PREMIUM", package_type="BASIC_PACKAGE",
            package_price_cents=100000, budget_hours=10, priority="RUSH")
        milestone, _ = setup_ready_milestone(project["id"], researcher["id"], client["id"],
                                             amount_cents=100000, sequence_no=1)
        return get_success_data(api_client.invoice_milestone(milestone["id"], PM))

    def test_invoiced_amount_applies_discount_surcharge_then_cap(self):
        """PRD §3.9: "A tier discount is applied first: a `STANDARD` client receives
        no discount, while a `PREMIUM` client receives 10 percent off, and the
        discounted figure is rounded half up to a whole cent *before* any surcharge
        is considered."
        PRD §3.9: "Then a rush surcharge is added: if the owning project's `priority`
        is `RUSH`, a flat 5000 cents is added to the rounded, discounted amount;
        otherwise nothing is added."
        PRD §3.9: "the milestone's `invoiced_amount_cents` is the smaller of the
        pre-cap figure and the rounded price cap."

        Design: Difficulty/combinatorial_formula/milestone_invoice_amount_tier_surcharge_cap_mode_a
        """
        milestone = self._invoice()
        assert milestone["invoiced_amount_cents"] == 95000, (
            f"expected min(90000+5000, 150000) = 95000, got {milestone['invoiced_amount_cents']}")

    def test_invoice_transitions_milestone_to_invoiced(self):
        """PRD §3.9: "Invoicing advances a milestone `READY → INVOICED` and is the
        moment its charge is computed."

        Design: Difficulty/combinatorial_formula/milestone_invoice_amount_tier_surcharge_cap_mode_a
        """
        milestone = self._invoice()
        assert milestone["status"] == "INVOICED", (
            f"expected status INVOICED after invoicing, got {milestone['status']}")


# ==========================================================================
# combinatorial_formula / project_billable_amount_per_milestone_rounding_mode_b
# ==========================================================================
class TestBillableAmountPerMilestoneRounding:
    def _setup(self):
        client, researcher, project = create_active_project(
            client_tier="STANDARD", package_type="BASIC_PACKAGE",
            package_price_cents=100000, budget_hours=10, priority="STANDARD")
        m1, _ = setup_ready_milestone(project["id"], researcher["id"], client["id"],
                                      amount_cents=12340, sequence_no=1,
                                      deliverable_type="RESEARCH_REPORT")
        m1 = get_success_data(api_client.invoice_milestone(m1["id"], PM))
        m2, _ = setup_ready_milestone(project["id"], researcher["id"], client["id"],
                                      amount_cents=12340, sequence_no=2,
                                      deliverable_type="FAMILY_TREE")
        m2 = get_success_data(api_client.invoice_milestone(m2["id"], PM))
        project = get_success_data(api_client.get_project(project["id"], PM))
        return m1, m2, project

    def test_line_total_rounds_agency_fee_per_milestone(self):
        """PRD §3.9: "computing each milestone's agency fee as 7.5 percent of its
        `invoiced_amount_cents` rounded half up to a whole cent, adding that fee to
        the milestone's `invoiced_amount_cents` to form its `line_total_cents`, and
        summing those per-milestone line totals."

        Design: Difficulty/combinatorial_formula/project_billable_amount_per_milestone_rounding_mode_b
        """
        m1, m2, _ = self._setup()
        assert m1["line_total_cents"] == 13266, (
            f"expected 12340 + round_half_up(925.5)=926 -> 13266, got {m1['line_total_cents']}")
        assert m2["line_total_cents"] == 13266, (
            f"expected 12340 + 926 -> 13266, got {m2['line_total_cents']}")

    def test_billable_amount_sums_individually_rounded_line_totals(self):
        """PRD §3.9: "The fee is rounded per milestone before summation — never by
        taking a percentage of the aggregate — so the total is the sum of the
        individually rounded line totals."

        Design: Difficulty/combinatorial_formula/project_billable_amount_per_milestone_rounding_mode_b
        """
        _, _, project = self._setup()
        assert project["billable_amount_cents"] == 26532, (
            f"expected 13266 + 13266 = 26532, got {project['billable_amount_cents']}")


# ==========================================================================
# Corner / calculations / dna_predicted_relationship_cousin_lower_boundary
# ==========================================================================
def test_dna_cousin_lower_boundary_at_200_cm():
    """PRD §3.5: "from 200 up to 1300 predicts `COUSIN`".
    PRD §3.5: "Interpreting the result advances it `ORDERED → INTERPRETED` and
    supplies the `cm_shared` shared-centimorgan measurement (zero or greater)."

    Design: Corner/calculations/dna_predicted_relationship_cousin_lower_boundary
    """
    client, researcher, project = create_active_project(
        package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=10,
        target_person_count=1)
    person = setup_verified_person(project["id"], researcher["id"], full_name="DNA Subject")
    rh = make_researcher_headers(researcher["id"])
    dna = get_success_data(api_client.create_dna_interpretation(
        create_dna_payload(project_id=project["id"], subject_person_id=person["id"],
                           test_provider="23andMe"), rh))
    resp = api_client.interpret_dna(dna["id"], {"cm_shared": 200}, rh)
    data = validate_success(resp, expected_status=200)
    assert data["predicted_relationship"] == "COUSIN", (
        f"cm_shared 200 (inclusive lower bound) must map to COUSIN, got {data['predicted_relationship']}")
    assert data["status"] == "INTERPRETED"

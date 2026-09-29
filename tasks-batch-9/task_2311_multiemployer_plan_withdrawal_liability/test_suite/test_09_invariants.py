"""Two conserved quantities under a compensating action: the employer's liability
decomposition across a regeneration, and the plan's UVB allocation across vacatur."""

from test_helpers.assertions import (
    assert_assessment_decomposition,
    assert_uvb_allocation_conserved,
)
from test_helpers.constants import (
    BASELINE_NET_ASSESSED_CENTS,
    BASELINE_QUARTERLY_INSTALLMENT_CENTS,
    BASELINE_UVB_TOTAL_CENTS,
)
from test_helpers.fixtures import (
    build_arbitration,
    build_issued_assessment,
    decide_review_request,
    file_review_request,
    get_assessment,
    get_employer,
    get_group,
    get_schedule,
    get_valuation,
    installment_at,
    issue_award,
    list_all_installments,
    pay_installment,
    regenerate_schedule,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import PLAN_TRUSTEE_SECONDARY_HEADERS
from test_helpers.types import AwardOutcome

CONCEDED_NET_CENTS = 150_000_000
OUTSTANDING_AFTER_ONE_PAYMENT_CENTS = (
    BASELINE_NET_ASSESSED_CENTS - BASELINE_QUARTERLY_INSTALLMENT_CENTS
)
REGENERATED_BASIS_CENTS = CONCEDED_NET_CENTS - BASELINE_QUARTERLY_INSTALLMENT_CENTS
ALLOCATED_AFTER_ISSUE_CENTS = BASELINE_NET_ASSESSED_CENTS
UNALLOCATED_AFTER_ISSUE_CENTS = BASELINE_UVB_TOTAL_CENTS - BASELINE_NET_ASSESSED_CENTS


def _conceded_reduction(api):
    """One paid instalment, then a review decision conceding 150000000 cents."""
    scenario = build_issued_assessment(
        api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
    )
    set_clock(api, "2026-09-30T00:00:00Z")
    run_sweep(api, scenario["plan"]["id"])
    first = installment_at(api, scenario["schedule"]["id"], 1)
    second = installment_at(api, scenario["schedule"]["id"], 2)
    pay_installment(api, first, scenario["employer"]["id"])
    scenario["first_installment"] = first
    scenario["second_installment"] = second
    scenario["liability_after_payment"] = get_employer(api, scenario["employer"]["id"])[
        "outstanding_liability_cents"
    ]

    set_clock(api, "2026-10-01T00:00:00Z")
    scenario["review_request"] = file_review_request(
        api,
        scenario["assessment"]["id"],
        scenario["employer"]["id"],
        challenged_assumption="UVB_POOL_ALLOCATION",
    )
    set_clock(api, "2026-10-15T00:00:00Z")
    decide_review_request(
        api,
        scenario["review_request"]["id"],
        decision="REDUCED",
        assumption_ruling="SUSTAINED",
        recomputed_net_assessed_cents=CONCEDED_NET_CENTS,
        headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
    )
    return scenario


def _vacated_allocation(api):
    """An issued 250000000-cent demand carried to a hearing against its anchor valuation."""
    return build_arbitration(
        api,
        advance_to_hearing=True,
        employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
    )


class TestLiabilityDecompositionSurvivesRegeneration:
    def test_the_regenerated_generation_credits_the_payment_and_ties_out_exactly(self, api):
        """The successor generation amortises 141071429 cents over four years, and its
        principal plus forgiveness plus applied credit reconstructs the conceded 150000000.

        PRD 2.7: "**Employer liability decomposition.** For any payment-schedule generation,
        the sum of `principal_cents` across that generation, plus `forgiven_by_cap_cents`,
        plus `applied_credit_cents`, equals the assessment's `net_assessed_cents`."

        Design: Difficulty/compensating_invariant/employer_outstanding_liability_decomposition_survives_schedule_regeneration
        """
        scenario = _conceded_reduction(api)
        assert scenario["liability_after_payment"] == OUTSTANDING_AFTER_ONE_PAYMENT_CENTS

        assessment = get_assessment(api, scenario["assessment"]["id"])
        generation = regenerate_schedule(
            api, scenario["assessment"]["id"], assessment["version"]
        )

        assert generation["generation_seq"] == 2
        assert generation["applied_credit_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS
        assert generation["amortization_basis_cents"] == REGENERATED_BASIS_CENTS
        assert generation["forgiven_by_cap_cents"] == 0
        assert generation["capped_basis_cents"] == REGENERATED_BASIS_CENTS
        assert generation["amortization_years"] == 4
        assert generation["installment_count"] == 16
        assert generation["quarterly_installment_cents"] == 8_816_964
        assert generation["final_installment_cents"] == 8_816_969
        assert generation["first_due_date"].startswith("2026-12-14T00:00:00")

        assert_assessment_decomposition(
            generation,
            list_all_installments(api, generation["id"]),
            CONCEDED_NET_CENTS,
        )

    def test_the_ledger_carries_no_drift_after_the_compensating_action(self, api):
        """The employer's balance lands exactly on the new capped basis, the paid instalment
        is spared and the unpaid one is voided.

        PRD 3.8: "Voided instalments carry their `principal_cents` out of the employer's
        `outstanding_liability_cents`, but any `amount_paid_cents` they had already collected
        still counts toward `applied_credit_cents` on the successor generation."

        Design: Difficulty/compensating_invariant/employer_outstanding_liability_decomposition_survives_schedule_regeneration
        """
        scenario = _conceded_reduction(api)
        assessment = get_assessment(api, scenario["assessment"]["id"])
        regenerate_schedule(api, scenario["assessment"]["id"], assessment["version"])

        assert get_schedule(api, scenario["schedule"]["id"])["status"] == "SUPERSEDED"
        paid = installment_at(api, scenario["schedule"]["id"], 1)
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS
        assert installment_at(api, scenario["schedule"]["id"], 2)["status"] == "VOID"

        reduced = get_assessment(api, scenario["assessment"]["id"])
        assert reduced["net_assessed_cents"] == CONCEDED_NET_CENTS
        assert reduced["award_adjustment_cents"] == (
            BASELINE_NET_ASSESSED_CENTS - CONCEDED_NET_CENTS
        )

        assert (
            get_employer(api, scenario["employer"]["id"])["outstanding_liability_cents"]
            == REGENERATED_BASIS_CENTS
        )
        assert (
            get_group(api, scenario["group"]["id"])["joint_exposure_cents"]
            == REGENERATED_BASIS_CENTS
        )


class TestPlanUvbAllocationIsConserved:
    def test_issuance_moves_value_from_unallocated_to_allocated_without_creating_any(self, api):
        """The anchor valuation opens at 0 allocated against 10000000000 unallocated and,
        once the demand is issued, carries 250000000 against 9750000000.

        PRD 2.7: "**Plan UVB allocation.** For every plan-year valuation,
        `allocated_uvb_cents` plus `unallocated_uvb_cents` always equals `uvb_total_cents`."

        Design: Difficulty/compensating_invariant/plan_uvb_allocation_conserved_across_issuance_and_vacatur
        """
        scenario = _vacated_allocation(api)
        at_certification = scenario["valuations"][2025]
        assert at_certification["allocated_uvb_cents"] == 0
        assert at_certification["unallocated_uvb_cents"] == BASELINE_UVB_TOTAL_CENTS
        assert_uvb_allocation_conserved(at_certification)

        after_issue = get_valuation(api, at_certification["id"])
        assert after_issue["allocated_uvb_cents"] == ALLOCATED_AFTER_ISSUE_CENTS
        assert after_issue["unallocated_uvb_cents"] == UNALLOCATED_AFTER_ISSUE_CENTS
        assert_uvb_allocation_conserved(after_issue)
        assert (
            get_assessment(api, scenario["assessment"]["id"])["valuation_id"]
            == at_certification["id"]
        )

    def test_vacatur_releases_the_allocation_while_the_assessed_figure_stands(self, api):
        """The vacating award returns the valuation to 0 against 10000000000, leaves it
        certified, and preserves the rescinded assessment's 250000000-cent figure.

        PRD 3.8: "Alongside that chain, the anchor valuation's `allocated_uvb_cents`
        decreases by `net_assessed_cents` while its `unallocated_uvb_cents` rises by the same
        amount, preserving the plan-UVB conservation rule"

        Design: Difficulty/compensating_invariant/plan_uvb_allocation_conserved_across_issuance_and_vacatur
        """
        scenario = _vacated_allocation(api)
        valuation_id = scenario["valuations"][2025]["id"]

        issue_award(
            api,
            scenario["arbitration"]["id"],
            AwardOutcome.VACATE.value,
            assumption_ruling="NOT_RAISED",
        )

        released = get_valuation(api, valuation_id)
        assert released["allocated_uvb_cents"] == 0
        assert released["unallocated_uvb_cents"] == BASELINE_UVB_TOTAL_CENTS
        assert released["uvb_total_cents"] == BASELINE_UVB_TOTAL_CENTS
        assert_uvb_allocation_conserved(released)
        assert released["status"] == "CERTIFIED"

        rescinded = get_assessment(api, scenario["assessment"]["id"])
        assert rescinded["lifecycle_status"] == "RESCINDED"
        assert rescinded["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS

"""Two non-linear machines: the assessment's parallel review and collection
dimensions, and the arbitration's cyclic remand loop."""

from test_helpers.constants import (
    BASELINE_NET_ASSESSED_CENTS,
    BASELINE_QUARTERLY_INSTALLMENT_CENTS,
)
from test_helpers.fixtures import (
    advance_arbitration,
    build_arbitration,
    build_issued_assessment,
    decide_review_request,
    file_review_request,
    get_arbitration,
    get_assessment,
    get_employer,
    get_installment,
    get_review_request,
    get_schedule,
    installment_at,
    issue_award,
    pay_installment,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import PLAN_TRUSTEE_SECONDARY_HEADERS
from test_helpers.types import ArbitrationStatus, AwardOutcome

OUTSTANDING_AFTER_ONE_PAYMENT_CENTS = (
    BASELINE_NET_ASSESSED_CENTS - BASELINE_QUARTERLY_INSTALLMENT_CENTS
)


def _paying_employer_scenario(api):
    """An issued demand whose first quarterly instalment has already been paid."""
    scenario = build_issued_assessment(
        api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
    )
    set_clock(api, "2026-09-30T00:00:00Z")
    run_sweep(api, scenario["plan"]["id"])
    first = installment_at(api, scenario["schedule"]["id"], 1)
    pay_installment(api, first, scenario["employer"]["id"])
    scenario["first_installment"] = get_installment(api, first["id"])
    scenario["assessment"] = get_assessment(api, scenario["assessment"]["id"])
    return scenario


class TestReviewAndCollectionDimensions:
    def test_filing_a_request_for_review_leaves_the_money_dimension_alone(self, api):
        """A paying employer that files a challenge stays CURRENT with its balance of
        241071429 cents untouched while the review dimension moves to REQUESTED.

        PRD 2.10: "Filing a request for review does not touch `collection_status`, does
        not move any instalment's `due_date`, and does not suspend the obligation to pay."

        Design: Difficulty/non_linear_state_machine/assessment_review_and_collection_dimensions_advance_independently
        """
        scenario = _paying_employer_scenario(api)
        assert scenario["assessment"]["review_status"] == "NONE"
        assert scenario["assessment"]["collection_status"] == "CURRENT"

        set_clock(api, "2026-10-01T00:00:00Z")
        file_review_request(
            api,
            scenario["assessment"]["id"],
            scenario["employer"]["id"],
            challenged_assumption="INTEREST_RATE",
            proposed_interest_rate_bps=500,
        )

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "REQUESTED"
        assert assessment["collection_status"] == "CURRENT"
        assert (
            get_employer(api, scenario["employer"]["id"])["outstanding_liability_cents"]
            == OUTSTANDING_AFTER_ONE_PAYMENT_CENTS
        )

    def test_deciding_the_request_moves_only_the_review_dimension(self, api):
        """The decision drives review_status REQUESTED to DECIDED while the collection
        dimension stays CURRENT and no monetary field moves.

        PRD 2.10: "Deciding a request for review does not touch `collection_status`
        either, and does not by itself change any monetary field on the assessment."

        Design: Difficulty/non_linear_state_machine/assessment_review_and_collection_dimensions_advance_independently
        """
        scenario = _paying_employer_scenario(api)
        set_clock(api, "2026-10-01T00:00:00Z")
        review_request = file_review_request(
            api,
            scenario["assessment"]["id"],
            scenario["employer"]["id"],
            challenged_assumption="INTEREST_RATE",
            proposed_interest_rate_bps=500,
        )

        set_clock(api, "2026-10-15T00:00:00Z")
        decide_review_request(
            api,
            review_request["id"],
            decision="AFFIRMED",
            assumption_ruling="REJECTED",
            headers=PLAN_TRUSTEE_SECONDARY_HEADERS,
        )

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "DECIDED"
        assert assessment["collection_status"] == "CURRENT"
        assert assessment["lifecycle_status"] == "ISSUED"
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert assessment["award_adjustment_cents"] == 0

        decided = get_review_request(api, review_request["id"])
        assert decided["status"] == "DECIDED"
        assert decided["assumption_ruling"] == "REJECTED"

        assert get_schedule(api, scenario["schedule"]["id"])["status"] == "ACTIVE"
        paid = get_installment(api, scenario["first_installment"]["id"])
        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == BASELINE_QUARTERLY_INSTALLMENT_CENTS


class TestArbitrationRemandCycle:
    def test_a_remand_returns_the_proceeding_to_briefing_at_the_next_round(self, api):
        """The proceeding re-enters BRIEFING, a state it already occupied, carrying
        round_number 2.

        PRD 3.8: "A `REMAND` award moves the arbitration `HEARING → AWARD_ISSUED`,
        recording the outcome and the assumption ruling and touching the assessed amount
        not at all; immediately afterwards the server itself moves it `AWARD_ISSUED →
        REMANDED` and increments `round_number` by one."

        Design: Difficulty/non_linear_state_machine/arbitration_remand_cycle_returns_to_briefing_and_increments_round
        """
        scenario = build_arbitration(
            api,
            employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
            review_overrides={"challenged_assumption": "MORTALITY"},
            assumption_ruling="REJECTED",
        )
        arbitration = scenario["arbitration"]
        assert arbitration["status"] == "BRIEFING"
        assert arbitration["round_number"] == 1

        advance_arbitration(api, arbitration["id"], ArbitrationStatus.HEARING.value)
        remanded = issue_award(
            api,
            arbitration["id"],
            AwardOutcome.REMAND.value,
            assumption_ruling="NOT_RAISED",
        )
        assert remanded["status"] == "REMANDED"
        assert remanded["round_number"] == 2

        second_briefing = advance_arbitration(
            api, arbitration["id"], ArbitrationStatus.BRIEFING.value
        )
        assert second_briefing["status"] == "BRIEFING"
        assert second_briefing["round_number"] == 2

    def test_an_affirm_award_closes_the_cycle_without_moving_any_money(self, api):
        """A second hearing ending in AFFIRM closes the proceeding at round 2, drives the
        review dimension to its terminal ARBITRATED, and leaves the demand at 250000000.

        PRD 3.8: "An `AFFIRM` award changes no monetary field anywhere."

        Design: Difficulty/non_linear_state_machine/arbitration_remand_cycle_returns_to_briefing_and_increments_round
        """
        scenario = build_arbitration(
            api,
            employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
            review_overrides={"challenged_assumption": "MORTALITY"},
            assumption_ruling="REJECTED",
        )
        arbitration_id = scenario["arbitration"]["id"]

        advance_arbitration(api, arbitration_id, ArbitrationStatus.HEARING.value)
        issue_award(
            api, arbitration_id, AwardOutcome.REMAND.value, assumption_ruling="NOT_RAISED"
        )
        advance_arbitration(api, arbitration_id, ArbitrationStatus.BRIEFING.value)
        advance_arbitration(api, arbitration_id, ArbitrationStatus.HEARING.value)
        issue_award(
            api, arbitration_id, AwardOutcome.AFFIRM.value, assumption_ruling="REJECTED"
        )

        closed = get_arbitration(api, arbitration_id)
        assert closed["status"] == "CLOSED"
        assert closed["round_number"] == 2
        assert closed["award_outcome"] == "AFFIRM"
        assert closed["closed_at"].startswith("2026-10-15T00:00:00")

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "ARBITRATED"
        assert assessment["net_assessed_cents"] == BASELINE_NET_ASSESSED_CENTS

        request = get_review_request(api, scenario["review_request"]["id"])
        assert request["arbitration_deadline_at"].startswith("2026-11-30T00:00:00")

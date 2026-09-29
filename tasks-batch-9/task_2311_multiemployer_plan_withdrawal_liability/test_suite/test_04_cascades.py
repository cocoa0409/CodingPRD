"""Two deep cascades: the rescission chain a vacating award runs, and the
delinquency chain the collection sweep runs."""

import pytest

from test_helpers.constants import BASELINE_NET_ASSESSED_CENTS
from test_helpers.fixtures import (
    build_arbitration,
    build_delinquent_schedule,
    get_arbitration,
    get_assessment,
    get_employer,
    get_event,
    get_group,
    get_schedule,
    installment_at,
    issue_award,
    list_all_installments,
)
from test_helpers.types import AwardOutcome

BASELINE_EXPOSURE_SCORE = 2_500.0


def _hearing_scenario(api):
    """An issued 250000000-cent demand carried into an arbitration hearing."""
    return build_arbitration(
        api,
        advance_to_hearing=True,
        employer_overrides={"obligation_start_year": 2021, "cba_count": 1},
    )


class TestVacateAwardRescissionCascade:
    def test_vacatur_voids_the_generation_and_every_open_installment(self, api):
        """Rescinding the assessment voids the live generation, and because that
        generation is void its unpaid instalments are voided too.

        PRD 3.8: "The live generation becomes `VOID` and its `refund_due_cents` is set to
        the sum of its instalments' `amount_paid_cents`."

        Design: Difficulty/transitive_cascade/vacate_award_unwinds_schedule_installments_employer_and_group_depth_five
        """
        scenario = _hearing_scenario(api)
        employer_before = get_employer(api, scenario["employer"]["id"])
        assert employer_before["outstanding_liability_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert employer_before["status"] == "COMPLETE_WITHDRAWN"

        issue_award(
            api,
            scenario["arbitration"]["id"],
            AwardOutcome.VACATE.value,
            assumption_ruling="NOT_RAISED",
        )

        assert get_assessment(api, scenario["assessment"]["id"])["lifecycle_status"] == "RESCINDED"
        schedule = get_schedule(api, scenario["schedule"]["id"])
        assert schedule["status"] == "VOID"
        assert schedule["refund_due_cents"] == 0
        installments = list_all_installments(api, schedule["id"])
        assert installments
        assert all(item["status"] == "VOID" for item in installments)

    def test_vacatur_returns_the_employer_and_its_group_to_a_clean_slate(self, api):
        """Because the instalments left the ledger the employer's balance returns to zero
        and it becomes CONTRIBUTING again, which drops the group's exposure to zero.

        PRD 3.8: "Because the employer's `outstanding_liability_cents` returned to 0, the
        employer's `status` returns to `CONTRIBUTING` — `COMPLETE_WITHDRAWN →
        CONTRIBUTING` or `PARTIAL_WITHDRAWN → CONTRIBUTING` — its `obligation_end_year` is
        reset to null, its `ceased_cba_count` is reset to 0 and its `credit_watch` is
        reset to false."

        Design: Difficulty/transitive_cascade/vacate_award_unwinds_schedule_installments_employer_and_group_depth_five
        """
        scenario = _hearing_scenario(api)
        group_before = get_group(api, scenario["group"]["id"])
        assert group_before["joint_exposure_cents"] == BASELINE_NET_ASSESSED_CENTS
        assert group_before["exposure_score"] == pytest.approx(
            BASELINE_EXPOSURE_SCORE, abs=0.0001
        )

        issue_award(
            api,
            scenario["arbitration"]["id"],
            AwardOutcome.VACATE.value,
            assumption_ruling="NOT_RAISED",
        )

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["outstanding_liability_cents"] == 0
        assert employer["status"] == "CONTRIBUTING"
        assert employer["obligation_end_year"] is None
        assert employer["credit_watch"] is False

        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == 0
        assert group["exposure_score"] == pytest.approx(0.0, abs=0.0001)

    def test_vacatur_also_unwinds_the_dispute_and_the_withdrawal_itself(self, api):
        """The award closes the proceeding, terminates the review dimension, resets the
        collection dimension and sends the withdrawal event back to no withdrawal.

        PRD 3.8: "the withdrawal event travels `ASSESSED → NO_WITHDRAWAL` with
        `determined_type` reset to `NONE` and `partial_withdrawal_fraction` reset to
        0.0000"

        Design: Difficulty/transitive_cascade/vacate_award_unwinds_schedule_installments_employer_and_group_depth_five
        """
        scenario = _hearing_scenario(api)

        issue_award(
            api,
            scenario["arbitration"]["id"],
            AwardOutcome.VACATE.value,
            assumption_ruling="NOT_RAISED",
        )

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["review_status"] == "ARBITRATED"
        assert assessment["collection_status"] == "NOT_YET_DUE"

        event = get_event(api, scenario["event"]["id"])
        assert event["status"] == "NO_WITHDRAWAL"
        assert event["determined_type"] == "NONE"
        assert event["partial_withdrawal_fraction"] == pytest.approx(0.0, abs=0.0001)

        arbitration = get_arbitration(api, scenario["arbitration"]["id"])
        assert arbitration["status"] == "CLOSED"
        assert arbitration["award_outcome"] == "VACATE"


class TestSweepDelinquencyCascade:
    def test_one_sweep_carries_two_installments_to_delinquent_and_the_schedule_to_default_eligible(
        self, api
    ):
        """A single pass marks both overdue instalments due and then delinquent, and two
        delinquencies make the generation default-eligible.

        PRD 3.7: "Because those instalments became delinquent,
        `consecutive_delinquent_count` reaches two, and the generation moves `ACTIVE →
        DEFAULT_ELIGIBLE`. Two delinquent instalments is the threshold; a generation with
        one is not yet default-eligible."

        Design: Difficulty/transitive_cascade/collection_sweep_delinquency_propagates_to_employer_credit_watch_depth_four
        """
        scenario = build_delinquent_schedule(
            api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
        )
        sweep = scenario["sweep"]

        assert sweep["installments_marked_due"] == 2
        assert sweep["installments_marked_delinquent"] == 2
        assert sweep["schedules_default_eligible"] == 1

        schedule_id = scenario["schedule"]["id"]
        assert installment_at(api, schedule_id, 1)["status"] == "DELINQUENT"
        assert installment_at(api, schedule_id, 2)["status"] == "DELINQUENT"
        assert installment_at(api, schedule_id, 3)["status"] == "SCHEDULED"

        schedule = get_schedule(api, schedule_id)
        assert schedule["consecutive_delinquent_count"] == 2
        assert schedule["status"] == "DEFAULT_ELIGIBLE"

    def test_the_delinquency_reaches_the_assessment_the_employer_and_the_group(self, api):
        """The default-eligible generation makes the assessment delinquent, which puts the
        employer on credit watch with two permanent strikes.

        PRD 3.7: "Because the assessment's `collection_status` became `DELINQUENT`, the
        employer's `credit_watch` becomes true and its `delinquency_strikes` reflects the
        newly delinquent instalments."

        Design: Difficulty/transitive_cascade/collection_sweep_delinquency_propagates_to_employer_credit_watch_depth_four
        """
        scenario = build_delinquent_schedule(
            api, employer_overrides={"obligation_start_year": 2021, "cba_count": 1}
        )

        assessment = get_assessment(api, scenario["assessment"]["id"])
        assert assessment["collection_status"] == "DELINQUENT"
        assert assessment["review_status"] == "NONE"

        employer = get_employer(api, scenario["employer"]["id"])
        assert employer["credit_watch"] is True
        assert employer["delinquency_strikes"] == 2
        assert employer["outstanding_liability_cents"] == BASELINE_NET_ASSESSED_CENTS

        group = get_group(api, scenario["group"]["id"])
        assert group["joint_exposure_cents"] == BASELINE_NET_ASSESSED_CENTS

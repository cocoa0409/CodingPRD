"""Two states re-entered more than once, with counters that only move one way.

The gift offer visits INDEPENDENCE_REVIEW three times and the report visits
SUBMITTED twice; neither second visit is a replay of the first.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    read_gift_offer,
    read_proposal,
    read_report,
    review_gift_offer,
    review_report,
    set_clock,
    setup_gift_offer_in_review,
    setup_released_award,
    submit_offer_for_review,
    submit_report,
    validate_error,
)
from test_helpers.fixtures import ED_HEADERS, FC_HEADERS

_DONOR_CONDITION_ONE = "Donor asks to preview the housing series before publication."
_DONOR_CONDITION_TWO = "Donor will accept a courtesy notice one hour before publication."


def _setup_offer_with_two_rounds_consumed():
    """A 500000-cent unrestricted offer sitting in CONDITIONS_REQUESTED with both
    negotiation rounds already used."""
    ctx = setup_gift_offer_in_review(
        offered_amount_cents=500000,
        designation="UNRESTRICTED",
        donor_conditions=_DONOR_CONDITION_ONE,
    )
    offer_id = ctx["offer"]["id"]
    review_gift_offer(
        offer_id,
        "REQUEST_CONDITIONS",
        review_note=(
            "Round 1: preview rights are incompatible with the firewall; "
            "please withdraw them."
        ),
    )
    submit_offer_for_review(offer_id, donor_conditions=_DONOR_CONDITION_TWO)
    ctx["offer"] = review_gift_offer(
        offer_id,
        "REQUEST_CONDITIONS",
        review_note="Round 2: advance notice is still a condition; it must go.",
    )
    return ctx


class TestGiftOfferConditionsCycleIsBoundedAtTwoRounds:
    """Three entries into INDEPENDENCE_REVIEW, two counted rounds."""

    def test_two_rounds_of_conditions_leave_the_counter_at_two(self):
        """Each REQUEST_CONDITIONS edge advances the counter once, so two rounds
        of negotiation leave the offer in CONDITIONS_REQUESTED at 2.

        PRD: "`REQUEST_CONDITIONS` moves the offer `INDEPENDENCE_REVIEW ->
        CONDITIONS_REQUESTED`, increments `conditions_round_count` by 1, and
        stores the `review_note` into `donor_conditions` as the conditions the
        newsroom is asking the donor to accept or drop."

        Design: Difficulty/non_linear_state_machine/nl_gift_offer_conditions_cycle_bounded_at_two_rounds
        """
        ctx = _setup_offer_with_two_rounds_consumed()

        offer = read_gift_offer(ctx["offer"]["id"])
        assert offer["status"] == "CONDITIONS_REQUESTED"
        assert offer["conditions_round_count"] == 2
        assert offer["donor_conditions"]

    def test_a_resubmission_without_conditions_recomputes_the_netting(self):
        """The third entry into INDEPENDENCE_REVIEW clears the conditions and
        rewrites all three netting outputs from the unchanged gross 500000.

        PRD: "All three outputs are rewritten on every submission, including a
        re-submission out of `CONDITIONS_REQUESTED`, and the offer's `version`
        increments by 1."

        Design: Difficulty/non_linear_state_machine/nl_gift_offer_conditions_cycle_bounded_at_two_rounds
        """
        ctx = _setup_offer_with_two_rounds_consumed()

        resubmitted = submit_offer_for_review(ctx["offer"]["id"])
        assert resubmitted["status"] == "INDEPENDENCE_REVIEW"
        assert resubmitted["donor_conditions"] is None
        assert resubmitted["offered_amount_cents"] == 500000
        assert resubmitted["stewardship_fee_cents"] == 0
        assert resubmitted["net_acceptable_amount_cents"] == 500000
        assert resubmitted["board_ratification_required"] is False
        assert resubmitted["conditions_round_count"] == 2

    def test_a_third_round_is_refused_and_leaves_no_trace(self):
        """With the counter already at 2 the negotiation is exhausted, and the
        rejected round changes neither the status nor the counter.

        PRD: "Negotiation is bounded: `conditions_round_count` must be strictly
        below 2 for another round to be requested, so at most two rounds are
        possible, and an attempt beyond that is
        `ERR_CONDITION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/nl_gift_offer_conditions_cycle_bounded_at_two_rounds
        """
        ctx = _setup_offer_with_two_rounds_consumed()
        offer_id = ctx["offer"]["id"]
        submit_offer_for_review(offer_id)

        response = api_client.gift_offer_independence_review(
            offer_id,
            {"decision": "REQUEST_CONDITIONS", "review_note": "Round 3: one more clarification."},
            ED_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_CONDITION_ROUNDS_EXHAUSTED)

        unchanged = read_gift_offer(offer_id)
        assert unchanged["status"] == "INDEPENDENCE_REVIEW"
        assert unchanged["conditions_round_count"] == 2
        assert unchanged["donor_conditions"] is None

    def test_clearance_becomes_legal_once_the_conditions_are_gone(self):
        """With `donor_conditions` withdrawn the only remaining forward exit is
        CLEAR, which snapshots the funder's score of 10 into the gate.

        PRD: "On success the funder's `independence_risk_score` is snapshotted
        into `acceptance_gate_score`, `cleared_by_user_id` is set to the ruling
        director's `X-User-ID`, and the offer's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/nl_gift_offer_conditions_cycle_bounded_at_two_rounds
        """
        ctx = _setup_offer_with_two_rounds_consumed()
        offer_id = ctx["offer"]["id"]
        submit_offer_for_review(offer_id)

        cleared = review_gift_offer(
            offer_id,
            "CLEAR",
            review_note="Conditions withdrawn; gift may be accepted.",
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["acceptance_gate_score"] == 10
        assert cleared["cleared_by_user_id"] == ED_HEADERS["X-User-ID"]
        assert cleared["conditions_round_count"] == 2


def _setup_report_ready_to_submit():
    """A restricted award with 210000 released against its single report, with
    the clock past the reporting period but before the due date."""
    ctx = setup_released_award(
        210000,
        reporting_cadence="SEMIANNUAL",
        title="Eviction data desk",
        legal_name="Fairhaven Foundation",
        award_probability_bps=7000,
    )
    set_clock("2027-03-01T00:00:00Z")
    ctx["report"] = read_report(ctx["reports"][0]["id"])
    return ctx


class TestReturnedReportResubmissionRecomputesVariance:
    """One report, two submissions, two different variances."""

    def test_the_single_report_carries_the_whole_award_and_the_release(self):
        """The semiannual cadence over a six-month window produces exactly one
        obligation, and the 210000 release is consumed against it.

        PRD: "Its `due_date` is `period_end` plus **45 days** of grace."

        Design: Difficulty/non_linear_state_machine/nl_grant_report_returned_resubmission_recomputes_variance
        """
        ctx = _setup_report_ready_to_submit()

        assert len(ctx["reports"]) == 1
        report = ctx["report"]
        assert report["status"] == "SCHEDULED"
        assert report["sequence_no"] == 1
        assert report["period_end"] == "2027-02-28"
        assert report["due_date"] == "2027-04-14"
        assert report["allocated_release_cents"] == 350000
        assert report["consumed_release_cents"] == 210000

    def test_a_variance_wider_than_two_thousand_bps_cannot_be_accepted(self):
        """Reporting 150000 against 210000 consumed is a variance of -2857, and
        the review must refuse it rather than accept the swing.

        PRD: "`ACCEPT` requires the absolute value of `variance_bps` to be no
        more than 2000; a wider swing must be returned for rework instead, and
        accepting it is refused with `ERR_VARIANCE_UNACCEPTABLE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/nl_grant_report_returned_resubmission_recomputes_variance
        """
        ctx = _setup_report_ready_to_submit()
        report_id = ctx["report"]["id"]

        submitted = submit_report(report_id, 150000)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["spend_reported_cents"] == 150000
        assert submitted["variance_bps"] == -2857

        response = api_client.review_grant_report(
            report_id, {"decision": "ACCEPT"}, FC_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_VARIANCE_UNACCEPTABLE)

        still_submitted = read_report(report_id)
        assert still_submitted["status"] == "SUBMITTED"
        assert still_submitted["variance_bps"] == -2857

    def test_a_return_wipes_the_figures_so_the_resubmission_recomputes_them(self):
        """RETURN nulls both fields, so submitting 200000 computes -476 from the
        surviving consumed release rather than adjusting the earlier -2857.

        PRD: "`RETURN` moves the report to `RETURNED` and clears
        `spend_reported_cents` and `variance_bps` back to null, closing the
        `SUBMITTED -> RETURNED -> SUBMITTED` revision cycle, which is unbounded."

        Design: Difficulty/non_linear_state_machine/nl_grant_report_returned_resubmission_recomputes_variance
        """
        ctx = _setup_report_ready_to_submit()
        report_id = ctx["report"]["id"]
        submit_report(report_id, 150000)

        returned = review_report(
            report_id,
            "RETURN",
            review_note="Underspend too wide; revise and resubmit.",
        )
        assert returned["status"] == "RETURNED"
        assert returned["spend_reported_cents"] is None
        assert returned["variance_bps"] is None

        resubmitted = submit_report(report_id, 200000)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["spend_reported_cents"] == 200000
        assert resubmitted["variance_bps"] == -476

        accepted = review_report(report_id, "ACCEPT", review_note="Within tolerance.")
        assert accepted["status"] == "ACCEPTED"
        assert read_proposal(ctx["proposal"]["id"])["compliance_flag"] == "COMPLIANT"

    def test_the_report_cycle_never_touches_the_release_buckets(self):
        """Through submission, refusal, return, resubmission and acceptance the
        bucket figures and the proposal ledger stand still.

        PRD: "A waived report keeps its bucket capacity, so a reinstated or
        re-examined award's total stays reconcilable against the sum of its
        buckets."

        Design: Difficulty/non_linear_state_machine/nl_grant_report_returned_resubmission_recomputes_variance
        """
        ctx = _setup_report_ready_to_submit()
        report_id = ctx["report"]["id"]
        proposal_id = ctx["proposal"]["id"]

        submit_report(report_id, 150000)
        review_report(report_id, "RETURN")
        submit_report(report_id, 200000)
        review_report(report_id, "ACCEPT")

        final_report = read_report(report_id)
        assert final_report["consumed_release_cents"] == 210000
        assert final_report["allocated_release_cents"] == 350000

        proposal = read_proposal(proposal_id)
        assert proposal["released_cents"] == 210000
        assert proposal["unreleased_cents"] == 140000
        assert proposal["returned_cents"] == 0
        assert proposal["awarded_amount_cents"] == 350000

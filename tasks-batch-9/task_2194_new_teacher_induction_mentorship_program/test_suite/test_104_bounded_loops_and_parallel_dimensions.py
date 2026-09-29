"""Non-linear lifecycles: the bounded dispute/resubmit loop on a contact log and
the two independent dimensions of an observation cycle that meet once.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_FEEDBACK_STATE_INVALID,
    ERR_RESUBMIT_LIMIT_REACHED,
)
from test_helpers.assertions import assert_two_decimals
from test_helpers.fixtures import (
    build_program,
    open_observation_cycle,
    read_match,
    read_novice,
    set_clock,
    submit_contact_log,
)
from test_helpers.test_users import ADMIN, make_mentor_headers, make_site_lead_headers

RUBRIC = {"planning": 4, "instruction": 3, "environment": 2, "assessment": 2}


class TestContactLogDisputeResubmitCycleBounded:
    """The revision loop closes twice and the third attempt is refused."""

    @staticmethod
    def _log_disputed_twice(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        mentor = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-07T12:00:00Z")
        log = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T09:00:00Z",
            minutes=45,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Co-planning conference on the fractions unit with the novice",
        )
        validate_success(
            api.review_contact_log(
                log["id"],
                f.review_payload("DISPUTE", note="Minutes do not match the sign-in sheet"),
                lead,
            )
        )
        validate_success(
            api.resubmit_contact_log(
                log["id"],
                f.resubmit_payload(
                    minutes=40,
                    contact_type="ONE_ON_ONE",
                    description="Co-planning conference on the fractions unit, corrected",
                ),
                mentor,
            )
        )
        validate_success(
            api.review_contact_log(
                log["id"],
                f.review_payload(
                    "DISPUTE", note="Minutes still do not match the sign-in sheet"
                ),
                lead,
            )
        )
        validate_success(
            api.resubmit_contact_log(
                log["id"],
                f.resubmit_payload(
                    minutes=35,
                    contact_type="CO_PLANNING",
                    description="Co-planning conference on the fractions unit, corrected again",
                ),
                mentor,
            )
        )
        validate_success(
            api.review_contact_log(
                log["id"],
                f.review_payload("DISPUTE", note="Third review still finds a discrepancy"),
                lead,
            )
        )
        program["log_id"] = log["id"]
        program["mentor_headers"] = mentor
        return program

    def test_third_resubmission_is_refused_and_the_row_stays_disputed(
        self, api: InductionApiClient
    ):
        """With resubmit_count at 2 the loop is closed and the log stays DISPUTED.

        The PRD bounds the loop explicitly: "The `SUBMITTED → DISPUTED →
        SUBMITTED` revision cycle is bounded: a log may be resubmitted at most
        twice, and a third attempt — that is, one made when `resubmit_count`
        already stands at 2 — is refused with `ERR_RESUBMIT_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/contact_log_dispute_resubmit_cycle_bounded
        """
        program = self._log_disputed_twice(api)

        response = api.resubmit_contact_log(
            program["log_id"],
            f.resubmit_payload(
                minutes=30,
                contact_type="CO_PLANNING",
                description="Co-planning conference on the fractions unit, third correction",
            ),
            program["mentor_headers"],
        )
        validate_error(response, ERR_RESUBMIT_LIMIT_REACHED, 409)

        log = validate_success(api.get_contact_log(program["log_id"], ADMIN))
        assert log["verification_status"] == "DISPUTED", (
            f"the refused resubmission leaves the row DISPUTED, got "
            f"{log['verification_status']}"
        )
        assert log["resubmit_count"] == 2, (
            f"resubmit_count must still stand at 2, got {log['resubmit_count']}"
        )

    def test_each_pass_of_the_loop_replaces_the_stored_claim(self, api: InductionApiClient):
        """Two passes leave the second replacement values stored and nothing credited.

        The PRD describes what a resubmission rewrites: "Resubmission returns the
        log to `SUBMITTED`, increments `resubmit_count`, clears `dispute_reason`
        back to null, restamps `submitted_by_user_id` from the acting
        `X-User-ID`, and refreshes the mentor's provisional accrual."

        Design: Difficulty/non_linear_state_machine/contact_log_dispute_resubmit_cycle_bounded
        """
        program = self._log_disputed_twice(api)

        log = validate_success(api.get_contact_log(program["log_id"], ADMIN))
        assert log["minutes"] == 35, (
            f"the second resubmission's 35 minutes must be stored, got {log['minutes']}"
        )
        assert log["contact_type"] == "CO_PLANNING", (
            f"the second resubmission's contact type must be stored, got "
            f"{log['contact_type']}"
        )
        assert log["credited_minutes"] == 0, (
            "nothing is credited while the log has never been verified"
        )
        assert log["dispute_reason"] is not None, (
            "a disputed log carries the reviewer's note as dispute_reason"
        )
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 0, (
            "the match accrues no verified minutes from a log stuck in the loop"
        )


class TestObservationParallelDimensionsWithJoin:
    """Phase and feedback_review_status move separately and meet at DOCUMENTED."""

    @staticmethod
    def _cycle_with_returned_feedback(api: InductionApiClient) -> dict:
        program = build_program(api)
        mentor = make_mentor_headers(program["mentor_id"])
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-07T12:00:00Z")
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:00:00Z",
        )
        validate_success(api.advance_cycle(cycle["id"], f.advance_payload("OBSERVED"), mentor))
        validate_success(
            api.write_feedback(
                cycle["id"],
                f.feedback_payload(
                    submit=False, growth_area_codes=["PLANNING"], rubric_scores=RUBRIC
                ),
                mentor,
            )
        )
        validate_success(
            api.advance_cycle(cycle["id"], f.advance_payload("POST_CONFERENCE"), mentor)
        )
        validate_success(
            api.write_feedback(
                cycle["id"],
                f.feedback_payload(
                    submit=True,
                    growth_area_codes=["PLANNING", "INSTRUCTION"],
                    rubric_scores=RUBRIC,
                ),
                mentor,
            )
        )
        validate_success(
            api.review_feedback(
                cycle["id"],
                f.feedback_review_payload(
                    "RETURN",
                    return_reason="Growth areas need to cite the exit ticket evidence",
                ),
                lead,
            )
        )
        program["cycle_id"] = cycle["id"]
        program["mentor_headers"] = mentor
        program["lead_headers"] = lead
        return program

    def test_documented_advance_is_refused_while_feedback_sits_at_returned(
        self, api: InductionApiClient
    ):
        """The join refuses the phase advance until the feedback dimension is ACCEPTED.

        The PRD makes the join one-sided: "It requires that
        `feedback_review_status` already be `ACCEPTED`; an advance attempted
        while the feedback dimension sits at `DRAFT`, `SUBMITTED` or `RETURNED`
        is refused with `ERR_FEEDBACK_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/observation_parallel_dimensions_with_join
        """
        program = self._cycle_with_returned_feedback(api)

        response = api.advance_cycle(
            program["cycle_id"], f.advance_payload("DOCUMENTED"), program["mentor_headers"]
        )
        validate_error(response, ERR_FEEDBACK_STATE_INVALID, 409)

        cycle = validate_success(api.get_observation_cycle(program["cycle_id"], ADMIN))
        assert cycle["phase"] == "POST_CONFERENCE", (
            f"the refused advance leaves the phase where it was, got {cycle['phase']}"
        )
        assert cycle["feedback_review_status"] == "RETURNED", (
            f"the feedback dimension stays RETURNED, got {cycle['feedback_review_status']}"
        )
        assert cycle["return_count"] == 1, (
            f"one return has been recorded, got {cycle['return_count']}"
        )
        assert_two_decimals(
            cycle["composite_rubric_score"], 2.75, "composite_rubric_score"
        )

    def test_acceptance_unlocks_but_does_not_perform_the_advance(
        self, api: InductionApiClient
    ):
        """After the second submission and an ACCEPT the phase still needs an explicit move.

        The PRD keeps the dimensions independent: "Accepting requires the
        dimension to be `SUBMITTED` and the phase to be `POST_CONFERENCE`; it
        clears `return_reason` to null and, crucially, **unlocks but does not
        perform** the phase advance into `DOCUMENTED`."

        Design: Difficulty/non_linear_state_machine/observation_parallel_dimensions_with_join
        """
        program = self._cycle_with_returned_feedback(api)

        validate_success(
            api.write_feedback(
                program["cycle_id"],
                f.feedback_payload(
                    submit=True,
                    growth_area_codes=["PLANNING", "INSTRUCTION", "ASSESSMENT"],
                    rubric_scores=RUBRIC,
                ),
                program["mentor_headers"],
            )
        )
        accepted = validate_success(
            api.review_feedback(
                program["cycle_id"],
                f.feedback_review_payload("ACCEPT"),
                program["lead_headers"],
            )
        )
        assert accepted["feedback_review_status"] == "ACCEPTED"
        assert accepted["phase"] == "POST_CONFERENCE", (
            "an acceptance must not move the phase dimension by itself, got "
            f"{accepted['phase']}"
        )
        assert accepted["return_reason"] is None, (
            "an acceptance clears return_reason back to null"
        )

        documented = validate_success(
            api.advance_cycle(
                program["cycle_id"],
                f.advance_payload("DOCUMENTED"),
                program["mentor_headers"],
            )
        )
        assert documented["phase"] == "DOCUMENTED", (
            f"the explicit advance now succeeds, got {documented['phase']}"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["documented_observation_cycles"] == 1, (
            f"one cycle reached DOCUMENTED, got {novice['documented_observation_cycles']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 15.00, "readiness_index_live")

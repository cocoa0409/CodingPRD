"""Cyclic and parallel state machines: the revision loop and the two appropriation dimensions."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_success,
)

EDUCATION = ({"agency_code": "DOE", "name": "Department of Education", "agency_type": "EXECUTIVE"},)


class TestAgencyRequestRevisionLoop:
    @staticmethod
    def _draft_request():
        ctx = fixtures.setup_development_cycle(agencies=EDUCATION)
        request = fixtures.create_draft_request(
            ctx["cycle"]["id"], ctx["agency"]["id"], base_budget_cents=1_000_000_000
        )
        return ctx, request

    def test_request_re_enters_submitted_twice_before_being_accepted(self, api):
        """PRD §3.2: "Submission moves the request `DRAFT → SUBMITTED`."
        PRD §3.2: "Returning the request for revision moves `UNDER_REVIEW → RETURNED_FOR_REVISION`, requires the row to be in `UNDER_REVIEW`, takes a `reason` which is stored in `last_return_reason`, increments `revision_count` by 1, and increments `version` by 1."
        PRD §3.2: "The loop closes because a returned request can be submitted again: submission also applies from `RETURNED_FOR_REVISION → SUBMITTED`, under exactly the same four preconditions as the first submission — the row in `RETURNED_FOR_REVISION` rather than `DRAFT`, the cycle in `DEVELOPMENT`, the acting identifier equal to `agency_id`, and every expansion package still carrying a qualifying measure — with the same recomputation of `total_request_cents` and the same version increment."
        PRD §3.2: "A request can therefore cycle `SUBMITTED → UNDER_REVIEW → RETURNED_FOR_REVISION → SUBMITTED` any number of times, and `revision_count` records how many times it entered `RETURNED_FOR_REVISION`."
        PRD §3.2: "Accepting the request moves `UNDER_REVIEW → ACCEPTED`, requires the row to be in `UNDER_REVIEW` and the owning cycle to be in either `DEVELOPMENT` or `EXECUTIVE_PREP`, recomputes `total_request_cents`, and increments `version` by 1."

        Design: Difficulty/non_linear_state_machine/agency_request_revision_loop_returns_to_submitted_twice
        """
        ctx, request = self._draft_request()
        agency_id = ctx["agency"]["id"]
        assert request["revision_count"] == 0
        assert request["last_return_reason"] is None

        first_pass = fixtures.submit_request(request["id"], agency_id)
        assert first_pass["status"] == "SUBMITTED"
        fixtures.begin_review(request["id"])
        returned_once = fixtures.return_for_revision(
            request["id"], "first pass: understate base"
        )
        assert returned_once["status"] == "RETURNED_FOR_REVISION"
        assert returned_once["revision_count"] == 1

        second_pass = fixtures.submit_request(request["id"], agency_id)
        assert second_pass["status"] == "SUBMITTED"
        fixtures.begin_review(request["id"])
        returned_twice = fixtures.return_for_revision(
            request["id"], "second pass: fix FTE table"
        )
        assert returned_twice["revision_count"] == 2

        third_pass = fixtures.submit_request(request["id"], agency_id)
        assert third_pass["status"] == "SUBMITTED"
        fixtures.begin_review(request["id"])
        accepted = fixtures.accept_request(request["id"])

        assert accepted["status"] == "ACCEPTED"
        assert accepted["revision_count"] == 2
        assert accepted["last_return_reason"] == "second pass: fix FTE table"
        assert accepted["total_request_cents"] == 1_000_000_000

    def test_accepted_is_terminal_so_a_fourth_submit_is_rejected(self, api):
        """PRD §3.2: "`ACCEPTED` is terminal."
        PRD §2.12: "The target row is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409)."
        PRD §3.2: "A request can therefore cycle `SUBMITTED → UNDER_REVIEW → RETURNED_FOR_REVISION → SUBMITTED` any number of times, and `revision_count` records how many times it entered `RETURNED_FOR_REVISION`."

        Design: Difficulty/non_linear_state_machine/agency_request_revision_loop_returns_to_submitted_twice
        """
        ctx, request = self._draft_request()
        agency_id = ctx["agency"]["id"]

        for reason in ("first pass: understate base", "second pass: fix FTE table"):
            fixtures.submit_request(request["id"], agency_id)
            fixtures.begin_review(request["id"])
            fixtures.return_for_revision(request["id"], reason)
        fixtures.submit_request(request["id"], agency_id)
        fixtures.begin_review(request["id"])
        accepted = fixtures.accept_request(request["id"])
        assert accepted["status"] == "ACCEPTED"

        response = api.submit_agency_request(
            request["id"], make_agency_officer_headers(agency_id)
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        after = fixtures.read_agency_request(request["id"])
        assert after["status"] == "ACCEPTED"
        assert after["revision_count"] == 2


class TestAppropriationParallelDimensions:
    @staticmethod
    def _approved_allotment_context():
        ctx = fixtures.setup_execution_cycle()
        allotment = fixtures.approved_allotment(
            ctx["appropriation"]["id"], quarter=1, requested_cents=400_000_000
        )
        assert allotment["computed_release_cents"] == 400_000_000
        ctx["allotment"] = allotment
        return ctx

    def test_release_then_freeze_leaves_the_authority_dimension_untouched(
        self, api, state_controller_headers
    ):
        """PRD §3.4: "An appropriation carries **two independent status dimensions**, and neither constrains the other's vocabulary."
        PRD §3.5: "Where current authority again means `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents`, a release that leaves `released_cents` greater than zero but strictly below current authority moves the row `UNRELEASED → PARTIALLY_RELEASED`; a release that brings `released_cents` exactly equal to current authority moves it `UNRELEASED → FULLY_RELEASED` in one step; and a release from a partly released row that reaches current authority exactly moves it `PARTIALLY_RELEASED → FULLY_RELEASED`."
        PRD §3.5: "The transition captures the outgoing value in `pre_freeze_cash_status`, stores the reason in `freeze_reason`, sets `cash_status` to `FROZEN`, and increments `version` by 1."

        Design: Difficulty/non_linear_state_machine/appropriation_authority_and_cash_dimensions_move_independently
        """
        ctx = self._approved_allotment_context()
        appropriation_id = ctx["appropriation"]["id"]

        fixtures.release_allotment(ctx["allotment"]["id"])
        after_release = fixtures.read_appropriation(appropriation_id)
        assert after_release["cash_status"] == "PARTIALLY_RELEASED"
        assert after_release["authority_status"] == "ENACTED"
        assert after_release["released_cents"] == 400_000_000

        frozen = validate_success(
            api.freeze_appropriation_cash(
                appropriation_id,
                {"reason": "controller cash hold pending audit"},
                state_controller_headers,
            ),
            200,
        )

        assert frozen["cash_status"] == "FROZEN"
        assert frozen["pre_freeze_cash_status"] == "PARTIALLY_RELEASED"
        assert frozen["authority_status"] == "ENACTED"
        assert frozen["enacted_amount_cents"] == 2_000_000_000
        assert frozen["available_authority_cents"] == 2_000_000_000

    def test_unfreeze_recomputes_cash_and_recall_returns_it_to_unreleased(
        self, api, state_controller_headers
    ):
        """PRD §3.5: "Unfreezing does **not** restore `pre_freeze_cash_status`."
        PRD §3.5: "It requires `cash_status` to be `FROZEN`, otherwise `ERR_INVALID_STATE`, and then recomputes the cash dimension from scratch: comparing `released_cents` against current authority — `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents` — a released total of zero takes the row `FROZEN → UNRELEASED`, a released total equal to current authority takes it `FROZEN → FULLY_RELEASED`, and anything in between takes it `FROZEN → PARTIALLY_RELEASED`."
        PRD §3.5: "On the appropriation, a recall that brings `released_cents` back to exactly zero moves the cash dimension `PARTIALLY_RELEASED → UNRELEASED`, while a recall that leaves `released_cents` still above zero moves it `FULLY_RELEASED → PARTIALLY_RELEASED`; the cash dimension is genuinely cyclic, and a release followed by its recall returns the row to `UNRELEASED`."

        Design: Difficulty/non_linear_state_machine/appropriation_authority_and_cash_dimensions_move_independently
        """
        ctx = self._approved_allotment_context()
        appropriation_id = ctx["appropriation"]["id"]
        allotment_id = ctx["allotment"]["id"]

        fixtures.release_allotment(allotment_id)
        validate_success(
            api.freeze_appropriation_cash(
                appropriation_id,
                {"reason": "controller cash hold pending audit"},
                state_controller_headers,
            ),
            200,
        )

        unfrozen = validate_success(
            api.unfreeze_appropriation_cash(appropriation_id, state_controller_headers), 200
        )
        assert unfrozen["cash_status"] == "PARTIALLY_RELEASED"
        assert unfrozen["released_cents"] == 400_000_000
        assert unfrozen["freeze_reason"] is None
        assert unfrozen["authority_status"] == "ENACTED"

        recalled = fixtures.recall_allotment(allotment_id, "quarter-1 plan withdrawn")
        assert recalled["status"] == "RECALLED"
        assert recalled["released_cents"] == 0

        final = fixtures.read_appropriation(appropriation_id)
        assert final["cash_status"] == "UNRELEASED"
        assert final["released_cents"] == 0
        assert final["authority_status"] == "ENACTED"
        assert final["available_authority_cents"] == 2_000_000_000
        assert final["enacted_amount_cents"] == 2_000_000_000

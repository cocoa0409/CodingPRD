"""The committee review cycle: the bounded revision loop and the property self-loop."""

from test_helpers import ApiErrorId, assert_money, validate_error
from test_helpers.fixtures import (
    create_case,
    cruised_stand,
    decide_case,
    read_case,
    read_property,
    submit_case,
)
from test_helpers.test_users import make_committee_headers


def _submitted_case(api):
    """A cruised tract with one case authored by analyst-1 and submitted for review."""
    ctx = cruised_stand(api)
    case = create_case(api, ctx.property_id)
    case = submit_case(api, case["id"])
    return ctx, case


def _request_revision(api, case_id, note):
    return api.decide_underwriting_case(
        case_id,
        {"decision": "REQUEST_REVISION", "decision_note": note},
        make_committee_headers("ic-1"),
    )


class TestRevisionLoopBoundedByTheCounter:
    """Two rounds of revision are allowed; the third is refused by the counter."""

    def test_a_revision_request_self_loops_the_property_and_raises_the_counter(self, api):
        """The case drops to REVISION_REQUESTED while the property stays under underwriting.

        PRD: "moves the case to `REVISION_REQUESTED` and increments its `revision_count` by one, while the property stays in `UNDER_UNDERWRITING` — a self-loop on the property dimension while the case cycles"

        Design: Difficulty/non_linear_state_machine/underwriting_revision_loop_terminates_at_two_rounds
        """
        ctx, case = _submitted_case(api)
        assert case["status"] == "SUBMITTED"
        assert read_property(api, ctx.property_id)["status"] == "UNDER_UNDERWRITING"

        decided = decide_case(
            api, case["id"], "REQUEST_REVISION", decision_note="Round 1 attempt."
        )

        assert decided["status"] == "REVISION_REQUESTED"
        assert decided["revision_count"] == 1
        assert read_property(api, ctx.property_id)["status"] == "UNDER_UNDERWRITING"

    def test_a_resubmission_out_of_revision_requested_clears_the_decision_note(self, api):
        """Resubmitting returns the case to SUBMITTED and drops the committee's note.

        PRD: "A resubmission out of `REVISION_REQUESTED` clears the previous `decision_note`."

        Design: Difficulty/non_linear_state_machine/underwriting_revision_loop_terminates_at_two_rounds
        """
        ctx, case = _submitted_case(api)
        decide_case(api, case["id"], "REQUEST_REVISION", decision_note="Round 1 attempt.")

        resubmitted = submit_case(api, case["id"])

        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1
        assert resubmitted["decision_note"] is None
        assert read_property(api, ctx.property_id)["status"] == "UNDER_UNDERWRITING"

    def test_the_third_revision_request_is_refused_once_two_rounds_are_absorbed(self, api):
        """After two rounds the counter is frozen at two and a third request is refused.

        PRD: "A revision request is permitted only while `revision_count` is strictly less than two; a third request against a case that has already absorbed two rounds is refused with `ERR_REVISION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/underwriting_revision_loop_terminates_at_two_rounds
        """
        ctx, case = _submitted_case(api)
        case_id = case["id"]

        decide_case(api, case_id, "REQUEST_REVISION", decision_note="Round 1 attempt.")
        submit_case(api, case_id)
        decide_case(api, case_id, "REQUEST_REVISION", decision_note="Round 2 attempt.")
        submit_case(api, case_id)

        response = _request_revision(api, case_id, "Round 3 attempt.")
        validate_error(response, ApiErrorId.REVISION_LIMIT_REACHED.value, 409)

        frozen = read_case(api, case_id)
        assert frozen["revision_count"] == 2
        assert frozen["status"] == "SUBMITTED"
        assert read_property(api, ctx.property_id)["status"] == "UNDER_UNDERWRITING"

    def test_the_valuation_stack_survives_the_revision_rounds_unchanged(self, api):
        """Every resubmission recomputes the same stack off the same unchanged inventory.

        PRD: "The valuation stack is computed at creation and recomputed from scratch at every submission, so that a case resubmitted after a cruise or a hazard event reflects the tract as it stands."

        Design: Difficulty/non_linear_state_machine/underwriting_revision_loop_terminates_at_two_rounds
        """
        _, case = _submitted_case(api)
        case_id = case["id"]
        assert_money(case["underwritten_value_usd"], 191966.99, "underwritten_value_usd")

        decide_case(api, case_id, "REQUEST_REVISION", decision_note="Round 1 attempt.")
        resubmitted = submit_case(api, case_id)
        decide_case(api, case_id, "REQUEST_REVISION", decision_note="Round 2 attempt.")
        final = submit_case(api, case_id)

        assert_money(
            resubmitted["underwritten_value_usd"], 191966.99, "underwritten_value_usd"
        )
        assert_money(final["underwritten_value_usd"], 191966.99, "underwritten_value_usd")
        assert_money(final["bid_price_usd"], 100000.00, "bid_price_usd")

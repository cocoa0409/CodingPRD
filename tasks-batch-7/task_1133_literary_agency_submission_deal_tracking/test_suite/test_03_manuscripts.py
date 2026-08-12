"""Manuscript evaluation: the bounded revision loop and the accept threshold."""
from test_helpers import (
    ApiErrorId,
    assign_query,
    assign_reader,
    create_agency,
    create_agent,
    create_author,
    evaluate_manuscript,
    intake_query,
    make_agent_headers,
    request_manuscript,
    validate_error,
    validate_success,
)


def _manuscript_submitted(name="Agency MC", genre="MEMOIR", word_count=95000):
    """Agency + agent + author + query assigned + manuscript spawned (SUBMITTED)."""
    agency = create_agency(name=name)
    agent = create_agent(agency["id"])
    author = create_author(agency["id"])
    query = intake_query(agent["id"], author["id"], genre=genre, word_count=word_count)
    assign_query(query["id"], agent["id"])
    manuscript = request_manuscript(query["id"], agent["id"], title="Loop Book")
    return agency, agent, author, manuscript


def _drive_to_evaluated(manuscript_id, agent_id, score):
    assign_reader(manuscript_id, agent_id)
    return evaluate_manuscript(manuscript_id, agent_id, eval_score=score)


class TestManuscriptRevisionLoop:
    def test_revision_loop_closes_twice(self, api):
        """PRD 3.3: "An agent may send it back to the author for revision (`EVALUATED` → `REVISION_REQUESTED`), which increments `revision_round` by one"
        PRD 3.3: "A resubmission returns the manuscript from `REVISION_REQUESTED` to `SUBMITTED` with no preconditions, ready for another reader assignment."

        Design: Difficulty/non_linear_state_machine/manuscript_revision_cycle_bounded_loop
        """
        _agency, agent, _author, manuscript = _manuscript_submitted()
        ms_id = manuscript["id"]

        _drive_to_evaluated(ms_id, agent["id"], 60)
        first = validate_success(
            api.request_revision(ms_id, make_agent_headers(agent["id"])), 200
        )
        assert first["status"] == "REVISION_REQUESTED"
        assert first["revision_round"] == 1

        resubmitted = validate_success(
            api.resubmit_manuscript(ms_id, make_agent_headers(agent["id"])), 200
        )
        assert resubmitted["status"] == "SUBMITTED"

        _drive_to_evaluated(ms_id, agent["id"], 65)
        second = validate_success(
            api.request_revision(ms_id, make_agent_headers(agent["id"])), 200
        )
        assert second["status"] == "REVISION_REQUESTED"
        assert second["revision_round"] == 2, "the cyclic loop must close a second time"

    def test_third_revision_rejected_at_cap(self, api):
        """PRD 3.3: "the loop is capped, and requesting a revision when `revision_round` has already reached 2 is rejected with `ERR_REVISION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/manuscript_revision_cycle_bounded_loop
        """
        _agency, agent, _author, manuscript = _manuscript_submitted()
        ms_id = manuscript["id"]

        for score in (60, 65):
            _drive_to_evaluated(ms_id, agent["id"], score)
            validate_success(api.request_revision(ms_id, make_agent_headers(agent["id"])), 200)
            validate_success(api.resubmit_manuscript(ms_id, make_agent_headers(agent["id"])), 200)

        _drive_to_evaluated(ms_id, agent["id"], 75)
        resp = api.request_revision(ms_id, make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)

        final = validate_success(api.get_manuscript(ms_id, make_agent_headers(agent["id"])), 200)
        assert final["revision_round"] == 2
        assert final["status"] == "EVALUATED", "the rejected third revision must leave state unchanged"


class TestManuscriptAcceptThreshold:
    def test_accept_score_69_rejected(self, api):
        """PRD 3.3: "acceptance (`EVALUATED` → `ACCEPTED`) requires an `eval_score` of at least 70 and is otherwise rejected with `ERR_SCORE_BELOW_THRESHOLD`; acceptance flips the author to `CLIENT`."

        Design: Difficulty/boundary_precision_check/manuscript_accept_eval_score_69_vs_70
        """
        _agency, agent, _author, manuscript = _manuscript_submitted(
            name="Agency B1", genre="FICTION", word_count=90000
        )
        _drive_to_evaluated(manuscript["id"], agent["id"], 69)

        resp = api.accept_manuscript(manuscript["id"], make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD.value)

        current = validate_success(
            api.get_manuscript(manuscript["id"], make_agent_headers(agent["id"])), 200
        )
        assert current["status"] == "EVALUATED"

    def test_accept_score_70_succeeds(self, api):
        """PRD 3.3: "acceptance (`EVALUATED` → `ACCEPTED`) requires an `eval_score` of at least 70 and is otherwise rejected with `ERR_SCORE_BELOW_THRESHOLD`; acceptance flips the author to `CLIENT`."

        Design: Difficulty/boundary_precision_check/manuscript_accept_eval_score_69_vs_70
        """
        _agency, agent, author, manuscript = _manuscript_submitted(
            name="Agency B1", genre="YA", word_count=90000
        )
        _drive_to_evaluated(manuscript["id"], agent["id"], 70)

        accepted = validate_success(
            api.accept_manuscript(manuscript["id"], make_agent_headers(agent["id"])), 200
        )
        assert accepted["status"] == "ACCEPTED", "70 meets the at-least-70 boundary"

        author_now = validate_success(
            api.get_author(author["id"], make_agent_headers(agent["id"])), 200
        )
        assert author_now["status"] == "CLIENT"

    def test_eval_score_out_of_range_invalid_request(self, api):
        """PRD 3.3: "The evaluation payload carries an `eval_score` between 0 and 100 inclusive — anything outside that range fails body validation with `ERR_INVALID_REQUEST`"

        Design: Corner/validations/eval_score_out_of_range_invalid_request
        """
        _agency, agent, _author, manuscript = _manuscript_submitted(
            name="Agency OR", genre="FICTION", word_count=90000
        )
        assign_reader(manuscript["id"], agent["id"])

        resp = api.evaluate_manuscript(
            manuscript["id"], {"eval_score": 101}, make_agent_headers(agent["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

        current = validate_success(
            api.get_manuscript(manuscript["id"], make_agent_headers(agent["id"])), 200
        )
        assert current["status"] == "READER_ASSIGNED"

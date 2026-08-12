"""Cross-cutting access rules and immediate-consistency guarantees."""
from test_helpers import (
    ApiErrorId,
    accept_manuscript,
    api_client,
    assign_query,
    assign_reader,
    create_agency,
    create_agent,
    create_author,
    create_client_agreement_payload,
    create_editor,
    create_round,
    evaluate_manuscript_payload,
    intake_query,
    make_agent_headers,
    make_contracts_manager_headers,
    open_round,
    queue_submission,
    request_manuscript,
    send_submission,
    setup_negotiating_deal,
    validate_error,
    validate_success,
)


class TestAccessControl:
    def test_missing_auth_header_returns_400(self, api):
        """PRD 2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD 2.9: "Every request is validated against an ordered pipeline; the first failing check determines the error response, so an earlier failure masks later ones."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        ctx = _setup_passed_submission()

        # The target is in a terminal state (PASSED), so a state check would
        # also reject this call; the missing user context must win at 400.
        resp = api.pass_submission(ctx["submission"]["id"], headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_all_roles_can_read_any_resource(self, api, agency_admin_headers,
                                             royalties_accountant_headers):
        """PRD 4: ""Any" in the table means any of the four roles of §2.1."

        Design: Corner/roles/all_roles_can_read_any_resource
        """
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency RB3")
        deal_id = ctx["deal"]["id"]
        agent_headers = make_agent_headers(ctx["agent"]["id"])

        for headers in (agency_admin_headers, agent_headers,
                        make_contracts_manager_headers("cm-1"),
                        royalties_accountant_headers):
            data = validate_success(api.get_deal(deal_id, headers), 200)
            assert data["id"] == deal_id, (
                "every role must be able to read the same deal"
            )


class TestImmediateConsistency:
    def test_mutations_visible_in_same_response(self, api):
        """PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD 3.3: "recording it moves the manuscript from `READER_ASSIGNED` to `EVALUATED`"
        PRD 3.5: "a pass — from either `SENT` or `UNDER_CONSIDERATION` — lands it in `PASSED` with `response_period_index` stamped."

        Design: Corner/consistency_model/mutations_visible_in_same_response
        """
        ctx = _setup_passed_submission(eval_score=77)
        assert ctx["evaluated"]["status"] == "EVALUATED"
        assert ctx["evaluated"]["eval_score"] == 77, (
            "the evaluate response already reflects the recorded score"
        )
        assert ctx["passed"]["status"] == "PASSED"
        assert ctx["passed"]["response_period_index"] == 0, (
            "the pass response carries the terminal state and the period stamp"
        )


def _setup_passed_submission(eval_score=77):
    """Full pipeline to a PASSED submission, capturing the mutation responses.

    Returns ctx with the raw evaluate and pass response payloads.
    """
    agency = create_agency(name="Agency AH")
    agent = create_agent(agency["id"])
    author = create_author(agency["id"])
    editor = create_editor(agency["id"])
    agent_id = agent["id"]

    query = intake_query(agent_id, author["id"], genre="FICTION", word_count=90000)
    assign_query(query["id"], agent_id)
    manuscript = request_manuscript(query["id"], agent_id, title="T")
    assign_reader(manuscript["id"], agent_id)

    evaluated = validate_success(
        api_client.evaluate_manuscript(
            manuscript["id"], evaluate_manuscript_payload(eval_score=eval_score),
            make_agent_headers(agent_id),
        ),
        200,
    )
    accept_manuscript(manuscript["id"], agent_id)

    agreement = validate_success(
        api_client.create_client_agreement(
            create_client_agreement_payload(author["id"], manuscript["id"], agent_id),
            make_agent_headers(agent_id),
        ),
        201,
    )
    validate_success(api_client.offer_agreement(agreement["id"], make_agent_headers(agent_id)), 200)
    validate_success(api_client.sign_agreement(agreement["id"], make_agent_headers(agent_id)), 200)

    round_data = create_round(manuscript["id"], agent_id)
    submission = queue_submission(round_data["id"], editor["id"], agent_id)
    open_round(round_data, agent_id)
    send_submission(submission["id"], agent_id)

    passed = validate_success(
        api_client.pass_submission(submission["id"], make_agent_headers(agent_id)), 200
    )
    return {
        "agency": agency, "agent": agent, "author": author, "editor": editor,
        "manuscript": manuscript, "agreement": agreement, "round": round_data,
        "submission": submission, "evaluated": evaluated, "passed": passed,
    }

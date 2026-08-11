"""Client representation agreements: offer gates, signing, and termination."""
from test_helpers import (
    ApiErrorId,
    accept_manuscript,
    assign_query,
    assign_reader,
    create_agency,
    create_agent,
    create_author,
    create_client_agreement_payload,
    evaluate_manuscript,
    intake_query,
    make_agent_headers,
    request_manuscript,
    setup_negotiating_deal,
    validate_error,
    validate_success,
)


def _evaluated_manuscript(name="Agency X2", score=75):
    """Agency + agent + author + manuscript EVALUATED (not yet accepted)."""
    agency = create_agency(name=name)
    agent = create_agent(agency["id"])
    author = create_author(agency["id"])
    query = intake_query(agent["id"], author["id"], genre="FICTION", word_count=90000)
    assign_query(query["id"], agent["id"])
    manuscript = request_manuscript(query["id"], agent["id"], title="Book One")
    assign_reader(manuscript["id"], agent["id"])
    evaluate_manuscript(manuscript["id"], agent["id"], eval_score=score)
    return agency, agent, author, manuscript


class TestAgreementOfferGate:
    def test_offer_blocked_until_manuscript_accepted(self, api):
        """PRD 3.4: "Offering the agreement to the author (`DRAFT` → `OFFERED`) is guarded twice: the manuscript must be `ACCEPTED` (`ERR_MANUSCRIPT_NOT_ACCEPTED`), and the acting agent must be the agreement's own `agent_id` (`ERR_NOT_ASSIGNED_AGENT`)."

        Design: Difficulty/cross_entity_state_dependency/agreement_offer_requires_manuscript_accepted
        """
        _agency, agent, author, manuscript = _evaluated_manuscript()
        agreement = validate_success(
            api.create_client_agreement(
                create_client_agreement_payload(author["id"], manuscript["id"], agent["id"]),
                make_agent_headers(agent["id"]),
            ),
            201,
        )
        assert agreement["status"] == "DRAFT"

        resp = api.offer_agreement(agreement["id"], make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_MANUSCRIPT_NOT_ACCEPTED.value)

        current = validate_success(
            api.get_client_agreement(agreement["id"], make_agent_headers(agent["id"])), 200
        )
        assert current["status"] == "DRAFT"

    def test_offer_succeeds_after_manuscript_accepted(self, api):
        """PRD 3.4: "Offering the agreement to the author (`DRAFT` → `OFFERED`) is guarded twice: the manuscript must be `ACCEPTED` (`ERR_MANUSCRIPT_NOT_ACCEPTED`), and the acting agent must be the agreement's own `agent_id` (`ERR_NOT_ASSIGNED_AGENT`)."

        Design: Difficulty/cross_entity_state_dependency/agreement_offer_requires_manuscript_accepted
        """
        _agency, agent, author, manuscript = _evaluated_manuscript()
        agreement = validate_success(
            api.create_client_agreement(
                create_client_agreement_payload(author["id"], manuscript["id"], agent["id"]),
                make_agent_headers(agent["id"]),
            ),
            201,
        )
        accept_manuscript(manuscript["id"], agent["id"])

        offered = validate_success(
            api.offer_agreement(agreement["id"], make_agent_headers(agent["id"])), 200
        )
        assert offered["status"] == "OFFERED", (
            "the same offer succeeds once the manuscript is ACCEPTED"
        )


class TestAgreementSigningAndTermination:
    def test_second_signed_agreement_same_manuscript_rejected(self, api):
        """PRD 3.4: "Signing (`OFFERED` → `SIGNED`) requires that no other agreement covering the same manuscript is already `SIGNED` — a duplicate is rejected with `ERR_AGREEMENT_ALREADY_SIGNED`"

        Design: Corner/validations/second_signed_agreement_same_manuscript_rejected
        """
        _agency, agent, author, manuscript = _evaluated_manuscript(name="Agency AS", score=80)
        accept_manuscript(manuscript["id"], agent["id"])

        agr1 = validate_success(
            api.create_client_agreement(
                create_client_agreement_payload(author["id"], manuscript["id"], agent["id"]),
                make_agent_headers(agent["id"]),
            ),
            201,
        )
        agr2 = validate_success(
            api.create_client_agreement(
                create_client_agreement_payload(
                    author["id"], manuscript["id"], agent["id"],
                    commission_pct_override=0.12,
                ),
                make_agent_headers(agent["id"]),
            ),
            201,
        )
        validate_success(api.offer_agreement(agr1["id"], make_agent_headers(agent["id"])), 200)
        validate_success(api.sign_agreement(agr1["id"], make_agent_headers(agent["id"])), 200)
        validate_success(api.offer_agreement(agr2["id"], make_agent_headers(agent["id"])), 200)

        resp = api.sign_agreement(agr2["id"], make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_ALREADY_SIGNED.value)

        current = validate_success(
            api.get_client_agreement(agr2["id"], make_agent_headers(agent["id"])), 200
        )
        assert current["status"] == "OFFERED"

    def test_terminate_agreement_with_live_deal_rejected(self, api, contracts_manager_headers):
        """PRD 3.4: "A `ContractsManager` may move a `SIGNED` agreement to `TERMINATED`, but only while no deal linked to that agreement is still in `NEGOTIATING`, `EXECUTED`, or `ACTIVE`; an open deal blocks termination with `ERR_DEAL_STILL_OPEN`."

        Design: Corner/validations/terminate_agreement_with_live_deal_rejected
        """
        ctx = setup_negotiating_deal(advance_cents=500000, agency_name="Agency DO")
        assert ctx["deal"]["status"] == "NEGOTIATING"

        resp = api.terminate_agreement(ctx["agreement"]["id"], contracts_manager_headers)
        validate_error(resp, ApiErrorId.ERR_DEAL_STILL_OPEN.value)

        current = validate_success(
            api.get_client_agreement(ctx["agreement"]["id"], contracts_manager_headers), 200
        )
        assert current["status"] == "SIGNED"

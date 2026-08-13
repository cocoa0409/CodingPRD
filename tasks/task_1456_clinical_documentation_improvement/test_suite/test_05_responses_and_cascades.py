"""Provider responses: recipient enforcement, terminal lockdown, cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_query,
    create_provider,
    drive_education_score,
    get_case,
    respond_to_query,
    setup_agreed_case,
    setup_sent_query,
    validate_error,
    validate_success,
)


class TestAgreeCascade:
    def test_agree_updates_case_and_review_deltas(self, api, cdi_specialist_headers):
        """PRD §3.6: "On `AGREE`, the case's working documentation is rewritten to
        the proposal: `working_drg_code` becomes `proposed_drg_code`,
        `working_drg_weight` becomes `proposed_drg_weight`, `working_soi` becomes
        `proposed_soi`, `working_rom` becomes `proposed_rom`, the case's
        `priority_score` is recomputed, and the owning review's opportunity deltas
        are recomputed."
        PRD §3.6: "`opportunity_weight_delta` is the sum, across the review's
        queries in `RESPONDED` status whose response type was `AGREE`, of each
        query's `proposed_drg_weight` minus the case's `initial_drg_weight`."

        Design: Difficulty/transitive_cascade/agree_response_cascade_query_to_case_to_review
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=2.5, proposed_soi=3, proposed_rom=4,
            discharge_period=10, initial_drg_weight=1.0,
        )
        case = get_case(scenario["case"]["id"])
        assert case["working_drg_code"] == "DRG-B"
        assert case["working_drg_weight"] == pytest.approx(2.5, abs=1e-9)
        assert case["working_soi"] == 3
        assert case["working_rom"] == 4
        # base 1.5 * acuity 1.50 (rom=4) * los 1.00 (period 0 < discharge 10) * 100
        assert case["priority_score"] == pytest.approx(225.0, abs=1e-4)
        review = validate_success(api.get_cdi_review(scenario["review"]["id"], cdi_specialist_headers))
        assert review["opportunity_weight_delta"] == pytest.approx(1.5, abs=1e-9)
        assert review["opportunity_soi_delta"] == 2
        assert review["opportunity_rom_delta"] == 3

    def test_two_agrees_stack_review_deltas(self, api, cdi_specialist_headers):
        """PRD §3.6: "These deltas are cumulative realizations: they are not
        recomputed downward when a later `AGREE` overwrites an earlier one, so two
        `AGREE` responses on the same case stack."

        Design: Difficulty/transitive_cascade/agree_response_cascade_query_to_case_to_review
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=2.0, proposed_soi=2, proposed_rom=2,
            discharge_period=10, initial_drg_weight=1.0,
        )
        # Second query on the same review; AGREE again with another +1.0 delta.
        q2 = create_query(
            scenario["review"]["id"], scenario["provider"]["id"], scenario["policy"]["id"],
            proposed_drg_code="DRG-C", proposed_drg_weight=2.0,
            proposed_soi=3, proposed_rom=3,
        )
        from test_helpers import send_query
        q2 = send_query(q2["id"], q2["version"])
        respond_to_query(q2["id"], scenario["provider"]["id"], response_type="AGREE")
        review = validate_success(api.get_cdi_review(scenario["review"]["id"], cdi_specialist_headers))
        assert review["opportunity_weight_delta"] == pytest.approx(1.0 + 1.0, abs=1e-9)
        assert review["opportunity_soi_delta"] == 1 + 2
        assert review["opportunity_rom_delta"] == 1 + 2


class TestImmediateConsistency:
    def test_agree_response_immediately_visible_on_case(self, api, cdi_specialist_headers):
        """PRD §3.6: "On `AGREE`, the case's working documentation is rewritten to
        the proposal: `working_drg_code` becomes `proposed_drg_code`,
        `working_drg_weight` becomes `proposed_drg_weight`, `working_soi` becomes
        `proposed_soi`, `working_rom` becomes `proposed_rom`"

        Design: Corner/consistency_model/agree_response_immediately_visible_on_case
        """
        scenario = setup_agreed_case(
            proposed_drg_weight=3.0, proposed_soi=4, proposed_rom=4,
            proposed_drg_code="DRG-B", initial_drg_weight=1.0, initial_drg_code="DRG-A",
        )
        case = validate_success(api.get_patient_case(scenario["case"]["id"], cdi_specialist_headers))
        assert case["working_drg_code"] == "DRG-B"
        assert case["working_drg_weight"] == pytest.approx(3.0, abs=1e-9)
        assert case["working_soi"] == 4
        assert case["working_rom"] == 4


class TestTerminalLockdown:
    def test_response_on_responded_query_returns_invalid_state(self, api):
        """PRD §3.6: "Only a query in `SENT` or `ESCALATED` status accepts a
        response (`ERR_INVALID_STATE` otherwise)"

        Design: Corner/state_machines/cdi_query_response_on_responded_returns_invalid_state
        """
        scenario = setup_agreed_case()
        query = scenario["query"]
        from test_helpers import api_client, create_query_response_payload, make_provider_headers
        resp = api_client.create_query_response(
            query["id"],
            create_query_response_payload(response_type="DISAGREE", response_text="second"),
            make_provider_headers(scenario["provider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRecipientEnforcement:
    def test_provider_cannot_respond_to_other_providers_query(self, api):
        """PRD §3.6: "the responder's `X-User-ID` must equal the query's
        `provider_id`, and any other responder — including the CDI specialist who
        authored the query — is rejected with `ERR_NOT_QUERY_RECIPIENT`."

        Design: Corner/validations/provider_cannot_respond_to_other_providers_query
        """
        scenario = setup_sent_query()
        other_provider = create_provider(scenario["program"]["id"], npi="NPI-other")
        from test_helpers import api_client, create_query_response_payload, make_provider_headers
        resp = api_client.create_query_response(
            scenario["query"]["id"],
            create_query_response_payload(response_type="AGREE", response_text="ok"),
            make_provider_headers(other_provider["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_QUERY_RECIPIENT)


class TestIntensiveReviewGate:
    def test_intensive_review_provider_blocked_from_agree(self, api):
        """PRD §3.6: "A provider whose `education_flag` has fallen to
        `INTENSIVE_REVIEW` may submit only `CLARIFICATION_REQUESTED` responses;
        any other response type from such a provider is rejected with
        `ERR_PROVIDER_UNDER_INTENSIVE_REVIEW`."

        Design: Corner/validations/intensive_review_provider_blocked_from_agree
        """
        scenario = setup_sent_query(response_due_periods=5, escalation_stage_periods=5)
        provider_id = scenario["provider"]["id"]
        # Drive score from 100 to 40 (< 50 -> INTENSIVE_REVIEW) via manual events.
        drive_education_score(provider_id, scenario["query"]["id"], 60)
        from test_helpers import api_client, create_query_response_payload, make_provider_headers
        resp = api_client.create_query_response(
            scenario["query"]["id"],
            create_query_response_payload(response_type="AGREE", response_text="ok"),
            make_provider_headers(provider_id),
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_UNDER_INTENSIVE_REVIEW)

    def test_intensive_review_provider_may_request_clarification(self, api):
        """PRD §3.6: "A provider whose `education_flag` has fallen to
        `INTENSIVE_REVIEW` may submit only `CLARIFICATION_REQUESTED` responses;
        any other response type from such a provider is rejected with
        `ERR_PROVIDER_UNDER_INTENSIVE_REVIEW`."

        Design: Corner/validations/intensive_review_provider_blocked_from_agree
        """
        scenario = setup_sent_query(response_due_periods=5, escalation_stage_periods=5)
        provider_id = scenario["provider"]["id"]
        drive_education_score(provider_id, scenario["query"]["id"], 60)
        response = respond_to_query(
            scenario["query"]["id"], provider_id,
            response_type="CLARIFICATION_REQUESTED",
            response_text="Please clarify the question.",
        )
        assert response["response_type"] == "CLARIFICATION_REQUESTED"

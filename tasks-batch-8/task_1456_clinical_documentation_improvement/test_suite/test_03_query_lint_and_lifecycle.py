"""CDIQuery drafting, non-leading lint, send guards, and edit lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_activate_review,
    create_case,
    create_cdi_query_payload,
    create_program,
    create_provider,
    create_query,
    send_query,
    setup_basic_scenario,
    setup_program_policy_provider,
    setup_sent_query,
    validate_error,
    validate_success,
    make_provider_headers,
)


class TestQuerySendReviewGuard:
    def test_send_rejected_when_review_on_hold(self, api, cdi_specialist_headers):
        """PRD §3.4: "its parent review must be `ACTIVE` (`ERR_REVIEW_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/query_send_requires_review_active
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        query = create_query(
            review["id"], scenario["provider"]["id"], scenario["policy"]["id"]
        )
        validate_success(api.hold_cdi_review(review["id"], cdi_specialist_headers))
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ACTIVE)

    def test_send_succeeds_when_review_active(self, api, cdi_specialist_headers):
        """PRD §3.4: "A successful send transitions the query to `SENT`, stamps
        `sent_period` with the program's current period, computes `due_period` as
        the `sent_period` plus the governing policy's `response_due_periods`, and
        increments the query's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/query_send_requires_review_active
        """
        scenario = setup_basic_scenario(discharge_period=5, response_due_periods=3)
        review = create_and_activate_review(scenario["case"]["id"])
        query = create_query(
            review["id"], scenario["provider"]["id"], scenario["policy"]["id"]
        )
        sent = validate_success(
            api.send_cdi_query(
                query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
            )
        )
        assert sent["status"] == "SENT"
        assert sent["sent_period"] == 0
        assert sent["due_period"] == 0 + 3
        assert sent["version"] == query["version"] + 1


class TestNonLeadingLint:
    def test_answer_in_question_rejected(self, api, cdi_specialist_headers):
        """PRD §3.4: "It records an `ANSWER_IN_QUESTION` finding when the proposed
        DRG code appears as a literal token inside the query text"
        PRD §3.4: "If any finding is present, the send fails with
        `ERR_LEADING_LANGUAGE` and the query remains in `DRAFT`."

        Design: Corner/calculations/non_leading_lint_catches_answer_in_question
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        query = create_query(
            review["id"], scenario["provider"]["id"], scenario["policy"]["id"],
            query_text="Is this DRG-B?", proposed_drg_code="DRG-B",
        )
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_LEADING_LANGUAGE)

    def test_empty_indicators_rejected(self, api, cdi_specialist_headers):
        """PRD §3.4: "and a `NO_INDICATORS` finding when the clinical indicators
        list is empty."
        PRD §3.4: "If any finding is present, the send fails with
        `ERR_LEADING_LANGUAGE` and the query remains in `DRAFT`."

        Design: Corner/calculations/non_leading_lint_catches_empty_indicators
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        query = create_query(
            review["id"], scenario["provider"]["id"], scenario["policy"]["id"],
            query_text="Please clarify.", clinical_indicators=[],
        )
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_LEADING_LANGUAGE)

    @pytest.mark.parametrize("phrase", [
        "do you agree that",
        "isn't it true",
        "clearly indicates",
        "should be coded as",
        "please document",
        "the patient has",
        "confirm the diagnosis of",
    ])
    def test_leading_phrase_rejected(self, api, cdi_specialist_headers, phrase):
        """PRD §3.4: "The lint records a finding for each occurrence —
        case-insensitive — of any leading phrase in the query text: "do you agree
        that", "isn't it true", "clearly indicates", "should be coded as", "please
        document", "the patient has", or "confirm the diagnosis of"."
        PRD §3.4: "If any finding is present, the send fails with
        `ERR_LEADING_LANGUAGE` and the query remains in `DRAFT`."

        Design: Corner/calculations/non_leading_lint_catches_empty_indicators
        """
        scenario = setup_basic_scenario(discharge_period=5)
        review = create_and_activate_review(scenario["case"]["id"])
        query = create_query(
            review["id"], scenario["provider"]["id"], scenario["policy"]["id"],
            query_text=f"{phrase} this condition? Additional context.",
        )
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_LEADING_LANGUAGE)


class TestLintVsProviderMembershipPriority:
    def test_leading_language_fires_before_provider_not_in_program(self, api, cdi_specialist_headers):
        """PRD §2.10: "Only after those five generic gates pass do business rules
        run: query language lint (`ERR_LEADING_LANGUAGE`), provider program
        membership (`ERR_PROVIDER_NOT_IN_PROGRAM`), ..."

        Design: Difficulty/priority_pair_validation_conflict/leading_language_vs_provider_not_in_program_on_send
        """
        program_a = create_program(facility_name="FA", program_code="PA")
        program_b = create_program(facility_name="FB", program_code="PB")
        from test_helpers import create_policy
        policy_a = create_policy(program_a["id"])
        provider_a = create_provider(program_a["id"])
        provider_b = create_provider(program_b["id"])
        case = create_case(program_a["id"], provider_a["id"])
        review = create_and_activate_review(case["id"])
        query = create_query(
            review["id"], provider_b["id"], policy_a["id"],
            query_text="Do you agree that the patient has sepsis?",
            clinical_indicators=["fever"],
        )
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_LEADING_LANGUAGE)

    def test_cross_program_provider_rejected_when_lint_clean(self, api, cdi_specialist_headers):
        """PRD §3.4: "the addressed provider must belong to the same program as the
        review's case (`ERR_PROVIDER_NOT_IN_PROGRAM`)"

        Design: Difficulty/priority_pair_validation_conflict/leading_language_vs_provider_not_in_program_on_send
        """
        program_a = create_program(facility_name="FA", program_code="PA")
        program_b = create_program(facility_name="FB", program_code="PB")
        from test_helpers import create_policy
        policy_a = create_policy(program_a["id"])
        provider_a = create_provider(program_a["id"])
        provider_b = create_provider(program_b["id"])
        case = create_case(program_a["id"], provider_a["id"])
        review = create_and_activate_review(case["id"])
        query = create_query(
            review["id"], provider_b["id"], policy_a["id"],
            query_text="Please clarify the documented acuity level.",
            clinical_indicators=["fever"],
        )
        resp = api.send_cdi_query(
            query["id"], {"expected_query_version": query["version"]}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_IN_PROGRAM)


class TestDraftEditLockdown:
    def test_edit_on_sent_query_returns_invalid_state(self, api, cdi_specialist_headers):
        """PRD §3.4: "may be freely edited while still a draft — text, indicators,
        proposed values, recipient, or policy — with each edit incrementing the
        query's `version` by 1."
        PRD §5: "`ERR_INVALID_STATE` | 409"

        Design: Corner/endpoints/query_edit_on_sent_query_returns_invalid_state
        """
        scenario = setup_sent_query()
        resp = api.update_cdi_query(
            scenario["query"]["id"], {"query_text": "edited"}, cdi_specialist_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestQueryResponseListing:
    def test_get_responses_returns_empty_array_before_response(self, api, cdi_specialist_headers):
        """PRD §4: "GET | `/api/cdi-queries/{id}/responses` | Get the response on a
        query (zero or one)"
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/get_query_responses_returns_empty_array_before_response
        """
        scenario = setup_sent_query()
        body = api.get_query_responses(scenario["query"]["id"], cdi_specialist_headers)
        assert body.status_code == 200
        payload = body.json()
        assert payload["response_type"] == "array"
        assert payload["data"] == []

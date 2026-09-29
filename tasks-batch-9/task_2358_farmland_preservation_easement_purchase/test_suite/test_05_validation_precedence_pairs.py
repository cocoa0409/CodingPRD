"""Two requests that break two rules at once, and which error must surface.

In each pair the two candidate rules sit on widely separated rungs of the §2.11
ladder, and the lower-rung error is the one a naive endpoint-local check emits.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    accept_as_landowner,
    api_client,
    make_landowner_headers,
    make_program_admin_headers,
    read_application,
    requirement_of_type,
    review_requirement_payload,
    set_clock,
    setup_accepted_application,
    setup_funded_application,
    setup_offered_application,
    submit_title_payload,
    withdrawal_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]


class TestWithdrawnAcceptancePrecedence:
    """Rung 9 (application state) against rung 19 (funding-plan completeness)."""

    def test_the_state_error_is_reported_over_the_funding_plan_error(self):
        """Withdrawal breaks the state test and the plan test in one stroke.

        PRD §2.11: "9. The subject row is in a state from which the requested
        transition exists — the state code for that entity and dimension."

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_application_acceptance_reports_state_error_over_funding_error
        """
        scenario = setup_funded_application()
        application_id = scenario["application"]["id"]
        landowner_headers = make_landowner_headers(scenario["landowner"]["id"])
        assert scenario["application"]["funding_plan_status"] == "FUNDED"

        withdrawn = validate_success(
            api_client.withdraw_application(
                application_id, withdrawal_payload(), landowner_headers
            )
        )
        # Withdrawal releases the plan, so both candidate rules now fail.
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["funding_plan_status"] == "RELEASED"

        response = api_client.accept_application(application_id, landowner_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value)

        # Nothing moved.
        after = read_application(application_id)
        assert after["status"] == "WITHDRAWN"
        assert after["agreed_price_cents"] is None

    def test_the_funding_plan_error_is_reported_when_only_the_plan_is_wrong(self):
        """With the state test satisfied, rung 19 surfaces on its own.

        PRD §3.7: "Both branches require `funding_plan_status` to be exactly
        `FUNDED` and `funded_cost_cents` to equal `total_program_cost_cents`, and
        a plan that fails either test is rejected with
        `ERR_FUNDING_PLAN_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_application_acceptance_reports_state_error_over_funding_error
        """
        scenario = setup_offered_application()
        application_id = scenario["application"]["id"]
        assert scenario["application"]["status"] == "OFFER_ISSUED"
        assert scenario["application"]["funding_plan_status"] == "UNFUNDED"

        response = api_client.accept_application(
            application_id, make_landowner_headers(scenario["landowner"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_FUNDING_PLAN_INCOMPLETE.value)

    def test_the_same_request_succeeds_when_neither_rule_is_broken(self):
        """The control leg: a FUNDED offer accepts cleanly.

        PRD §3.7: "A `Landowner` accepts from `OFFER_ISSUED`, which requires
        `X-User-ID` to equal the application's `landowner_id` and requires the
        logical clock to be at or before `current_offer_expires_on`; the price
        locked into `agreed_price_cents` is `current_offer_cents`."

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_application_acceptance_reports_state_error_over_funding_error
        """
        scenario = setup_funded_application()
        set_clock("2026-10-12T00:00:00Z")
        accepted = accept_as_landowner(
            scenario["application"]["id"], scenario["landowner"]["id"]
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["agreed_price_cents"] == 175_550_000
        assert accepted["funding_plan_status"] == "OBLIGATED"


class TestClosingReviewSodPrecedence:
    """Rung 10 (segregation of duties) against rung 15 (title exceptions)."""

    @staticmethod
    def _submitted_title_requirement(exception_count: int) -> str:
        scenario = setup_accepted_application()
        requirement = requirement_of_type(
            scenario["application"]["id"], "TITLE_COMMITMENT"
        )
        submitted = validate_success(
            api_client.submit_closing_requirement(
                requirement["id"], submit_title_payload(exception_count), OFFICER
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == OFFICER_USER_ID
        assert submitted["exception_count"] == exception_count
        return requirement["id"]

    def test_the_sod_error_is_reported_over_the_title_exception_error(self):
        """A self-review of a two-exception title package reports the SoD gate.

        PRD §2.11: "10. Segregation of duties — `ERR_APPRAISAL_REVIEW_SOD` or
        `ERR_CLOSING_REVIEW_SOD`."

        Design: Difficulty/priority_pair_validation_conflict/closing_requirement_review_reports_segregation_of_duties_over_title_exception_error
        """
        requirement_id = self._submitted_title_requirement(2)

        # A ProgramAdmin presenting the submitting officer's own identifier.
        response = api_client.review_closing_requirement(
            requirement_id,
            review_requirement_payload("ACCEPT"),
            make_program_admin_headers(OFFICER_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_CLOSING_REVIEW_SOD.value, 403)

        still_submitted = validate_success(
            api_client.get_closing_requirement(requirement_id, ADMIN)
        )
        assert still_submitted["status"] == "SUBMITTED"
        assert still_submitted["reviewed_by_user_id"] is None

    def test_the_title_exception_error_is_reported_by_a_distinct_reviewer(self):
        """With the SoD gate satisfied, rung 15 surfaces on its own.

        PRD §3.7: "Accepting a `TITLE_COMMITMENT` while its `exception_count` is
        greater than 0 is rejected with `ERR_TITLE_EXCEPTIONS_OUTSTANDING`."

        Design: Difficulty/priority_pair_validation_conflict/closing_requirement_review_reports_segregation_of_duties_over_title_exception_error
        """
        requirement_id = self._submitted_title_requirement(2)

        response = api_client.review_closing_requirement(
            requirement_id, review_requirement_payload("ACCEPT"), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_TITLE_EXCEPTIONS_OUTSTANDING.value)

    def test_the_sod_error_fires_alone_on_a_clean_title_package(self):
        """The SoD gate does not depend on the exception count at all.

        PRD §2.9: "A closing-requirement review must be performed by a user
        other than the one who last submitted that requirement: `X-User-ID` must
        differ from `submitted_by_user_id`, otherwise the review is rejected with
        `ERR_CLOSING_REVIEW_SOD`."

        Design: Difficulty/priority_pair_validation_conflict/closing_requirement_review_reports_segregation_of_duties_over_title_exception_error
        """
        requirement_id = self._submitted_title_requirement(0)

        response = api_client.review_closing_requirement(
            requirement_id,
            review_requirement_payload("ACCEPT"),
            make_program_admin_headers(OFFICER_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_CLOSING_REVIEW_SOD.value, 403)

        # A rejection by the submitter is barred just as an acceptance is.
        rejection = api_client.review_closing_requirement(
            requirement_id,
            review_requirement_payload("REJECT", deficiency_note="stale commitment"),
            make_program_admin_headers(OFFICER_USER_ID),
        )
        validate_error(rejection, ApiErrorId.ERR_CLOSING_REVIEW_SOD.value, 403)

        # And a distinct reviewer completes it.
        accepted = validate_success(
            api_client.review_closing_requirement(
                requirement_id, review_requirement_payload("ACCEPT"), ADMIN
            )
        )
        assert accepted["status"] == "SATISFIED"

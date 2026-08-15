"""Cross-cutting contract: header context, error envelope, the not-found family,
volunteer field rules, and the close-out sponsorship gate."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    commit_sponsorship,
    complete_event,
    create_event,
    create_sponsorship,
    get_event,
    get_sponsorship,
    setup_in_progress_event,
    setup_matched_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

CEM = TEST_USERS["cem_headers"]
FC = TEST_USERS["finance_headers"]


class TestHeaderContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying a role value the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.create_service_event(
            {
                "name": "NoAuth",
                "event_start_at": "2026-08-20T09:00:00Z",
                "event_end_at": "2026-08-20T15:00:00Z",
                "budget_cents": 100,
            },
            {},  # no X-User-ID / X-User-Role headers at all
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api, any_headers):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_service_project(NON_EXISTENT_UUID, any_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)
        assert resp.status_code == 404
        assert len(error_data["message"].strip()) > 0
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_remaining_not_found_errors_triggerable(self, api, any_headers, logistics_headers):
        """PRD §2.10: "The full not-found family — `ERR_NONPROFIT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_MEAL_PLAN_NOT_FOUND`, `ERR_SUPERVISION_NOT_FOUND`, `ERR_SPONSORSHIP_NOT_FOUND`, `ERR_IMPACT_RECORD_NOT_FOUND`, and `ERR_SURVEY_NOT_FOUND` — is likewise used for body-referenced foreign keys that do not exist, checked after the path identifiers."

        Design: Corner/errors/remaining_not_found_errors_triggerable
        """
        event = create_event("Day 42", budget_cents=500000)

        probes = [
            (api.get_nonprofit_partner(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_NONPROFIT_NOT_FOUND),
            (api.get_employee_volunteer(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_VOLUNTEER_NOT_FOUND),
            (api.get_registration(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_REGISTRATION_NOT_FOUND),
            (api.get_procurement_order(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_ORDER_NOT_FOUND),
            # Vehicle has no single-GET endpoint: probe via a manifest's body FK
            (
                api.create_transport_manifest(
                    {
                        "event_id": event["id"],
                        "vehicle_id": NON_EXISTENT_UUID,
                        "depart_at": "2026-08-20T08:00:00Z",
                        "return_at": "2026-08-20T10:00:00Z",
                        "cost_cents": 1000,
                    },
                    logistics_headers,
                ),
                ApiErrorId.ERR_VEHICLE_NOT_FOUND,
            ),
            (api.get_transport_manifest(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_MANIFEST_NOT_FOUND),
            (api.get_meal_plan(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_MEAL_PLAN_NOT_FOUND),
            (api.get_supervision_assignment(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_SUPERVISION_NOT_FOUND),
            (api.get_sponsorship(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_SPONSORSHIP_NOT_FOUND),
            (api.get_impact_record(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_IMPACT_RECORD_NOT_FOUND),
            (api.get_feedback_survey(NON_EXISTENT_UUID, any_headers), ApiErrorId.ERR_SURVEY_NOT_FOUND),
        ]
        for resp, expected in probes:
            validate_error(resp, expected)
            assert resp.status_code == 404, f"{expected} should be HTTP 404"


class TestVolunteerFieldRules:
    def test_volunteer_missing_required_email_rejected(self, api, cem_headers, any_headers):
        """PRD §2.6: "Residual field-level failures anywhere in the pipeline — a missing required field, an enum value outside its allowed set, a range violation such as a quantity or amount below its floor — are rejected with `ERR_VALIDATION` (HTTP 422)."
        PRD §3.3: "Employees join the program when a `CommunityEngagementManager` registers a volunteer profile with `full_name`, `email`, `department`, and `date_of_birth` (an ISO 8601 date), plus optional `skills` (skill tags, defaulting to empty), `dietary_tags`, and `is_staff_lead`."

        Design: Corner/entities/volunteer_missing_required_email_rejected
        """
        resp = api.create_employee_volunteer(
            {"full_name": "No Email", "department": "Eng", "date_of_birth": "1990-01-01"},
            cem_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _, meta = validate_paginated(api.list_employee_volunteers(any_headers, params={}))
        assert meta["total_count"] == 0

    def test_duplicate_email_rejected(self, api, cem_headers):
        """PRD §3.3: "The `email` must be unique across all employee volunteers — a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409)."

        Design: Corner/validations/duplicate_email_rejected
        """
        first = api.create_employee_volunteer(
            {"full_name": "Vol One", "email": "v1@corp.com", "department": "Eng", "date_of_birth": "1990-01-01"},
            cem_headers,
        )
        validate_success(first, 201)
        dup = api.create_employee_volunteer(
            {"full_name": "Vol Uno", "email": "v1@corp.com", "department": "Sales", "date_of_birth": "1991-01-01"},
            cem_headers,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestCloseGate:
    def test_close_blocked_until_sponsorships_terminal(self, api, cem_headers):
        """PRD §3.7: "Closing is the financial gate: the event must be `COMPLETED`, and every sponsorship of the event must have reached a terminal state — `SETTLED` or `WITHDRAWN`; outstanding pledges or commitments reject the close with `ERR_UNRESOLVED_SPONSORSHIPS`."
        PRD §3.8: "for `FLAT`, the base is `rate_cents`; for `PER_CHECK_IN`, the base is `rate_cents` multiplied by the event's `checked_in_headcount` — actual check-ins only, so a no-show who was counted in the provisional estimate drops out; for `PER_VERIFIED_HOUR`, the base is `rate_cents` multiplied by the event's `total_verified_hours`, rounded half-up to whole cents. The settled amount is again the smaller of the base and `effective_cap_cents`."

        Design: Corner/validations/close_blocked_until_sponsorships_terminal
        """
        sc = setup_in_progress_event(event_name="Day 25", budget_cents=500000)
        event_id = sc["event"]["id"]
        sponsorship = create_sponsorship(
            event_id, match_type="FLAT", rate_cents=5000, pledge_cap_cents=9000
        )
        commit_sponsorship(sponsorship["id"])
        complete_event(event_id)

        # A COMMITTED sponsorship is not terminal: close is rejected
        denied = api.close_event(event_id, cem_headers)
        validate_error(denied, ApiErrorId.ERR_UNRESOLVED_SPONSORSHIPS)
        assert get_event(event_id)["status"] == "COMPLETED"

        # Settle (FLAT: min(5000, 9000)), then close succeeds
        settled = validate_success(api.settle_sponsorship(sponsorship["id"], FC), 200)
        assert settled["settled_amount_cents"] == 5000
        closed = validate_success(api.close_event(event_id, cem_headers), 200)
        assert closed["status"] == "CLOSED"

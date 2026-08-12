"""Application lifecycle basics, authentication/authorization, and ownership
rules (PRD §2.1, §2.6, §2.7, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_application,
    begin_review,
    create_application,
    create_application_payload,
    create_org,
    create_restriction_payload,
    create_title,
    create_title_and_org,
    create_title_payload,
    current_application_version,
    make_applicant_headers,
    reset_clock,
    submit_application,
    validate_error,
    validate_success,
)


class TestApplicationInitialState:
    def test_application_initial_state_is_draft(
        self, api, rights_admin_headers, licensing_officer_headers
    ):
        """PRD §3.3: "A draft starts in `status` `DRAFT` with `review_round` 0."

        Design: Corner/state_machines/application_initial_state_is_draft
        """
        reset_clock()
        title, org, applicant = create_title_and_org()
        app = create_application(title["id"], org["id"], applicant)
        assert app["status"] == "DRAFT"
        assert app["review_round"] == 0


class TestApplicationInvalidTransitions:
    def test_invalid_transition_approve_from_draft(
        self, api, rights_admin_headers, licensing_officer_headers
    ):
        """PRD §3.3: "Approval is the high-stakes transition" — it is defined
        only from `UNDER_REVIEW` ("Approval then evaluates three availability
        preconditions" after the officer has begun review).
        PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/invalid_transition_approve_from_draft
        """
        reset_clock()
        title, org, applicant = create_title_and_org()
        app = create_application(title["id"], org["id"], applicant)
        resp = api.approve_application(
            app["id"],
            {"expected_application_version": app["version"]},
            licensing_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_reject_from_terminal_state_returns_invalid_state(
        self, api, rights_admin_headers, licensing_officer_headers
    ):
        """PRD §3.3: "Rejection is the simpler sibling: from `UNDER_REVIEW`, an
        officer rejects the application ... the application's `status` becomes
        `REJECTED`". A second reject no longer starts from `UNDER_REVIEW`.
        PRD §2.7: "then state-machine from-state checks (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/reject_from_terminal_state_returns_invalid_state
        """
        reset_clock()
        title, org, applicant = create_title_and_org()
        app = create_application(title["id"], org["id"], applicant)
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        rejected = validate_success(
            api.reject_application(
                app["id"], {"reason": "Insufficient info"}, licensing_officer_headers
            ),
            expected_status=200,
        )
        assert rejected["status"] == "REJECTED"
        resp = api.reject_application(
            app["id"], {"reason": "Again"}, licensing_officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestAuthentication:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "a request missing either header, or presenting a role
        string the server does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        reset_clock()
        resp = api.list_titles({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_wrong_role_cannot_create_title(
        self, api, rights_admin_headers, materials_clerk_headers
    ):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /licensing/titles is authorized for RightsAdmin only.

        Design: Corner/validations/wrong_role_cannot_create_title
        """
        reset_clock()
        resp = api.create_title(create_title_payload(), materials_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_applicant_cannot_approve_own_application(
        self, api, rights_admin_headers, licensing_officer_headers
    ):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /licensing/applications/{application_id}/approve is
        authorized for LicensingOfficer only.

        Design: Corner/rbac/applicant_cannot_approve_own_application
        """
        reset_clock()
        title, org, applicant = create_title_and_org()
        app = create_application(title["id"], org["id"], applicant)
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        version = current_application_version(app["id"])
        resp = api.approve_application(
            app["id"], {"expected_application_version": version}, applicant
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_finance_officer_cannot_create_rental(
        self, api, rights_admin_headers, finance_officer_headers
    ):
        """PRD §2.1: "A request whose role is recognized but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /licensing/rentals is authorized for MaterialsClerk only.

        Design: Corner/rbac/finance_officer_cannot_create_rental
        """
        from test_helpers import setup_active_agreement, create_rental_payload

        ctx = setup_active_agreement()
        resp = api.create_rental(
            create_rental_payload(ctx["agreement"]["id"]), finance_officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestOwnershipEnforcement:
    def test_applicant_cannot_act_on_other_orgs_application(
        self, api, rights_admin_headers
    ):
        """PRD §2.1: "When an entity-backed caller attempts to act on a resource
        owned by a different organization — for example, an `Applicant`
        submitting a `LicenseApplication` whose `organization_id` does not match
        the `X-User-ID` header — the request is rejected with
        `ERR_FORBIDDEN_OWNER_MISMATCH` (HTTP 403)."

        Design: Corner/validations/applicant_cannot_act_on_other_orgs_application
        """
        reset_clock()
        title = create_title()
        org1 = create_org(legal_name="Org One")
        org2 = create_org(legal_name="Org Two")
        app = create_application(
            title["id"], org1["id"], make_applicant_headers(org1["id"])
        )
        resp = api.submit_application(
            app["id"], make_applicant_headers(org2["id"])
        )
        validate_error(
            resp, ApiErrorId.ERR_FORBIDDEN_OWNER_MISMATCH, expected_status=403
        )


class TestTemporalValidation:
    def test_window_start_must_precede_window_end(self, api, rights_admin_headers):
        """PRD §2.4: "A range whose `window_start` is not strictly before its
        `window_end` is malformed and is rejected with `ERR_INVALID_TEMPORAL`
        (HTTP 400)".

        Design: Corner/validations/window_start_must_precede_window_end
        """
        reset_clock()
        title = create_title()
        payload = create_restriction_payload(
            window_start="2026-06-10T00:00:00Z",
            window_end="2026-06-01T00:00:00Z",
        )
        resp = api.create_restriction(title["id"], payload, rights_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_TEMPORAL, expected_status=400)


class TestApplicationReviewCycle:
    def test_review_round_increments_each_cycle(
        self, api, rights_admin_headers, licensing_officer_headers
    ):
        """PRD §3.3: "A `LicensingOfficer` picks up a `SUBMITTED` application by
        moving it to `UNDER_REVIEW`. That action increments `review_round` by
        one and recomputes the `determined_classification` from the
        classification rule."

        Design: Difficulty/non_linear_state_machine/application_review_cycle_loops_back_to_submitted
        """
        reset_clock()
        title, org, applicant = create_title_and_org()
        app = create_application(title["id"], org["id"], applicant)
        submit_application(app["id"], applicant)
        first = begin_review(app["id"])
        assert first["review_round"] == 1
        validate_success(
            api.return_for_info_application(
                app["id"], {"notes": "Need venue contract"}, licensing_officer_headers
            ),
            expected_status=200,
        )
        submit_application(app["id"], applicant)
        second = begin_review(app["id"])
        assert second["review_round"] == 2
        assert second["status"] == "UNDER_REVIEW"

    def test_returned_application_is_editable_and_resubmittable(
        self, api, rights_admin_headers, licensing_officer_headers
    ):
        """PRD §3.3: "The applicant may edit a returned application — the same
        set of fields as in draft — and resubmit it; resubmission moves the
        application back to `SUBMITTED`, refreshes `submitted_at`, and
        recomputes the `AvailabilitySnapshot`."

        Design: Difficulty/non_linear_state_machine/application_review_cycle_loops_back_to_submitted
        """
        reset_clock()
        title, org, applicant = create_title_and_org()
        app = create_application(title["id"], org["id"], applicant)
        submit_application(app["id"], applicant)
        begin_review(app["id"])
        returned = validate_success(
            api.return_for_info_application(
                app["id"], {"notes": "Need venue contract"}, licensing_officer_headers
            ),
            expected_status=200,
        )
        assert returned["status"] == "RETURNED_FOR_INFO"
        edited = validate_success(
            api.patch_application(
                app["id"], {"venue_seating_capacity": 120}, applicant
            ),
            expected_status=200,
        )
        assert edited["venue_seating_capacity"] == 120
        resubmitted = validate_success(
            api.submit_application(app["id"], applicant), expected_status=200
        )
        assert resubmitted["status"] == "SUBMITTED"

"""Application drafting, submission, scope review, and duplicate guards."""
from test_helpers import (
    ApiErrorId,
    assert_application,
    assert_audit,
    assert_instant_equal,
    client_headers,
    create_application_payload,
    get_application,
    application_audits,
    make_application,
    make_client,
    make_scheme,
    reject_application,
    setup_accepted_chain,
    setup_granted_chain,
    submit_application,
    validate_error,
    validate_success,
)


class TestApplicationCreation:
    def test_application_created_in_draft_initial_state(self, api):
        """PRD §3.3: "A new application starts in `DRAFT`, with `submitted_at`
        and `reviewed_at` null and `provisional_fee_quote` not yet computed."

        Design: Corner/state_machines/application_created_in_draft_initial_state
        """
        scheme = make_scheme()
        client = make_client()
        resp = api.create_application(
            create_application_payload(scheme["id"]), client_headers(client))
        data = validate_success(resp, 201)
        assert_application(data)
        assert data["status"] == "DRAFT"
        assert data["provisional_fee_quote"] is None
        assert data["submitted_at"] is None
        assert data["reviewed_at"] is None
        assert data["client_id"] == client["id"]

    def test_application_creation_missing_scope_text_returns_400(self, api):
        """PRD §3.3: "Malformed payloads — a missing required field, an empty
        scope array, an enum outside its allowed set — are rejected with
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/application_creation_missing_scope_text_returns_400
        """
        scheme = make_scheme()
        client = make_client()
        payload = create_application_payload(scheme["id"])
        del payload["scope_text"]
        resp = api.create_application(payload, client_headers(client))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_application_rejects_invalid_risk_tier_returns_400(self, api):
        """PRD §3.3: "Each entry of `product_categories` is an object pairing
        a `category_code` with a `risk_tier` of `STANDARD` or `HIGH`"
        PRD §3.3: "Malformed payloads — a missing required field, an empty
        scope array, an enum outside its allowed set — are rejected with
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/application_rejects_invalid_risk_tier_returns_400
        """
        scheme = make_scheme()
        client = make_client()
        payload = create_application_payload(
            scheme["id"],
            product_categories=[{"category_code": "BAKERY",
                                 "risk_tier": "EXTREME"}])
        resp = api.create_application(payload, client_headers(client))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_application_with_unsupported_category_returns_422(self, api):
        """PRD §3.3: "every `category_code` must appear in the scheme's
        `supported_category_codes` — a request naming an unsupported category
        is rejected with `ERR_SCOPE_CATEGORY_UNSUPPORTED` (422)."

        Design: Corner/validations/application_with_unsupported_category_returns_422
        """
        scheme = make_scheme()
        client = make_client()
        payload = create_application_payload(
            scheme["id"], scope_text="fish canning",
            product_categories=[{"category_code": "SEAFOOD",
                                 "risk_tier": "STANDARD"}])
        resp = api.create_application(payload, client_headers(client))
        validate_error(resp, ApiErrorId.ERR_SCOPE_CATEGORY_UNSUPPORTED, 422)

    def test_duplicate_open_application_rejected(self, api):
        """PRD §3.3: "Only one open application may exist per client and
        scheme: if the same client already has an application for the same
        scheme in `DRAFT` or `SUBMITTED`, creation is rejected with
        `ERR_DUPLICATE_APPLICATION` (409)."

        Design: Corner/validations/duplicate_open_application_rejected
        """
        scheme = make_scheme()
        client = make_client()
        make_application(client, scheme, scope_text="baked goods")
        resp = api.create_application(
            create_application_payload(
                scheme["id"], site_name="Site B", scope_text="second site",
                product_categories=[{"category_code": "DAIRY",
                                     "risk_tier": "STANDARD"}]),
            client_headers(client))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPLICATION, 409)


class TestApplicationTransitions:
    def test_application_submit_moves_draft_to_submitted(self, api):
        """PRD §3.3: "Submitting moves the application from `DRAFT` to
        `SUBMITTED`."
        PRD §3.3: "Submission stamps `submitted_at` with the current logical
        time and increments the application's `version`."
        PRD §2.6: "At startup the logical clock reads 2026-08-01T00:00:00Z."

        Design: Corner/state_machines/application_submit_moves_draft_to_submitted
        """
        scheme = make_scheme()
        client = make_client()
        app = make_application(client, scheme)
        version_before = app["version"]
        resp = api.submit_application(app["id"], client_headers(client))
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED"
        assert_instant_equal(data["submitted_at"], "2026-08-01T00:00:00Z")
        assert data["version"] == version_before + 1

    def test_application_resubmit_rejected(self, api):
        """PRD §3.3: "the application must actually be in `DRAFT`, otherwise
        `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/application_resubmit_rejected
        """
        scheme = make_scheme()
        client = make_client()
        app = submit_application(make_application(client, scheme), client)
        resp = api.submit_application(app["id"], client_headers(client))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        assert get_application(app["id"])["status"] == "SUBMITTED"

    def test_application_review_from_draft_rejected(self, api,
                                                    scheme_admin_headers):
        """PRD §3.3: "Rejection requires the application to be `SUBMITTED`
        (otherwise `ERR_INVALID_APPLICATION_STATE`)"
        PRD §3.3: "Acceptance applies three checks in addition: the
        application must be `SUBMITTED`"

        Design: Corner/state_machines/application_review_from_draft_rejected
        """
        scheme = make_scheme()
        client = make_client()
        app = make_application(client, scheme)
        resp = api.review_application(app["id"], {"outcome": "ACCEPTED"},
                                      scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        # Acceptance is what brings the first audit into existence; a rejected
        # review from DRAFT creates none.
        assert application_audits(app["id"]) == []

    def test_rejected_application_terminal_lockdown(self, api,
                                                    scheme_admin_headers):
        """PRD §3.3: "Rejection requires the application to be `SUBMITTED`
        (otherwise `ERR_INVALID_APPLICATION_STATE`) and moves it to the
        terminal `REJECTED` state, stamping `reviewed_at`, storing the supplied
        `rejection_reason`, and incrementing `version`."

        Design: Corner/state_machines/rejected_application_terminal_lockdown
        """
        scheme = make_scheme()
        client = make_client()
        app = make_application(client, scheme)
        app = submit_application(app, client)
        app = reject_application(app)
        assert app["status"] == "REJECTED"

        resp = api.submit_application(app["id"], client_headers(client))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        resp = api.review_application(app["id"], {"outcome": "ACCEPTED"},
                                      scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE, 409)
        assert get_application(app["id"])["status"] == "REJECTED"

    def test_audit_sequence_number_and_window_system_assigned(self, api):
        """PRD §3.3: "Acceptance stamps `reviewed_at` with the current logical
        time, computes the `provisional_fee_quote` per the quote variant in
        §2.9, increments `version`, and brings the first audit into existence:
        its `sequence_number` is 1, its `audit_type` is `INITIAL`, its status
        is `SCHEDULED`, its `window_start` is fourteen days after
        `reviewed_at`, and its `window_end` is the scheme's
        `announced_max_window_days` days after that start."

        Design: Corner/entities/audit_sequence_number_and_window_system_assigned
        """
        chain = setup_accepted_chain()
        assert len(application_audits(chain.app["id"])) == 1
        audit = chain.audit
        assert_audit(audit)
        assert audit["sequence_number"] == 1
        assert audit["audit_type"] == "INITIAL"
        assert audit["status"] == "SCHEDULED"
        assert audit["auditor_id"] is None
        # Acceptance ran at the default logical clock 2026-08-01T00:00:00Z.
        assert_instant_equal(audit["window_start"], "2026-08-15T00:00:00Z")
        assert_instant_equal(audit["window_end"], "2026-09-14T00:00:00Z")

    def test_duplicate_active_certificate_scope_rejected(self, api,
                                                         scheme_admin_headers):
        """PRD §3.3: "no certificate for the same client and scheme may exist
        in `ACTIVE` or `SUSPENDED` (`ERR_DUPLICATE_CERTIFICATION_SCOPE`, 409)."

        Design: Corner/validations/duplicate_active_certificate_scope_rejected
        """
        chain = setup_granted_chain()
        assert chain.certificate["status"] == "ACTIVE"
        # The first application is ACCEPTED (not open), so a second create is
        # allowed; acceptance is what must fail.
        app2 = make_application(
            chain.client, chain.scheme, site_name="Site A expansion",
            scope_text="adding dairy",
            categories=[{"category_code": "DAIRY", "risk_tier": "HIGH"}])
        app2 = submit_application(app2, chain.client)
        resp = api.review_application(app2["id"], {"outcome": "ACCEPTED"},
                                      scheme_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CERTIFICATION_SCOPE, 409)
        assert get_application(app2["id"])["status"] == "SUBMITTED"

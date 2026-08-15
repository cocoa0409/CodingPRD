"""Response envelope, authentication, role authorization, and ownership (PRD §2.1, §2.2, §2.7)."""
from test_helpers import (
    ADVISOR,
    ADMIN,
    BOGUS_UUID,
    COMPLIANCE,
    ApiErrorId,
    assert_iso_instant_equal,
    build_user_headers,
    create_active_client,
    create_benchmark,
    create_client_payload,
    create_ips_payload,
    create_security_payload,
    deposit,
    get_success_data,
    make_client_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
    setup_active_portfolio,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestErrorEnvelope:
    def test_error_envelope_shape_for_400(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" — "The `error_id` is a unique,
        machine-readable string that identifies the specific error." and "The
        `message` provides a human-readable explanation of what went wrong."
        PRD §2.7: "required fields present; types valid; enum values within
        their declared sets; ranges enforced (risk scores between 1 and 100
        inclusive; `target_pct` greater than 0 and at most 100; `band_pct`
        greater than 0 and at most 50; quantities at least 1 on intake;
        `amount_cents` greater than 0; price inputs at least 1;
        `review_cadence_months` between 1 and 24 inclusive; dates in
        `YYYY-MM-DD` form; datetimes in ISO 8601 UTC); a duplicate
        `asset_class` inside a `targets` array; unknown request fields — all
        rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/errors/error_envelope_shape_for_4xx
        """
        resp = api.create_security(
            create_security_payload(ticker="BAD", asset_class="EQUITY",
                                    initial_price_cents=100),
            COMPLIANCE,
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert err.get("message"), "error payload carries a human-readable message"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]

    def test_error_envelope_shape_for_422(self, api):
        """PRD §2.7: "ids carried in the body (`client_id`, `benchmark_id`,
        `portfolio_id`, `security_id`, `ips_id`, `proposed_benchmark_id`,
        `ratified_minute_id`, and every element of `amendment_refs`) must
        resolve to existing resources, else `ERR_INVALID_REFERENCE` (HTTP 422)."

        Design: Corner/errors/error_envelope_shape_for_4xx
        """
        create_active_client(full_name="Env", risk_tolerance_score=50)
        resp = api.create_ips(
            create_ips_payload(BOGUS_UUID, BOGUS_UUID, objective_text="X",
                               risk_tolerance_score=50),
            ADVISOR,
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)
        assert err.get("message")
        assert resp.json()["response_type"] == "error"


class TestNotFoundAndPriority:
    def test_get_nonexistent_resource_returns_not_found(self, api):
        """PRD §2.7: "path identifiers are resolved strictly left to right; the
        first identifier that does not resolve yields `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_nonexistent_resource_returns_not_found
        """
        resp = api.get_portfolio(BOGUS_UUID, ADVISOR)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err.get("message"), "error payload carries a message"
        assert resp.json()["response_type"] == "error"

    def test_shape_validation_fires_before_path_existence(self, api):
        """PRD §2.7: "Checks run in a fixed priority order, and when several
        checks would fail, the request is rejected with the error from the
        earliest category" — request shape (4) precedes path existence (5).

        Design: Corner/validations/shape_validation_fires_before_path_existence
        """
        resp = api.reprice_security(BOGUS_UUID, 0, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_body_foreign_key_reference_must_exist(self, api):
        """PRD §2.7: "ids carried in the body (`client_id`, `benchmark_id`,
        `portfolio_id`, `security_id`, `ips_id`, `proposed_benchmark_id`,
        `ratified_minute_id`, and every element of `amendment_refs`) must
        resolve to existing resources, else `ERR_INVALID_REFERENCE` (HTTP 422)."

        Design: Corner/validations/body_foreign_key_reference_must_exist
        """
        fx = setup_active_portfolio(targets=[
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
        ])
        resp1 = api.create_position(
            {"portfolio_id": fx["portfolio"]["id"], "security_id": BOGUS_UUID,
             "quantity": 1, "opening_cost_basis_cents": 100},
            ADVISOR,
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_REFERENCE)
        resp2 = api.create_ips(
            create_ips_payload(fx["client"]["id"], BOGUS_UUID, objective_text="Y",
                               risk_tolerance_score=50),
            ADVISOR,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REFERENCE)


class TestAuthentication:
    def test_rbac_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing or blank header, or whose
        `X-User-Role` is not one of these six spellings, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/rbac_missing_auth_headers_unauthenticated
        """
        payload = create_client_payload(full_name="X", risk_tolerance_score=50)
        # No headers at all.
        validate_error(api.create_client(payload, {}), ApiErrorId.ERR_UNAUTHENTICATED)
        # Declared role but no X-User-ID.
        validate_error(api.create_client(payload, {"X-User-Role": "Advisor"}),
                       ApiErrorId.ERR_UNAUTHENTICATED)
        # Undeclared role spelling.
        validate_error(api.create_client(payload, build_user_headers("u-1", "SuperUser")),
                       ApiErrorId.ERR_UNAUTHENTICATED)


class TestForbiddenRole:
    def test_rbac_advisor_cannot_run_compliance_operations(self, api):
        """PRD §2.1: "A request whose role is valid but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." — role authorization (priority 2)
        precedes path existence (priority 5), so even bogus ids yield 403.

        Design: Corner/rbac/rbac_advisor_cannot_run_compliance_operations
        """
        validate_error(api.reprice_security(BOGUS_UUID, 100, ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(api.approve_proposal(BOGUS_UUID, ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(api.void_trade(BOGUS_UUID, ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(api.run_compliance_checkpoint(ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(api.freeze_portfolio(BOGUS_UUID, ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_compliance_cannot_run_advisory_or_committee_operations(self, api):
        """PRD §2.1: "A request whose role is valid but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/rbac_compliance_cannot_run_advisory_or_committee_operations
        """
        validate_error(
            api.create_client(create_client_payload(full_name="X"), COMPLIANCE),
            ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(
            api.create_portfolio({"client_id": BOGUS_UUID, "name": "P",
                                  "tax_status": "TAXABLE"}, COMPLIANCE),
            ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(
            api.vote_ips_amendment(BOGUS_UUID, "APPROVE", COMPLIANCE),
            ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(
            api.model_withdrawal(BOGUS_UUID, COMPLIANCE),
            ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_committee_roles_are_strictly_split(self, api):
        """PRD §2.1: "A request whose role is valid but not among the roles
        authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)." — the chair may not vote or record
        minutes; members may not ratify or finalize (PRD §4 role columns).

        Design: Corner/rbac/rbac_committee_roles_are_strictly_split
        """
        bench = create_benchmark(name="B")
        chair = make_committee_chair_headers("chair-9")
        member = make_committee_member_headers("cm-9")
        validate_error(api.vote_ips_amendment(BOGUS_UUID, "APPROVE", chair),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(
            api.create_committee_minute(
                {"meeting_date": "2026-08-01", "amendment_refs": [],
                 "decisions_text": "X"}, chair),
            ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(api.ratify_committee_minute(BOGUS_UUID, member),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(
            api.finalize_ips_amendment(BOGUS_UUID, bench["id"], bench["version"],
                                       member),
            ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_rbac_platform_admin_confined_to_clock(self, api):
        """PRD §2.5: "A `PlatformAdmin`-only capability sets the clock: the
        request carries `to_iso8601`, the target instant, and the response
        echoes the new reading as `current_utc`. This is the only operation
        `PlatformAdmin` may perform."

        Design: Corner/rbac/rbac_platform_admin_confined_to_clock
        """
        validate_error(
            api.create_client(create_client_payload(full_name="X"), ADMIN),
            ApiErrorId.ERR_FORBIDDEN_ROLE)
        ok = validate_success(api.set_clock("2026-08-02T00:00:00Z", ADMIN))
        assert_iso_instant_equal(ok["current_utc"], "2026-08-02T00:00:00Z")
        validate_error(api.set_clock("2026-08-03T00:00:00Z", ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestClientOwnership:
    def test_rbac_client_ownership_enforced_by_user_id(self, api):
        """PRD §2.1: "ownership checks on any resource that belongs to a client
        — the client record itself, its IPS records and allocation targets, its
        portfolios, positions, withdrawal requests, performance reports, and
        cash-flow events — compare the resource's owning-client foreign key to
        `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."

        Design: Corner/rbac/rbac_client_ownership_enforced_by_user_id
        """
        c1 = create_active_client(full_name="C1", risk_tolerance_score=50)
        c2 = create_active_client(full_name="C2", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(c1["id"], bench["id"], objective_text="X",
                               risk_tolerance_score=50), ADVISOR))
        # C2 reading C1's record: ownership mismatch.
        validate_error(api.get_client(c1["id"], make_client_headers(c2["id"])),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        # C1 reading itself.
        assert validate_success(api.get_client(c1["id"], make_client_headers(c1["id"])))[
            "id"] == c1["id"]
        # C2 signing C1's IPS: ownership (priority 3) precedes the state check.
        validate_error(api.client_sign_ips(ips["id"], make_client_headers(c2["id"])),
                       ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        # C1 signing its own DRAFT IPS passes ownership but fails the state gate.
        validate_error(api.client_sign_ips(ips["id"], make_client_headers(c1["id"])),
                       ApiErrorId.ERR_IPS_INVALID_STATE)

    def test_rbac_client_scoped_lists(self, api):
        """PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of
        the acting `Client` entity"; PRD §3.2: "a `Client` sees only its own
        household's rows."

        Design: Corner/rbac/rbac_client_scoped_lists
        """
        c1 = create_active_client(full_name="L1", risk_tolerance_score=50)
        c2 = create_active_client(full_name="L2", risk_tolerance_score=50)
        get_success_data(api.create_portfolio(
            {"client_id": c1["id"], "name": "P", "tax_status": "TAXABLE"}, ADVISOR))
        rows, meta = validate_paginated(
            api.list_portfolios(make_client_headers(c1["id"])))
        assert len(rows) == 1, "Client list is scoped to its own portfolios"
        assert rows[0]["client_id"] == c1["id"]
        rows2, _ = validate_paginated(
            api.list_portfolios(make_client_headers(c2["id"])))
        assert rows2 == [], "the other household sees none of c1's portfolios"

    def test_rbac_withdrawal_create_shared_but_cancel_client_only(self, api):
        """PRD §3.6: "Either an `Advisor` or the owning `Client` creates the
        request with a `portfolio_id`, an `amount_cents` greater than 0, and a
        `funding_mode` of `CASH_FIRST`, `PRO_RATA`, or `TAX_AWARE`, which
        selects the impact-model variant used later; a client creating against
        another household's portfolio is rejected with
        `ERR_NOT_RESOURCE_OWNER`."
        PRD §3.6: "The owning `Client` may cancel from `SUBMITTED` or `MODELED`
        — ownership-checked against the portfolio's `client_id`, else
        `ERR_NOT_RESOURCE_OWNER` — and canceling a modeled request likewise
        clears the model."

        Design: Corner/rbac/rbac_withdrawal_create_shared_but_cancel_client_only
        """
        fx = setup_active_portfolio(targets=[
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
        ])
        c1 = fx["client"]
        c2 = create_active_client(full_name="W2", risk_tolerance_score=50)
        deposit(fx["portfolio"]["id"], 100000)
        # Create by a non-owning client: ownership rejection.
        validate_error(
            api.create_withdrawal_request(
                {"portfolio_id": fx["portfolio"]["id"], "amount_cents": 1000,
                 "funding_mode": "CASH_FIRST"}, make_client_headers(c2["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        # Create by the Advisor (shared operation).
        w = validate_success(api.create_withdrawal_request(
            {"portfolio_id": fx["portfolio"]["id"], "amount_cents": 1000,
             "funding_mode": "CASH_FIRST"}, ADVISOR), 201)
        assert w["status"] == "SUBMITTED"
        # Cancel is Client-exclusive (PRD §4 lists only Client).
        validate_error(api.cancel_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        # The owning client cancels successfully.
        cancelled = validate_success(
            api.cancel_withdrawal(w["id"], make_client_headers(c1["id"])))
        assert cancelled["status"] == "CANCELLED"

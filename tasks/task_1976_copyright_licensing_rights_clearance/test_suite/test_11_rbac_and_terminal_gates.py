"""RBAC denials, owner-only withdrawal, terminal-state retirement gates, embargo."""
from test_helpers import (
    ApiErrorId,
    advance_request,
    assert_same_instant,
    create_asset,
    create_clearance_request,
    create_clearance_request_payload,
    get_success_data,
    grant_license,
    make_curator_headers,
    make_ingest_headers,
    make_negotiator_headers,
    make_officer_headers,
    make_payer_headers,
    make_requester_headers,
    post_round,
    setup_approved_request,
    setup_holder_asset,
    setup_license,
    setup_request_in_negotiating,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRbacAuthentication:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request that is missing `X-User-Role`, carries an
        undeclared role value, or — for an entity-backed role — is missing
        `X-User-ID` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        # Headers missing X-User-Role entirely.
        headers = {"X-User-ID": "u_no_role", "Content-Type": "application/json"}
        resp = api.list_assets(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbacDenials:
    def test_requester_cannot_grant(self, api):
        """PRD §4: "POST /rights/clearance-requests/{id}/grant ... Authorized
        Role(s): ClearanceOfficer"
        PRD §2.1: "A request whose declared role is not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/rbac_requester_cannot_grant
        """
        holder, asset, req, _rid = setup_approved_request(
            offered_fee_cents=200000,
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        requester = make_requester_headers("req_rb_1")
        err = api.grant_license(req["id"], 200000, requester)
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_negotiator_cannot_post_payment_payer_cannot_post_round(self, api):
        """PRD §4: "POST /rights/licenses/{id}/payments ... Authorized
        Role(s): FinancePayer" and "POST
        /rights/clearance-requests/{id}/rounds ... Authorized Role(s):
        Negotiator, RightsHolderRep"
        PRD §2.1: "A request whose declared role is not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/rbac_negotiator_cannot_post_payments
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
        )
        # Negotiator trying to post a payment.
        negotiator = make_negotiator_headers("neg_rb_1")
        err1 = api.post_payment(
            lic["id"],
            {"amount_cents": 200000, "expected_license_version": lic["version"]},
            negotiator,
        )
        validate_error(err1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # Build a second request in NEGOTIATING and have a FinancePayer try to post a round.
        req2, _ = create_clearance_request(
            asset["id"],
            media="STREAMING",
            territory="LATAM",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=1,
        )
        req2 = advance_request(req2["id"], req2["version"])
        req2 = advance_request(req2["id"], req2["version"])
        payer = make_payer_headers("fin_rb_1")
        err2 = api.post_round(req2["id"], {"offered_fee_cents": 50000}, payer)
        validate_error(err2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_ingestion_agent_cannot_file_takedown(self, api):
        """PRD §4: "POST /rights/assets/{id}/takedown-notices ... Authorized
        Role(s): AssetCurator"
        PRD §2.1: "A request whose declared role is not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/roles/rbac_ingestion_cannot_file_takedown
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        ingest = make_ingest_headers("ing_rb_1")
        err = api.file_takedown_notice(asset["id"], {"claimant_name": "Wrong Role"}, ingest)
        validate_error(err, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnerOnlyWithdraw:
    def test_non_owner_withdraw_forbidden(self, api):
        """PRD §3.2: "Withdrawal is the requester's own exit: the calling
        header must equal the recorded `requester_id` — another user's
        attempt is `ERR_FORBIDDEN_OWNER_ONLY`"

        Design: Corner/errors/error_forbidden_owner_only_on_withdraw
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=1,
            requester_user_id="req_c_30",
        )
        other = make_requester_headers("req_c_31")
        err = api.withdraw_clearance_request(req["id"], other)
        validate_error(err, ApiErrorId.ERR_FORBIDDEN_OWNER_ONLY)


class TestAssetRetirement:
    def test_retire_blocked_by_live_license_then_succeeds_after_expiry(self, api):
        """PRD §3.9: "No license on the asset may stand in `ACTIVE` or
        `SUSPENDED` lifecycle — live licenses block retirement with
        `ERR_ASSET_HAS_LIVE_LICENSES`."

        Design: Corner/state_machines/asset_retire_terminal_and_blocked_by_live_license
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
        )
        curator = make_curator_headers("cur_rt_1")
        err1 = api.retire_asset(asset["id"], curator)
        validate_error(err1, ApiErrorId.ERR_ASSET_HAS_LIVE_LICENSES)

        # Expire the license.
        api.set_clock("2026-08-21T00:00:00Z", curator)
        ok = api.retire_asset(asset["id"], curator)
        retired = get_success_data(ok)
        assert retired["posture"] == "RETIRED"

    def test_second_retire_already_terminal(self, api):
        """PRD §3.9: "The asset must not already be `RETIRED` — a second
        retirement is `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/asset_retire_terminal_and_blocked_by_live_license
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-08-20T00:00:00Z",
        )
        curator = make_curator_headers("cur_rt_2")
        api.set_clock("2026-08-21T00:00:00Z", curator)
        ok = api.retire_asset(asset["id"], curator)
        get_success_data(ok)
        err2 = api.retire_asset(asset["id"], curator)
        validate_error(err2, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestRetireBlockedByOpenRequests:
    def test_retire_blocked_by_submitted_request(self, api):
        """PRD §3.9: "no clearance request may still be open — a request in
        `SUBMITTED`, `HOLDER_REVIEW`, `NEGOTIATING`, or `APPROVED` blocks
        with `ERR_ASSET_HAS_OPEN_REQUESTS`."

        Design: Corner/errors/error_asset_has_open_requests_blocks_retire
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, _rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=1,
        )
        curator = make_curator_headers("cur_or_1")
        err = api.retire_asset(asset["id"], curator)
        validate_error(err, ApiErrorId.ERR_ASSET_HAS_OPEN_REQUESTS)


class TestEmbargoGate:
    def test_embargo_boundary_minus_one_second_fails_exact_passes(self, api):
        """PRD §3.2: "The embargo gate applies here, at creation: if the
        asset carries an `embargo_until`, the `use_start_at` must be on or
        after the instant thirty days past it; equality passes, anything
        earlier is rejected with `ERR_EMBARGO_ACTIVE`."

        Design: Difficulty/boundary_precision_check/embargo_boundary_exact_pass_minus_one_second_fails
        """
        holder, asset = setup_holder_asset(
            permitted_media=["PRINT"],
            embargo_until="2026-08-10T00:00:00Z",
            work_kind="LITERARY_EXCERPT",
        )
        requester = make_requester_headers("req_eb_1")
        # embargo_until 2026-08-10 + 30 days = 2026-09-09T00:00:00Z.
        err = api.create_clearance_request(
            asset["id"],
            {
                "media": "PRINT",
                "territory": "NA",
                "use_start_at": "2026-09-08T23:59:59Z",
                "use_end_at": "2026-12-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        validate_error(err, ApiErrorId.ERR_EMBARGO_ACTIVE)

        ok = api.create_clearance_request(
            asset["id"],
            {
                "media": "PRINT",
                "territory": "NA",
                "use_start_at": "2026-09-09T00:00:00Z",
                "use_end_at": "2026-12-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        ok_data = get_success_data(ok)
        assert ok_data["status"] == "SUBMITTED"

    def test_embargo_buffer_window_semantics_distinct_from_overlap(self, api):
        """PRD §3.2: "if the asset carries an `embargo_until`, the
        `use_start_at` must be on or after the instant thirty days past it;
        equality passes, anything earlier is rejected with
        `ERR_EMBARGO_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/embargo_buffer_window_vs_plain_term_overlap_semantics
        """
        holder, asset = setup_holder_asset(
            permitted_media=["PRINT"],
            embargo_until="2026-10-01T00:00:00Z",
            work_kind="LITERARY_EXCERPT",
        )
        requester = make_requester_headers("req_eb_2")
        # embargo_until 2026-10-01 + 30 days = 2026-10-31T00:00:00Z.
        err = api.create_clearance_request(
            asset["id"],
            {
                "media": "PRINT",
                "territory": "NA",
                "use_start_at": "2026-10-30T23:59:59Z",
                "use_end_at": "2026-12-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        validate_error(err, ApiErrorId.ERR_EMBARGO_ACTIVE)
        ok = api.create_clearance_request(
            asset["id"],
            {
                "media": "PRINT",
                "territory": "NA",
                "use_start_at": "2026-10-31T00:00:00Z",
                "use_end_at": "2026-12-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        ok_data = get_success_data(ok)
        assert ok_data["status"] == "SUBMITTED"


class TestRenewalAlertFiring:
    def test_alert_fires_at_term_end_minus_30d(self, api):
        """PRD §3.9: "Renewal alerts exist to warn the desk ahead of the end:
        created at grant in `SCHEDULED` with `fires_at` thirty days before
        `term_end_at`, an alert moves `SCHEDULED` → `FIRED` when the clock
        reaches `fires_at` while the license is still `ACTIVE`"

        Design: Corner/state_machines/renewal_alert_fires_at_term_end_minus_30d
        """
        # term_end 2026-11-10 → fires_at 2026-10-11T00:00:00Z.
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        curator = make_curator_headers("cur_ra_1")
        api.set_clock("2026-10-11T00:00:00Z", curator)
        alerts, _ = validate_paginated(
            api.list_license_renewal_alerts(lic["id"], make_officer_headers("off_ra_1"))
        )
        # PRD pins the instant (term_end - 30 days), not the fractional-digit
        # wire format of this non-audit datetime field.
        assert_same_instant(alerts[0]["fires_at"], "2026-10-11T00:00:00Z")
        assert alerts[0]["status"] == "FIRED"


class TestMediaGateAtAdvance:
    def test_media_not_permitted_rejected_at_first_advance(self, api):
        """PRD §3.2: "The media gate comes second: the request's `media`
        must be among the asset's `permitted_media`, else
        `ERR_MEDIA_NOT_PERMITTED`."

        Design: Corner/validations/media_not_in_permitted_set_rejected
        """
        holder, asset = setup_holder_asset(
            work_kind="SOUND_RECORDING", permitted_media=["RADIO"]
        )
        req, _rid = create_clearance_request(
            asset["id"],
            media="THEATRICAL",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=1,
        )
        officer = make_officer_headers("off_mg_1")
        err = api.advance_clearance_request(req["id"], req["version"], officer)
        validate_error(err, ApiErrorId.ERR_MEDIA_NOT_PERMITTED)


class TestPostureGateAtAdvance:
    def test_advance_blocked_when_asset_encumbered_by_pending_notice(self, api):
        """PRD §3.2: "The posture gate comes last — deliberately after the
        orphan gate, so the more specific diligence diagnosis wins over the
        blunter `ERR_ASSET_POSTURE_BLOCKED`, which fires whenever the posture
        is anything other than `CLEAR`."

        Design: Difficulty/cross_entity_state_dependency/clearance_advance_gated_by_asset_posture
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        # File a PENDING takedown on the asset (posture → ENCUMBERED).
        curator = make_curator_headers("cur_pg_1")
        api.file_takedown_notice(asset["id"], {"claimant_name": "Watcher"}, curator)
        # Identical request on the encumbered asset.
        req, _rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        officer = make_officer_headers("off_pg_1")
        err = api.advance_clearance_request(req["id"], req["version"], officer)
        validate_error(err, ApiErrorId.ERR_ASSET_POSTURE_BLOCKED)

    def test_advance_allowed_when_asset_clear(self, api):
        """PRD §3.2: "a `ClearanceOfficer` advances the request along
        `SUBMITTED` → `HOLDER_REVIEW` → `NEGOTIATING`, one step per call"

        Design: Difficulty/cross_entity_state_dependency/clearance_advance_gated_by_asset_posture
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, _rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        officer = make_officer_headers("off_pg_2")
        ok = api.advance_clearance_request(req["id"], req["version"], officer)
        ok_data = get_success_data(ok)
        assert ok_data["status"] == "HOLDER_REVIEW"

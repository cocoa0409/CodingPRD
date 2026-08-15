"""Validation priority pairs and OCC stale-version guards."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_request,
    create_clearance_request,
    get_success_data,
    grant_license,
    make_curator_headers,
    make_ingest_headers,
    make_negotiator_headers,
    make_officer_headers,
    make_payer_headers,
    post_round,
    post_round_raw,
    setup_approved_request,
    setup_holder_asset,
    setup_license,
    setup_request_in_negotiating,
    validate_error,
    validate_success,
)


class TestValidationPriorityPairs:
    def test_state_error_beats_fiscal_error_on_approved_request(self, api):
        """PRD §2.8: "every request is validated against the following ladder,
        evaluated top to bottom; a failure at any rung masks every rung below
        it." PRD §2.8 step 6: "Transition legality — the target resource is in
        a state from which the requested transition exists; failure is
        `ERR_INVALID_STATE` (HTTP 409)." PRD §2.8 step 11: "Fiscal rules —
        the most-favored-nation floor at acceptance, overpayment rejection,
        refund eligibility, segregation of duties on approval, payment, and
        certification; failures include `ERR_MFN_FLOOR_VIOLATION`"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_accept_on_approved_request
        """
        # Request already APPROVED (no round transition exists from APPROVED).
        holder, asset, req, _rid = setup_approved_request(
            offered_fee_cents=50000,
            media="SOCIAL",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-10-01T00:00:00Z",
            requested_units=10,
            holder_kind="PUBLISHER",
            mfn_floor_cents=5000,
            work_kind="STILL_IMAGE",
            permitted_media=["SOCIAL", "PRINT"],
        )
        # Post another accept=true round with a below-floor fee — both state
        # (APPROVED has no round transition) and fiscal (below MFN floor) fire.
        err = post_round_raw(
            req["id"],
            {"offered_fee_cents": 100, "accept": True},
            role="Negotiator",
            user_id="neg_prio_1",
        )
        validate_error(err, ApiErrorId.ERR_INVALID_STATE)

    def test_safety_error_beats_temporal_error_on_grant(self, api):
        """PRD §2.8 step 7: "DMCA and takedown safety gates — counter-notices
        inside their window, revocations backed by an upheld notice, new
        clearance work only on unblocked assets; failures include
        `ERR_COUNTER_WINDOW_LAPSED`, `ERR_NO_UPHELD_TAKEDOWN`, and
        `ERR_ASSET_POSTURE_BLOCKED` (HTTP 409)."
        PRD §2.8 step 9: "Temporal rules — use windows well-formed, embargo
        gates, usage inside the license term, holds unexpired at consumption,
        grant windows non-overlapping; failures include `ERR_INVALID_WINDOW`,
        `ERR_EMBARGO_ACTIVE`, `ERR_USAGE_OUTSIDE_TERM`, `ERR_HOLD_EXPIRED`,
        and `ERR_LICENSE_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_grant_during_lapsed_notice_with_overlap
        """
        # L1 ACTIVE: STREAMING/NA [2026-08-10, 2026-10-10).
        holder, asset, req1, lic1, _ = setup_license(
            fee_cents=200000,
            media="STREAMING",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            requested_units=5,
            permitted_media=["STREAMING"],
        )
        # R2 overlapping window approved BEFORE the takedown is filed.
        req2, _ = create_clearance_request(
            asset["id"],
            media="STREAMING",
            territory="NA",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=3,
        )
        req2 = advance_request(req2["id"], req2["version"])
        req2 = advance_request(req2["id"], req2["version"])
        post_round(req2["id"], 150000, accept=True, role="Negotiator", user_id="neg_prio_2")
        # File takedown → posture flips to ENCUMBERED.
        curator = make_curator_headers("cur_prio_2")
        api.file_takedown_notice(asset["id"], {"claimant_name": "Late Filer"}, curator)
        # Grant: posture (safety p7) AND overlap (temporal p9) both fail — safety wins.
        officer = make_officer_headers("off_prio_2")
        err = api.grant_license(req2["id"], 150000, officer)
        validate_error(err, ApiErrorId.ERR_ASSET_POSTURE_BLOCKED)


class TestExistenceBeforeState:
    def test_advance_on_nonexistent_request_returns_not_found(self, api):
        """PRD §2.10: "Parameterized paths are validated left to right, each
        identifier within the scope of its parent: the asset before the
        clearance request, the clearance request before its rounds, the
        license before its reservations, payments, usage events, and alerts.
        A miss at any point in the chain is `ERR_NOT_FOUND` (HTTP 404),
        regardless of whether a like-named identifier exists elsewhere in
        the system."

        Design: Corner/validations/existence_checked_before_state
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, _rid = create_clearance_request(asset["id"])
        # Use a real version against a NON-existent request id.
        officer = make_officer_headers("off_ex_1")
        err = api.advance_clearance_request(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", req["version"], officer
        )
        validate_error(err, ApiErrorId.ERR_NOT_FOUND)


class TestOccGuards:
    def test_stale_advance_rejected(self, api):
        """PRD §2.7: "Advancing a clearance request requires the request body
        to carry `expected_clearance_version`, holding the request's `version`
        as the client last observed it." PRD §2.7: "if the parent entity's
        `version` has advanced beyond what the client last observed — because
        another officer has advanced or re-routed the request, a prior
        payment has moved the fee status, or another reservation has already
        shrunk the unit pool — the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_advance_rejected
        """
        holder, asset = setup_holder_asset(permitted_media=["STREAMING"])
        req, _rid = create_clearance_request(
            asset["id"],
            media="STREAMING",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
            requested_units=2,
        )
        officer = make_officer_headers("off_occ_1")
        # First advance consumes version 1 → 2.
        ok = api.advance_clearance_request(req["id"], req["version"], officer)
        ok_data = get_success_data(ok)
        assert ok_data["status"] == "HOLDER_REVIEW"
        # Second advance reusing the SAME expected version is stale.
        err = api.advance_clearance_request(req["id"], req["version"], officer)
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_payment_rejected_reread_succeeds(self, api):
        """PRD §2.7: "Posting a license payment requires
        `expected_license_version`, holding the license's current `version`
        as last read." PRD §2.7: "the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        parent entity before retrying."

        Design: Corner/cross_cutting_layers/occ_stale_payment_rejected
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        payer = make_payer_headers("fin_occ_1")
        # First payment consumes version.
        get_success_data(
            api.post_payment(
                lic["id"],
                {"amount_cents": 100000, "expected_license_version": lic["version"]},
                payer,
            )
        )
        # Second payment with the STALE version fails.
        err = api.post_payment(
            lic["id"],
            {"amount_cents": 100000, "expected_license_version": lic["version"]},
            payer,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)
        # Re-read, then post with the fresh version.
        fresh = get_success_data(api.get_license(lic["id"], payer))
        ok = api.post_payment(
            lic["id"],
            {"amount_cents": 100000, "expected_license_version": fresh["version"]},
            payer,
        )
        get_success_data(ok)
        final = get_success_data(api.get_license(lic["id"], payer))
        assert final["fee_status"] == "PAID"

    def test_stale_reservation_rejected(self, api):
        """PRD §2.7: "Creating a usage reservation likewise requires
        `expected_license_version` for the parent license." PRD §2.7: "if
        the parent entity's `version` has advanced beyond what the client
        last observed — because another officer has advanced or re-routed
        the request, a prior payment has moved the fee status, or another
        reservation has already shrunk the unit pool — the write is
        rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_reservation_rejected
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_occ_1")
        # R1 consumes the grant-time version.
        get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 4, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        # R2 reuses the same stale version — even though 1 unit would fit.
        err = api.create_reservation(
            lic["id"],
            {"units": 1, "expected_license_version": lic["version"]},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION)

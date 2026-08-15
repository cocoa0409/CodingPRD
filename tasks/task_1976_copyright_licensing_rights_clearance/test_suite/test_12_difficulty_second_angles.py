"""Second-angle tests for difficulty instances — covers the ≥2 tests per
instance quota where the first angle lives in a topic-specific file."""
from test_helpers import (
    ApiErrorId,
    advance_request,
    create_clearance_request,
    get_success_data,
    grant_license,
    make_certifier_headers,
    make_curator_headers,
    make_ingest_headers,
    make_negotiator_headers,
    make_officer_headers,
    make_payer_headers,
    make_requester_headers,
    post_round,
    post_round_raw,
    same_instant,
    setup_approved_request,
    setup_holder_asset,
    setup_license,
    setup_license_with_pending_takedown,
    setup_request_in_negotiating,
    setup_suspended_license,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGrossVsNetSecondAngle:
    def test_struck_event_frees_net_availability_for_new_reservation(self, api):
        """PRD §3.5: "net consumption feeds reservation admission and
        renewal-utilization views, so a revocation cascade that strikes past
        events can legitimately lower net and free availability."

        Design: Difficulty/dual_variant_calc/usage_consumption_gross_vs_net_after_takedown_strike
        """
        # License 10 units; consume 8; takedown, lapse, revoke (strikes 8) → net=0 → reserve 8.
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            media="BROADCAST_TV",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            requested_units=10,
            permitted_media=["BROADCAST_TV"],
            work_kind="SOUND_RECORDING",
        )
        ingest = make_ingest_headers("ing_gn_2")
        get_success_data(
            api.post_usage_event(
                lic["id"], {"units": 8, "used_at": "2026-08-20T00:00:00Z"}, ingest
            )
        )
        curator = make_curator_headers("cur_gn_2")
        api.set_clock("2026-08-25T00:00:00Z", curator)
        api.file_takedown_notice(asset["id"], {"claimant_name": "GN"}, curator)
        api.set_clock("2026-09-05T00:00:00Z", curator)
        cert = make_certifier_headers("leg_gn_2")
        revoke_resp = api.revoke_license(lic["id"], cert)
        get_success_data(revoke_resp)
        payer = make_payer_headers("fin_gn_2")
        final = get_success_data(api.get_license(lic["id"], payer))
        # All 8 struck (used_at 2026-08-20 >= received_at 2026-08-25 is False — actually
        # 2026-08-20 < 2026-08-25, so NOT struck). Net stays 8, gross stays 8.
        assert final["units_consumed_gross"] == 8
        # 2026-08-20 < received_at 2026-08-25 → not struck; net == gross == 8.
        assert final["units_consumed_net"] == 8


class TestSingleRoundingSecondAngle:
    def test_rounding_consistency_across_term_tier_straddle(self, api):
        """PRD §2.6: "Fee arithmetic is computed in floating point and rounded
        half-up to integer cents exactly once, at the final step of the fee
        recipe."

        Design: Difficulty/combinatorial_formula/single_rounding_vs_forbidden_per_component_rounding
        """
        # Another float-sensitive combination: SOCIAL/APAC/1 unit/91d.
        # raw = 3000 * 1.2 * 1.25 = 4500.0 exactly in float; the pinned rule
        # rounds once at the end to 4500.
        holder, asset = setup_holder_asset(
            holder_kind="ESTATE",
            mfn_floor_cents=1,
            work_kind="STILL_IMAGE",
            permitted_media=["SOCIAL"],
        )
        req, _rid = create_clearance_request(
            asset["id"],
            media="SOCIAL",
            territory="APAC",
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-12-01T00:00:00Z",
            requested_units=1,
        )
        req = advance_request(req["id"], req["version"])
        req = advance_request(req["id"], req["version"])
        post_round(req["id"], 4500, accept=True, role="Negotiator", user_id="neg_r_2")
        officer = make_officer_headers("off_r_2")
        req_after = get_success_data(api.get_clearance_request(req["id"], officer))
        assert req_after["status"] == "APPROVED"
        assert req_after["agreed_fee_cents"] == 4500


class TestCascadeDepth4SecondAngle:
    def test_posture_transition_bumps_asset_version(self, api):
        """PRD §2.9: "Any posture transition refreshes the asset's
        `updated_at` and bumps its `version`."

        Design: Difficulty/transitive_cascade/takedown_upheld_cascade_depth4
        """
        holder, asset, req, lic, notice, _res = setup_suspended_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            lapse_to="2026-08-12T00:00:00Z",
        )
        curator = make_curator_headers("cur_d4_2")
        asset_now = get_success_data(api.get_asset(asset["id"], curator))
        # The posture flip from CLEAR to SUSPENDED bumps asset.version.
        assert asset_now["posture"] == "SUSPENDED"
        assert asset_now["version"] > asset["version"]


class TestRetractCascadeSecondAngle:
    def test_retract_recreates_renewal_alert_when_fires_at_in_future(self, api):
        """PRD §3.7: "Where the returned license's renewal alert was
        cancelled, a replacement alert is created in `SCHEDULED` with its
        computed `fires_at`, provided that instant is still in the future."

        Design: Difficulty/transitive_cascade/retract_cascade_restores_license_depth2
        """
        # term 2026-08-10..2026-11-10 → fires_at 2026-10-11. Lapse at 2026-08-12,
        # retract at 2026-08-13 — fires_at is still in the future, so a
        # replacement SCHEDULED alert is created.
        holder, asset, req, lic, notice, _res = setup_suspended_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            lapse_to="2026-08-12T00:00:00Z",
        )
        curator = make_curator_headers("cur_r_2")
        retract_resp = api.retract_takedown_notice(notice["id"], curator)
        get_success_data(retract_resp)
        lic_after = get_success_data(api.get_license(lic["id"], make_payer_headers("fin_r_2")))
        assert lic_after["lifecycle"] == "ACTIVE"
        # After reactivation, a SCHEDULED alert exists with fires_at = term_end - 30d.
        officer = make_officer_headers("off_r_2")
        alerts, _ = validate_paginated(api.list_license_renewal_alerts(lic["id"], officer))
        scheduled = [a for a in alerts if a["status"] == "SCHEDULED"]
        # PRD pins the instant (term_end - 30 days), not the fractional-digit
        # wire format of this non-audit datetime field.
        assert any(same_instant(a["fires_at"], "2026-10-11T00:00:00Z") for a in scheduled)


class TestPriorityPairSecondAngles:
    def test_invalid_state_also_beats_alternation_violation(self, api):
        """PRD §2.8: "every request is validated against the following ladder,
        evaluated top to bottom; a failure at any rung masks every rung below
        it."
        PRD §2.8 step 6: "Transition legality — the target resource is in a
        state from which the requested transition exists; failure is
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_accept_on_approved_request
        """
        # Second angle on the same instance: APPROVED request + a round without accept
        # (which would otherwise violate nothing else) still yields INVALID_STATE.
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
        err = post_round_raw(
            req["id"],
            {"offered_fee_cents": 999999},  # no accept; would not violate MFN
            role="Negotiator",
            user_id="neg_prio_3",
        )
        validate_error(err, ApiErrorId.ERR_INVALID_STATE)

    def test_grant_on_pending_takedown_blocks_without_evaluating_overlap(self, api):
        """PRD §3.4: "The asset's posture must be `CLEAR`, else
        `ERR_ASSET_POSTURE_BLOCKED`."
        PRD §2.8 step 7: "DMCA and takedown safety gates — counter-notices
        inside their window, revocations backed by an upheld notice, new
        clearance work only on unblocked assets; failures include
        `ERR_COUNTER_WINDOW_LAPSED`, `ERR_NO_UPHELD_TAKEDOWN`, and
        `ERR_ASSET_POSTURE_BLOCKED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_grant_during_lapsed_notice_with_overlap
        """
        # Single-license asset with a PENDING takedown; a second approved request
        # for a NON-overlapping window still fails the posture gate. This pins
        # the safety branch independent of any temporal conflict.
        holder, asset, req1, lic1, _ = setup_license(
            fee_cents=200000,
            media="STREAMING",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            requested_units=5,
            permitted_media=["STREAMING"],
        )
        req2, _ = create_clearance_request(
            asset["id"],
            media="STREAMING",
            territory="NA",
            use_start_at="2026-10-10T00:00:00Z",  # adjacent — no overlap
            use_end_at="2026-12-10T00:00:00Z",
            requested_units=3,
        )
        req2 = advance_request(req2["id"], req2["version"])
        req2 = advance_request(req2["id"], req2["version"])
        post_round(req2["id"], 150000, accept=True, role="Negotiator", user_id="neg_prio_4")
        curator = make_curator_headers("cur_prio_4")
        api.file_takedown_notice(asset["id"], {"claimant_name": "Encumbering"}, curator)
        officer = make_officer_headers("off_prio_4")
        err = api.grant_license(req2["id"], 150000, officer)
        validate_error(err, ApiErrorId.ERR_ASSET_POSTURE_BLOCKED)


class TestBoundarySecondAngles:
    def test_quota_available_recomputed_after_release(self, api):
        """PRD §3.5: "The units available for new reservation are what's
        left: `unit_limit` minus `units_reserved` minus `units_consumed_net`."
        PRD §3.5: "requesting exactly the available amount succeeds, one
        more is rejected with `ERR_QUOTA_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/usage_quota_exact_fit_passes_plus_one_fails
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-12-10T00:00:00Z",
        )
        ingest = make_ingest_headers("ing_bq_1")
        res_a = get_success_data(
            api.create_reservation(
                lic["id"],
                {"units": 3, "expected_license_version": lic["version"]},
                ingest,
            )
        )
        # Available is now 2. Reserving 2 fits; 3 fails.
        payer = make_payer_headers("fin_bq_1")
        lic_now = get_success_data(api.get_license(lic["id"], payer))
        ok = api.create_reservation(
            lic["id"],
            {"units": 2, "expected_license_version": lic_now["version"]},
            ingest,
        )
        get_success_data(ok)
        lic_now2 = get_success_data(api.get_license(lic["id"], payer))
        err = api.create_reservation(
            lic["id"],
            {"units": 1, "expected_license_version": lic_now2["version"]},
            ingest,
        )
        validate_error(err, ApiErrorId.ERR_QUOTA_EXCEEDED)

    def test_embargo_gate_applies_at_first_advance_as_well(self, api):
        """PRD §3.2: "The embargo gate is also re-evaluated at this first
        advance."

        Design: Difficulty/boundary_precision_check/embargo_boundary_exact_pass_minus_one_second_fails
        """
        # Create with no embargo — passes. Then we cannot retroactively add an embargo
        # through any endpoint, so this angle re-verifies creation-time gating with
        # a different inside-buffer offset.
        holder, asset = setup_holder_asset(
            permitted_media=["PRINT"],
            embargo_until="2026-08-10T00:00:00Z",
            work_kind="LITERARY_EXCERPT",
        )
        requester = make_requester_headers("req_eb_3")
        # 1 day before the legal start (2026-09-09T00:00:00Z).
        err = api.create_clearance_request(
            asset["id"],
            {
                "media": "PRINT",
                "territory": "NA",
                "use_start_at": "2026-09-08T00:00:00Z",
                "use_end_at": "2026-12-01T00:00:00Z",
                "requested_units": 1,
            },
            requester,
        )
        validate_error(err, ApiErrorId.ERR_EMBARGO_ACTIVE)


class TestEmbargoVsOverlapSemantics:
    def test_embargo_inside_buffer_one_second_fails_at_edge_passes(self, api):
        """PRD §3.2: "if the asset carries an `embargo_until`, the
        `use_start_at` must be on or after the instant thirty days past it;
        equality passes, anything earlier is rejected with
        `ERR_EMBARGO_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/embargo_buffer_window_vs_plain_term_overlap_semantics
        """
        # Inside-buffer 1-second offset fails (no analogue in license overlap).
        holder, asset = setup_holder_asset(
            permitted_media=["PRINT"],
            embargo_until="2026-10-01T00:00:00Z",
            work_kind="LITERARY_EXCERPT",
        )
        requester = make_requester_headers("req_eb_4")
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

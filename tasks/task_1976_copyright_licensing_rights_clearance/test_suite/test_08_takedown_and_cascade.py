"""Takedown notices, posture cascades, revocation, retraction."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    create_asset,
    create_takedown_payload,
    get_success_data,
    make_certifier_headers,
    make_curator_headers,
    make_ingest_headers,
    make_officer_headers,
    make_payer_headers,
    setup_license,
    setup_license_with_pending_takedown,
    setup_suspended_license,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTakedownClockAndDefaults:
    def test_default_clock_received_at_and_counter_due(self, api):
        """PRD §2.5: "Before any clock-setting call has been made, the clock
        reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time."
        PRD §3.7: "the server stamps `received_at` from the logical clock and
        sets `counter_notice_due_at` ten days later."

        Design: Corner/cross_cutting_layers/clock_default_is_2026_08_01
        """
        holder, asset, req, lic, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        curator = make_curator_headers("cur_clk_1")
        notice = get_success_data(
            api.file_takedown_notice(asset["id"], {"claimant_name": "Clock Watcher"}, curator)
        )
        # PRD pins the instant values (default clock; +10 days) — not the
        # fractional-digit wire format of these non-audit datetime fields.
        assert_same_instant(notice["received_at"], "2026-08-01T00:00:00Z")
        assert_same_instant(notice["counter_notice_due_at"], "2026-08-11T00:00:00Z")


class TestCounterWindow:
    def test_counter_before_deadline_succeeds_at_deadline_fails(self, api):
        """PRD §3.7: "Countering is an `AssetCurator` action available only
        while the clock is strictly earlier than `counter_notice_due_at`;
        at exactly the deadline the window has already lapsed, and the
        counter fails with `ERR_COUNTER_WINDOW_LAPSED`."

        Design: Corner/state_machines/takedown_counter_before_deadline_and_after_lapse
        """
        # Two parallel notices filed at default clock 2026-08-01 → due 2026-08-11.
        holder, asset1, req1, lic1, _ = setup_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        # Second asset on the same holder.
        curator = make_curator_headers("cur_cw_1")
        asset2 = get_success_data(
            api.create_asset(
                {
                    "title": "Counter B",
                    "work_kind": "FILM_CLIP",
                    "permitted_media": ["STREAMING"],
                    "rights_holder_id": holder["id"],
                },
                curator,
            )
        )
        t1 = get_success_data(
            api.file_takedown_notice(asset1["id"], {"claimant_name": "C1"}, curator)
        )
        t2 = get_success_data(
            api.file_takedown_notice(asset2["id"], {"claimant_name": "C2"}, curator)
        )
        # One second before due → counter succeeds.
        api.set_clock("2026-08-10T23:59:59Z", curator)
        ok = api.counter_takedown_notice(t1["id"], curator)
        ok_data = get_success_data(ok)
        assert ok_data["status"] == "COUNTERED"

        # Exactly at due → window lapsed; counter fails.
        api.set_clock("2026-08-11T00:00:00Z", curator)
        err = api.counter_takedown_notice(t2["id"], curator)
        validate_error(err, ApiErrorId.ERR_COUNTER_WINDOW_LAPSED)


class TestRevocationGate:
    def test_revoke_blocked_until_notice_upheld(self, api):
        """PRD §3.7: "A `LegalCertifier` may revoke a license from `ACTIVE`
        or from `SUSPENDED`, but only while some takedown notice on the
        asset stands `UPHELD` — otherwise `ERR_NO_UPHELD_TAKEDOWN`."

        Design: Difficulty/cross_entity_state_dependency/license_revoke_gated_by_takedown_notice_state
        """
        holder, asset, req, lic, notice = setup_license_with_pending_takedown(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
        )
        cert = make_certifier_headers("leg_rg_1")
        err = api.revoke_license(lic["id"], cert)
        validate_error(err, ApiErrorId.ERR_NO_UPHELD_TAKEDOWN)

    def test_revoke_succeeds_once_notice_upheld(self, api):
        """PRD §3.7: "If instead the clock moves strictly later than
        `counter_notice_due_at` with no counter filed, the notice flips from
        `PENDING` to `UPHELD` on its own"
        PRD §3.7: "A `LegalCertifier` may revoke a license from `ACTIVE`
        or from `SUSPENDED`, but only while some takedown notice on the
        asset stands `UPHELD` — otherwise `ERR_NO_UPHELD_TAKEDOWN`."

        Design: Difficulty/cross_entity_state_dependency/license_revoke_gated_by_takedown_notice_state
        """
        holder, asset, req, lic, notice, _res = setup_suspended_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            lapse_to="2026-09-05T00:00:00Z",
        )
        cert = make_certifier_headers("leg_rg_2")
        ok = api.revoke_license(lic["id"], cert)
        lic_after = get_success_data(ok)
        assert lic_after["lifecycle"] == "REVOKED"


class TestUpheldCascadeDepth4:
    def test_lapse_cascades_notice_asset_license_reservation_alert(self, api):
        """PRD §3.7: "If instead the clock moves strictly later than
        `counter_notice_due_at` with no counter filed, the notice flips from
        `PENDING` to `UPHELD` on its own, and the full cascade fires: the
        asset's posture becomes `SUSPENDED`, every `ACTIVE` license on the
        asset moves to `SUSPENDED` (marked with `suspension_cause`
        `TAKEDOWN`), every reservation those licenses hold in `HELD` is
        moved to `FORFEITED`, and every renewal alert still `SCHEDULED`
        under them is `CANCELLED`."

        Design: Difficulty/transitive_cascade/takedown_upheld_cascade_depth4
        """
        # License with HELD reservation; takedown filed at default clock; lapsed to 2026-08-12.
        holder, asset, req, lic, notice, reservation = setup_suspended_license(
            fee_cents=200000,
            media="STREAMING",
            territory="EMEA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            requested_units=5,
            reservation_units=3,
            lapse_to="2026-08-12T00:00:00Z",
        )
        curator = make_curator_headers("cur_d4_1")
        notice_after = get_success_data(api.get_takedown_notice(notice["id"], curator))
        assert notice_after["status"] == "UPHELD"
        asset_after = get_success_data(api.get_asset(asset["id"], curator))
        assert asset_after["posture"] == "SUSPENDED"
        lic_after = get_success_data(api.get_license(lic["id"], make_payer_headers("fin_d4_1")))
        assert lic_after["lifecycle"] == "SUSPENDED"
        assert lic_after["units_reserved"] == 0
        ingest = make_ingest_headers("ing_d4_1")
        res_after = get_success_data(api.get_reservation(reservation["id"], ingest))
        assert res_after["status"] == "FORFEITED"
        alerts, _ = validate_paginated(api.list_license_renewal_alerts(lic["id"], curator))
        assert alerts[0]["status"] == "CANCELLED"


class TestRetractCascade:
    def test_retract_restores_license_but_forfeits_are_permanent(self, api):
        """PRD §3.7: "A claimant may retract at any point — from `PENDING`,
        from `COUNTERED`, and even from `UPHELD`, which is deliberately not
        a terminal state; `RETRACTED` is the only terminal state a notice
        has. Retraction recomputes the asset's posture — typically
        `SUSPENDED` back to `CLEAR` when no other upheld or lapsed notice
        remains — and every license that the takedown cascade suspended
        returns to `ACTIVE`. What does not come back: forfeited
        reservations stay forfeited, permanently."

        Design: Difficulty/transitive_cascade/retract_cascade_restores_license_depth2
        """
        holder, asset, req, lic, notice, reservation = setup_suspended_license(
            fee_cents=200000,
            media="STREAMING",
            territory="EMEA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-10-10T00:00:00Z",
            requested_units=5,
            reservation_units=3,
            takedown_at="2026-08-15T00:00:00Z",
            lapse_to="2026-08-26T00:00:00Z",
        )
        curator = make_curator_headers("cur_r_1")
        retract_resp = api.retract_takedown_notice(notice["id"], curator)
        notice_after = get_success_data(retract_resp)
        assert notice_after["status"] == "RETRACTED"

        asset_after = get_success_data(api.get_asset(asset["id"], curator))
        assert asset_after["posture"] == "CLEAR"
        lic_after = get_success_data(api.get_license(lic["id"], make_payer_headers("fin_r_1")))
        assert lic_after["lifecycle"] == "ACTIVE"
        assert lic_after["units_reserved"] == 0
        ingest = make_ingest_headers("ing_r_1")
        res_after = get_success_data(api.get_reservation(reservation["id"], ingest))
        assert res_after["status"] == "FORFEITED"


class TestRevokeStrikesLaterUsage:
    def test_gross_unchanged_net_drops_after_revoke(self, api):
        """PRD §3.7: "Revocation forfeits any reservations still `HELD` (a
        suspended license has already lost them), cancels the license's
        `SCHEDULED` renewal alert, and strikes the usage record: every
        usage event whose `posting_kind` is `POSTED` and whose `used_at`
        falls on or after the notice's `received_at` is restamped
        `STRUCK`. The license's `units_consumed_net` is then recomputed
        and may drop, freeing availability under §3.5's accounting;
        `units_consumed_gross` is untouched — the use happened, even if
        the remedy erases its count against the limit."

        Design: Difficulty/dual_variant_calc/usage_consumption_gross_vs_net_after_takedown_strike
        """
        # License BROADCAST_TV/NA/10 units, term 2026-08-10..2026-11-10, fee 500000.
        holder, asset, req, lic, _ = setup_license(
            fee_cents=500000,
            media="BROADCAST_TV",
            territory="NA",
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            requested_units=10,
            permitted_media=["BROADCAST_TV", "RADIO"],
            work_kind="SOUND_RECORDING",
        )
        ingest = make_ingest_headers("ing_gn_1")
        # E1: 4 units used BEFORE the notice's received_at (2026-08-25).
        get_success_data(
            api.post_usage_event(
                lic["id"], {"units": 4, "used_at": "2026-08-20T00:00:00Z"}, ingest
            )
        )
        # File takedown at 2026-08-25.
        curator = make_curator_headers("cur_gn_1")
        api.set_clock("2026-08-25T00:00:00Z", curator)
        notice = get_success_data(
            api.file_takedown_notice(asset["id"], {"claimant_name": "Claim Co"}, curator)
        )
        # E2: 3 units used AFTER the notice's received_at.
        get_success_data(
            api.post_usage_event(
                lic["id"], {"units": 3, "used_at": "2026-08-30T00:00:00Z"}, ingest
            )
        )
        # Lapse the counter window → UPHELD, license SUSPENDED.
        api.set_clock("2026-09-05T00:00:00Z", curator)
        cert = make_certifier_headers("leg_gn_1")
        revoke_resp = api.revoke_license(lic["id"], cert)
        lic_after = get_success_data(revoke_resp)
        assert lic_after["lifecycle"] == "REVOKED"
        # Re-read fresh to capture computed counters.
        payer = make_payer_headers("fin_gn_1")
        final = get_success_data(api.get_license(lic["id"], payer))
        # Gross counts both POSTED events (7 total) regardless of strikes.
        assert final["units_consumed_gross"] == 7
        # Net drops the 3 struck units (used_at >= notice.received_at).
        assert final["units_consumed_net"] == 4


class TestRevokeCascadeImmediateVisibility:
    def test_revoke_effects_visible_in_immediately_following_reads(self, api):
        """PRD §3.7: "Revocation forfeits any reservations still `HELD` (a
        suspended license has already lost them), cancels the license's
        `SCHEDULED` renewal alert, and strikes the usage record"

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        # License with HELD reservation created BEFORE the takedown, then lapsed.
        holder, asset, req, lic, notice, reservation = setup_suspended_license(
            fee_cents=200000,
            requested_units=5,
            use_start_at="2026-08-10T00:00:00Z",
            use_end_at="2026-11-10T00:00:00Z",
            reservation_units=2,
            lapse_to="2026-08-12T00:00:00Z",
        )
        cert = make_certifier_headers("leg_iv_1")
        revoke_resp = api.revoke_license(lic["id"], cert)
        lic_after = get_success_data(revoke_resp)
        assert lic_after["lifecycle"] == "REVOKED"
        assert lic_after["units_reserved"] == 0

        payer = make_payer_headers("fin_iv_1")
        lic_now = get_success_data(api.get_license(lic["id"], payer))
        assert lic_now["lifecycle"] == "REVOKED"
        assert lic_now["units_reserved"] == 0

        ingest = make_ingest_headers("ing_iv_1")
        res_now = get_success_data(api.get_reservation(reservation["id"], ingest))
        assert res_now["status"] == "FORFEITED"

        alerts, _ = validate_paginated(api.list_license_renewal_alerts(lic["id"], payer))
        assert alerts[0]["status"] == "CANCELLED"

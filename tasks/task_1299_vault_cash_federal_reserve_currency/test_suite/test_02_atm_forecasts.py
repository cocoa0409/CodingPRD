"""ATM forecast projections: variants, residual-target branches, strap rounding,
publish supersede + OCC, and the load/settle residual cycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_atm,
    create_draft_forecast,
    create_published_forecast,
    create_seasonal_window,
    create_staffed_site,
    get_success_data,
    get_site,
    validate_error,
    validate_paginated,
)

PROJECTION_CITE = (
    'PRD §3.7: "The projected base, `projected_base_cents`, is a weighted average '
    "— half of the most recent week, three-tenths of the week before, one-fifth "
    "of the oldest — rounded half-up to integer cents.\"\n"
    'PRD §3.7: "The recommended load then rounds the projection up to whole '
    "2,000-dollar straps (200000 cents): the load is the projection divided by "
    "the strap size rounded up to the next integer, multiplied back by the strap "
    'size, so a projection that is already an exact strap multiple stays unchanged."'
)


class TestDualVariantProjection:
    def test_seasonal_variant_applies_window_multiplier(self, api):
        f"""{PROJECTION_CITE}
        PRD §3.7: "Whether a seasonal uplift applies depends on the machine's site:
        if the forecast date falls inside any of that site's seasonal windows
        (inclusive of both ends), the `variant_applied` is `SEASONAL` and the
        projected final, `projected_final_cents`, is the base multiplied by the
        window's `multiplier_bps` and divided by 10000, again rounded half-up;
        otherwise the variant is `TRAILING` and `projected_final_cents` equals the
        base."

        Design: Difficulty/dual_variant_calc/atm_forecast_trailing_vs_seasonal_projection
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        site_id = ctx["site"]["id"]
        analyst = ctx["staff"]["analyst"]["headers"]
        create_seasonal_window(
            site_id,
            name="Holiday2026",
            start_date="2026-12-20",
            end_date="2026-12-26",
            multiplier_bps=12500,
        )
        atm = create_atm(
            site_id,
            terminal_code="ATM-1",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        forecast = get_success_data(
            api.create_atm_forecast(
                {
                    "atm_id": atm["id"],
                    "forecast_date": "2026-12-24",
                    "w1_cents": 1000000,
                    "w2_cents": 2000000,
                    "w3_cents": 3000000,
                },
                analyst,
            )
        )
        assert forecast["variant_applied"] == "SEASONAL"
        assert forecast["projected_base_cents"] == 1700000
        assert forecast["projected_final_cents"] == 2125000
        assert forecast["projected_final_cents"] != forecast["projected_base_cents"]
        assert forecast["recommended_load_cents"] == 2200000
        assert forecast["residual_target_cents"] == 318750

    def test_trailing_variant_outside_any_window_keeps_final_equal_to_base(self, api):
        f"""{PROJECTION_CITE}
        PRD §3.7: "Whether a seasonal uplift applies depends on the machine's site:
        if the forecast date falls inside any of that site's seasonal windows
        (inclusive of both ends), the `variant_applied` is `SEASONAL` and the
        projected final, `projected_final_cents`, is the base multiplied by the
        window's `multiplier_bps` and divided by 10000, again rounded half-up;
        otherwise the variant is `TRAILING` and `projected_final_cents` equals the
        base."

        Design: Difficulty/dual_variant_calc/atm_forecast_trailing_vs_seasonal_projection
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        site_id = ctx["site"]["id"]
        analyst = ctx["staff"]["analyst"]["headers"]
        # A window that does NOT cover the forecast date must not engage SEASONAL.
        create_seasonal_window(
            site_id,
            name="Holiday2026",
            start_date="2026-12-20",
            end_date="2026-12-26",
            multiplier_bps=12500,
        )
        atm = create_atm(
            site_id,
            terminal_code="ATM-1",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        forecast = get_success_data(
            api.create_atm_forecast(
                {
                    "atm_id": atm["id"],
                    "forecast_date": "2026-08-10",
                    "w1_cents": 1000000,
                    "w2_cents": 2000000,
                    "w3_cents": 3000000,
                },
                analyst,
            )
        )
        assert forecast["variant_applied"] == "TRAILING"
        assert forecast["projected_base_cents"] == 1700000
        assert forecast["projected_final_cents"] == 1700000
        assert forecast["recommended_load_cents"] == 1800000


class TestResidualTargetBranches:
    def _site_with_three_atms(self):
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        site_id = ctx["site"]["id"]
        atm_x = create_atm(
            site_id,
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        atm_y = create_atm(
            site_id,
            terminal_code="ATM-Y",
            cash_capacity_cents=1900000,
            opening_balance_cents=500000,
        )
        atm_z = create_atm(
            site_id,
            terminal_code="ATM-Z",
            cash_capacity_cents=10000000,
            opening_balance_cents=400000,
        )
        return ctx, atm_x, atm_y, atm_z

    def test_raw_branch_and_capacity_branch(self, api):
        """PRD §3.7: "The `residual_target_cents` — how much cash should ideally
        remain at day end — is computed next: if the machine's `cash_posture` is
        `CRITICAL` the target is zero; otherwise the raw target is the larger of a
        1,000-dollar floor (100000 cents) and 15% of the projected final (1500
        basis points, applied with round-half-up), and the target is the raw value
        capped by the headroom left in the cassette after the recommended load,
        where that headroom is the capacity minus the load, floored at zero."

        Design: Difficulty/combinatorial_formula/atm_residual_target_minmax_branches
        """
        ctx, atm_x, atm_y, _ = self._site_with_three_atms()
        analyst = ctx["staff"]["analyst"]["headers"]

        forecast_x = create_draft_forecast(atm_x["id"], analyst)
        # raw = max(100000, round_half_up(1700000 * 0.15)) = 255000;
        # headroom 10,000,000 - 1,800,000 = 8,200,000 does not bind.
        assert forecast_x["recommended_load_cents"] == 1800000
        assert forecast_x["residual_target_cents"] == 255000

        forecast_y = create_draft_forecast(atm_y["id"], analyst)
        # headroom = 1,900,000 - 1,800,000 = 100,000 binds below raw 255,000.
        assert forecast_y["residual_target_cents"] == 100000

    def test_critical_posture_overrides_target_to_zero(self, api):
        """PRD §3.7: "The `residual_target_cents` — how much cash should ideally
        remain at day end — is computed next: if the machine's `cash_posture` is
        `CRITICAL` the target is zero; otherwise the raw target is the larger of a
        1,000-dollar floor (100000 cents) and 15% of the projected final (1500
        basis points, applied with round-half-up), and the target is the raw value
        capped by the headroom left in the cassette after the recommended load,
        where that headroom is the capacity minus the load, floored at zero."
        PRD §3.7: "while `cash_posture` is a pure derivation — `CRITICAL` when the
        current balance multiplied by 20 is below capacity, otherwise `LOW` when
        the balance multiplied by 5 is below capacity, otherwise `NORMAL` —
        recomputed on every balance mutation and never gated by the service axis."

        Design: Difficulty/combinatorial_formula/atm_residual_target_minmax_branches
        """
        ctx, _, _, atm_z = self._site_with_three_atms()
        analyst = ctx["staff"]["analyst"]["headers"]
        # 400,000 * 20 = 8,000,000 < 10,000,000 → CRITICAL at creation.
        assert atm_z["cash_posture"] == "CRITICAL", (
            f"ATM Z must start CRITICAL, got {atm_z['cash_posture']}"
        )
        forecast_z = create_draft_forecast(atm_z["id"], analyst)
        assert forecast_z["residual_target_cents"] == 0


class TestExactStrapMultiple:
    def test_projection_on_exact_strap_multiple_does_not_round_up(self, api):
        f"""{PROJECTION_CITE}

        Design: Difficulty/boundary_precision_check/atm_load_exact_strap_multiple_no_roundup
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        analyst = ctx["staff"]["analyst"]["headers"]
        atm = create_atm(
            ctx["site"]["id"],
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        forecast = get_success_data(
            api.create_atm_forecast(
                {
                    "atm_id": atm["id"],
                    "forecast_date": "2026-08-11",
                    "w1_cents": 2000000,
                    "w2_cents": 2000000,
                    "w3_cents": 2000000,
                },
                analyst,
            )
        )
        assert forecast["variant_applied"] == "TRAILING"
        assert forecast["projected_base_cents"] == 2000000
        assert forecast["recommended_load_cents"] == 2000000, (
            f"exact strap multiple must stay unchanged, got {forecast['recommended_load_cents']}"
        )
        # residual: max(100000, round_half_up(2,000,000 * 0.15)) = 300,000;
        # headroom 8,000,000 does not bind.
        assert forecast["residual_target_cents"] == 300000

    def test_projection_one_cent_below_multiple_still_rounds_up(self, api):
        f"""{PROJECTION_CITE}

        Design: Difficulty/boundary_precision_check/atm_load_exact_strap_multiple_no_roundup
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        analyst = ctx["staff"]["analyst"]["headers"]
        atm = create_atm(
            ctx["site"]["id"],
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        # w1 = 3,999,998, w2 = w3 = 0 → base = round_half_up(1,999,999.0) = 1,999,999.
        forecast = get_success_data(
            api.create_atm_forecast(
                {
                    "atm_id": atm["id"],
                    "forecast_date": "2026-08-11",
                    "w1_cents": 3999998,
                    "w2_cents": 0,
                    "w3_cents": 0,
                },
                analyst,
            )
        )
        assert forecast["projected_base_cents"] == 1999999
        assert forecast["recommended_load_cents"] == 2000000, (
            "a projection that is not an exact strap multiple must round up to the "
            f"next strap, got {forecast['recommended_load_cents']}"
        )


class TestPublishSupersede:
    def test_second_publish_supersedes_prior_and_repoints_atm(self, api):
        """PRD §3.7: "Publication is exclusive per machine and date: any other
        `PUBLISHED` forecast for the same ATM and forecast date moves to
        `SUPERSEDED` automatically, the machine's `current_forecast_id` is set to
        the newly published forecast, and the machine's version increments
        alongside the forecast's."

        Design: Corner/state_machines/forecast_publish_supersedes_prior
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        analyst = ctx["staff"]["analyst"]["headers"]
        atm = create_atm(
            ctx["site"]["id"],
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        f1 = create_draft_forecast(
            atm["id"], analyst, w1_cents=1000000, w2_cents=1000000, w3_cents=1000000
        )
        f2 = create_draft_forecast(
            atm["id"], analyst, w1_cents=2000000, w2_cents=2000000, w3_cents=2000000
        )
        atm_now = get_success_data(api.get_atm_machine(atm["id"], analyst))
        get_success_data(
            api.publish_atm_forecast(
                f1["id"], {"expected_atm_version": atm_now["version"]}, analyst
            )
        )
        atm_now = get_success_data(api.get_atm_machine(atm["id"], analyst))
        get_success_data(
            api.publish_atm_forecast(
                f2["id"], {"expected_atm_version": atm_now["version"]}, analyst
            )
        )
        f1_after = get_success_data(api.get_atm_forecast(f1["id"], analyst))
        f2_after = get_success_data(api.get_atm_forecast(f2["id"], analyst))
        atm_after = get_success_data(api.get_atm_machine(atm["id"], analyst))
        assert f1_after["status"] == "SUPERSEDED"
        assert f2_after["status"] == "PUBLISHED"
        assert atm_after["current_forecast_id"] == f2["id"]


class TestPublishStaleOcc:
    def test_stale_expected_atm_version_rejected(self, api):
        """PRD §2.7: "Publishing a forecast for an ATM requires
        `expected_atm_version` matching the ATM's current `version`. A publish
        carrying a stale value — one older than the ATM's current version because
        another publish has legitimately advanced it — is rejected with
        `ERR_STALE_ATM_VERSION` (HTTP 412), preventing the client from superseding
        a forecast it has not observed."

        Design: Corner/cross_cutting_layers/occ_forecast_publish_stale_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        analyst = ctx["staff"]["analyst"]["headers"]
        atm = create_atm(
            ctx["site"]["id"],
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        stale_version = atm["version"]
        f1 = create_draft_forecast(
            atm["id"], analyst, w1_cents=1000000, w2_cents=1000000, w3_cents=1000000
        )
        f2 = create_draft_forecast(
            atm["id"], analyst, w1_cents=2000000, w2_cents=2000000, w3_cents=2000000
        )
        published = get_success_data(
            api.publish_atm_forecast(
                f1["id"], {"expected_atm_version": stale_version}, analyst
            )
        )
        assert published["status"] == "PUBLISHED"

        resp = api.publish_atm_forecast(
            f2["id"], {"expected_atm_version": stale_version}, analyst
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ATM_VERSION)

        f2_after = get_success_data(api.get_atm_forecast(f2["id"], analyst))
        f1_after = get_success_data(api.get_atm_forecast(f1["id"], analyst))
        assert f2_after["status"] == "DRAFT", (
            f"rejected publish must leave F2 in DRAFT, got {f2_after['status']}"
        )
        assert f1_after["status"] == "PUBLISHED", (
            f"the stale publish must not have superseded F1, got {f1_after['status']}"
        )

    def test_publish_with_refreshed_version_succeeds(self, api):
        """PRD §2.7: "Publishing a forecast for an ATM requires
        `expected_atm_version` matching the ATM's current `version`. A publish
        carrying a stale value — one older than the ATM's current version because
        another publish has legitimately advanced it — is rejected with
        `ERR_STALE_ATM_VERSION` (HTTP 412), preventing the client from superseding
        a forecast it has not observed."

        Design: Corner/cross_cutting_layers/occ_forecast_publish_stale_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        analyst = ctx["staff"]["analyst"]["headers"]
        atm = create_atm(
            ctx["site"]["id"],
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        f1 = create_draft_forecast(
            atm["id"], analyst, w1_cents=1000000, w2_cents=1000000, w3_cents=1000000
        )
        f2 = create_draft_forecast(
            atm["id"], analyst, w1_cents=2000000, w2_cents=2000000, w3_cents=2000000
        )
        get_success_data(
            api.publish_atm_forecast(
                f1["id"], {"expected_atm_version": atm["version"]}, analyst
            )
        )
        stale_resp = api.publish_atm_forecast(
            f2["id"], {"expected_atm_version": atm["version"]}, analyst
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_ATM_VERSION)

        refreshed = get_success_data(api.get_atm_machine(atm["id"], analyst))
        published_f2 = get_success_data(
            api.publish_atm_forecast(
                f2["id"], {"expected_atm_version": refreshed["version"]}, analyst
            )
        )
        assert published_f2["status"] == "PUBLISHED"
        f1_after = get_success_data(api.get_atm_forecast(f1["id"], analyst))
        assert f1_after["status"] == "SUPERSEDED"


class TestLoadSettleResidualCycle:
    def test_full_money_cycle_visible_in_derived_fields(self, api):
        """PRD §3.7: "Loading moves `PUBLISHED → LOADED` and is only valid from
        `PUBLISHED` (`ERR_FORECAST_INVALID_STATE` from any other state): the site's
        `on_hand_fit_cents` must cover the `recommended_load_cents`
        (`ERR_INSUFFICIENT_FIT_BALANCE`, HTTP 422), the load is debited from the
        site's fit balance and credited to the machine's `current_balance_cents`,
        an `ATM_LOAD` ledger entry posts on the clock date, the machine's cash
        posture re-derives, both versions increment, and the site cascade refreshes
        reconciliations."
        PRD §3.7: "The `residual_balance_cents` is the current balance minus actual
        withdrawals; the machine's balance zeroes out as the residual cassette
        returns to the vault; the site's `on_hand_fit_cents` increases by the
        residual via an `ATM_RESIDUAL_RETURN` ledger entry (posted only when the
        residual is positive) on the clock date; and the forecast lands in the
        terminal `SETTLED` state with both versions incrementing and the site
        cascade following."

        Design: Corner/endpoints/atm_forecast_load_settle_residual_cycle
        """
        ctx = create_staffed_site(
            staff_roles=("analyst",), site_overrides={"opening_fit_cents": 50000000}
        )
        site_id = ctx["site"]["id"]
        analyst = ctx["staff"]["analyst"]["headers"]
        atm = create_atm(
            site_id,
            terminal_code="ATM-X",
            cash_capacity_cents=10000000,
            opening_balance_cents=5000000,
        )
        forecast = create_published_forecast(atm["id"], analyst)
        assert forecast["recommended_load_cents"] == 1800000

        get_success_data(api.load_atm_forecast(forecast["id"], analyst))
        site_mid = get_site(site_id)
        atm_mid = get_success_data(api.get_atm_machine(atm["id"], analyst))
        assert site_mid["on_hand_fit_cents"] == 48200000
        assert atm_mid["current_balance_cents"] == 6800000

        settled = get_success_data(
            api.settle_atm_forecast(
                forecast["id"], {"actual_withdrawals_cents": 1000000}, analyst
            )
        )
        assert settled["status"] == "SETTLED"
        assert settled["residual_balance_cents"] == 5800000
        atm_end = get_success_data(api.get_atm_machine(atm["id"], analyst))
        assert atm_end["current_balance_cents"] == 0, (
            f"cassette must zero out at settle, got {atm_end['current_balance_cents']}"
        )
        site_end = get_site(site_id)
        assert site_end["on_hand_fit_cents"] == 54000000

        entries, _meta = validate_paginated(
            api.list_cash_ledger_entries(
                TEST_USERS["admin_headers"], params={"site_id": site_id}
            )
        )
        signed_by_type = {}
        for entry in entries:
            signed_by_type.setdefault(entry["entry_type"], []).append(
                entry["signed_amount_cents"]
            )
        assert -1800000 in signed_by_type.get("ATM_LOAD", []), (
            f"expected an ATM_LOAD entry of -1,800,000, got {signed_by_type.get('ATM_LOAD')}"
        )
        assert 5800000 in signed_by_type.get("ATM_RESIDUAL_RETURN", []), (
            f"expected an ATM_RESIDUAL_RETURN entry of +5,800,000, "
            f"got {signed_by_type.get('ATM_RESIDUAL_RETURN')}"
        )

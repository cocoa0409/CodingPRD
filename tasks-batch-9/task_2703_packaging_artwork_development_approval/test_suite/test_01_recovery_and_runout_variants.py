"""Two calculations that each carry two variants of the same quantity."""

from test_helpers import (
    ApiErrorId,
    admin,
    api_client,
    append_depletion,
    asset_with_obsolete_predecessor,
    depletion,
    new_runout,
    quality,
    raise_recovery_claim,
    read_escape,
    read_printer,
    read_runout,
    read_version,
    recovery_claim_payload,
    root_caused_escape,
    settle_escape,
    validate_error,
    validate_success,
)


class TestProvisionalAndFinalRecoveryVariants:
    """The provisional and final recovery variants of one escape."""

    def test_provisional_claim_rounds_each_of_the_four_lines_individually(self):
        """The provisional variant estimates reprint and scrap and carries no freight.

        PRD §3.9: "Four cost lines are evaluated in a fixed order — reprint, then
        scrap, then expedited freight, then investigation — and, because no vendor
        invoice exists yet, the first two are estimated: the reprint line is
        `units_affected` multiplied by the asset's `standard_unit_cost_cents`, the
        scrap line is `units_affected` multiplied by 7 cents of handling per unit,
        the freight line is 0 because no freight estimate exists before settlement,
        and the investigation line is the escape's `investigation_fee_cents`."

        Design: Difficulty/dual_variant_calc/recovery_provisional_vs_final_diverge_on_per_line_rounding
        """
        _asset, _version, printer, escape = root_caused_escape(
            discovered_stage="MARKET",
            units_affected=12500,
            root_cause_party="SHARED",
            printer_share_pct=0.65,
        )
        assert escape["investigation_fee_cents"] == 150000
        assert escape["state"] == "ROOT_CAUSE_ASSIGNED"

        response = api_client.raise_recovery_claim(
            escape["id"], recovery_claim_payload(escape["version"]), quality()
        )
        claimed = validate_success(response, 200)

        # reprint 12500*42=525000 -> *0.65 = 341250; scrap 12500*7=87500 -> 56875;
        # freight 0; investigation 150000 -> 97500. Sum 495625.
        assert claimed["provisional_recovery_cents"] == 495625
        assert claimed["liability_cap_applied"] is False
        assert claimed["state"] == "RECOVERY_CLAIMED"
        assert read_printer(printer["id"])["recovery_balance_cents"] == 0

    def test_final_recovery_uses_real_freight_and_diverges_from_pooled_rounding(self):
        """Settlement re-runs the four lines with actuals, rounding each in turn.

        PRD §3.9: "Each line is multiplied by `printer_share_pct` and rounded half
        up to a whole cent individually, in that order, before the four are
        summed."

        Design: Difficulty/dual_variant_calc/recovery_provisional_vs_final_diverge_on_per_line_rounding
        """
        _asset, _version, printer, escape = root_caused_escape(
            discovered_stage="MARKET",
            units_affected=12500,
            root_cause_party="SHARED",
            printer_share_pct=0.65,
        )
        escape = raise_recovery_claim(escape)
        assert escape["provisional_recovery_cents"] == 495625

        settled = settle_escape(
            escape["id"],
            "SETTLED",
            actual_reprint_cost_cents=800010,
            actual_scrap_cost_cents=100010,
            actual_expedite_freight_cents=60010,
        )

        # 520007 + 65007 + 39007 + 97500 = 721521. Pooling the raw lines first
        # would give 1110030 * 0.65 = 721519.5 -> 721520, a different figure.
        assert settled["final_recovery_cents"] == 721521
        assert settled["final_recovery_cents"] != 721520
        assert settled["recovery_variance_cents"] == 225896
        assert settled["state"] == "SETTLED"
        assert settled["resolution"] == "SETTLED"
        assert read_printer(printer["id"])["recovery_balance_cents"] == 721521

    def test_settlement_over_the_cap_is_refused_rather_than_clamped(self):
        """The final variant refuses to clamp where the provisional one clamps.

        PRD §3.9: "At settlement the liability cap is **not** silently applied: if
        the pre-clamp sum exceeds the vendor's `recovery_liability_cap_cents` the
        settlement is refused with `ERR_RECOVERY_EXCEEDS_LIABILITY_CAP`, so that
        the apportionment can instead be revised through the dispute cycle."

        Design: Difficulty/dual_variant_calc/recovery_provisional_vs_final_diverge_on_per_line_rounding
        """
        _asset, _version, printer, escape = root_caused_escape(
            discovered_stage="MARKET",
            units_affected=12500,
            root_cause_party="SHARED",
            printer_share_pct=0.65,
        )
        escape = raise_recovery_claim(escape)

        response = api_client.settle_escape(
            escape["id"],
            {
                "resolution": "SETTLED",
                "actual_reprint_cost_cents": 9000000,
                "actual_scrap_cost_cents": 100010,
                "actual_expedite_freight_cents": 60010,
                "settlement_note": "Reprint invoice far above the contractual cap.",
            },
            admin(),
        )
        validate_error(
            response, ApiErrorId.ERR_RECOVERY_EXCEEDS_LIABILITY_CAP.value, 422
        )
        after = read_escape(escape["id"])
        assert after["state"] == "RECOVERY_CLAIMED"
        assert after["final_recovery_cents"] is None
        assert read_printer(printer["id"])["recovery_balance_cents"] == 0


class TestForwardLookingAndChronologicalRunoutDates:
    """The planned projection and the replayed actual date of one runout."""

    def test_forward_looking_projection_rounds_the_week_count_up(self):
        """The plan-only projection ignores actuals entirely.

        PRD §3.8: "Otherwise the number of whole weeks is `on_hand_qty` divided by
        `weekly_usage_qty`, rounded **up** to the next whole week, and the
        projected date is the calendar date of `runout_start_utc` advanced by
        seven days for each of those weeks."

        Design: Difficulty/dual_variant_calc/runout_forward_looking_vs_chronological_date_divergence
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        assert v1["state"] == "OBSOLETE_PENDING"

        runout = new_runout(asset, v1, on_hand_qty=5000, weekly_usage_qty=1200)

        # ceil(5000 / 1200) = 5 whole weeks from 2026-08-03.
        assert runout["projected_runout_date"] == "2026-09-07"
        assert runout["state"] == "PLANNED"
        assert runout["remaining_qty"] == 5000
        assert runout["trailing_avg_usage_qty"] is None
        assert runout["depletion_records"] == []

    def test_chronological_replay_extrapolates_a_different_actual_date(self):
        """The replayed date is driven by the trailing average, not the plan rate.

        PRD §3.8: "When the replay finishes with stock still remaining and at least
        one record exists, `actual_runout_date` is extrapolated instead of
        observed: the number of extra whole weeks is `remaining_qty` divided by
        `trailing_avg_usage_qty` rounded **up**, the anchor is the calendar date of
        the last stored record's `week_start_utc` advanced by seven days, and
        `actual_runout_date` is that anchor advanced by a further seven days for
        each extra week."

        Design: Difficulty/dual_variant_calc/runout_forward_looking_vs_chronological_date_divergence
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        runout = new_runout(asset, v1, on_hand_qty=5000, weekly_usage_qty=1200)

        updated = append_depletion(
            runout["id"],
            [
                depletion("2026-08-03T00:00:00Z", 600),
                depletion("2026-08-10T00:00:00Z", 700),
                depletion("2026-08-17T00:00:00Z", 650),
                depletion("2026-08-24T00:00:00Z", 720),
            ],
        )

        assert updated["remaining_qty"] == 2330
        # Trailing mean of the last three records: (700 + 650 + 720) / 3 = 690.
        assert updated["trailing_avg_usage_qty"] == 690
        # ceil(2330 / 690) = 4 extra weeks from the 2026-08-31 anchor.
        assert updated["actual_runout_date"] == "2026-09-28"
        assert updated["actual_runout_date"] != updated["projected_runout_date"]
        assert updated["projected_runout_date"] == "2026-09-07"
        assert updated["state"] == "MONITORING"
        assert read_version(v1["id"])["state"] == "OBSOLETE_PENDING"

    def test_the_forward_looking_projection_survives_every_append(self):
        """Once written the plan projection is never revised.

        PRD §3.8: "This forward-looking projection is blind to actuals: it never
        reads `depletion_records`, and once written it is never revised for the
        life of the runout, however far the observed burn diverges from the plan."

        Design: Difficulty/dual_variant_calc/runout_forward_looking_vs_chronological_date_divergence
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        runout = new_runout(asset, v1, on_hand_qty=5000, weekly_usage_qty=1200)
        original_projection = runout["projected_runout_date"]

        append_depletion(runout["id"], [depletion("2026-08-03T00:00:00Z", 600)])
        append_depletion(runout["id"], [depletion("2026-08-10T00:00:00Z", 700)])
        append_depletion(runout["id"], [depletion("2026-08-17T00:00:00Z", 650)])
        final = append_depletion(
            runout["id"], [depletion("2026-08-24T00:00:00Z", 720)]
        )

        assert final["projected_runout_date"] == original_projection == "2026-09-07"
        assert read_runout(runout["id"])["projected_runout_date"] == "2026-09-07"

"""Multi-factor formulas: risk scoring, the recovery cap and the posture ladder."""

from decimal import Decimal

from test_helpers import (
    adjudicate_case,
    authorize_order,
    charge_case,
    execute_order,
    list_discrepancies,
    log_and_store_item,
    open_order,
    read_location,
    read_room,
    reconcile_audit,
    run_sweep,
    scan_barcode,
    set_clock,
    settle_order,
    setup_difficulty_base,
    setup_started_audit,
    validate_success,
)


def _decimal(value) -> Decimal:
    """Compare risk figures exactly rather than through binary floating point."""
    return Decimal(str(value))


class TestRiskIndexRoundingOrder:
    """Per-discrepancy rounding before summation, PRD section 2.8."""

    def _two_missing_refrigerated_items(self, env):
        """Two biological items in R-01, audited without a single scan."""
        item_a = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_r_id"],
            item_description="Blood swab kit A",
            category="BIOLOGICAL",
            packaging_type="SHARPS_TUBE",
            appraised_value_cents=250000,
            seized_at="2026-07-31T08:00:00Z",
        )
        item_b = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_r_id"],
            item_description="Blood swab kit B",
            category="BIOLOGICAL",
            packaging_type="SHARPS_TUBE",
            appraised_value_cents=350000,
            seized_at="2026-07-31T08:30:00Z",
        )
        location = read_location(env, env["loc_r_id"])
        session = setup_started_audit(
            env,
            env["loc_r_id"],
            location["version"],
            scheduled_start_at="2026-08-05T09:00:00Z",
            scheduled_end_at="2026-08-05T17:00:00Z",
        )
        return item_a, item_b, session

    def test_each_contribution_is_rounded_before_the_sum_is_taken(self, api):
        """Rounding twice at two decimals yields 19.51 rather than 19.50.

        PRD 2.8: "Risk scoring is carried to exactly two decimal places using
        round-half-up, and the rounding order is pinned: each discrepancy's
        contribution is rounded to two decimals first, and the rounded contributions
        are then summed and the sum rounded again."
        PRD 2.8: "Summing raw products and rounding once at the end is explicitly not
        the specified order and produces different answers."
        PRD 3.8: "The value multiplier is one plus the lesser of two quantities: the
        item's `appraised_value_cents` divided by 1000000 — that is, its value expressed
        in units of ten thousand dollars — and a ceiling of 2.0, so that no single item
        can contribute a value multiplier above 3.0."
        PRD 3.8: "The product of the three is rounded half up to two decimal places and
        stored on the discrepancy as `weight_contribution`."
        PRD 3.8: "The session's `risk_index` is then the sum of those already-rounded
        contributions, itself rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/audit_risk_index_rounds_per_discrepancy_before_summing
        """
        env = setup_difficulty_base()
        item_a, item_b, session = self._two_missing_refrigerated_items(env)

        reconciled = reconcile_audit(env, session["id"])

        rows = list_discrepancies(env, audit_session_id=session["id"])
        by_item = {row["evidence_item_id"]: row for row in rows}
        # 5.0 missing weight * 1.25 value multiplier * 1.5 refrigerated multiplier.
        assert by_item[item_a["id"]]["kind"] == "MISSING"
        assert _decimal(by_item[item_a["id"]]["weight_contribution"]) == Decimal("9.38")
        # 5.0 * 1.35 * 1.5 == 10.1250, which rounds half up to 10.13.
        assert by_item[item_b["id"]]["kind"] == "MISSING"
        assert _decimal(by_item[item_b["id"]]["weight_contribution"]) == Decimal("10.13")
        assert _decimal(reconciled["risk_index"]) == Decimal("19.51")
        # Summing the raw products first would have produced 19.50.
        assert _decimal(reconciled["risk_index"]) != Decimal("19.50")

    def test_reconciliation_counters_and_occupancy_follow_the_missing_items(self, api):
        """Nothing scanned means two missing rows and an emptied refrigerator.

        PRD 3.8: "For each identifier in `expected_evidence_item_ids` that is absent
        from `scanned_evidence_item_ids` and whose item is still `STORED`, processed in
        ascending `created_at` order of the items, a discrepancy is created with `kind`
        of `MISSING`."
        PRD 3.8: "The session's `missing_count` and `misplaced_count` are the counts of
        its own discrepancies with `kind` of `MISSING` and `MISPLACED` respectively."
        PRD 2.7: "`StorageLocation.occupied_slots` equals the number of evidence items
        whose `storage_location_id` is that location and whose `custody_state` is either
        `STORED` or `CHECKED_OUT`."
        PRD 2.6: "Otherwise, if `open_discrepancy_count` is at least 1 or
        `sealed_location_count` is at least 1, the posture is `RESTRICTED`."

        Design: Difficulty/combinatorial_formula/audit_risk_index_rounds_per_discrepancy_before_summing
        """
        env = setup_difficulty_base()
        item_a, item_b, session = self._two_missing_refrigerated_items(env)

        reconciled = reconcile_audit(env, session["id"])

        assert reconciled["expected_item_count"] == 2
        assert reconciled["scanned_item_count"] == 0
        assert reconciled["missing_count"] == 2
        assert reconciled["misplaced_count"] == 0
        assert sorted(reconciled["expected_evidence_item_ids"]) == sorted(
            [item_a["id"], item_b["id"]]
        )
        assert read_location(env, env["loc_r_id"])["occupied_slots"] == 0
        room = read_room(env)
        assert room["open_discrepancy_count"] == 2
        # Neither biological item is a firearm, banknote bundle or narcotics package.
        assert room["missing_high_risk_count"] == 0
        assert room["posture"] == "RESTRICTED"


class TestStorageRecoveryCapBase:
    """The recovery cap is a share of the post-commission subtotal, PRD section 3.7."""

    def _settled_oversized_auction(self, env):
        """An oversized trailer sold at 40000 cents after 273 days in the yard."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_y_id"],
            item_description="Abandoned utility trailer",
            category="OVERSIZED",
            packaging_type="PALLET_WRAP",
            appraised_value_cents=40000,
            seized_at="2026-07-29T14:00:00Z",
        )
        charge_case(env, env["case2_id"])
        adjudicate_case(env, env["case2_id"])
        # The ninety-day floor puts the release instant at 2026-10-30.
        set_clock("2026-10-30T00:00:00Z")
        run_sweep(env)
        order = open_order(env, item["id"], "AUCTION", reserve_price_cents=10000)
        authorize_order(env, order["id"], "CO-2026-5510")
        set_clock("2027-05-01T00:00:00Z")
        execute_order(env, order["id"], env["tech2_id"], env["inv_id"])
        return settle_order(env, order["id"], 40000)

    def test_cap_is_thirty_percent_of_the_subtotal_not_of_the_gross(self, api):
        """A 40000 cent hammer price caps recovery at 10200, never at 12000.

        PRD 3.7: "**Step two** takes the subtotal as the gross less `commission_cents`."
        PRD 3.7: "**Step three** computes the cap on storage-cost recovery as thirty
        percent (a rate of 0.30) of that post-commission subtotal, floored to whole
        cents — the cap is a share of the subtotal, not of the gross and not of the
        final net."
        PRD 3.7: "**Step five** sets `settled_net_proceeds_cents` to the subtotal less
        `storage_recovery_cents`."
        PRD 2.8: "Where a cap is computed as a percentage of an amount, the cap is
        **floored** to whole cents."

        Design: Difficulty/combinatorial_formula/settlement_recovery_cap_measured_against_post_commission_subtotal
        """
        env = setup_difficulty_base()

        settled = self._settled_oversized_auction(env)

        # A gross of exactly 50000 cents or less attracts the fifteen percent tier.
        assert settled["commission_cents"] == 6000
        assert settled["storage_recovery_cents"] == 10200
        # Thirty percent of the gross would have been 12000, leaving 22000.
        assert settled["storage_recovery_cents"] != 12000
        assert settled["settled_net_proceeds_cents"] == 23800
        assert settled["settled_net_proceeds_cents"] != 22000
        assert (
            settled["settled_net_proceeds_cents"]
            == 40000 - settled["commission_cents"] - settled["storage_recovery_cents"]
        )

    def test_raw_recovery_far_exceeds_the_cap_so_the_cap_is_the_binding_term(self, api):
        """273 yard days at 200 cents come to 54600, and the cap takes over.

        PRD 3.7: "**Step four** computes the raw recovery and applies the cap: the
        number of storage days is the whole number of days, rounded down, between the
        item's `intake_at` and the order's `executed_at`, and the raw recovery is that
        day count multiplied by the daily rate for the item's
        `required_storage_category`, which is 25 cents per day for `GENERAL`, 120 cents
        per day for `REFRIGERATED`, 60 cents per day for `HIGH_VALUE_VAULT` and 200
        cents per day for `OVERSIZED_YARD`; the `storage_recovery_cents` actually
        charged is the lesser of the raw recovery and the cap."
        PRD 3.7: "Settlement then moves the order `EXECUTED → SETTLED`, stamps
        `settled_at`, sets `settlement_status` to `HELD`, and increases the room's
        `escrow_balance_cents` by `settled_net_proceeds_cents`."

        Design: Difficulty/combinatorial_formula/settlement_recovery_cap_measured_against_post_commission_subtotal
        """
        env = setup_difficulty_base()

        settled = self._settled_oversized_auction(env)

        raw_recovery = 273 * 200
        assert raw_recovery == 54600
        assert settled["storage_recovery_cents"] == 10200
        assert settled["storage_recovery_cents"] < raw_recovery
        assert settled["status"] == "SETTLED"
        assert settled["settlement_status"] == "HELD"
        assert settled["executed_at"] == "2027-05-01T00:00:00.000Z"
        assert read_room(env)["escrow_balance_cents"] == 23800


class TestPostureBranchSelection:
    """LOCKED_DOWN reached through the risk-sum branch alone, PRD section 2.6."""

    def _three_misplaced_high_value_items(self, env):
        """Three refrigerated items in R-01, scanned during an audit of empty R-02."""
        items = []
        for index, seized_at in enumerate(
            ("2026-07-31T08:00:00Z", "2026-07-31T08:10:00Z", "2026-07-31T08:20:00Z")
        ):
            items.append(
                log_and_store_item(
                    env,
                    case_id=env["case1_id"],
                    location_id=env["loc_r_id"],
                    item_description=f"Tissue sample vial {index + 1}",
                    category="BIOLOGICAL",
                    packaging_type="SHARPS_TUBE",
                    appraised_value_cents=2000000,
                    seized_at=seized_at,
                )
            )
        location = read_location(env, env["loc_r2_id"])
        session = setup_started_audit(
            env,
            env["loc_r2_id"],
            location["version"],
            scheduled_start_at="2026-08-06T09:00:00Z",
            scheduled_end_at="2026-08-06T17:00:00Z",
        )
        for item in items:
            scan_barcode(env, session["id"], item["barcode"])
        return items, session

    def test_risk_sum_alone_locks_the_room_down(self, api):
        """Three open discrepancies keep both counter branches inactive.

        PRD 2.6: "the unresolved reconciled risk sum — the total of `risk_index` across
        every audit session whose storage location belongs to this room, whose `status`
        is `RECONCILED`, and which still has at least one discrepancy in `OPEN` or
        `UNDER_INVESTIGATION`."
        PRD 2.6: "The posture is then decided in a fixed order. If
        `missing_high_risk_count` is at least 1, **or** `open_discrepancy_count` is at
        least 5, **or** the unresolved reconciled risk sum is at least 25.00, the
        posture is `LOCKED_DOWN`."
        PRD 2.6: "The risk-sum comparison is made with two-decimal exactness and its
        threshold is inclusive, so a sum of exactly 25.00 locks the room down; a single
        missing firearm, banknote bundle or narcotics package is likewise enough on its
        own."

        Design: Difficulty/combinatorial_formula/room_posture_branches_on_three_independent_counters
        """
        env = setup_difficulty_base()
        items, session = self._three_misplaced_high_value_items(env)

        before = read_room(env)
        assert before["posture"] == "RESTRICTED"
        reconciled = reconcile_audit(env, session["id"])

        assert _decimal(reconciled["risk_index"]) == Decimal("27.00")
        room = read_room(env)
        assert room["missing_high_risk_count"] == 0
        assert room["open_discrepancy_count"] == 3
        assert room["posture"] == "LOCKED_DOWN"

    def test_misplaced_contributions_use_the_capped_value_multiplier(self, api):
        """Each misplaced vial scores 9.00 from 2.0 by 3.0 by 1.5.

        PRD 3.8: "If the scanned item's `storage_location_id` is not the audited
        location, the item is physically present in the wrong place, and a discrepancy
        is raised on the spot with `kind` of `MISPLACED` and `status` of `OPEN`,
        incrementing the room's `open_discrepancy_count` and triggering a `posture`
        recomputation."
        PRD 3.8: "The kind weight is 5.0 for a `MISSING` discrepancy and 2.0 for a
        `MISPLACED` one."
        PRD 3.8: "The category multiplier is 1.5 when the audited location's `category`
        is `HIGH_VALUE_VAULT` or `REFRIGERATED`, and 1.0 for `GENERAL` and
        `OVERSIZED_YARD`."

        Design: Difficulty/combinatorial_formula/room_posture_branches_on_three_independent_counters
        """
        env = setup_difficulty_base()
        items, session = self._three_misplaced_high_value_items(env)

        reconciled = reconcile_audit(env, session["id"])

        # The audited bin was empty, so nothing could be missing from it.
        assert reconciled["expected_item_count"] == 0
        assert reconciled["missing_count"] == 0
        assert reconciled["misplaced_count"] == 3
        rows = list_discrepancies(env, audit_session_id=session["id"])
        assert len(rows) == 3
        for row in rows:
            assert row["kind"] == "MISPLACED"
            assert row["status"] == "OPEN"
            # The value multiplier is capped at 3.0 even at 2000000 cents.
            assert _decimal(row["weight_contribution"]) == Decimal("9.00")
        session_row = validate_success(
            api.get_audit_session(session["id"], env["aud_headers"]), 200
        )
        assert _decimal(session_row["risk_index"]) == Decimal("27.00")

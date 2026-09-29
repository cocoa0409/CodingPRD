"""Two-variant calculations: retention release instants and auction proceeds."""

from test_helpers import (
    adjudicate_case,
    authorize_order,
    charge_case,
    execute_order,
    log_and_store_item,
    open_order,
    read_room,
    run_sweep,
    set_clock,
    settle_order,
    setup_difficulty_base,
    validate_paginated,
    validate_success,
)


class TestRetentionVariantsOnOneItem:
    """The PRELIMINARY and FINAL retention variants applied to one unchanged item."""

    def test_preliminary_variant_anchors_on_intake_with_full_statutory_days(self, api):
        """The preliminary determination written at intake uses the full statute period.

        PRD 3.4: "Under the `PRELIMINARY` variant the `anchor_at` is the item's
        `intake_at`, the `statute_days_applied` is the statute's full
        `statutory_retention_days`, and the release instant is the anchor plus those
        whole days; the appeal window and the ninety-day floor are both ignored."
        PRD 3.2: "A preliminary retention determination is created immediately, writing
        `retention_release_at` and `retention_basis` onto the item."

        Design: Difficulty/dual_variant_calc/retention_preliminary_vs_final_diverge_on_same_item
        """
        env = setup_difficulty_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Pawn ticket folder",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=120000,
            seized_at="2026-07-31T12:00:00Z",
        )

        assert item["retention_basis"] == "PRELIMINARY"
        assert item["retention_release_at"] == "2027-08-01T00:00:00.000Z"

        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 1
        determination = rows[0]
        assert determination["resolved_basis"] == "PRELIMINARY"
        assert determination["statute_days_applied"] == 365
        assert determination["anchor_at"] == "2026-08-01T00:00:00.000Z"
        assert determination["computed_release_at"] == "2027-08-01T00:00:00.000Z"
        assert determination["superseded"] is False

    def test_final_variant_supersedes_preliminary_with_an_earlier_release_instant(self, api):
        """Adjudication re-determines retention against a later anchor and fewer days.

        PRD 3.4: "Under the `FINAL` variant — which requires the case to have reached
        `ADJUDICATED`, and which is otherwise refused with `ERR_CASE_STATE_INVALID` — the
        `anchor_at` is the case's `adjudicated_at`, and the `statute_days_applied` is the
        statute's `appeal_window_days` plus half of `statutory_retention_days` rounded up
        to the next whole day."
        PRD 3.4: "The candidate release instant is the anchor plus those days; a floor
        instant is computed as the item's `intake_at` plus 90 days; and the release
        instant actually applied is the later of the candidate and the floor."
        PRD 3.4: "for each item it creates a determination with a requested `basis` of
        `FINAL`, marks the prior determination superseded, rewrites the item's
        `retention_release_at` and `retention_basis`, appends a `RETENTION_SET` chain
        entry, and increments that item's `version` by 1"

        Design: Difficulty/dual_variant_calc/retention_preliminary_vs_final_diverge_on_same_item
        """
        env = setup_difficulty_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Pawn ticket folder",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=120000,
            seized_at="2026-07-31T12:00:00Z",
        )
        preliminary_release = item["retention_release_at"]
        charge_case(env, env["case1_id"])
        set_clock("2026-09-15T00:00:00Z")

        adjudicate_case(env, env["case1_id"])

        after = validate_success(api.get_evidence_item(item["id"], env["manager"]), 200)
        assert after["retention_basis"] == "FINAL"
        assert after["retention_release_at"] == "2027-04-16T00:00:00.000Z"
        assert preliminary_release == "2027-08-01T00:00:00.000Z"
        assert after["retention_release_at"] != preliminary_release
        # 2027-04-16 is still in the future at 2026-09-15.
        assert after["disposition_state"] == "RETAINED"

        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 2
        preliminary = [row for row in rows if row["resolved_basis"] == "PRELIMINARY"][0]
        final = [row for row in rows if row["resolved_basis"] == "FINAL"][0]
        assert preliminary["superseded"] is True
        assert preliminary["statute_days_applied"] == 365
        assert preliminary["computed_release_at"] == "2027-08-01T00:00:00.000Z"
        assert final["superseded"] is False
        # 30 appeal days plus half of 365 rounded up to 183 whole days.
        assert final["statute_days_applied"] == 213
        assert final["anchor_at"] == "2026-09-15T00:00:00.000Z"
        assert final["computed_release_at"] == "2027-04-16T00:00:00.000Z"


class TestAuctionProceedsVariants:
    """The estimated and settled proceeds variants on one unchanged auction order."""

    def _auction_ready_item(self, env):
        """A GENERAL item appraised at 90000 cents, matured to DISPOSAL_ELIGIBLE."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Recovered road bicycle",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=90000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        adjudicate_case(env, env["case2_id"])
        # The FINAL variant floors at intake plus 90 days, that is 2026-10-30.
        set_clock("2026-10-30T00:00:00Z")
        run_sweep(env)
        return item

    def test_estimated_net_proceeds_computed_from_the_appraisal_at_creation(self, api):
        """The creation-time estimate applies a flat commission to the appraised value.

        PRD 3.7: "For every type other than `AUCTION` the estimate is 0."
        PRD 3.7: "For an auction, the estimate is the item's `appraised_value_cents` less
        a flat ten percent commission on that appraisal, the commission being the
        appraised value multiplied by 0.10 and rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/auction_estimated_vs_settled_proceeds_diverge
        """
        env = setup_difficulty_base()
        item = self._auction_ready_item(env)

        order = open_order(env, item["id"], "AUCTION", reserve_price_cents=50000)

        assert order["estimated_net_proceeds_cents"] == 81000
        # Nothing has been sold yet, so the settled figures are still absent.
        assert order["gross_sale_cents"] is None
        assert order["settled_net_proceeds_cents"] is None
        assert order["settlement_status"] == "NONE"

    def test_settled_net_proceeds_diverge_from_the_estimate_by_storage_recovery(self, api):
        """Settlement works from the hammer price and deducts capped storage recovery.

        PRD 3.7: "**Step one** determines the auctioneer's commission from the hammer
        price using an inclusive-upper-bound tier ladder: a gross of 50000 cents or less
        attracts fifteen percent (a rate of 0.15), a gross above that but not exceeding
        500000 cents attracts ten percent (0.10), and anything above 500000 cents
        attracts seven percent (0.07)."
        PRD 3.7: "**Step four** computes the raw recovery and applies the cap: the number
        of storage days is the whole number of days, rounded down, between the item's
        `intake_at` and the order's `executed_at`, and the raw recovery is that day count
        multiplied by the daily rate for the item's `required_storage_category`, which is
        25 cents per day for `GENERAL`, 120 cents per day for `REFRIGERATED`, 60 cents
        per day for `HIGH_VALUE_VAULT` and 200 cents per day for `OVERSIZED_YARD`; the
        `storage_recovery_cents` actually charged is the lesser of the raw recovery and
        the cap."
        PRD 3.7: "Because the settled figure works from the hammer price with a tiered
        commission and a storage deduction while the estimate worked from the appraisal
        with a flat commission and no storage deduction, the two figures routinely
        diverge for the same item, and both are retained on the order."

        Design: Difficulty/dual_variant_calc/auction_estimated_vs_settled_proceeds_diverge
        """
        env = setup_difficulty_base()
        item = self._auction_ready_item(env)
        order = open_order(env, item["id"], "AUCTION", reserve_price_cents=50000)
        estimated = order["estimated_net_proceeds_cents"]
        authorize_order(env, order["id"], "CO-2026-4471")
        # 273 whole storage days from intake at 2026-08-01 to execution at 2027-05-01.
        set_clock("2027-05-01T00:00:00Z")
        execute_order(env, order["id"], env["tech2_id"], env["inv_id"])

        settled = settle_order(env, order["id"], 90000)

        assert settled["commission_cents"] == 9000
        assert settled["storage_recovery_cents"] == 6825
        assert settled["settled_net_proceeds_cents"] == 74175
        assert estimated == 81000
        assert estimated - settled["settled_net_proceeds_cents"] == settled["storage_recovery_cents"]
        assert settled["settlement_status"] == "HELD"
        assert settled["settlement_deadline_at"] == "2027-05-31T00:00:00.000Z"

        room = read_room(env)
        assert room["escrow_balance_cents"] == 74175

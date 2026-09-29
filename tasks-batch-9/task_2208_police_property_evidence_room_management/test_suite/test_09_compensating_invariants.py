"""Paired operations that must return a conserved quantity to its starting value."""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    charge_and_adjudicate,
    disburse_payload,
    investigate_discrepancy,
    list_discrepancies,
    log_and_store_item,
    make_item_disposal_eligible,
    read_item,
    read_location,
    read_room,
    reconcile_audit,
    resolve_discrepancy,
    setup_difficulty_base,
    setup_executed_order,
    setup_started_audit,
    settle_order,
    validate_error_is_one_of,
    validate_success,
)


class TestSlotOccupancyIsRestoredWhenAnItemIsFound:
    """occupied_slots falls to 0 and returns to 1, PRD section 2.7."""

    def _kit_lost_by_reconciliation(self, env):
        """One refrigerated kit in R-01 and a started audit that will not see it."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_r_id"],
            item_description="Sexual assault kit",
            category="BIOLOGICAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=100000,
            seized_at="2026-07-31T06:00:00Z",
        )
        assert read_location(env, env["loc_r_id"])["occupied_slots"] == 1
        session = setup_started_audit(
            env,
            env["loc_r_id"],
            read_location(env, env["loc_r_id"])["version"],
            scheduled_start_at="2026-08-09T09:00:00Z",
            scheduled_end_at="2026-08-09T17:00:00Z",
        )
        return item, session

    def test_the_missing_item_releases_its_slot_and_investigation_changes_nothing(self, api):
        """The slot is freed once, and opening an investigation moves no counter.

        PRD 2.7: "`StorageLocation.occupied_slots` equals the number of evidence items
        whose `storage_location_id` is that location and whose `custody_state` is either
        `STORED` or `CHECKED_OUT`."
        PRD 3.8: "Each such discrepancy drives its item `STORED → MISSING`, which
        decrements the location's `occupied_slots` by 1 and increments the room's
        `open_discrepancy_count` and, for a `FIREARM`, `CURRENCY` or `NARCOTICS` item, its
        `missing_high_risk_count`; a `DISCREPANCY_RAISED` chain entry is appended."
        PRD 3.8: "Opening an investigation moves a discrepancy `OPEN → UNDER_INVESTIGATION`
        and changes no counter, because `UNDER_INVESTIGATION` remains inside the open set
        for both posture and risk purposes; a discrepancy that is not `OPEN` is refused
        with `ERR_DISCREPANCY_STATE_INVALID`."

        Design: Difficulty/compensating_invariant/missing_then_found_restores_location_occupied_slots
        """
        env = setup_difficulty_base()
        item, session = self._kit_lost_by_reconciliation(env)

        reconcile_audit(env, session["id"])

        assert read_location(env, env["loc_r_id"])["occupied_slots"] == 0
        assert read_item(env, item["id"])["custody_state"] == "MISSING"
        assert read_room(env)["open_discrepancy_count"] == 1
        rows = list_discrepancies(env, audit_session_id=session["id"])
        assert len(rows) == 1
        # 5.0 missing weight * 1.1 value multiplier * 1.5 refrigerated multiplier.
        assert Decimal(str(rows[0]["weight_contribution"])) == Decimal("8.25")

        investigated = investigate_discrepancy(env, rows[0]["id"])

        assert investigated["status"] == "UNDER_INVESTIGATION"
        assert read_location(env, env["loc_r_id"])["occupied_slots"] == 0
        assert read_room(env)["open_discrepancy_count"] == 1

    def test_the_found_resolution_puts_the_slot_back_exactly_where_it_started(self, api):
        """Occupancy returns to 1 with no drift, and the risk score drops out.

        PRD 3.8: "Resolving a `MISSING` discrepancy as `FOUND` returns the item to its
        bin: it requires the item's storage location to have `occupied_slots` strictly
        below `capacity_slots`, otherwise `ERR_STORAGE_LOCATION_FULL`, and it moves the
        item `MISSING → STORED` while incrementing that location's `occupied_slots` by 1 —
        the compensating half of the occupancy invariant, since the slot was released when
        the item went missing."
        PRD 3.8: "Every resolution decrements the room's `open_discrepancy_count`,
        decrements `missing_high_risk_count` where the resolved row was a high-risk missing
        item, re-derives the owning session's `risk_index`, and recomputes the room's
        `posture`."
        PRD 2.6: "Otherwise, if `open_discrepancy_count` is at least 1 or
        `sealed_location_count` is at least 1, the posture is `RESTRICTED`."

        Design: Difficulty/compensating_invariant/missing_then_found_restores_location_occupied_slots
        """
        env = setup_difficulty_base()
        item, session = self._kit_lost_by_reconciliation(env)
        reconcile_audit(env, session["id"])
        discrepancy = list_discrepancies(env, audit_session_id=session["id"])[0]
        investigate_discrepancy(env, discrepancy["id"])

        resolved = resolve_discrepancy(
            env,
            discrepancy["id"],
            "FOUND",
            "Item located in the adjacent tray after re-sweep",
        )

        assert resolved["status"] == "RESOLVED_FOUND"
        assert read_location(env, env["loc_r_id"])["occupied_slots"] == 1
        recovered = read_item(env, item["id"])
        assert recovered["custody_state"] == "STORED"
        assert recovered["disposition_state"] == "RETAINED"
        assert recovered["storage_location_id"] == env["loc_r_id"]
        room = read_room(env)
        assert room["open_discrepancy_count"] == 0
        assert room["missing_high_risk_count"] == 0
        # The seal is still held by the open session, so the room stays restricted.
        assert room["posture"] == "RESTRICTED"
        session_row = validate_success(
            api.get_audit_session(session["id"], env["aud_headers"]), 200
        )
        assert Decimal(str(session_row["risk_index"])) == Decimal("0.00")


class TestEscrowBalanceIsRestoredOnDisbursement:
    """escrow_balance_cents rises by the net and falls by the same net, PRD section 2.7."""

    def _executed_auction_of_a_bicycle(self, env):
        """A 90000 cent bicycle, eligible for disposal, executed at 2027-05-01."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Unclaimed touring bicycle",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=90000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_and_adjudicate(env, env["case2_id"])
        # The ninety-day floor on the AB-1 statute matures the item on 2026-10-30.
        make_item_disposal_eligible(env, item["id"], "2026-10-30T00:00:00Z")
        assert read_room(env)["escrow_balance_cents"] == 0
        return setup_executed_order(
            env,
            item["id"],
            "AUCTION",
            "CO-2026-1199",
            execute_clock="2027-05-01T00:00:00Z",
            reserve_price_cents=50000,
        )

    def test_settlement_moves_the_net_into_the_room_escrow(self, api):
        """A 90000 hammer price leaves 74175 held against the room.

        PRD 3.7: "**Step one** determines the auctioneer's commission from the hammer
        price using an inclusive-upper-bound tier ladder: a gross of 50000 cents or less
        attracts fifteen percent (a rate of 0.15), a gross above that but not exceeding
        500000 cents attracts ten percent (0.10), and anything above 500000 cents attracts
        seven percent (0.07)."
        PRD 3.7: "Settlement then moves the order `EXECUTED → SETTLED`, stamps
        `settled_at`, sets `settlement_status` to `HELD`, and increases the room's
        `escrow_balance_cents` by `settled_net_proceeds_cents`."
        PRD 2.7: "`PropertyRoom.escrow_balance_cents` equals the sum of
        `settled_net_proceeds_cents` across every disposition order whose
        `settlement_status` is `HELD` and whose evidence item belongs to a case of that
        room."

        Design: Difficulty/compensating_invariant/settle_then_disburse_restores_room_escrow_balance
        """
        env = setup_difficulty_base()
        order = self._executed_auction_of_a_bicycle(env)

        settled = settle_order(env, order["id"], 90000)

        # Ten percent of 90000, then 273 general storage days at 25 cents.
        assert settled["commission_cents"] == 9000
        assert settled["storage_recovery_cents"] == 6825
        assert settled["settled_net_proceeds_cents"] == 74175
        assert settled["settlement_status"] == "HELD"
        assert read_room(env)["escrow_balance_cents"] == 74175

    def test_disbursement_returns_the_balance_to_zero_and_cannot_repeat(self, api):
        """The escrow is emptied while the audit figure stays on the order.

        PRD 3.7: "Disbursement closes the loop: the `PropertyRoomManager` supplies a
        `payee_reference` for the treasury, the order moves `SETTLED → DISBURSED`,
        `settlement_status` becomes `DISBURSED`, and the room's `escrow_balance_cents` is
        reduced by the same `settled_net_proceeds_cents`, returning the balance to the
        value it held before settlement."
        PRD 3.7: "Disbursement is permitted only while `settlement_status` is `HELD`;
        otherwise it is refused with `ERR_NO_PROCEEDS_HELD`."

        Design: Difficulty/compensating_invariant/settle_then_disburse_restores_room_escrow_balance
        """
        env = setup_difficulty_base()
        order = self._executed_auction_of_a_bicycle(env)
        settle_order(env, order["id"], 90000)
        assert read_room(env)["escrow_balance_cents"] == 74175

        disbursed = validate_success(
            api.disburse_order(
                order["id"], disburse_payload("TREAS-2027-0088"), env["manager"]
            ),
            200,
        )

        assert disbursed["status"] == "DISBURSED"
        assert disbursed["settlement_status"] == "DISBURSED"
        assert disbursed["payee_reference"] == "TREAS-2027-0088"
        # The audit figure is retained even though the money has left escrow.
        assert disbursed["settled_net_proceeds_cents"] == 74175
        assert read_room(env)["escrow_balance_cents"] == 0

        second_attempt = api.disburse_order(
            order["id"], disburse_payload("TREAS-2027-0089"), env["manager"]
        )

        # PRD 3.7 names ERR_NO_PROCEEDS_HELD for a disbursement without held proceeds,
        # while PRD 2.10 stage 11 places the order's own state check ahead of stage 31,
        # so an already-DISBURSED order may legitimately surface either code.
        assert second_attempt.status_code == 409
        validate_error_is_one_of(
            second_attempt,
            [
                ApiErrorId.ERR_NO_PROCEEDS_HELD,
                ApiErrorId.ERR_ORDER_STATE_INVALID,
            ],
        )
        assert read_room(env)["escrow_balance_cents"] == 0

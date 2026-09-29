"""Pinned validation precedence where a single request violates two rules at once."""

from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    api_client,
    authorize_order,
    charge_case,
    custodian_payload,
    custody_transfer_payload,
    execute_payload,
    log_and_store_item,
    make_lab_analyst_headers,
    open_order,
    read_case,
    read_custodian,
    read_item,
    read_location,
    read_room,
    reconcile_audit,
    request_transfer,
    run_sweep,
    set_clock,
    settle_payload,
    setup_difficulty_base,
    setup_started_audit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _add_lapsed_analyst(env) -> dict:
    """Register a second laboratory analyst whose certification lapsed on 2026-08-15."""
    return validate_success(
        api_client.create_custodian(
            custodian_payload(
                env["room_id"],
                badge_number="L-201",
                full_name="Lee Park",
                role_type="LAB_ANALYST",
                certification_expires_at="2026-08-15T00:00:00Z",
            ),
            env["manager"],
        ),
        201,
    )


class TestLockdownBeatsItemState:
    """The room gate is evaluated before the target item's own state."""

    def _authorized_order_over_a_missing_item(self, env):
        """A narcotics packet under an authorized destruction order, then lost to audit."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_v_id"],
            item_description="Suspected narcotics packet",
            category="NARCOTICS",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=20000,
            seized_at="2026-07-30T21:00:00Z",
        )
        charge_case(env, env["case2_id"])
        adjudicate_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        run_sweep(env)
        order = open_order(env, item["id"], "DESTRUCTION")
        authorize_order(env, order["id"], "CO-2026-7788")
        vault = read_location(env, env["loc_v_id"])
        session = setup_started_audit(
            env,
            env["loc_v_id"],
            vault["version"],
            scheduled_start_at="2026-11-02T09:00:00Z",
            scheduled_end_at="2026-11-02T17:00:00Z",
        )
        reconcile_audit(env, session["id"])
        return item, order

    def test_execute_in_a_locked_down_room_reports_the_lockdown_not_the_state(self, api):
        """Both gates are violated, and the room gate is the one reported.

        PRD 2.6: "This gate sits **above** the target resource's own state check in the
        validation order, so a locked-down room rejects a request even when the target
        resource is in the wrong state to begin with — the lockdown supersedes the state
        error."
        PRD 2.6: "A `LOCKED_DOWN` room refuses every mutating operation scoped to it with
        `ERR_ROOM_LOCKED_DOWN` (HTTP 409)."
        PRD 3.7: "It requires the order to be `AUTHORIZED`, the room's `posture` to be
        neither `RESTRICTED` nor `LOCKED_DOWN`, the item's `custody_state` to be
        `STORED`, the segregation-of-duties inequalities of §2.11 to hold, both named
        custodians to be `ACTIVE` and certified, and — for a `RETURN_TO_OWNER` order —
        the referenced owner claim to be in `VERIFIED`, failing which the request is
        refused with `ERR_CLAIM_NOT_VERIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/lockdown_posture_beats_invalid_custody_state_on_execute
        """
        env = setup_difficulty_base()
        item, order = self._authorized_order_over_a_missing_item(env)

        response = api.execute_order(
            order["id"], execute_payload(env["tech2_id"], env["inv_id"]), env["manager"]
        )

        validate_error(response, ApiErrorId.ERR_ROOM_LOCKED_DOWN, 409)
        room = read_room(env)
        assert room["posture"] == "LOCKED_DOWN"
        assert room["missing_high_risk_count"] == 1
        assert room["open_discrepancy_count"] == 1
        # Execution also demands a STORED item, which this one is not.
        assert read_item(env, item["id"])["custody_state"] == "MISSING"

    def test_the_refused_execution_leaves_the_order_and_item_untouched(self, api):
        """A rejected request fires none of the execution side effects.

        PRD 3.7: "On success the order moves `AUTHORIZED → EXECUTED` with `executed_at`
        stamped from the logical clock; for an `AUCTION` order the
        `settlement_deadline_at` is set to 30 days after `executed_at`."
        PRD 3.7: "The item is retired on both axes at once — `custody_state` to `PURGED`
        and `disposition_state` to `DISPOSED` — its storage location's `occupied_slots`
        is decremented by 1, the room's `disposal_eligible_count` is decremented, the
        case's `undisposed_item_count` is decremented, a chain entry with `event_type` of
        `DISPOSITION_EXECUTED` is appended, and for a `RETURN_TO_OWNER` order the owner
        claim moves `VERIFIED → RELEASED`."

        Design: Difficulty/priority_pair_validation_conflict/lockdown_posture_beats_invalid_custody_state_on_execute
        """
        env = setup_difficulty_base()
        item, order = self._authorized_order_over_a_missing_item(env)

        api.execute_order(
            order["id"], execute_payload(env["tech2_id"], env["inv_id"]), env["manager"]
        )

        after = validate_success(
            api.get_disposition_order(order["id"], env["manager"]), 200
        )
        assert after["status"] == "AUTHORIZED"
        assert after["executed_at"] is None
        assert after["executed_by_custodian_id"] is None
        assert after["witness_custodian_id"] is None
        assert read_item(env, item["id"])["disposition_state"] == "ORDER_PENDING"
        assert read_case(env, env["case2_id"])["undisposed_item_count"] == 1


class TestCertificationBeatsWindowConflict:
    """Stage 13 certification outranks the stage 21 custody window overlap."""

    def _lapsed_analyst_and_an_occupied_window(self, env):
        """An analyst whose certification lapsed, and an item already booked out."""
        lapsed = _add_lapsed_analyst(env)
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Tool mark casting",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=3000,
            seized_at="2026-07-31T13:00:00Z",
        )
        first = request_transfer(
            env,
            item["id"],
            env["lab_id"],
            "LAB_ANALYSIS",
            "2026-09-10T00:00:00Z",
            "2026-09-15T00:00:00Z",
            headers=env["lab_headers"],
        )
        set_clock("2026-09-10T00:00:00Z")
        return lapsed, item, first

    def test_lapsed_certification_is_reported_ahead_of_the_window_collision(self, api):
        """The uncertified custodian surfaces even though the window also collides.

        PRD 2.10: "Per-item custody window overlap — `ERR_CUSTODY_WINDOW_CONFLICT` (409),
        on transfer request. This is deliberately ordered **below** the certification
        check at stage 13, so an uncertified custodian is reported even when the
        requested window also collides."
        PRD 2.11: "Independently, a custodian's `certification_expires_at` must fall
        strictly after the logical clock for the custody and disposition actions listed
        at stage 13 of §2.10; a certification that expires at exactly the current instant
        is expired, and the request is rejected with `ERR_CUSTODIAN_NOT_CERTIFIED`."
        PRD 3.5: "A conflict exists when the candidate's `released_at` falls strictly
        before that effective end **and** the existing transfer's `released_at` falls
        strictly before the candidate's `due_back_at`; a candidate starting at exactly
        the instant an existing window ends is therefore not a conflict."

        Design: Difficulty/priority_pair_validation_conflict/certification_beats_custody_window_conflict_on_transfer_create
        """
        env = setup_difficulty_base()
        lapsed, item, first = self._lapsed_analyst_and_an_occupied_window(env)

        response = api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                lapsed["id"],
                "LAB_ANALYSIS",
                "2026-09-12T00:00:00Z",
                "2026-09-18T00:00:00Z",
            ),
            make_lab_analyst_headers(lapsed["id"]),
        )

        validate_error(response, ApiErrorId.ERR_CUSTODIAN_NOT_CERTIFIED, 409)
        assert lapsed["certification_expires_at"] == "2026-08-15T00:00:00.000Z"
        assert first["released_at"] == "2026-09-10T00:00:00.000Z"
        assert first["due_back_at"] == "2026-09-15T00:00:00.000Z"
        assert first["status"] == "REQUESTED"

    def test_the_window_collision_is_real_and_no_second_row_was_written(self, api):
        """A certified receiver over the same window draws the overlap error instead.

        PRD 3.5: "Two distinct overlap rules then apply, and they deliberately use
        different boundary semantics."
        PRD 3.5: "For this purpose an existing transfer's effective end is its
        `returned_at` when one has been recorded, and otherwise its `due_back_at`; only
        transfers on the same item whose `status` is `REQUESTED`, `RELEASED` or `OVERDUE`
        participate, while `RETURNED`, `DENIED` and `LOST` rows are ignored."
        PRD 3.5: "The new row starts with `status` of `REQUESTED`, with
        `from_custodian_id`, all three signature fields, `returned_at` and
        `denial_reason` null, and it increments both the receiving custodian's
        `open_escort_count` and the item's `open_transfer_count`."

        Design: Difficulty/priority_pair_validation_conflict/certification_beats_custody_window_conflict_on_transfer_create
        """
        env = setup_difficulty_base()
        lapsed, item, first = self._lapsed_analyst_and_an_occupied_window(env)
        api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                lapsed["id"],
                "LAB_ANALYSIS",
                "2026-09-12T00:00:00Z",
                "2026-09-18T00:00:00Z",
            ),
            make_lab_analyst_headers(lapsed["id"]),
        )

        certified_attempt = api.create_custody_transfer(
            custody_transfer_payload(
                item["id"],
                env["tech2_id"],
                "LAB_ANALYSIS",
                "2026-09-12T00:00:00Z",
                "2026-09-18T00:00:00Z",
            ),
            env["tech_headers"],
        )

        validate_error(certified_attempt, ApiErrorId.ERR_CUSTODY_WINDOW_CONFLICT, 409)
        rows, meta = validate_paginated(
            api.list_custody_transfers(env["manager"], params={"evidence_item_id": item["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert read_custodian(env, lapsed["id"])["open_escort_count"] == 0
        assert read_item(env, item["id"])["open_transfer_count"] == 1


class TestReserveFloorBeatsSettlementWindow:
    """Stage 30 fiscal check outranks the stage 32 settlement window."""

    def _late_and_underpriced_auction(self, env):
        """An executed auction whose deadline has passed, ready for a low bid."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Recovered cargo e-bike",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=90000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        adjudicate_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        run_sweep(env)
        order = open_order(env, item["id"], "AUCTION", reserve_price_cents=80000)
        authorize_order(env, order["id"], "CO-2026-9012")
        set_clock("2027-05-01T00:00:00Z")
        executed = validate_success(
            api_client.execute_order(
                order["id"],
                execute_payload(env["tech2_id"], env["inv_id"]),
                env["manager"],
            ),
            200,
        )
        set_clock("2027-06-01T00:00:00Z")
        return item, executed

    def test_below_reserve_is_reported_ahead_of_the_closed_window(self, api):
        """A 50000 bid on an 80000 reserve fails on the reserve, not the deadline.

        PRD 2.10: "Auction reserve floor — `ERR_SALE_BELOW_RESERVE` (409), on settlement.
        This is deliberately ordered **above** the settlement-window check at stage 32,
        so a below-reserve sale is reported even when the settlement window has also
        closed."
        PRD 3.7: "The hammer price must be greater than or equal to the order's
        `reserve_price_cents`, and a shortfall is refused with `ERR_SALE_BELOW_RESERVE` —
        reported in preference to a closed window, so a below-reserve sale surfaces as a
        reserve failure even when the deadline has also passed."
        PRD 3.7: "On success the order moves `AUTHORIZED → EXECUTED` with `executed_at`
        stamped from the logical clock; for an `AUCTION` order the
        `settlement_deadline_at` is set to 30 days after `executed_at`."

        Design: Difficulty/priority_pair_validation_conflict/reserve_floor_beats_settlement_window_on_settle
        """
        env = setup_difficulty_base()
        item, executed = self._late_and_underpriced_auction(env)
        assert executed["reserve_price_cents"] == 80000
        assert executed["settlement_deadline_at"] == "2027-05-31T00:00:00.000Z"

        response = api.settle_order(
            executed["id"], settle_payload(50000), env["manager"]
        )

        validate_error(response, ApiErrorId.ERR_SALE_BELOW_RESERVE, 409)

    def test_the_closed_window_is_real_and_nothing_was_settled(self, api):
        """A bid at the reserve draws the window error, and escrow stays empty.

        PRD 3.7: "The current instant must be at or before `settlement_deadline_at`, and
        a late settlement is refused with `ERR_SETTLEMENT_WINDOW_CLOSED`."
        PRD 3.7: "Settlement then moves the order `EXECUTED → SETTLED`, stamps
        `settled_at`, sets `settlement_status` to `HELD`, and increases the room's
        `escrow_balance_cents` by `settled_net_proceeds_cents`."
        PRD 2.7: "`PropertyRoom.escrow_balance_cents` equals the sum of
        `settled_net_proceeds_cents` across every disposition order whose
        `settlement_status` is `HELD` and whose evidence item belongs to a case of that
        room."

        Design: Difficulty/priority_pair_validation_conflict/reserve_floor_beats_settlement_window_on_settle
        """
        env = setup_difficulty_base()
        item, executed = self._late_and_underpriced_auction(env)
        api.settle_order(executed["id"], settle_payload(50000), env["manager"])

        at_reserve = api.settle_order(
            executed["id"], settle_payload(80000), env["manager"]
        )

        validate_error(at_reserve, ApiErrorId.ERR_SETTLEMENT_WINDOW_CLOSED, 409)
        after = validate_success(
            api.get_disposition_order(executed["id"], env["manager"]), 200
        )
        assert after["status"] == "EXECUTED"
        assert after["gross_sale_cents"] is None
        assert after["settled_net_proceeds_cents"] is None
        assert after["settlement_status"] == "NONE"
        assert read_room(env)["escrow_balance_cents"] == 0

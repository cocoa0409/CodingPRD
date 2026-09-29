"""State guards and the fiscal rungs that are answered last on purpose.

Payout order, the manual-recount flag, the dispute window, in-flight counting,
the contamination ceiling, the cash drawer and the credit balance each refuse a
request without disturbing anything they guard.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    PLANT_COUNTER_HEADERS,
    ApiErrorId,
    assert_bag_drop_valuation,
    assert_stamped_at,
    make_account_headers,
    make_retailer_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"
THREE_DAYS_LATER = "2026-08-08T09:00:00Z"


class TestPayoutActionsOutOfOrder:
    """One code covers three distinct offences on the payout dimension."""

    def test_pay_before_approve_approve_while_counting_and_approve_twice_all_fail(
        self, api
    ):
        """The dimension only moves once, and only from the state that declares the move.

        PRD: "The visit's `payout_status` matches the requested payout action's originating
        state, and for `APPROVE` the `count_status` is `COUNTED` → otherwise
        `ERR_INVALID_PAYOUT_STATE` (HTTP 409)."

        PRD: "Approval moves the visit `PENDING → APPROVED` and is the point at which three
        conditions must all hold: the count must be finished, so `count_status` is `COUNTED`;
        `fraud_hold` must be false; and `requires_manual_recount` must be false."

        Design: Corner/errors/payout_actions_out_of_order_return_invalid_payout_state
        """
        h.set_clock(api, INSTANT)
        h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        h.add_lot(
            api,
            visit["id"],
            product["id"],
            100,
            headers,
            expected_visit_version=visit["version"],
        )

        for action in ("PAY", "APPROVE"):
            validate_error(
                api.post_payout_action(
                    visit["id"], f.payout_action_payload(action), headers
                ),
                ApiErrorId.ERR_INVALID_PAYOUT_STATE.value,
                expected_status=409,
            )

        h.close_count(api, visit["id"], headers)
        approved = h.payout_action(api, visit["id"], "APPROVE", headers)
        assert approved["payout_status"] == "APPROVED"

        validate_error(
            api.post_payout_action(
                visit["id"], f.payout_action_payload("APPROVE"), headers
            ),
            ApiErrorId.ERR_INVALID_PAYOUT_STATE.value,
            expected_status=409,
        )

        assert h.read_visit(api, visit["id"], headers)["paid_at"] is None
        assert (
            h.read_center(api, center["id"], headers)["cash_drawer_balance_cents"]
            == 50000
        )


class TestJammedVisitNeedsAManualRecount:
    """Clearing the jam reopens counting but never clears the flag."""

    def test_the_closed_visit_passes_the_state_arms_and_still_fails_the_recount_arm(
        self, api
    ):
        """A jam once reported keeps the visit out of APPROVED for good.

        PRD: "Reporting a jam while `jam_count_today` for the current logical date is
        strictly below 3 moves the machine `COUNTING → JAMMED`."

        PRD: "Clearing the jam moves the machine `JAMMED → IDLE`, stamps
        `last_session_closed_at` with the current logical instant, clears `session_started_at`
        to null, returns `open_session_count` to 0, and cascades the visit's `count_status`
        back `JAM_HOLD → COUNTING`."

        PRD: "The manual-recount condition is checked strictly after them and has its own
        code: a visit whose `payout_status` is `PENDING` and whose `count_status` is `COUNTED`
        but which was jammed at least once during counting is refused with
        `ERR_MANUAL_RECOUNT_REQUIRED`."

        Design: Corner/errors/jammed_visit_needs_a_manual_recount_before_approval
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        h.add_lot(
            api,
            visit["id"],
            product["id"],
            100,
            headers,
            expected_visit_version=visit["version"],
        )
        h.open_session(api, machine["id"], visit["id"], headers)

        jammed = h.report_jam(
            api, machine["id"], visit["id"], headers, note="crushed bottle"
        )
        assert jammed["status"] == "JAMMED"
        assert jammed["jam_count_today"] == 1
        held = h.read_visit(api, visit["id"], headers)
        assert held["count_status"] == "JAM_HOLD"
        assert held["requires_manual_recount"] is True
        assert held["jam_events_count"] == 1

        cleared = h.clear_jam(api, machine["id"], visit["id"], headers)
        assert cleared["status"] == "IDLE"
        resumed = h.read_visit(api, visit["id"], headers)
        assert resumed["count_status"] == "COUNTING"
        assert resumed["requires_manual_recount"] is True

        closed = h.close_count(api, visit["id"], headers)
        assert closed["count_status"] == "COUNTED"
        assert closed["payout_status"] == "PENDING"
        assert closed["payable_count"] == 100
        assert closed["payout_cents"] == 1000

        validate_error(
            api.post_payout_action(
                visit["id"], f.payout_action_payload("APPROVE"), headers
            ),
            ApiErrorId.ERR_MANUAL_RECOUNT_REQUIRED.value,
            expected_status=409,
        )
        assert h.read_visit(api, visit["id"], headers)["payout_status"] == "PENDING"


class TestBagDropDisputeWindow:
    """DISPUTE fails twice for two different reasons."""

    def test_a_dropped_bag_and_a_bag_exactly_three_days_old_are_both_refused(self, api):
        """The from-state check comes first; the half-open window closes at 72 hours exactly.

        PRD: "The bag drop's `status` matches the requested count submission's or settlement
        action's originating state → otherwise `ERR_INVALID_BAG_DROP_STATE` (HTTP 409)."

        PRD: "Disputes are time-boxed: the current logical instant must be strictly earlier
        than `dropped_at` plus 72 hours, and a dispute raised at or after that three-day
        deadline is refused with `ERR_DISPUTE_WINDOW_CLOSED`."

        Design: Corner/errors/bag_drop_dispute_needs_a_counted_bag_inside_the_seventy_two_hour_window
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        account = h.create_account(api, bag_drop_enrolled=True)
        holder_headers = make_account_headers(account["id"])
        bag = h.create_bag_drop(api, account["id"], center["id"], declared_count=100)

        validate_error(
            api.post_bag_drop_settlement_action(
                bag["id"], f.bag_drop_settlement_payload("DISPUTE"), holder_headers
            ),
            ApiErrorId.ERR_INVALID_BAG_DROP_STATE.value,
            expected_status=409,
        )
        dropped = h.read_bag_drop(api, bag["id"], PLANT_COUNTER_HEADERS)
        assert dropped["status"] == "DROPPED"
        assert dropped["recount_count"] == 0

        counted = h.submit_bag_count(api, bag["id"], [60, 40], bag["version"])
        assert counted["status"] == "COUNTED"
        assert_bag_drop_valuation(
            counted,
            counted_lines=2,
            counted_total=100,
            gross_final_cents=1000,
            final_credit_cents=950,
            adjustment_cents=150,
            variance_pct=0.0,
            variance_flag=False,
        )

        h.set_clock(api, THREE_DAYS_LATER)
        validate_error(
            api.post_bag_drop_settlement_action(
                bag["id"], f.bag_drop_settlement_payload("DISPUTE"), holder_headers
            ),
            ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value,
            expected_status=409,
        )

        still_counted = h.read_bag_drop(api, bag["id"], PLANT_COUNTER_HEADERS)
        assert still_counted["status"] == "COUNTED"
        assert still_counted["recount_count"] == 0
        assert (
            h.read_account(api, account["id"], ADMIN_HEADERS)["credit_balance_cents"]
            == 800
        )


class TestReconcileNeedsEveryCountClosed:
    """The quarter's guard reads the other aggregate's state, not its own."""

    def test_a_counting_visit_blocks_the_quarter_until_it_closes(self, api):
        """The identical RECONCILE call fails and then succeeds.

        PRD: "Reconciliation — `RECONCILE` — moves the quarter `OPEN → RECONCILING` and
        requires the field work to be finished: no visit whose `visit_date` lies inside the
        closed interval from `start_date` to `end_date` may still have `count_status` `OPEN`,
        `COUNTING` or `JAM_HOLD`, and unfinished counting blocks the action with
        `ERR_PERIOD_HAS_OPEN_VISITS`."

        PRD: "Reconciliation then books two ledger lines, both with `container_count` 0 and
        `source_kind` `PROGRAM_ACTION` because neither represents containers moving: one with
        `entry_type` `HANDLING_FEE` and `amount_cents` equal to `handling_fee_cents`, and one
        with `entry_type` `UNREDEEMED_SWEEP` and `amount_cents` equal to the negative of
        `sweep_to_funding_cents`."

        Design: Corner/errors/reconcile_refuses_a_period_with_an_unclosed_visit
        """
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=1000)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        visit = h.open_center_machine_visit(api, center["id"], machine["id"])
        h.add_lot(
            api,
            visit["id"],
            product["id"],
            100,
            headers,
            expected_visit_version=visit["version"],
        )

        validate_error(
            api.post_period_action(
                period["id"], f.period_action_payload("RECONCILE"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_PERIOD_HAS_OPEN_VISITS.value,
            expected_status=409,
        )
        blocked = h.read_period(api, period["id"])
        assert blocked["status"] == "OPEN"
        assert blocked["reconciled_at"] is None
        assert blocked["funding_status"] == "UNSETTLED"
        assert blocked["version"] == 1

        h.close_count(api, visit["id"], headers)
        reconciling = h.period_action(api, period["id"], "RECONCILE")
        assert reconciling["status"] == "RECONCILING"
        assert_stamped_at(reconciling["reconciled_at"], INSTANT)

        entries = h.list_ledger(api, period["id"])
        assert [entry["entry_type"] for entry in entries] == [
            "HANDLING_FEE",
            "UNREDEEMED_SWEEP",
        ]


class TestOpenVisitsBlockClosureAndExemption:
    """Two aggregates share one in-flight-work guard and two codes."""

    def test_the_centre_and_the_store_both_wait_for_their_counts(self, api):
        """Closing both counts clears both refusals at once.

        PRD: "The precondition is that no visit of this centre still has `count_status`
        `OPEN`, `COUNTING` or `JAM_HOLD`; unfinished counting blocks closure with
        `ERR_CENTER_HAS_OPEN_VISITS`."

        PRD: "First, the store must have no visit still sitting in `count_status` `OPEN`,
        `COUNTING` or `JAM_HOLD`; unfinished counting blocks the claim with
        `ERR_RETAILER_HAS_OPEN_VISITS`."

        PRD: "And a visit may legitimately be closed with no lots at all: closing from
        `OPEN → COUNTED` runs the same valuation over an empty lot set, yielding `capped_count`
        0, `shrink_adjustment_count` 0, `payable_count` 0, `refused_over_limit_count` 0 and
        `payout_cents` 0, and the daily bucket step leaves `containers_redeemed_today`
        unchanged."

        Design: Corner/errors/open_visits_block_center_closure_and_exemption_claims
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        retailer = h.create_retailer(api)
        center_headers = h.make_center_headers(center["id"])
        retailer_headers = make_retailer_headers(retailer["id"])

        center_visit = h.open_center_hand_visit(api, center["id"])
        retailer_visit = h.open_retailer_visit(api, retailer["id"])

        validate_error(
            api.post_center_status_change(
                center["id"], f.center_status_change_payload("CLOSE"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_CENTER_HAS_OPEN_VISITS.value,
            expected_status=409,
        )
        assert h.read_center(api, center["id"], center_headers)["status"] == "OPERATIONAL"

        validate_error(
            api.post_exemption_action(
                retailer["id"],
                f.exemption_action_payload("CLAIM_EXEMPTION"),
                retailer_headers,
            ),
            ApiErrorId.ERR_RETAILER_HAS_OPEN_VISITS.value,
            expected_status=409,
        )
        blocked = h.read_retailer(api, retailer["id"], retailer_headers)
        assert blocked["obligation_status"] == "OBLIGATED"
        assert blocked["nearest_center_id"] is None

        for visit_id, headers in (
            (center_visit["id"], center_headers),
            (retailer_visit["id"], retailer_headers),
        ):
            closed = h.close_count(api, visit_id, headers)
            assert closed["count_status"] == "COUNTED"
            assert closed["payout_cents"] == 0

        granted = h.exemption_action(
            api, retailer["id"], "CLAIM_EXEMPTION", retailer_headers
        )
        assert granted["obligation_status"] == "EXEMPT"
        assert granted["nearest_center_distance_miles"] == 1.00


class TestContaminationCeilingIsInclusive:
    """Six per cent cannot be baled; five per cent can."""

    def test_a_dirty_batch_stays_sorted_while_a_clean_one_reaches_baled(self, api):
        """0.06 is refused at BALE and 0.05 passes, so the limit is inclusive.

        PRD: "Baling is only permitted on a clean enough batch: `contamination_pct` must be
        at most 0.05, and a batch above five per cent contamination is refused with
        `ERR_CONTAMINATION_LIMIT_EXCEEDED`."

        PRD: "Baling stores the weights, sets `bale_count` to the number of weights supplied,
        and sets `gross_weight_kg` to the sum of those weights rounded to 2 decimal places."

        PRD: "Plant processing drives the batch forward through two named actions, `SORT` and
        `BALE`, each requested by naming an `action` and each incrementing the batch's `version`
        by 1."

        Design: Corner/errors/baling_a_dirty_batch_exceeds_the_contamination_limit
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [200]
        )
        dirty = h.create_batch(api, center["id"], 100)
        clean = h.create_batch(api, center["id"], 100, batch_code="BATCH-1002")

        sorted_dirty = h.sort_batch(api, dirty["id"], 0.06)
        assert sorted_dirty["status"] == "SORTED"
        assert sorted_dirty["contamination_pct"] == 0.06

        validate_error(
            api.post_batch_processing_action(
                dirty["id"], f.bale_action_payload([50.0]), PLANT_COUNTER_HEADERS
            ),
            ApiErrorId.ERR_CONTAMINATION_LIMIT_EXCEEDED.value,
            expected_status=422,
        )
        refused = h.read_batch(api, dirty["id"], PLANT_COUNTER_HEADERS)
        assert refused["status"] == "SORTED"
        assert refused["version"] == sorted_dirty["version"]

        assert h.sort_batch(api, clean["id"], 0.05)["contamination_pct"] == 0.05
        baled = h.bale_batch(api, clean["id"], [50.0])
        assert baled["status"] == "BALED"
        assert baled["bale_count"] == 1
        assert baled["gross_weight_kg"] == 50.00


class TestPayoutCannotExceedTheDrawer:
    """Approval is free; payment is not."""

    def test_a_thin_drawer_stops_the_payment_and_leaves_the_books_alone(self, api):
        """100 cents cannot settle a 1000-cent payout, and nothing moves.

        PRD: "At a redemption centre the drawer must actually hold the money:
        `cash_drawer_balance_cents` must be at least the visit's `payout_cents`, or the request
        is refused with `ERR_INSUFFICIENT_CASH_DRAWER`."

        PRD: "Activation copies `opening_cash_cents` into `cash_drawer_balance_cents` and
        clears `suspension_reason` to null."

        Design: Corner/errors/payout_cannot_exceed_the_cash_in_the_drawer
        """
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        h.initiate_deposits(
            api, distributor["id"], product["id"], 300, period["id"]
        )
        fleet = h.create_operational_center(
            api,
            {"site_name": "Thin Drawer Center", "opening_cash_cents": 100},
        )
        center, machine = fleet["center"], fleet["machine"]
        headers = h.make_center_headers(center["id"])

        visit = h.create_counted_center_visit(
            api, center["id"], machine["id"], product["id"], [100]
        )
        h.payout_action(api, visit["id"], "APPROVE", headers)

        validate_error(
            api.post_payout_action(
                visit["id"], f.payout_action_payload("PAY"), headers
            ),
            ApiErrorId.ERR_INSUFFICIENT_CASH_DRAWER.value,
            expected_status=422,
        )

        unpaid = h.read_visit(api, visit["id"], headers)
        assert unpaid["payout_status"] == "APPROVED"
        assert unpaid["payout_cents"] == 1000
        assert unpaid["paid_at"] is None
        assert h.read_center(api, center["id"], headers)["cash_drawer_balance_cents"] == 100

        entries, meta = validate_paginated(
            api.list_ledger_entries(period["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1
        assert entries[0]["entry_type"] == "DEPOSIT_INITIATED"
        assert entries[0]["amount_cents"] == 3000

        stored_period = h.read_period(api, period["id"])
        assert stored_period["redemptions_paid_cents"] == 0
        assert stored_period["outstanding_liability_cents"] == 3000


class TestWithdrawalsAndClosureRespectTheBalance:
    """600 cannot be taken from 500, and 500 cannot be left behind."""

    def test_the_exact_withdrawal_satisfies_both_fiscal_rungs_at_once(self, api):
        """An over-withdrawal and a premature close both fail; withdrawing 500 clears both.

        PRD: "For a `WITHDRAW` or `CLAWBACK` credit action, the account's
        `credit_balance_cents` is at least the requested `amount_cents` → otherwise
        `ERR_INSUFFICIENT_CREDIT_BALANCE` (HTTP 422)."

        PRD: "The account's `credit_balance_cents` must equal 0, and none of the account's
        bag drops may still sit in `DROPPED`, `COUNTED` or `DISPUTED`; a non-zero balance or an
        unsettled bag blocks the close with `ERR_ACCOUNT_BALANCE_NONZERO`."

        PRD: "On success `bag_drop_enrolled` is set to false in both branches."

        Design: Corner/errors/withdrawals_and_closure_respect_the_credit_balance
        """
        h.set_clock(api, INSTANT)
        account = h.create_account(api)
        h.post_credit_action(
            api,
            account["id"],
            "MANUAL_GRANT",
            500,
            ADMIN_HEADERS,
            expected_version=account["version"],
        )
        funded = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert funded["credit_balance_cents"] == 500

        validate_error(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload("WITHDRAW", 600, funded["version"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INSUFFICIENT_CREDIT_BALANCE.value,
            expected_status=422,
        )
        validate_error(
            api.post_account_status_change(
                account["id"], f.account_status_change_payload("CLOSE"), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_ACCOUNT_BALANCE_NONZERO.value,
            expected_status=409,
        )

        unchanged = h.read_account(api, account["id"], ADMIN_HEADERS)
        assert unchanged["credit_balance_cents"] == 500
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["version"] == funded["version"]

        entry = validate_success(
            api.post_credit_action(
                account["id"],
                f.credit_action_payload("WITHDRAW", 500, funded["version"]),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert entry["amount_cents"] == -500
        assert entry["balance_after_cents"] == 0

        closed = h.account_status_change(api, account["id"], "CLOSE")
        assert closed["status"] == "CLOSED"
        assert closed["bag_drop_enrolled"] is False

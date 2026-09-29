"""Multi-hop cascades across the mill graph, and the cross-cutting platform contract.

Covers the dye-lot rejection cascade down through rolls, allocations, orders and the
style replenishment flag; the style-discontinue cascade that releases an account's
credit hold; the order-cancellation leg that restores a production run's linear
yardage; the runout style that auto-discontinues when its last order closes; and the
authentication / authorization / not-found contract across roles and resources.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    build_user_headers,
    factories,
    fixtures,
    is_iso8601_timestamp,
    make_dealer_buyer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]
EXTRUDER = TEST_USERS["extrusion_operator_headers"]
DYER = TEST_USERS["dye_house_operator_headers"]
QA = TEST_USERS["qa_lab_technician_headers"]
CERTIFIER = TEST_USERS["certification_officer_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]

# A well-formed UUID that is deliberately never minted by any setup below.
PROBE_ID = "00000000-0000-4000-8000-000000000404"

RUN_WINDOW_OPEN = "2026-08-05T08:00:00Z"


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _list_all(list_method, headers, params=None):
    """Read one generous page off a list endpoint, returning (data, meta)."""
    query = {"limit": 100, "offset": 0}
    query.update(params or {})
    return validate_paginated(list_method(headers, params=query))


def _run_yardage(api, production_run_id):
    """The run's linear-yard ledger and the yardage doffed off it.

    Returns ``(ledger_total, doffed_total)`` where the ledger total is the sum of
    ``available_yards`` over non-scrapped rolls, plus the ``yards`` on their
    RESERVED / CUT / SHIPPED allocation lines, plus ``initial_yards`` over scrapped
    rolls; and the doffed total counts only the run's non-remnant rolls.
    """
    rolls, _ = _list_all(
        api.list_roll_goods, PLANNER, {"production_run_id": production_run_id}
    )
    ledger = 0.0
    for roll in rolls:
        if roll["inventory_status"] == "SCRAPPED":
            ledger += roll["initial_yards"]
            continue
        ledger += roll["available_yards"]
        lines, _ = _list_all(
            api.list_cut_allocations, PLANNER, {"roll_good_id": roll["id"]}
        )
        ledger += sum(
            line["yards"]
            for line in lines
            if line["status"] in ("RESERVED", "CUT", "SHIPPED")
        )
    doffed = sum(r["initial_yards"] for r in rolls if not r["is_remnant"])
    return round(ledger, 1), round(doffed, 1)


def _setup_committed_piece_dyed_order():
    """A piece-dyed 400.0-yard roll off an APPROVED lot, 300.0 yards committed.

    Returns the fixture context extended with ``allocation``: the single RESERVED
    line of the ALLOCATED cut order.
    """
    ctx = fixtures.setup_allocated_cut_order(
        piece_dyed=True,
        roll_overrides={"initial_yards": 400.0},
        order_overrides={"requested_yards": 300.0},
    )
    lines = ctx["allocations"]
    assert len(lines) == 1, f"expected one allocation line, got {len(lines)}"
    ctx["allocation"] = lines[0]
    return ctx


def _setup_discontinue_credit_scenario():
    """Two CUSTOM orders plus one RUNNING_LINE order that hold the account exactly
    on its credit limit.

    The three reservations are 513000, 42750 and 513000 cents, so a limit of
    1068750 cents admits all three (the admission gate is inclusive) and leaves the
    account on CREDIT_HOLD (the posture comparison is inclusive too).
    """
    style = fixtures.create_active_style(style_code="ST-SD-01")
    account = fixtures.create_account(
        account_code="AC-01", account_type="BUILDER", credit_limit_cents=1068750
    )
    custom_one = fixtures.create_cut_order(
        account["id"],
        style["id"],
        order_code="CO-01",
        order_type="CUSTOM",
        requested_yards=120.0,
        shade_tolerance="SINGLE_LOT",
    )
    running_line = fixtures.create_cut_order(
        account["id"],
        style["id"],
        order_code="CO-03",
        order_type="RUNNING_LINE",
        requested_yards=10.0,
        shade_tolerance="ANY",
    )
    custom_two = fixtures.create_cut_order(
        account["id"],
        style["id"],
        order_code="CO-02",
        order_type="CUSTOM",
        requested_yards=120.0,
        shade_tolerance="SINGLE_LOT",
    )
    return {
        "style": style,
        "account": account,
        "custom_one": custom_one,
        "custom_two": custom_two,
        "running_line": running_line,
    }


def _setup_runout_candidate_style():
    """An ACTIVE style with no runs and one SUBMITTED RUNNING_LINE order."""
    style = fixtures.create_active_style(style_code="ST-SD-01")
    account = fixtures.create_account(
        account_code="AC-01", account_type="DEALER", credit_limit_cents=100000000
    )
    order = fixtures.create_cut_order(
        account["id"],
        style["id"],
        order_code="CO-01",
        order_type="RUNNING_LINE",
        requested_yards=100.0,
        shade_tolerance="ANY",
    )
    return {"style": style, "account": account, "cut_order": order}


# ---------------------------------------------------------------------------
# The five-hop dye-lot rejection cascade
# ---------------------------------------------------------------------------


class TestDyeLotRejectionCascade:
    def test_reject_scraps_the_roll_voids_the_line_and_backorders_the_order(self, api):
        """Rejecting an APPROVED lot scraps its roll, voids the RESERVED line and drops the order to BACKORDERED.

        PRD: "The first hop scraps the goods: every roll good whose dye lot is this lot
        and whose `inventory_status` is not already `SCRAPPED` has its `qa_status` set to
        `FAILED`, its `inventory_status` set to `SCRAPPED` and its `available_yards`
        forced to 0"; "The second hop, caused by the first, voids commitments: every
        allocation line whose roll is one of those newly scrapped rolls and whose status
        is `RESERVED` transitions `RESERVED` to `VOIDED`."; "The third hop, caused by the
        second, reopens orders: every cut order referenced by a voided line recomputes
        its `allocated_yards`, and each such order whose status is `ALLOCATED` and whose
        `allocated_yards` now falls strictly below its `requested_yards` transitions
        `ALLOCATED` to `BACKORDERED`."

        Design: Difficulty/transitive_cascade/dye_lot_rejection_five_hop_cascade_to_style_replenishment_flag
        """
        ctx = _setup_committed_piece_dyed_order()
        lot_id = ctx["dye_lot"]["id"]
        roll_id = ctx["roll_good"]["id"]
        order_id = ctx["cut_order"]["id"]
        allocation_id = ctx["allocation"]["id"]

        assert ctx["cut_order"]["status"] == "ALLOCATED", (
            "setup must leave the order ALLOCATED, got "
            f"{ctx['cut_order']['status']}"
        )

        rejected = validate_success(
            api.disposition_dye_lot(
                lot_id, factories.disposition_dye_lot_payload("REJECT"), DYER
            ),
            expected_status=200,
        )
        assert rejected["status"] == "REJECTED", (
            f"expected REJECTED, got {rejected['status']} after the reject disposition"
        )

        roll = fixtures.refresh_roll_good(roll_id)
        assert roll["qa_status"] == "FAILED", (
            f"expected qa_status FAILED, got {roll['qa_status']} after the reject"
        )
        assert roll["inventory_status"] == "SCRAPPED", (
            f"expected inventory_status SCRAPPED, got {roll['inventory_status']} "
            "after the reject"
        )
        assert roll["available_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected available_yards 0.0, got {roll['available_yards']} on a "
            "scrapped roll"
        )

        line = validate_success(api.get_cut_allocation(allocation_id, PLANNER))
        assert line["status"] == "VOIDED", (
            f"expected the RESERVED line to be VOIDED, got {line['status']}"
        )

        order = fixtures.refresh_cut_order(order_id)
        assert order["status"] == "BACKORDERED", (
            f"expected BACKORDERED, got {order['status']} after its only line voided"
        )
        assert order["allocated_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected allocated_yards 0.0, got {order['allocated_yards']} after the "
            "line was voided"
        )

    def test_reject_charges_scrapped_yards_and_zeroes_both_uncommitted_figures(
        self, api
    ):
        """The lot's scrap charge is initial_yards less shipped yards, driving both uncommitted figures to 0.0.

        PRD: "for each such roll the lot's `scrapped_yards` increases by that roll's
        scrap charge, defined as the roll's `initial_yards` less the yards already
        shipped off that roll"; "In both sums, allocation lines drawn from rolls whose
        `inventory_status` is `SCRAPPED` are excluded, because that yardage has already
        been charged to `scrapped_yards`."

        Design: Difficulty/transitive_cascade/dye_lot_rejection_five_hop_cascade_to_style_replenishment_flag
        """
        ctx = _setup_committed_piece_dyed_order()
        lot_id = ctx["dye_lot"]["id"]

        validate_success(
            api.disposition_dye_lot(
                lot_id, factories.disposition_dye_lot_payload("REJECT"), DYER
            ),
            expected_status=200,
        )

        lot = fixtures.refresh_dye_lot(lot_id)
        assert lot["scrapped_yards"] == pytest.approx(400.0, abs=0.01), (
            f"expected scrapped_yards 400.0, got {lot['scrapped_yards']} for a "
            "400.0-yard roll with nothing shipped"
        )
        assert lot["uncommitted_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected uncommitted_yards 0.0, got {lot['uncommitted_yards']} after the "
            "whole lot was scrapped"
        )
        assert lot["shipped_basis_uncommitted_yards"] == pytest.approx(0.0, abs=0.01), (
            "expected shipped_basis_uncommitted_yards 0.0, got "
            f"{lot['shipped_basis_uncommitted_yards']} after the whole lot was scrapped"
        )

    def test_reject_recomputes_the_style_backorder_posture_and_raises_the_flag(
        self, api
    ):
        """The reopened 300.0-yard order lifts open_backorder_yards to 300.0 and sets REPLENISH_REQUIRED.

        PRD: "The fourth hop, caused by the third, recomputes each affected style's
        `open_backorder_yards`."; "The fifth hop, caused by the fourth, raises the alarm:
        each such style whose `open_backorder_yards` reaches or exceeds 250 yards sets
        its `replenishment_flag` to `REPLENISH_REQUIRED`."

        Design: Difficulty/transitive_cascade/dye_lot_rejection_five_hop_cascade_to_style_replenishment_flag
        """
        ctx = _setup_committed_piece_dyed_order()
        style_id = ctx["style"]["id"]

        before = fixtures.refresh_style(style_id)
        assert before["replenishment_flag"] == "NONE", (
            "a fully allocated style must not be flagged before the reject, got "
            f"{before['replenishment_flag']}"
        )

        validate_success(
            api.disposition_dye_lot(
                ctx["dye_lot"]["id"],
                factories.disposition_dye_lot_payload("REJECT"),
                DYER,
            ),
            expected_status=200,
        )

        style = fixtures.refresh_style(style_id)
        assert style["open_backorder_yards"] == pytest.approx(300.0, abs=0.01), (
            f"expected open_backorder_yards 300.0, got {style['open_backorder_yards']} "
            "for one BACKORDERED order of 300.0 requested and 0.0 allocated yards"
        )
        assert style["replenishment_flag"] == "REPLENISH_REQUIRED", (
            f"expected REPLENISH_REQUIRED, got {style['replenishment_flag']} at "
            "300.0 open backorder yards"
        )

    def test_reject_zeroes_the_invoice_but_leaves_the_credit_hold_untouched(self, api):
        """With every line voided the settlement collapses to 0, while reserved_credit_cents and credit_used_cents stay at 1282500.

        PRD: "with every line voided, the zero-line guard drives `gross_cents`,
        `freight_cents`, `remnant_credit_cents` and `net_invoice_cents` all to 0"; "But
        the order's `reserved_credit_cents` and the account's `credit_used_cents` are
        left completely untouched, because the credit hold follows `requested_yards`,
        not `allocated_yards`."

        Design: Difficulty/transitive_cascade/dye_lot_rejection_five_hop_cascade_to_style_replenishment_flag
        """
        ctx = _setup_committed_piece_dyed_order()
        order_id = ctx["cut_order"]["id"]
        account_id = ctx["account"]["id"]

        validate_success(
            api.disposition_dye_lot(
                ctx["dye_lot"]["id"],
                factories.disposition_dye_lot_payload("REJECT"),
                DYER,
            ),
            expected_status=200,
        )

        order = fixtures.refresh_cut_order(order_id)
        assert order["gross_cents"] == 0, (
            f"expected gross_cents 0, got {order['gross_cents']} with every line voided"
        )
        assert order["freight_cents"] == 0, (
            f"expected freight_cents 0, got {order['freight_cents']} on a line-less order"
        )
        assert order["remnant_credit_cents"] == 0, (
            f"expected remnant_credit_cents 0, got {order['remnant_credit_cents']} on a "
            "line-less order"
        )
        assert order["net_invoice_cents"] == 0, (
            f"expected net_invoice_cents 0, got {order['net_invoice_cents']} on a "
            "line-less order"
        )

        assert order["reserved_credit_cents"] == 1282500, (
            f"expected reserved_credit_cents 1282500, got "
            f"{order['reserved_credit_cents']} — the hold follows requested_yards"
        )
        account = fixtures.refresh_account(account_id)
        assert account["credit_used_cents"] == 1282500, (
            f"expected credit_used_cents 1282500, got {account['credit_used_cents']} — "
            "the cascade must not release the hold"
        )


# ---------------------------------------------------------------------------
# The three-hop style-discontinue cascade
# ---------------------------------------------------------------------------


class TestStyleDiscontinueReleasesCredit:
    def test_discontinue_cancels_the_custom_orders_and_zeroes_their_reservations(
        self, api
    ):
        """Discontinuing the style cancels both SUBMITTED CUSTOM orders and zeroes their reserved_credit_cents.

        PRD: "In both cases the style's `status` becomes `RUNOUT` and the side-effect
        chain is identical."; "The first hop cancels every cut order of this style whose
        `order_type` is `CUSTOM` and whose status is `SUBMITTED`, moving each from
        `SUBMITTED` to `CANCELLED`."; "The second hop, caused by the first, drives the
        account credit ledger: each such cancellation decrements the buying account's
        `credit_used_cents` by that order's `reserved_credit_cents` and then sets the
        order's own `reserved_credit_cents` to 0."

        Design: Difficulty/transitive_cascade/style_discontinue_three_hop_cascade_releases_account_credit_hold
        """
        ctx = _setup_discontinue_credit_scenario()

        assert ctx["custom_one"]["reserved_credit_cents"] == 513000, (
            "120.0 yards at 4275 cents must reserve 513000 cents, got "
            f"{ctx['custom_one']['reserved_credit_cents']}"
        )
        assert ctx["running_line"]["reserved_credit_cents"] == 42750, (
            "10.0 yards at 4275 cents must reserve 42750 cents, got "
            f"{ctx['running_line']['reserved_credit_cents']}"
        )

        style = validate_success(
            api.discontinue_style(
                ctx["style"]["id"],
                factories.discontinue_style_payload(reason="style runout announced"),
                PLANNER,
            ),
            expected_status=200,
        )
        assert style["status"] == "RUNOUT", (
            f"expected RUNOUT, got {style['status']} after discontinuation"
        )

        for label, order in (
            ("CO-01", ctx["custom_one"]),
            ("CO-02", ctx["custom_two"]),
        ):
            refreshed = fixtures.refresh_cut_order(order["id"])
            assert refreshed["status"] == "CANCELLED", (
                f"expected {label} CANCELLED, got {refreshed['status']} after the "
                "discontinue cascade"
            )
            assert refreshed["reserved_credit_cents"] == 0, (
                f"expected {label} reserved_credit_cents 0, got "
                f"{refreshed['reserved_credit_cents']} after cancellation"
            )

        account = fixtures.refresh_account(ctx["account"]["id"])
        assert account["credit_used_cents"] == 42750, (
            f"expected credit_used_cents 42750, got {account['credit_used_cents']} — "
            "only the RUNNING_LINE hold should survive"
        )

    def test_discontinue_lifts_the_account_off_credit_hold(self, api):
        """Releasing the two custom holds drops credit_used_cents below the limit and flips CREDIT_HOLD to ACTIVE.

        PRD: "the account reads `CREDIT_HOLD` when `credit_used_cents` is greater than or
        equal to `credit_limit_cents` and `ACTIVE` when it is strictly below"; "The third
        hop, caused by the second, re-evaluates account posture: any account whose
        `credit_used_cents` now sits strictly below its `credit_limit_cents` and whose
        `status` is `CREDIT_HOLD` transitions `CREDIT_HOLD` to `ACTIVE`."

        Design: Difficulty/transitive_cascade/style_discontinue_three_hop_cascade_releases_account_credit_hold
        """
        ctx = _setup_discontinue_credit_scenario()

        before = fixtures.refresh_account(ctx["account"]["id"])
        assert before["credit_used_cents"] == 1068750, (
            "the three reservations must total 1068750 cents, got "
            f"{before['credit_used_cents']}"
        )
        assert before["status"] == "CREDIT_HOLD", (
            f"expected CREDIT_HOLD, got {before['status']} with credit_used_cents "
            f"{before['credit_used_cents']} exactly on the limit "
            f"{before['credit_limit_cents']}"
        )

        validate_success(
            api.discontinue_style(
                ctx["style"]["id"],
                factories.discontinue_style_payload(reason="style runout announced"),
                PLANNER,
            ),
            expected_status=200,
        )

        after = fixtures.refresh_account(ctx["account"]["id"])
        assert after["credit_used_cents"] == 42750, (
            f"expected credit_used_cents 42750, got {after['credit_used_cents']} after "
            "the two custom holds were released"
        )
        assert after["status"] == "ACTIVE", (
            f"expected ACTIVE, got {after['status']} with credit_used_cents "
            f"{after['credit_used_cents']} strictly below the limit "
            f"{after['credit_limit_cents']}"
        )

    def test_discontinue_leaves_the_running_line_order_and_its_hold_alone(self, api):
        """The RUNNING_LINE order stays SUBMITTED with its full 42750-cent hold; only CUSTOM orders cascade.

        PRD: "The first hop cancels every cut order of this style whose `order_type` is
        `CUSTOM` and whose status is `SUBMITTED`, moving each from `SUBMITTED` to
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/style_discontinue_three_hop_cascade_releases_account_credit_hold
        """
        ctx = _setup_discontinue_credit_scenario()

        validate_success(
            api.discontinue_style(
                ctx["style"]["id"],
                factories.discontinue_style_payload(reason="style runout announced"),
                PLANNER,
            ),
            expected_status=200,
        )

        running_line = fixtures.refresh_cut_order(ctx["running_line"]["id"])
        assert running_line["status"] == "SUBMITTED", (
            f"expected the RUNNING_LINE order to stay SUBMITTED, got "
            f"{running_line['status']}"
        )
        assert running_line["reserved_credit_cents"] == 42750, (
            "expected the RUNNING_LINE hold to stay at 42750 cents, got "
            f"{running_line['reserved_credit_cents']}"
        )


# ---------------------------------------------------------------------------
# Cancellation restores a production run's linear yardage
# ---------------------------------------------------------------------------


class TestOrderCancelRestoresRunYardage:
    def test_allocating_moves_yards_from_the_roll_onto_the_line(self, api):
        """The allocation debits the roll's 200.0 available yards and credits the line with the identical figure.

        PRD: "Committing yards debits a roll's `available_yards` and credits the
        allocation's `yards` by the identical figure; cancelling the order releases the
        allocation and credits exactly that figure back."; "an allocation that drives
        `available_yards` to exactly zero moves a passed roll `AVAILABLE` to
        `COMMITTED`, taking it out of the candidate pool, and the release or voiding of
        lines that returns yardage moves it `COMMITTED` back to `AVAILABLE`"

        Design: Difficulty/compensating_invariant/order_cancel_restores_production_run_linear_yardage
        """
        ctx = fixtures.setup_submitted_cut_order(
            account_overrides={
                "account_code": "AC-01",
                "account_type": "COMMERCIAL",
                "credit_limit_cents": 100000000,
            },
            roll_overrides={"initial_yards": 200.0},
            order_overrides={"requested_yards": 200.0},
        )
        roll_id = ctx["roll_good"]["id"]
        order_id = ctx["cut_order"]["id"]

        before = fixtures.refresh_roll_good(roll_id)
        assert before["available_yards"] == pytest.approx(200.0, abs=0.01), (
            f"expected available_yards 200.0, got {before['available_yards']} before "
            "the allocate"
        )
        assert before["inventory_status"] == "AVAILABLE", (
            f"expected AVAILABLE, got {before['inventory_status']} before the allocate"
        )

        order = validate_success(
            api.allocate_cut_order(order_id, PLANNER), expected_status=200
        )
        assert order["status"] == "ALLOCATED", (
            f"expected ALLOCATED, got {order['status']} after the waterfall closed the "
            "order out"
        )

        lines = fixtures.list_allocations_for_order(order_id)
        assert len(lines) == 1, f"expected one allocation line, got {len(lines)}"
        line = lines[0]
        assert line["yards"] == pytest.approx(200.0, abs=0.01), (
            f"expected the line to carry 200.0 yards, got {line['yards']}"
        )
        assert line["status"] == "RESERVED", (
            f"expected RESERVED, got {line['status']} on a fresh allocation line"
        )

        after = fixtures.refresh_roll_good(roll_id)
        assert after["available_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected available_yards 0.0, got {after['available_yards']} after "
            "committing every yard"
        )
        assert after["inventory_status"] == "COMMITTED", (
            f"expected COMMITTED, got {after['inventory_status']} after the roll was "
            "drawn to zero"
        )

    def test_allocate_then_cancel_leaves_the_run_yardage_bit_identical(self, api):
        """The run's linear-yard ledger reads 200.0 before the allocate, after the allocate and after the cancel.

        PRD: "For any run, the sum of `available_yards` across its non-scrapped rolls,
        plus the sum of `yards` across allocations on those rolls in status `RESERVED`,
        `CUT` or `SHIPPED`, plus the sum of `initial_yards` across its scrapped rolls,
        must always equal the total `initial_yards` doffed off that run counting only its
        non-remnant rolls."; "The forward action and its compensating action must leave
        the run's total yardage bit-identical, on figures rounded to 1 decimal place."

        Design: Difficulty/compensating_invariant/order_cancel_restores_production_run_linear_yardage
        """
        ctx = fixtures.setup_submitted_cut_order(
            account_overrides={
                "account_code": "AC-01",
                "account_type": "COMMERCIAL",
                "credit_limit_cents": 100000000,
            },
            roll_overrides={"initial_yards": 200.0},
            order_overrides={"requested_yards": 200.0},
        )
        run_id = ctx["run"]["id"]
        order_id = ctx["cut_order"]["id"]

        pre_ledger, pre_doffed = _run_yardage(api, run_id)
        assert pre_ledger == pytest.approx(200.0, abs=0.01), (
            f"expected a 200.0-yard run ledger before the allocate, got {pre_ledger}"
        )
        assert pre_ledger == pytest.approx(pre_doffed, abs=0.01), (
            f"run ledger {pre_ledger} must equal the doffed total {pre_doffed} before "
            "the allocate"
        )

        validate_success(
            api.allocate_cut_order(order_id, PLANNER), expected_status=200
        )
        mid_ledger, mid_doffed = _run_yardage(api, run_id)
        assert mid_ledger == pytest.approx(200.0, abs=0.01), (
            f"expected a 200.0-yard run ledger after the allocate, got {mid_ledger}"
        )
        assert mid_ledger == pytest.approx(mid_doffed, abs=0.01), (
            f"run ledger {mid_ledger} must equal the doffed total {mid_doffed} after "
            "the allocate"
        )

        validate_success(
            api.cancel_cut_order(
                order_id,
                factories.cancel_cut_order_payload(
                    reason="job cancelled by the general contractor"
                ),
                PLANNER,
            ),
            expected_status=200,
        )
        post_ledger, post_doffed = _run_yardage(api, run_id)
        assert post_ledger == pre_ledger, (
            f"run yardage must be bit-identical across the compensating leg: was "
            f"{pre_ledger}, now {post_ledger} after the cancel"
        )
        assert post_ledger == pytest.approx(post_doffed, abs=0.01), (
            f"run ledger {post_ledger} must equal the doffed total {post_doffed} after "
            "the cancel"
        )

    def test_cancel_releases_the_line_and_returns_the_roll_to_available(self, api):
        """The cancel releases the RESERVED line, returns 200.0 yards to the roll and mints no remnant child.

        PRD: "Every line of the order in `RESERVED` transitions `RESERVED` to
        `RELEASED`."; "Each affected roll's `available_yards` is recomputed, and a roll
        that regains yardage flips `COMMITTED` back to `AVAILABLE`"

        Design: Difficulty/compensating_invariant/order_cancel_restores_production_run_linear_yardage
        """
        ctx = fixtures.setup_submitted_cut_order(
            account_overrides={
                "account_code": "AC-01",
                "account_type": "COMMERCIAL",
                "credit_limit_cents": 100000000,
            },
            roll_overrides={"initial_yards": 200.0},
            order_overrides={"requested_yards": 200.0},
        )
        roll_id = ctx["roll_good"]["id"]
        order_id = ctx["cut_order"]["id"]

        validate_success(
            api.allocate_cut_order(order_id, PLANNER), expected_status=200
        )
        line_id = fixtures.list_allocations_for_order(order_id)[0]["id"]

        cancelled = validate_success(
            api.cancel_cut_order(
                order_id,
                factories.cancel_cut_order_payload(
                    reason="job cancelled by the general contractor"
                ),
                PLANNER,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled['status']} after the cancel"
        )

        line = validate_success(api.get_cut_allocation(line_id, PLANNER))
        assert line["status"] == "RELEASED", (
            f"expected the RESERVED line to be RELEASED, got {line['status']}"
        )

        roll = fixtures.refresh_roll_good(roll_id)
        assert roll["available_yards"] == pytest.approx(200.0, abs=0.01), (
            f"expected available_yards back at 200.0, got {roll['available_yards']} "
            "after the cancel"
        )
        assert roll["inventory_status"] == "AVAILABLE", (
            f"expected COMMITTED to flip back to AVAILABLE, got "
            f"{roll['inventory_status']} after the cancel"
        )
        assert roll["qa_status"] == "PASSED", (
            f"expected qa_status PASSED to be untouched, got {roll['qa_status']} after "
            "the cancel"
        )

        rolls, _ = _list_all(
            api.list_roll_goods, PLANNER, {"production_run_id": ctx["run"]["id"]}
        )
        children = [r for r in rolls if r.get("parent_roll_id") == roll_id]
        assert children == [], (
            f"a cancel must mint no remnant child, found {len(children)} child roll(s)"
        )


# ---------------------------------------------------------------------------
# Runout auto-discontinuation
# ---------------------------------------------------------------------------


class TestRunoutAutoDiscontinuation:
    def test_cancelling_the_last_open_order_discontinues_the_runout_style(self, api):
        """Discontinue parks the style in RUNOUT while its RUNNING_LINE order is open; cancelling that order reaches DISCONTINUED and frees the credit.

        PRD: "After every cut-order ship and every cut-order cancellation, the server
        checks each `RUNOUT` style: when no roll good produced by any run of the style
        has an `inventory_status` of `AVAILABLE` or `COMMITTED`, and no cut order of the
        style has a status of `SUBMITTED`, `ALLOCATED`, `BACKORDERED` or `CUT`, the style
        transitions `RUNOUT` to `DISCONTINUED`, which is terminal."

        Design: Corner/state_machines/runout_style_auto_discontinues_when_its_last_order_closes
        """
        ctx = _setup_runout_candidate_style()
        style_id = ctx["style"]["id"]
        order_id = ctx["cut_order"]["id"]

        runout = validate_success(
            api.discontinue_style(
                style_id,
                factories.discontinue_style_payload(reason="line retired"),
                PLANNER,
            ),
            expected_status=200,
        )
        assert runout["status"] == "RUNOUT", (
            f"expected RUNOUT, got {runout['status']} while one order is still open"
        )

        parked = fixtures.refresh_cut_order(order_id)
        assert parked["status"] == "SUBMITTED", (
            f"expected the RUNNING_LINE order to stay SUBMITTED, got {parked['status']} "
            "after the discontinue"
        )

        cancelled = validate_success(
            api.cancel_cut_order(
                order_id,
                factories.cancel_cut_order_payload(reason="dealer withdrew"),
                PLANNER,
            ),
            expected_status=200,
        )
        assert cancelled["status"] == "CANCELLED", (
            f"expected CANCELLED, got {cancelled['status']} after the cancel"
        )
        assert cancelled["reserved_credit_cents"] == 0, (
            f"expected reserved_credit_cents 0, got "
            f"{cancelled['reserved_credit_cents']} after cancellation"
        )

        style = fixtures.refresh_style(style_id)
        assert style["status"] == "DISCONTINUED", (
            f"expected DISCONTINUED, got {style['status']} once the style's last open "
            "order closed"
        )
        assert style["open_backorder_yards"] == pytest.approx(0.0, abs=0.01), (
            f"expected open_backorder_yards 0.0, got {style['open_backorder_yards']} "
            "with no open order left"
        )
        assert style["replenishment_flag"] == "NONE", (
            f"expected replenishment_flag NONE, got {style['replenishment_flag']}"
        )

        account = fixtures.refresh_account(ctx["account"]["id"])
        assert account["credit_used_cents"] == 0, (
            f"expected credit_used_cents 0, got {account['credit_used_cents']} after "
            "the only hold was released"
        )
        assert account["status"] == "ACTIVE", (
            f"expected ACTIVE, got {account['status']} with no credit in use"
        )


# ---------------------------------------------------------------------------
# The platform contract: authentication, authorization and not-found
# ---------------------------------------------------------------------------


class TestAuthenticationContract:
    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param({}, id="no_identity_headers"),
            pytest.param({"X-User-ID": "planner-1"}, id="role_header_absent"),
            pytest.param({"X-User-Role": "MillPlanner"}, id="user_id_header_absent"),
            pytest.param(
                build_user_headers("planner-1", "ShiftSupervisor"),
                id="undeclared_role",
            ),
        ],
    )
    def test_missing_or_undeclared_identity_is_unauthenticated(self, api, headers):
        """A request with an absent identity header or a role outside the seven declared names is refused 401 and writes nothing.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the seven
        role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_missing_x_user_headers_returns_unauthenticated
        """
        response = api.create_account(
            factories.create_account_payload(
                account_code="AC-01", account_type="DEALER", credit_limit_cents=500000
            ),
            headers,
        )
        validate_error(response, "ERR_UNAUTHENTICATED")

        data, meta = validate_paginated(
            api.list_accounts(ADMIN, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"an unauthenticated request must create no row, got total_count "
            f"{meta['total_count']}"
        )
        assert data == [], f"expected no accounts, got {len(data)}"


class TestNotFoundContract:
    @pytest.mark.parametrize(
        "method_name,expected_error_id",
        [
            ("get_account", "ERR_ACCOUNT_NOT_FOUND"),
            ("get_polymer_lot", "ERR_POLYMER_LOT_NOT_FOUND"),
            ("get_reclamation_batch", "ERR_RECLAMATION_BATCH_NOT_FOUND"),
            ("get_fiber_batch", "ERR_FIBER_BATCH_NOT_FOUND"),
            ("get_tufting_machine", "ERR_MACHINE_NOT_FOUND"),
            ("get_dye_vessel", "ERR_VESSEL_NOT_FOUND"),
            ("get_dye_lot", "ERR_DYE_LOT_NOT_FOUND"),
            ("get_product_test", "ERR_PRODUCT_TEST_NOT_FOUND"),
            ("get_certification", "ERR_CERTIFICATION_NOT_FOUND"),
            ("get_cut_order", "ERR_CUT_ORDER_NOT_FOUND"),
            ("get_cut_allocation", "ERR_CUT_ALLOCATION_NOT_FOUND"),
        ],
    )
    def test_unknown_path_id_returns_the_resources_own_not_found_error(
        self, api, method_name, expected_error_id
    ):
        """The same well-formed but unknown id yields a resource-specific 404 on each single-id read path.

        PRD: "**Path existence, left to right.** Every resource named by a path segment
        must exist, validated in the order the segments appear in the URL."; "The first
        segment that resolves to nothing decides the error:"

        Design: Corner/errors/unknown_path_ids_return_each_resources_own_not_found_error
        """
        response = getattr(api, method_name)(PROBE_ID, ADMIN)
        assert response.status_code == 404, (
            f"{method_name} on an unknown id must return HTTP 404, got "
            f"{response.status_code}"
        )
        validate_error(response, expected_error_id)


class TestRoleAllowLists:
    def test_each_role_performs_its_own_exclusive_operations(self, api):
        """The extrusion operator spins yarn, the planner curates and schedules, the dye-house operator books a vessel and only PlantAdmin moves the clock.

        PRD: "An `ExtrusionOperator` runs the polymer receiving dock, the reclamation
        line and the spinning extruders."; "A `MillPlanner` curates the style catalogue,
        registers tufters, schedules and drives tufting runs, doffs rolls off backed
        runs, and fulfils cut orders out of roll-good inventory."; "A `DyeHouseOperator`
        formulates piece-dye lots, books and charges vessels, records spectrophotometer
        readings, and decides approve, re-dye or reject."; "it is the only role permitted
        to move the logical clock"

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operations
        """
        polymer_lot = validate_success(
            api.create_polymer_lot(
                factories.create_polymer_lot_payload(
                    lot_code="PL-N66-01",
                    polymer_type="NYLON_66",
                    received_kg=5000.0,
                    melt_flow_index=18.0,
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )

        fiber_batch = validate_success(
            api.create_fiber_batch(
                factories.create_fiber_batch_payload(
                    polymer_lot["id"],
                    batch_code="FB-01",
                    input_kg=4000.0,
                    denier_target=1200.0,
                    filament_count=72,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code=None,
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )
        validate_success(
            api.extrude_fiber_batch(
                fiber_batch["id"],
                factories.extrude_fiber_batch_payload(
                    throughput_g_per_min=7200.0, spin_speed_m_per_min=750.0
                ),
                EXTRUDER,
            ),
            expected_status=200,
        )
        released = validate_success(
            api.disposition_fiber_batch(
                fiber_batch["id"],
                factories.disposition_fiber_batch_payload("RELEASE"),
                EXTRUDER,
            ),
            expected_status=200,
        )
        assert released["status"] == "RELEASED", (
            f"expected RELEASED, got {released['status']} after the extrusion operator "
            "released the batch"
        )
        assert released["denier_actual"] == pytest.approx(1200.0, abs=0.01), (
            f"expected denier_actual 1200.0, got {released['denier_actual']}"
        )

        style = validate_success(
            api.create_style(
                factories.create_piece_dyed_style_payload(
                    style_code="ST-PD-01", list_price_cents_per_yard=4275
                ),
                PLANNER,
            ),
            expected_status=201,
        )
        activated = validate_success(
            api.activate_style(style["id"], PLANNER), expected_status=200
        )
        assert activated["status"] == "ACTIVE", (
            f"expected ACTIVE, got {activated['status']} after the planner activated "
            "the style"
        )

        machine = validate_success(
            api.create_tufting_machine(
                factories.create_tufting_machine_payload(
                    machine_code="TM-01",
                    native_gauge_code="G_1_10",
                    changeover_minutes=0,
                ),
                PLANNER,
            ),
            expected_status=201,
        )

        validate_success(
            api.create_dye_vessel(
                factories.create_dye_vessel_payload(
                    vessel_code="DV-01", vessel_type="BECK", capacity_kg=2000.0
                ),
                DYER,
            ),
            expected_status=201,
        )

        run = validate_success(
            api.create_production_run(
                factories.create_production_run_payload(
                    style["id"], machine["id"], fiber_batch["id"], run_code="PR-01"
                ),
                PLANNER,
            ),
            expected_status=201,
        )

        clock = validate_success(
            api.set_clock(factories.set_clock_payload(RUN_WINDOW_OPEN), ADMIN),
            expected_status=200,
        )
        assert is_iso8601_timestamp(clock["current_utc"]), (
            f"current_utc must be an ISO 8601 timestamp, got {clock['current_utc']!r}"
        )
        assert clock["current_utc"].startswith("2026-08-05T08:00:00"), (
            f"expected the clock to read 2026-08-05T08:00:00Z, got "
            f"{clock['current_utc']}"
        )
        for field in (
            "lapsed_certification_ids",
            "suspended_style_ids",
            "held_production_run_ids",
        ):
            assert clock[field] == [], (
                f"expected {field} empty on a plant with no certificates, got "
                f"{clock[field]}"
            )

        tufting = validate_success(
            api.load_setup_production_run(
                run["id"], factories.load_setup_payload(), PLANNER
            ),
            expected_status=200,
        )
        assert tufting["status"] == "TUFTING", (
            f"expected TUFTING, got {tufting['status']} after the planner loaded the "
            "setup"
        )


class TestRoleDenials:
    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda api: api.create_style(
                    factories.create_piece_dyed_style_payload(style_code="ST-X"),
                    EXTRUDER,
                ),
                id="extrusion_operator_drafting_a_style",
            ),
            pytest.param(
                lambda api: api.create_product_test(
                    factories.create_product_test_payload(
                        PROBE_ID, PROBE_ID, test_type="WEAR_TARR", result_value=4.0
                    ),
                    PLANNER,
                ),
                id="planner_recording_a_lab_test",
            ),
            pytest.param(
                lambda api: api.create_certification(
                    factories.create_certification_payload(
                        PROBE_ID, [PROBE_ID], cert_type="DOC_FF_1_70"
                    ),
                    DYER,
                ),
                id="dye_house_operator_issuing_a_certificate",
            ),
            pytest.param(
                lambda api: api.set_clock(
                    factories.set_clock_payload(RUN_WINDOW_OPEN), QA
                ),
                id="qa_technician_moving_the_clock",
            ),
            pytest.param(
                lambda api: api.allocate_cut_order(
                    PROBE_ID,
                    make_dealer_buyer_headers("00000000-0000-4000-8000-000000000001"),
                ),
                id="dealer_buyer_allocating_an_unknown_order",
            ),
        ],
    )
    def test_a_role_outside_the_endpoints_allow_list_is_unauthorized(self, api, call):
        """A well-formed request from a role the endpoint does not authorize is refused 403 before the path id is ever resolved.

        PRD: "If the headers are well formed but the declared role is not among the roles
        authorized for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."; "**Authorization.** The acting role appears in
        the called endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED`
        (403)."; "Evaluation stops at the first failing rung."

        Design: Corner/rbac/disallowed_roles_are_rejected_as_unauthorized
        """
        response = call(api)
        assert response.status_code == 403, (
            f"an unauthorized role must be refused HTTP 403, got "
            f"{response.status_code}: {response.text}"
        )
        validate_error(response, "ERR_UNAUTHORIZED")

        _, meta = validate_paginated(
            api.list_styles(ADMIN, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"a refused request must write nothing, got total_count "
            f"{meta['total_count']} styles"
        )

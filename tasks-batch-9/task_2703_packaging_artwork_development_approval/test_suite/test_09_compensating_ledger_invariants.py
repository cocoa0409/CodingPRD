"""Reversing operations that debit a ledger without rewriting what they reverse."""

from test_helpers import (
    ApiErrorId,
    admin,
    api_client,
    approved_proof,
    approved_version,
    cancel_plate_order,
    cancel_plate_order_payload,
    coord,
    disposition_reversal_payload,
    new_plate_order,
    new_printer,
    read_asset,
    read_plate_order,
    read_runout,
    read_version,
    reverse_disposition,
    scrapped_runout,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CANCEL_REASON = "Print run deferred; plates not yet cut."
CANCEL_INSTANT = "2026-08-05T09:00:00Z"


class TestPlateOrderCancellationCompensatesTheAssetLedger:
    """Two live orders, one cancelled, and a ledger that must stay exact."""

    def _two_ordered_sets(self):
        _brief, asset, version = approved_version(
            asset_overrides={"plate_budget_cents": 500000}
        )
        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        order_1 = new_plate_order(version["id"], printer, proof, plate_set_count=6)
        order_2 = new_plate_order(version["id"], printer, proof, plate_set_count=3)

        assert order_1["cost_cents"] == 163000
        assert order_2["cost_cents"] == 114000
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 277000
        return asset, version, printer, proof, order_1, order_2

    def test_the_debit_is_exact_single_shot_and_leaves_the_order_untouched(self):
        """The cancelled order keeps its money fields; the asset gives the money back.

        PRD §3.7: "The asset's `committed_plate_cost_cents` is debited by exactly the
        order's stored `cost_cents`, and that stored `cost_cents` is itself never
        rewritten."

        Design: Difficulty/compensating_invariant/plate_order_cancellation_debits_the_committed_ledger_without_rewriting_cost
        """
        asset, _version, _printer, _proof, order_1, _order_2 = self._two_ordered_sets()
        set_clock(CANCEL_INSTANT)

        cancelled = cancel_plate_order(order_1["id"], cancel_reason=CANCEL_REASON)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == CANCEL_REASON
        assert cancelled["auto_cancelled"] is False
        assert cancelled["cancelled_at"].startswith("2026-08-05T09:00:00")
        assert cancelled["cost_cents"] == 163000
        assert cancelled["plate_subtotal_cents"] == 103000

        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 114000

        again = api_client.cancel_plate_order(
            order_1["id"], cancel_plate_order_payload(cancel_reason=CANCEL_REASON), coord()
        )
        validate_error(again, ApiErrorId.ERR_PLATE_ORDER_NOT_CANCELLABLE.value, 409)

        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 114000
        assert read_plate_order(order_1["id"])["cost_cents"] == 163000

    def test_the_released_headroom_funds_an_order_that_would_not_have_fitted(self):
        """The ledger tracks only live orders, so cancelling really frees budget.

        PRD §3.7: "Because `committed_plate_cost_cents` sums only orders whose
        `status` is `ORDERED`, cancelled orders free their budget back up."

        Design: Difficulty/compensating_invariant/plate_order_cancellation_debits_the_committed_ledger_without_rewriting_cost
        """
        asset, version, printer, proof, order_1, order_2 = self._two_ordered_sets()

        cancel_plate_order(order_1["id"], cancel_reason=CANCEL_REASON)

        order_3 = validate_success(
            api_client.create_plate_order(
                {
                    "artwork_version_id": version["id"],
                    "printer_id": printer["id"],
                    "printer_proof_id": proof["id"],
                    "plate_set_count": 10,
                    "expedite": True,
                },
                coord(),
            ),
            201,
        )
        # 72000 + 62000 + 26000 plates, a 90000 setup for nine or more, 62500 expedite.
        assert order_3["cost_cents"] == 312500
        assert order_3["plate_subtotal_cents"] == 160000
        assert order_3["setup_fee_cents"] == 90000
        assert order_3["expedite_fee_cents"] == 62500
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 426500

        cancel_plate_order(order_2["id"], cancel_reason=CANCEL_REASON)
        assert read_asset(asset["id"])["committed_plate_cost_cents"] == 312500

        rows, _meta = validate_paginated(
            api_client.list_plate_orders(
                coord(), params={"status": "CANCELLED", "limit": 100}
            )
        )
        assert {row["id"] for row in rows} == {order_1["id"], order_2["id"]}
        assert all(row["auto_cancelled"] is False for row in rows)


class TestRunoutReversalCompensatesBothAssetLedgers:
    """A scrap write-off unwound without recomputing anything."""

    def _scrapped(self):
        _brief, asset, v1, v2, runout = scrapped_runout(weekly_usage_qty=4000)
        assert runout["state"] == "SCRAPPED"
        assert runout["reversal_count"] == 0
        assert runout["total_changeover_cost_cents"] == 504013
        assert asset["obsolete_units_total"] == 10000
        assert asset["changeover_cost_committed_cents"] == 504013
        return asset, v1, v2, runout

    def test_both_ledgers_are_debited_by_exactly_what_the_scrap_credited(self):
        """The debits are the stored amounts, and the physical units are never rewritten.

        PRD §3.8: "It is a pure compensating action: the asset's
        `obsolete_units_total` is debited by exactly the `units_scrapped` being reversed
        and its `changeover_cost_committed_cents` by exactly the
        `total_changeover_cost_cents` that disposition credited."

        Design: Difficulty/compensating_invariant/runout_disposition_reversal_debits_both_ledgers_and_rewinds_the_cascade
        """
        asset, _v1, _v2, runout = self._scrapped()

        reversed_row = reverse_disposition(runout["id"])

        assert reversed_row["state"] == "MONITORING"
        assert reversed_row["reversal_count"] == 1
        assert reversed_row["disposition"] is None
        assert reversed_row["units_scrapped"] == 0
        assert reversed_row["units_reworked"] == 0
        assert reversed_row["material_writeoff_cents"] == 0
        assert reversed_row["relabel_cost_cents"] == 0
        assert reversed_row["changeover_base_cents"] == 0
        assert reversed_row["changeover_expedite_cents"] == 0
        assert reversed_row["total_changeover_cost_cents"] == 0

        after = read_asset(asset["id"])
        assert after["obsolete_units_total"] == 0
        assert after["changeover_cost_committed_cents"] == 0

        assert reversed_row["on_hand_qty"] == 20000
        assert reversed_row["remaining_qty"] == 13334
        consumed = sum(
            record["units_consumed"] for record in reversed_row["depletion_records"]
        )
        assert len(reversed_row["depletion_records"]) == 2
        assert consumed == 6666
        assert reversed_row["on_hand_qty"] == reversed_row["remaining_qty"] + consumed

    def test_the_cascade_rewinds_one_step_and_the_reversal_is_single_shot(self):
        """The version and asset step back one state each, and no further.

        PRD §3.8: "The reversal also unwinds the obsolescence cascade by one step:
        the obsolete version moves `OBSOLETE → OBSOLETE_PENDING` with `obsoleted_at`
        cleared back to null, and the asset moves `SUPERSEDED → SUPERSEDE_PENDING`."

        Design: Difficulty/compensating_invariant/runout_disposition_reversal_debits_both_ledgers_and_rewinds_the_cascade
        """
        asset, v1, v2, runout = self._scrapped()

        reverse_disposition(runout["id"])

        rewound_version = read_version(v1["id"])
        assert rewound_version["state"] == "OBSOLETE_PENDING"
        assert rewound_version["obsoleted_at"] is None

        rewound_asset = read_asset(asset["id"])
        assert rewound_asset["obsolescence_state"] == "SUPERSEDE_PENDING"
        assert rewound_asset["current_approved_version_id"] == v2["id"]
        assert read_version(v2["id"])["state"] == "APPROVED"

        again = api_client.reverse_runout_disposition(
            runout["id"], disposition_reversal_payload(), admin()
        )
        validate_error(again, ApiErrorId.ERR_RUNOUT_STATE_INVALID.value, 409)

        unchanged = read_runout(runout["id"])
        assert unchanged["reversal_count"] == 1
        assert read_asset(asset["id"])["obsolete_units_total"] == 0
        assert read_asset(asset["id"])["changeover_cost_committed_cents"] == 0

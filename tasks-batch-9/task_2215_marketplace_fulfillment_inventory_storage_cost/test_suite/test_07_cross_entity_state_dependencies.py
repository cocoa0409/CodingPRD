"""Writes whose legality lives on another row: the centre's receiving posture, the
lot's reconciliation dimension and the seller's quota period."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    confirm_plan,
    create_plan,
    file_claim,
    newest_quota,
    open_quota,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_quota,
    read_seller,
    receive_plan,
    run_storage_billing,
    set_clock,
    set_receiving_posture,
    setup_baseline,
    setup_received_lot,
    ship_plan,
    validate_error,
    validate_paginated,
)


class TestConfirmationGatedOnReceivingPosture:
    """The plan is beyond reproach; only the centre's posture blocks it."""

    def _draft_at_a_suspended_centre(self) -> dict:
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 100)
        set_receiving_posture(ctx["fc_id"], receiving_status="SUSPENDED")
        ctx["plan"] = plan
        return ctx

    def test_a_suspended_centre_blocks_an_otherwise_valid_confirmation(self):
        """The centre's operator suspends receiving, and the seller's compliant 100-unit
        plan can no longer be confirmed.

        PRD 3.1: "Either an `FcOperator` acting for that centre or a `MarketplaceAdmin` may
        later adjust its posture, revising `receiving_status` to `OPEN`, `THROTTLED` or
        `SUSPENDED`, and revising `receiving_capacity_units_per_window`."
        PRD 3.4: "the destination centre's `receiving_status` must be `OPEN` or `THROTTLED`,
        never `SUSPENDED` (`ERR_FC_RECEIVING_SUSPENDED`)"

        Design: Difficulty/cross_entity_state_dependency/plan_confirm_gated_on_fulfillment_center_receiving_status
        """
        ctx = self._draft_at_a_suspended_centre()
        response = api_client.confirm_plan(ctx["plan"]["id"], {}, ctx["seller_headers"])
        validate_error(response, ApiErrorId.ERR_FC_RECEIVING_SUSPENDED.value)
        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["status"] == "DRAFT"

    def test_reopening_the_centre_lets_the_same_plan_confirm_and_move_the_ledgers(self):
        """Returning the posture to OPEN unblocks the identical request, which then books
        100 units into all three ledgers at once.

        PRD 3.4: "The seller's `restock_reserved_units` increases by the plan's
        `allocated_units`, the active quota period's `utilized_units` increases by the same
        amount, and the destination centre's `committed_receiving_units` increases by the
        plan's `declared_units`."
        PRD 3.4: "`prep_compliance_status` becomes `COMPLIANT` and `confirmed_at` is stamped
        with the logical clock's current instant."

        Design: Difficulty/cross_entity_state_dependency/plan_confirm_gated_on_fulfillment_center_receiving_status
        """
        ctx = self._draft_at_a_suspended_centre()
        api_client.confirm_plan(ctx["plan"]["id"], {}, ctx["seller_headers"])
        reopened = set_receiving_posture(ctx["fc_id"], receiving_status="OPEN")
        assert reopened["receiving_status"] == "OPEN"

        confirmed = confirm_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["allocated_units"] == 100
        assert confirmed["final_allocated_units"] == 100
        assert confirmed["confirmed_at"].startswith("2026-08-01T00:00:00")
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 100
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 100
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 100


class TestInboundLossClaimGatedOnLotReconciliation:
    """Only a lot at DISCREPANCY_OPEN accepts an inbound-loss claim, and only one."""

    def _reconciled_lot_of_six_hundred(self) -> dict:
        return setup_received_lot(
            units=600,
            appointment_window_start="2026-08-01T00:00:00Z",
            appointment_window_end="2026-08-02T00:00:00Z",
        )

    def _open_a_fifty_unit_shortfall(self, ctx: dict) -> dict:
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        line = add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 200)
        confirm_plan(plan["id"], ctx["seller_id"])
        ship_plan(plan["id"], ctx["seller_id"])
        ctx["second_receipt"] = receive_plan(
            plan["id"], ctx["fc_id"], [(line["id"], 150, 0)]
        )
        return ctx

    def test_a_reconciled_lot_refuses_an_inbound_loss_claim(self):
        """Nothing is missing on a fully received lot, so filing is refused outright.

        PRD 3.8: "A `LOST_INBOUND` claim additionally requires that the lot's
        `reconciliation_status` be exactly `DISCREPANCY_OPEN`; anything else — including a
        lot already carrying a claim, whose status is `DISCREPANCY_CLAIMED` — is rejected
        with `ERR_LOT_NO_OPEN_DISCREPANCY`, which is what locks a lot against a second
        concurrent inbound-loss claim."

        Design: Difficulty/cross_entity_state_dependency/lost_inbound_claim_gated_on_lot_reconciliation_status
        """
        ctx = self._reconciled_lot_of_six_hundred()
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["reconciliation_status"] == (
            "RECONCILED"
        )
        response = api_client.file_reimbursement_claim(
            {
                "inventory_lot_id": ctx["lot_id"],
                "claim_type": "LOST_INBOUND",
                "claimed_units": 10,
                "evidence_document_count": 2,
                "evidence_reference": "EARLY-1",
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LOT_NO_OPEN_DISCREPANCY.value)

    def test_a_short_second_receipt_opens_the_gate_for_exactly_one_claim(self):
        """A 50-unit shortfall on the same lot admits one claim, which moves the lot to
        DISCREPANCY_CLAIMED and locks out a second.

        PRD 3.8: "A successful `LOST_INBOUND` filing moves the lot's reconciliation
        dimension `DISCREPANCY_OPEN → DISCREPANCY_CLAIMED` without moving any units."
        PRD 3.5: "The second link, caused by the first, is discrepancy opening: every lot
        that absorbed a short line has that line's `shortfall_units` added to the lot's
        `missing_units`, its `reconciliation_status` moved from `RECONCILED` to
        `DISCREPANCY_OPEN`, and its `discrepancy_opened_at` stamped with the logical clock's
        current instant — this instant is the anchor of the `LOST_INBOUND` filing deadline —
        while the seller's `open_discrepancy_units` increases by the total shortfall."

        Design: Difficulty/cross_entity_state_dependency/lost_inbound_claim_gated_on_lot_reconciliation_status
        """
        ctx = self._open_a_fifty_unit_shortfall(self._reconciled_lot_of_six_hundred())
        assert ctx["second_receipt"]["status"] == "PARTIALLY_RECEIVED"

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["missing_units"] == 50
        assert lot["fulfillable_units"] == 750

        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "LOST_INBOUND", 50, 2,
            evidence_reference="OPEN-1",
        )
        assert claim["status"] == "SUBMITTED"
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["reconciliation_status"] == (
            "DISCREPANCY_CLAIMED"
        )

        response = api_client.file_reimbursement_claim(
            {
                "inventory_lot_id": ctx["lot_id"],
                "claim_type": "LOST_INBOUND",
                "claimed_units": 50,
                "evidence_document_count": 2,
                "evidence_reference": "OPEN-2",
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LOT_NO_OPEN_DISCREPANCY.value)

        _rows, meta = validate_paginated(
            api_client.list_lot_reimbursement_claims(
                ctx["lot_id"], ctx["seller_headers"]
            )
        )
        assert meta["total_count"] == 1

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["listing_status"] == "ACTIVE"
        assert listing["inventory_health"] == "HEALTHY"


class TestConfirmationGatedOnAnActiveQuotaPeriod:
    """A billing run past `period_end` strands the draft until a new period opens."""

    def _draft_whose_quota_has_expired(self) -> dict:
        ctx = setup_baseline(
            quota={"period_start": "2026-08-01T00:00:00Z",
                   "period_end": "2026-08-15T00:00:00Z"}
        )
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 100)
        set_clock("2026-08-20T00:00:00Z")
        ctx["plan"] = plan
        ctx["run"] = run_storage_billing()
        return ctx

    def test_the_billing_run_expires_the_period_and_blocks_confirmation(self):
        """The sweep flips the period to EXPIRED, and the untouched draft can no longer be
        confirmed at all.

        PRD 3.9: "Every quota period whose `status` is `ACTIVE` and whose `period_end` is at
        or before the logical clock's current instant moves `ACTIVE → EXPIRED`; no ledger
        moves, but the seller can no longer confirm plans until a new period is opened, and
        attempts fail with `ERR_NO_ACTIVE_RESTOCK_QUOTA`."

        Design: Difficulty/cross_entity_state_dependency/plan_confirm_gated_on_active_restock_quota_period
        """
        ctx = self._draft_whose_quota_has_expired()
        assert ctx["run"]["expired_quota_count"] == 1
        assert read_quota(ctx["quota_id"], ctx["seller_id"])["status"] == "EXPIRED"

        response = api_client.confirm_plan(ctx["plan"]["id"], {}, ctx["seller_headers"])
        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_RESTOCK_QUOTA.value)
        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["status"] == "DRAFT"

    def test_opening_a_fresh_period_lets_the_draft_confirm_against_the_new_row(self):
        """A second period restores confirmation, and the 100 units land on the new row
        while the expired one keeps its own zero.

        PRD 3.1: "A seller has at most one period whose `status` is `ACTIVE` at any instant,
        and periods whose `status` is `SUPERSEDED` or `EXPIRED` are never re-scored."
        PRD 3.4: "The seller's `restock_reserved_units` increases by the plan's
        `allocated_units`, the active quota period's `utilized_units` increases by the same
        amount, and the destination centre's `committed_receiving_units` increases by the
        plan's `declared_units`."

        Design: Difficulty/cross_entity_state_dependency/plan_confirm_gated_on_active_restock_quota_period
        """
        ctx = self._draft_whose_quota_has_expired()
        api_client.confirm_plan(ctx["plan"]["id"], {}, ctx["seller_headers"])
        second = open_quota(
            ctx["seller_id"],
            period_start="2026-08-20T00:00:00Z",
            period_end="2028-01-01T00:00:00Z",
        )
        assert second["status"] == "ACTIVE"

        confirmed = confirm_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["allocated_units"] == 100
        assert read_quota(second["id"], ctx["seller_id"])["utilized_units"] == 100
        assert read_quota(ctx["quota_id"], ctx["seller_id"])["utilized_units"] == 0
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 100

"""State-machine breadth: the ledger-neutral shipping hop, four wrong-source-state
guards, the declared initial states of three entities, terminal states that absorb every
further action, and the two reinstatement guards."""
from test_helpers import (
    ADJUDICATOR,
    ApiErrorId,
    add_line_item,
    api_client,
    cancel_removal,
    classify_unfulfillable,
    confirm_plan,
    create_in_transit_plan,
    create_listing,
    create_plan,
    decide_claim,
    file_claim,
    lots_for_listing,
    newest_quota,
    read_claim,
    read_fulfillment_center,
    read_listing,
    read_lot,
    read_plan,
    read_removal_order,
    read_seller,
    receive_plan,
    request_removal,
    set_clock,
    setup_baseline,
    setup_lot_with_split_pools,
    ship_plan,
    validate_error,
)


class TestShippingIsLedgerNeutral:
    """CONFIRMED → IN_TRANSIT flips one field and moves no numbers at all."""

    def _confirmed_four_hundred_then_four_days_later(self) -> dict:
        ctx = setup_baseline()
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        ctx["line_item"] = add_line_item(
            plan["id"], ctx["seller_id"], ctx["listing_id"], 400
        )
        ctx["plan"] = confirm_plan(plan["id"], ctx["seller_id"])
        set_clock("2026-08-05T09:30:00Z")
        return ctx

    def test_shipping_moves_the_status_without_restamping_the_confirmation(self):
        """The ship happens four days after the confirmation, and `confirmed_at` still
        carries the earlier instant.

        PRD 3.4: "A plan whose `status` is `CONFIRMED` moves `CONFIRMED → IN_TRANSIT`,
        optionally recording a `carrier_reference`; an attempt against a plan in any other
        status fails with `ERR_PLAN_NOT_CONFIRMED`."
        PRD 3.4: "`prep_compliance_status` becomes `COMPLIANT` and `confirmed_at` is
        stamped with the logical clock's current instant."

        Design: Corner/state_machines/plan_ship_transition_applies_declared_side_effects
        """
        ctx = self._confirmed_four_hundred_then_four_days_later()
        shipped = ship_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert shipped["status"] == "IN_TRANSIT"
        assert shipped["confirmed_at"].startswith("2026-08-01T00:00:00")
        assert shipped["prep_compliance_status"] == "COMPLIANT"

    def test_shipping_leaves_all_three_ledgers_and_the_allocation_untouched(self):
        """The plan stays inside the reserving set, so the reservation, the period's
        consumption and the centre's commitment all still read 400.

        PRD 3.4: "No ledger moves, because the plan stays inside the reserving set of
        `CONFIRMED`, `IN_TRANSIT` and `PARTIALLY_RECEIVED`."
        PRD 2.7: "The first is the seller's reservation ledger: `restock_reserved_units` on
        a `SellerAccount` always equals the sum of `allocated_units` across that seller's
        inbound shipment plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or
        `PARTIALLY_RECEIVED`."

        Design: Corner/state_machines/plan_ship_transition_applies_declared_side_effects
        """
        ctx = self._confirmed_four_hundred_then_four_days_later()
        ship_plan(ctx["plan"]["id"], ctx["seller_id"])

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["final_allocated_units"] == 400
        assert plan["received_units"] == 0
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 400
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 400
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 400
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["inventory_health"] == (
            "OUT_OF_STOCK"
        )


class TestWrongSourceStateGuards:
    """Four transitions attempted from four wrong states, four distinct 409 codes."""

    def _three_plans_in_three_states(self) -> dict:
        ctx = setup_baseline(quota={"base_capacity_units": 3000})
        draft = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        ctx["draft_line"] = add_line_item(
            draft["id"], ctx["seller_id"], ctx["listing_id"], 100
        )
        in_transit = create_in_transit_plan(
            ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], 200,
            "2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z",
        )
        complete = create_in_transit_plan(
            ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], 50,
            "2026-08-14T00:00:00Z", "2026-08-15T00:00:00Z",
        )
        receive_plan(
            complete["plan"]["id"], ctx["fc_id"], [(complete["line_item"]["id"], 50, 0)]
        )
        ctx.update({
            "draft": draft,
            "in_transit": in_transit["plan"],
            "complete": complete["plan"],
        })
        return ctx

    def test_shipping_a_draft_and_confirming_an_in_transit_plan_are_both_refused(self):
        """Each transition names its own required source state, and each refusal keeps the
        plan exactly where it was.

        PRD 3.4: "A plan whose `status` is `CONFIRMED` moves `CONFIRMED → IN_TRANSIT`,
        optionally recording a `carrier_reference`; an attempt against a plan in any other
        status fails with `ERR_PLAN_NOT_CONFIRMED`."
        PRD 3.4: "The plan's `status` must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); it must carry
        at least one line item (`ERR_PLAN_HAS_NO_LINE_ITEMS`)"

        Design: Corner/state_machines/plan_lifecycle_actions_rejected_from_wrong_source_state
        """
        ctx = self._three_plans_in_three_states()
        validate_error(
            api_client.ship_plan(ctx["draft"]["id"], {}, ctx["seller_headers"]),
            ApiErrorId.ERR_PLAN_NOT_CONFIRMED.value, 409,
        )
        validate_error(
            api_client.confirm_plan(ctx["in_transit"]["id"], {}, ctx["seller_headers"]),
            ApiErrorId.ERR_PLAN_NOT_DRAFT.value, 409,
        )
        assert read_plan(ctx["draft"]["id"], ctx["seller_id"])["status"] == "DRAFT"
        assert read_plan(ctx["in_transit"]["id"], ctx["seller_id"])["status"] == "IN_TRANSIT"

    def test_receiving_a_draft_and_cancelling_a_completed_plan_are_both_refused(self):
        """Receipt demands a shipped plan and cancellation refuses a plan that has already
        been received, while the ledgers keep the figures the earlier receipt left behind.

        PRD 3.5: "The plan's `status` must be `IN_TRANSIT` or `PARTIALLY_RECEIVED`,
        otherwise the attempt fails with `ERR_PLAN_NOT_RECEIVABLE`, and the acting
        operator's `X-User-ID` must equal the plan's `destination_fc_id`, otherwise
        `ERR_FC_SCOPE_VIOLATION`."
        PRD 3.4: "It is permitted from `DRAFT` and from `CONFIRMED` only; from any other
        status it fails with `ERR_PLAN_NOT_CANCELLABLE`."

        Design: Corner/state_machines/plan_lifecycle_actions_rejected_from_wrong_source_state
        """
        ctx = self._three_plans_in_three_states()
        validate_error(
            api_client.receive_plan(
                ctx["draft"]["id"],
                {
                    "received_lines": [
                        {
                            "shipment_line_item_id": ctx["draft_line"]["id"],
                            "received_units": 1,
                            "unfulfillable_units": 0,
                        }
                    ]
                },
                ctx["fc_headers"],
            ),
            ApiErrorId.ERR_PLAN_NOT_RECEIVABLE.value, 409,
        )
        validate_error(
            api_client.cancel_plan(ctx["complete"]["id"], {}, ctx["seller_headers"]),
            ApiErrorId.ERR_PLAN_NOT_CANCELLABLE.value, 409,
        )
        assert read_plan(ctx["complete"]["id"], ctx["seller_id"])["status"] == (
            "RECEIVED_COMPLETE"
        )

    def test_the_completed_plan_left_the_reservation_but_not_the_quota_consumption(self):
        """Only the in-transit plan still reserves units, while the period keeps both plans'
        consumption because a receipt never gives capacity back.

        PRD 3.5: "The plan leaves the reserving set: the seller's `restock_reserved_units`
        is decremented by the plan's `allocated_units`, the destination centre's
        `committed_receiving_units` is decremented by the plan's `declared_units`, and the
        plan's `allocated_units` is then set to 0 — keeping both conserved ledgers intact."
        PRD 3.4: "Note that a quota period's `utilized_units` is never decremented by a
        receipt — only by cancellation and by reversion — so consumed capacity stays
        consumed for the period."

        Design: Corner/state_machines/plan_lifecycle_actions_rejected_from_wrong_source_state
        """
        ctx = self._three_plans_in_three_states()
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 200
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 250
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 200


class TestDeclaredInitialStates:
    """A lot, a removal order and a claim each open on their own declared state."""

    def _lot_with_eighty_fulfillable_and_twenty_damaged(self) -> dict:
        return setup_lot_with_split_pools(80, 20)

    def test_a_credited_lot_opens_active_and_reconciled(self):
        """The full receipt leaves nothing missing, so both lot dimensions open on their
        first values and the classification split is exactly 80 against 20.

        PRD 2.8: "An `InventoryLot` has a `lot_status` (`ACTIVE`, `PARTIALLY_REMOVED` or
        `DEPLETED`) and a `reconciliation_status` (`RECONCILED`, `DISCREPANCY_OPEN`,
        `DISCREPANCY_CLAIMED` or `DISCREPANCY_RESOLVED`)."
        PRD 3.6: "The move subtracts that count from the lot's `fulfillable_units` and adds
        it to the lot's `unfulfillable_units`, leaving `units_received_total` unchanged, and
        stamps `unfulfillable_recorded_at` with the logical clock's current instant — the
        anchor of the `DAMAGED_WAREHOUSE` filing deadline."

        Design: Corner/state_machines/claim_and_removal_initial_states_are_submitted_and_requested
        """
        ctx = self._lot_with_eighty_fulfillable_and_twenty_damaged()
        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["lot_status"] == "ACTIVE"
        assert lot["reconciliation_status"] == "RECONCILED"
        assert lot["fulfillable_units"] == 80
        assert lot["unfulfillable_units"] == 20
        assert lot["units_received_total"] == 100

    def test_a_removal_order_opens_requested_with_nothing_settled(self):
        """The request reserves the damaged pool and opens unpriced, with no completion
        stamp.

        PRD 3.6: "A successful request opens at `status` of `REQUESTED` with
        `removal_fee_cents`, `liquidation_recovery_cents` and `net_settlement_cents` all at
        0 and `completed_at` null."
        PRD 3.6: "It reserves the units: `requested_units` is subtracted from whichever pool
        the `unit_pool` names and added to the lot's `units_reserved_for_removal`, leaving
        `units_received_total` unchanged."

        Design: Corner/state_machines/claim_and_removal_initial_states_are_submitted_and_requested
        """
        ctx = self._lot_with_eighty_fulfillable_and_twenty_damaged()
        removal = request_removal(
            ctx["lot_id"], ctx["seller_id"], 20,
            removal_method="DISPOSAL", unit_pool="UNFULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-02T00:00:00Z",
        )
        assert removal["status"] == "REQUESTED"
        assert removal["completed_at"] is None
        assert removal["liquidation_recovery_cents"] == 0

        stored = read_removal_order(removal["id"], ctx["seller_id"])
        assert stored["status"] == "REQUESTED"
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["units_reserved_for_removal"] == 20

    def test_a_claim_opens_submitted_with_a_sixty_day_deadline_and_nothing_awarded(self):
        """The damage was recorded on the first of August, so the deadline lands sixty days
        later and every settlement figure starts at zero.

        PRD 3.8: "Filing pins `filing_deadline_at` to the selected anchor plus 60 days, and
        the claim opens at `status` of `SUBMITTED` with `resubmission_count` of 0,
        `eligible_units`, `approved_units` and `reimbursement_amount_cents` all at 0, and
        `decided_at` null."
        PRD 3.8: "`DAMAGED_WAREHOUSE` draws on the lot's `unfulfillable_units`, anchors on
        `unfulfillable_recorded_at`, and requires at least 3."

        Design: Corner/state_machines/claim_and_removal_initial_states_are_submitted_and_requested
        """
        ctx = self._lot_with_eighty_fulfillable_and_twenty_damaged()
        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 5, 3,
            evidence_reference="EV-DMG-1",
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["resubmission_count"] == 0
        assert claim["eligible_units"] == 0
        assert claim["approved_units"] == 0
        assert claim["reimbursement_amount_cents"] == 0
        assert claim["decided_at"] is None
        assert claim["filing_deadline_at"].startswith("2026-09-30T00:00:00")


class TestTerminalStatesAbsorbEveryAction:
    """A DENIED claim and a CANCELLED removal refuse every further transition."""

    def _denied_claim(self) -> dict:
        ctx = setup_lot_with_split_pools(100, 20)
        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 5, 3,
            evidence_reference="EV-DMG-1",
        )
        ctx["claim"] = decide_claim(
            claim["id"], "DENIED", decision_note="insufficient evidence quality"
        )
        return ctx

    def _cancelled_removal(self) -> dict:
        ctx = setup_lot_with_split_pools(100, 20)
        removal = request_removal(
            ctx["lot_id"], ctx["seller_id"], 20,
            removal_method="DISPOSAL", unit_pool="UNFULFILLABLE",
            removal_window_start="2026-09-01T00:00:00Z",
            removal_window_end="2026-09-02T00:00:00Z",
        )
        ctx["removal"] = cancel_removal(removal["id"], ctx["seller_id"])
        return ctx

    def test_a_denied_claim_refuses_both_resubmission_and_a_second_decision(self):
        """Denial is absorbing: neither the seller nor the adjudicator can move the claim
        again, and no money ever moved.

        PRD 3.8: "Resubmission requires `status` of `INFO_REQUESTED` (otherwise
        `ERR_CLAIM_NOT_ACTIONABLE`), a `resubmission_count` strictly below 2, and a logical
        clock at or before `filing_deadline_at`."
        PRD 3.8: "Deciding requires `status` of `SUBMITTED` (otherwise
        `ERR_CLAIM_NOT_ACTIONABLE`) and carries a `decision` of either `APPROVED` or
        `DENIED`, plus an optional `decision_note`."

        Design: Corner/state_machines/terminal_claim_and_removal_reject_all_further_actions
        """
        ctx = self._denied_claim()
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["status"] == "DENIED"

        validate_error(
            api_client.resubmit_claim(
                claim_id,
                {"evidence_document_count": 4, "evidence_reference": "EV-DMG-2"},
                ctx["seller_headers"],
            ),
            ApiErrorId.ERR_CLAIM_NOT_ACTIONABLE.value, 409,
        )
        validate_error(
            api_client.decide_claim(
                claim_id,
                {"decision": "APPROVED", "decision_note": "reversal attempt"},
                ADJUDICATOR,
            ),
            ApiErrorId.ERR_CLAIM_NOT_ACTIONABLE.value, 409,
        )

        claim = read_claim(claim_id)
        assert claim["status"] == "DENIED"
        assert claim["resubmission_count"] == 0
        assert claim["reimbursement_amount_cents"] == 0
        assert read_seller(ctx["seller_id"])["reimbursement_credit_cents"] == 0

    def test_a_cancelled_removal_refuses_completion(self):
        """Cancellation is absorbing too: the centre cannot execute the order afterwards,
        and the units it once held are back in the damaged pool.

        PRD 3.6: "The order's `status` must be `REQUESTED`, otherwise
        `ERR_REMOVAL_NOT_REQUESTED`; the acting operator's `X-User-ID` must equal the
        holding lot's `fulfillment_center_id`, otherwise `ERR_FC_SCOPE_VIOLATION`; and the
        logical clock must have reached the `removal_window_start`, with the exact instant
        accepted, otherwise `ERR_REMOVAL_WINDOW_NOT_OPEN`."
        PRD 2.6: "The target resource's own state permits the operation —
        `ERR_PLAN_NOT_DRAFT`, `ERR_PLAN_NOT_CONFIRMED`, `ERR_PLAN_NOT_RECEIVABLE`,
        `ERR_PLAN_NOT_CANCELLABLE`, `ERR_REMOVAL_NOT_REQUESTED`,
        `ERR_CLAIM_NOT_ACTIONABLE` or `ERR_LISTING_NOT_SUPPRESSED`, all HTTP 409, on every
        state-transition operation."

        Design: Corner/state_machines/terminal_claim_and_removal_reject_all_further_actions
        """
        ctx = self._cancelled_removal()
        assert ctx["removal"]["status"] == "CANCELLED"

        validate_error(
            api_client.complete_removal_order(
                ctx["removal"]["id"], {}, ctx["fc_headers"]
            ),
            ApiErrorId.ERR_REMOVAL_NOT_REQUESTED.value, 409,
        )

        assert read_removal_order(ctx["removal"]["id"], ctx["seller_id"])["status"] == (
            "CANCELLED"
        )
        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_reserved_for_removal"] == 0
        assert lot["unfulfillable_units"] == 20


class TestReinstatementGuards:
    """One endpoint, two guards, two different 409 codes."""

    def _one_healthy_and_one_stranded_listing(self) -> dict:
        ctx = setup_baseline()
        second = create_listing(ctx["seller_id"], sku="SKU-BETA")
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        healthy_line = add_line_item(
            plan["id"], ctx["seller_id"], ctx["listing_id"], 100
        )
        stranded_line = add_line_item(plan["id"], ctx["seller_id"], second["id"], 50)
        confirm_plan(plan["id"], ctx["seller_id"])
        ship_plan(plan["id"], ctx["seller_id"])
        receive_plan(
            plan["id"], ctx["fc_id"],
            [(healthy_line["id"], 100, 0), (stranded_line["id"], 50, 0)],
        )
        stranded_lot = lots_for_listing(second["id"], ctx["seller_id"])[0]
        classify_unfulfillable(
            stranded_lot["id"], ctx["fc_id"], 50, disposition_reason="WAREHOUSE_DAMAGE"
        )
        ctx.update({"second_listing_id": second["id"], "stranded_lot": stranded_lot})
        return ctx

    def test_reinstating_a_listing_that_was_never_suppressed_is_refused(self):
        """The healthy listing is still ACTIVE, so there is no suppression to clear.

        PRD 3.2: "A `SellerOperator` reinstates a listing, optionally attaching a
        `reinstatement_note`, and the transition from `SUPPRESSED` back to `ACTIVE` requires
        two things: the listing's `listing_status` is currently `SUPPRESSED`, otherwise the
        attempt fails with `ERR_LISTING_NOT_SUPPRESSED`; and the listing's
        `fulfillable_units` is at least 1, otherwise it fails with
        `ERR_SUPPRESSION_CONDITION_PERSISTS`."
        PRD 3.2: "Otherwise health is `HEALTHY`."

        Design: Corner/state_machines/listing_reinstate_guards_reject_when_not_suppressed_or_cause_persists
        """
        ctx = self._one_healthy_and_one_stranded_listing()
        healthy = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert healthy["listing_status"] == "ACTIVE"
        assert healthy["inventory_health"] == "HEALTHY"

        validate_error(
            api_client.reinstate_sku_listing(
                ctx["listing_id"], {}, ctx["seller_headers"]
            ),
            ApiErrorId.ERR_LISTING_NOT_SUPPRESSED.value, 409,
        )
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["listing_status"] == (
            "ACTIVE"
        )

    def test_reinstating_while_the_stranding_persists_is_refused(self):
        """The suppressed listing still holds 50 damaged units and no fulfillable ones, so
        the cause of the suppression has not gone away.

        PRD 3.2: "Reinstatement is that act."
        PRD 3.6: "Listing health is then recomputed, which can suppress the listing with
        `suppression_reason` of `STRANDED_INVENTORY` when the fulfillable pool has been
        emptied."

        Design: Corner/state_machines/listing_reinstate_guards_reject_when_not_suppressed_or_cause_persists
        """
        ctx = self._one_healthy_and_one_stranded_listing()
        stranded = read_listing(ctx["second_listing_id"], ctx["seller_id"])
        assert stranded["listing_status"] == "SUPPRESSED"
        assert stranded["suppression_reason"] == "STRANDED_INVENTORY"
        assert stranded["inventory_health"] == "STRANDED"

        validate_error(
            api_client.reinstate_sku_listing(
                ctx["second_listing_id"], {}, ctx["seller_headers"]
            ),
            ApiErrorId.ERR_SUPPRESSION_CONDITION_PERSISTS.value, 409,
        )

        after = read_listing(ctx["second_listing_id"], ctx["seller_id"])
        assert after["listing_status"] == "SUPPRESSED"
        assert after["suppression_reason"] == "STRANDED_INVENTORY"
        assert read_seller(ctx["seller_id"])["suppressed_listing_count"] == 1

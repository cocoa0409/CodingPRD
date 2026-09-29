"""Non-linear state machines: a listing whose two dimensions diverge, and a claim
that cycles between INFO_REQUESTED and SUBMITTED under a hard cap."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    classify_unfulfillable,
    confirm_plan,
    create_plan,
    file_claim,
    place_multi_channel_order,
    read_claim,
    read_listing,
    read_lot,
    read_seller,
    receive_plan,
    request_claim_info,
    resubmit_claim,
    setup_received_lot,
    ship_plan,
    validate_error,
    validate_success,
)


def _stranded_after_mcf_draw() -> dict:
    """100 received units, 60 reclassified unfulfillable, the remaining 40 shipped out
    through MCF — which empties the fulfillable pool and suppresses the listing."""
    ctx = setup_received_lot(units=100)
    classify_unfulfillable(
        ctx["lot_id"], ctx["fc_id"], 60, disposition_reason="CUSTOMER_DAMAGE"
    )
    ctx["order"] = place_multi_channel_order(
        ctx["seller_id"], ctx["listing_id"], 40, 1.00, "ZONE_1", "MCF", 20000
    )
    return ctx


def _restock_the_suppressed_listing(ctx: dict) -> dict:
    """A second shipment of 50 units into the same centre, credited to the same lot."""
    plan = create_plan(
        ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
    )
    line = add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 50)
    confirm_plan(plan["id"], ctx["seller_id"])
    ship_plan(plan["id"], ctx["seller_id"])
    receive_plan(plan["id"], ctx["fc_id"], [(line["id"], 50, 0)])
    return ctx


class TestListingSuppressionOutlivesInventoryHealth:
    """Health re-derives on every pool move; suppression only clears on request."""

    def test_mcf_draw_empties_the_pool_and_suppresses_with_stranded_inventory(self):
        """Drawing the last 40 fulfillable units leaves 60 unfulfillable behind, which
        pins the suppression reason to STRANDED_INVENTORY and health to STRANDED.

        PRD 3.2: "The same recomputation that derives health also asks whether
        `fulfillable_units` has fallen to 0 while `lot_ever_created` is true. When both
        hold, `listing_status` becomes `SUPPRESSED` and `suppression_reason` is pinned by
        priority, first match winning: `MISSING_INVENTORY` when the listing's
        `missing_units` is at least 1, otherwise `STRANDED_INVENTORY` when its
        `unfulfillable_units` is at least 1, otherwise `ZERO_FULFILLABLE`."

        Design: Difficulty/non_linear_state_machine/sku_listing_stays_suppressed_while_inventory_health_returns_to_healthy
        """
        ctx = _stranded_after_mcf_draw()
        assert ctx["order"]["mcf_fee_cents"] == 15200
        assert ctx["order"]["order_status"] == "MCF_SHIPPED"

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["listing_status"] == "SUPPRESSED"
        assert listing["suppression_reason"] == "STRANDED_INVENTORY"
        assert listing["inventory_health"] == "STRANDED"
        assert listing["fulfillable_units"] == 0
        assert listing["unfulfillable_units"] == 60
        assert read_seller(ctx["seller_id"])["suppressed_listing_count"] == 1

    def test_restocking_returns_health_to_healthy_while_the_listing_stays_suppressed(self):
        """50 fresh units restore HEALTHY inventory health, but nothing un-suppresses the
        listing and the seller's suppressed count still reads 1.

        PRD 2.8: "A listing may therefore sit at `listing_status` of `SUPPRESSED` while its
        `inventory_health` has already recovered to `HEALTHY`, and that combination is
        correct, not a bug."
        PRD 3.2: "When the condition does not hold, `listing_status` and
        `suppression_reason` are left exactly as they were; there is no automatic
        un-suppression, and a listing that has regained stock stays dark until someone
        acts."

        Design: Difficulty/non_linear_state_machine/sku_listing_stays_suppressed_while_inventory_health_returns_to_healthy
        """
        ctx = _restock_the_suppressed_listing(_stranded_after_mcf_draw())

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["listing_status"] == "SUPPRESSED"
        assert listing["suppression_reason"] == "STRANDED_INVENTORY"
        assert listing["inventory_health"] == "HEALTHY"
        assert listing["fulfillable_units"] == 50
        assert read_seller(ctx["seller_id"])["suppressed_listing_count"] == 1

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["units_received_total"] == 150
        assert lot["units_shipped_mcf"] == 40
        assert lot["lot_status"] == "ACTIVE"
        assert lot["reconciliation_status"] == "RECONCILED"

    def test_reinstatement_clears_suppression_without_touching_health(self):
        """An explicit reinstatement is the only path back to ACTIVE, and it leaves the
        already-recovered inventory health exactly where it was.

        PRD 3.2: "A successful reinstatement sets `suppression_reason` back to `NONE` and
        decrements the seller's `suppressed_listing_count` by 1. It does not touch
        `inventory_health`, which was already tracking reality independently."

        Design: Difficulty/non_linear_state_machine/sku_listing_stays_suppressed_while_inventory_health_returns_to_healthy
        """
        ctx = _restock_the_suppressed_listing(_stranded_after_mcf_draw())
        response = api_client.reinstate_sku_listing(
            ctx["listing_id"], {"reinstatement_note": "restocked"}, ctx["seller_headers"]
        )
        listing = validate_success(response, 200)
        assert listing["listing_status"] == "ACTIVE"
        assert listing["suppression_reason"] == "NONE"
        assert listing["inventory_health"] == "HEALTHY"
        assert listing["fulfillable_units"] == 50
        assert listing["unfulfillable_units"] == 60
        assert read_seller(ctx["seller_id"])["suppressed_listing_count"] == 0


class TestClaimInformationCycleCap:
    """Two resubmissions are allowed; the third is refused and leaves the claim parked."""

    def _claim_under_review(self) -> dict:
        ctx = setup_received_lot(units=100)
        classify_unfulfillable(
            ctx["lot_id"], ctx["fc_id"], 40, disposition_reason="WAREHOUSE_DAMAGE"
        )
        ctx["claim"] = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 40, 3,
            evidence_reference="CASE-77",
        )
        return ctx

    def test_two_information_cycles_increment_the_count_and_overwrite_the_evidence(self):
        """Each answered information request bumps `resubmission_count` by one and replaces
        the stored evidence figures, while the 60-day deadline stays pinned.

        PRD 3.8: "Resubmission requires `status` of `INFO_REQUESTED` (otherwise
        `ERR_CLAIM_NOT_ACTIONABLE`), a `resubmission_count` strictly below 2, and a logical
        clock at or before `filing_deadline_at`. It moves the claim `INFO_REQUESTED →
        SUBMITTED` and increments `resubmission_count` by 1."
        PRD 3.8: "The seller answers by resubmitting with a fresh `evidence_document_count`
        and `evidence_reference`, which overwrite the stored values and must again clear the
        type's evidence minimum."

        Design: Difficulty/non_linear_state_machine/reimbursement_claim_info_cycle_capped_at_two_resubmissions
        """
        ctx = self._claim_under_review()
        claim_id = ctx["claim"]["id"]
        assert ctx["claim"]["filing_deadline_at"].startswith("2026-09-30T00:00:00")

        request_claim_info(claim_id, "Send warehouse photos")
        first = resubmit_claim(claim_id, ctx["seller_id"], 3, "CASE-77-R1")
        assert first["resubmission_count"] == 1
        assert first["status"] == "SUBMITTED"

        request_claim_info(claim_id, "Send carrier statement")
        second = resubmit_claim(claim_id, ctx["seller_id"], 4, "CASE-77-R2")
        assert second["resubmission_count"] == 2
        assert second["evidence_document_count"] == 4
        assert second["evidence_reference"] == "CASE-77-R2"

    def test_third_resubmission_is_refused_and_leaves_the_claim_info_requested(self):
        """With the count already at 2 the claim cannot be answered again, so it stays in
        INFO_REQUESTED carrying the evidence from the second cycle.

        PRD 3.8: "The cap is hard: a third resubmission attempt, made when
        `resubmission_count` already stands at 2, is rejected with
        `ERR_RESUBMISSION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/reimbursement_claim_info_cycle_capped_at_two_resubmissions
        """
        ctx = self._claim_under_review()
        claim_id = ctx["claim"]["id"]
        request_claim_info(claim_id, "Send warehouse photos")
        resubmit_claim(claim_id, ctx["seller_id"], 3, "CASE-77-R1")
        request_claim_info(claim_id, "Send carrier statement")
        resubmit_claim(claim_id, ctx["seller_id"], 4, "CASE-77-R2")
        request_claim_info(claim_id, "One more document")

        response = api_client.resubmit_claim(
            claim_id,
            {"evidence_document_count": 5, "evidence_reference": "CASE-77-R3"},
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value)

        claim = read_claim(claim_id)
        assert claim["status"] == "INFO_REQUESTED"
        assert claim["resubmission_count"] == 2
        assert claim["evidence_document_count"] == 4
        assert claim["evidence_reference"] == "CASE-77-R2"
        assert claim["reimbursement_amount_cents"] == 0
        assert claim["decided_at"] is None

"""Requests that break two rules at once, where the fixed ladder decides which error
the caller actually sees."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_line_item,
    api_client,
    classify_unfulfillable,
    create_listing,
    create_plan,
    file_claim,
    newest_quota,
    read_claim,
    read_fulfillment_center,
    read_plan,
    read_seller,
    register_seller,
    request_claim_info,
    resubmit_claim,
    set_clock,
    setup_baseline,
    setup_received_lot,
    validate_error,
    validate_paginated,
)

# Four performance inputs scoring 545, which caps the restock limit at 1500 units.
MID_SCORING_QUOTA = {
    "sell_through_rate": 1.2500,
    "excess_units_ratio": 0.1500,
    "stranded_ratio": 0.0500,
    "in_stock_rate": 0.8000,
}


class TestSuspendedCentreOutranksTheRestockLimit:
    """A 2000-unit draft against a 1500-unit limit and a suspended centre breaks two
    rules; step 9 answers before step 19."""

    def _over_limit_draft_at_a_suspended_centre(self) -> dict:
        ctx = setup_baseline(quota=dict(MID_SCORING_QUOTA))
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 2000)
        api_client.update_fulfillment_center(
            ctx["fc_id"], {"receiving_status": "SUSPENDED"}, ADMIN
        )
        ctx["plan"] = plan
        return ctx

    def test_confirmation_reports_the_suspended_centre_not_the_restock_limit(self):
        """The plan is over its 1500-unit restock limit and bound for a suspended centre,
        and the cross-entity state check answers first.

        PRD 2.6: "Because several operations are guarded by many rules at once, the order of
        evaluation is part of the contract: the first rule that fails determines the
        response, and no later rule may mask an earlier one."
        PRD 2.6: "Cross-entity state preconditions, all HTTP 409: the destination centre's
        `receiving_status` is not `SUSPENDED` at confirmation
        (`ERR_FC_RECEIVING_SUSPENDED`)"

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_suspension_error_wins_over_fiscal_restock_limit
        """
        ctx = self._over_limit_draft_at_a_suspended_centre()
        response = api_client.confirm_plan(
            ctx["plan"]["id"], {}, ctx["seller_headers"]
        )
        validate_error(response, ApiErrorId.ERR_FC_RECEIVING_SUSPENDED.value)

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["status"] == "DRAFT"
        assert plan["declared_units"] == 2000
        assert plan["provisional_allocated_units"] == 1500
        assert plan["allocation_status"] == "OVER_LIMIT"

    def test_reopening_the_centre_exposes_the_restock_limit_underneath(self):
        """With the suspension lifted the very same confirmation now fails on the fiscal
        rule instead, and still persists nothing.

        PRD 2.6: "Restock limit at confirmation — `ERR_RESTOCK_LIMIT_EXCEEDED` (HTTP 422)."
        PRD 3.4: "The `FINAL` waterfall runs, and if the resulting `final_allocated_units`
        is strictly below the plan's `declared_units` the confirmation is rejected with
        `ERR_RESTOCK_LIMIT_EXCEEDED` and nothing is persisted; a grant exactly equal to
        `declared_units` is accepted."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_suspension_error_wins_over_fiscal_restock_limit
        """
        ctx = self._over_limit_draft_at_a_suspended_centre()
        api_client.update_fulfillment_center(
            ctx["fc_id"], {"receiving_status": "OPEN"}, ADMIN
        )
        response = api_client.confirm_plan(
            ctx["plan"]["id"], {}, ctx["seller_headers"]
        )
        validate_error(response, ApiErrorId.ERR_RESTOCK_LIMIT_EXCEEDED.value)

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["status"] == "DRAFT"
        assert plan["final_allocated_units"] == 0
        assert plan["prep_compliance_status"] == "PENDING"
        assert plan["confirmed_at"] is None
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 0
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 0
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 0


class TestLabelRequirementOutranksTheSellerMismatch:
    """A line naming another seller's listing with a non-FNSKU label breaks two rules;
    step 11 answers before step 16."""

    def _draft_plus_a_foreign_listing(self) -> dict:
        ctx = setup_baseline()
        other = register_seller(
            legal_name="Southgate Trading",
            storage_cubic_feet_entitlement=500.0000,
            unit_cost_cap_cents=90000,
        )
        foreign = create_listing(other["id"], sku="SKU-FOREIGN")
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
        )
        ctx.update({"other_seller": other, "foreign_listing": foreign, "plan": plan})
        return ctx

    def test_line_creation_reports_the_label_requirement_not_the_mismatch(self):
        """A `MANUFACTURER_BARCODE` label at a `LABEL_ONLY` centre is caught before anyone
        notices the listing belongs to another seller.

        PRD 3.4: "When the profile is `LABEL_ONLY` or `CASE_PACK_STRICT`, every line item
        must have `label_type` of exactly `FNSKU`; anything else triggers
        `ERR_LABEL_REQUIREMENT_UNMET`."
        PRD 2.6: "Label requirement — `ERR_LABEL_REQUIREMENT_UNMET` (HTTP 422), enforced on
        both line-item creation and plan confirmation."

        Design: Difficulty/priority_pair_validation_conflict/line_item_safety_label_error_wins_over_referential_seller_mismatch
        """
        ctx = self._draft_plus_a_foreign_listing()
        response = api_client.create_line_item(
            ctx["plan"]["id"],
            {
                "sku_listing_id": ctx["foreign_listing"]["id"],
                "units": 100,
                "case_pack_units": 10,
                "polybagged": True,
                "label_type": "MANUFACTURER_BARCODE",
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LABEL_REQUIREMENT_UNMET.value)

        plan = read_plan(ctx["plan"]["id"], ctx["seller_id"])
        assert plan["declared_units"] == 0
        assert plan["provisional_allocated_units"] == 0

    def test_a_compliant_label_exposes_the_seller_mismatch_underneath(self):
        """Switching the same line to `FNSKU` clears the label rule and lets the
        referential rule speak, and the plan still holds no lines.

        PRD 3.3: "The line's listing must belong to the plan's own seller — if the listing's
        `seller_account_id` differs from the plan's, the line is rejected with
        `ERR_LISTING_SELLER_MISMATCH`."
        PRD 2.6: "Referential coherence, both HTTP 422: a line item's listing belongs to the
        plan's own seller (`ERR_LISTING_SELLER_MISMATCH`, on line-item creation)"

        Design: Difficulty/priority_pair_validation_conflict/line_item_safety_label_error_wins_over_referential_seller_mismatch
        """
        ctx = self._draft_plus_a_foreign_listing()
        response = api_client.create_line_item(
            ctx["plan"]["id"],
            {
                "sku_listing_id": ctx["foreign_listing"]["id"],
                "units": 100,
                "case_pack_units": 10,
                "polybagged": True,
                "label_type": "FNSKU",
            },
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LISTING_SELLER_MISMATCH.value)

        _rows, meta = validate_paginated(
            api_client.list_plan_line_items(ctx["plan"]["id"], ctx["seller_headers"])
        )
        assert meta["total_count"] == 0
        assert read_plan(ctx["plan"]["id"], ctx["seller_id"])["declared_units"] == 0


class TestClosedFilingWindowOutranksTheResubmissionCap:
    """A third resubmission attempted after the deadline breaks two rules; step 13
    answers before step 15."""

    def _claim_with_both_resubmissions_spent(self) -> dict:
        ctx = setup_received_lot(units=100)
        classify_unfulfillable(
            ctx["lot_id"], ctx["fc_id"], 40, disposition_reason="WAREHOUSE_DAMAGE"
        )
        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 40, 3,
            evidence_reference="CASE-88",
        )
        request_claim_info(claim["id"], "Send warehouse photos")
        resubmit_claim(claim["id"], ctx["seller_id"], 3, "CASE-88-R1")
        request_claim_info(claim["id"], "Send the disposition log")
        resubmit_claim(claim["id"], ctx["seller_id"], 4, "CASE-88-R2")
        request_claim_info(claim["id"], "final ask")
        ctx["claim"] = claim
        return ctx

    def test_resubmission_past_the_deadline_reports_the_closed_window(self):
        """With the clock moved past the 60-day deadline, the temporal rule answers even
        though the resubmission cap is also exhausted.

        PRD 3.8: "Filing pins `filing_deadline_at` to the selected anchor plus 60 days, and
        the claim opens at `status` of `SUBMITTED` with `resubmission_count` of 0,
        `eligible_units`, `approved_units` and `reimbursement_amount_cents` all at 0, and
        `decided_at` null."
        PRD 2.6: "Claim filing window — `ERR_CLAIM_FILING_WINDOW_CLOSED` (HTTP 422),
        enforced on both claim filing and claim resubmission."

        Design: Difficulty/priority_pair_validation_conflict/resubmit_temporal_deadline_error_wins_over_resubmission_cap
        """
        ctx = self._claim_with_both_resubmissions_spent()
        assert ctx["claim"]["filing_deadline_at"].startswith("2026-09-30T00:00:00")
        set_clock("2026-10-01T00:00:00Z")

        response = api_client.resubmit_claim(
            ctx["claim"]["id"],
            {"evidence_document_count": 5, "evidence_reference": "CASE-88-R3"},
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_FILING_WINDOW_CLOSED.value)

        claim = read_claim(ctx["claim"]["id"])
        assert claim["status"] == "INFO_REQUESTED"
        assert claim["resubmission_count"] == 2
        assert claim["evidence_reference"] == "CASE-88-R2"
        assert claim["filing_deadline_at"].startswith("2026-09-30T00:00:00")

    def test_inside_the_window_the_same_attempt_reports_the_exhausted_cap(self):
        """Left inside the filing window, the identical third attempt falls through to the
        structural cap instead.

        PRD 3.8: "The cap is hard: a third resubmission attempt, made when
        `resubmission_count` already stands at 2, is rejected with
        `ERR_RESUBMISSION_LIMIT_REACHED`."
        PRD 3.8: "Resubmission requires `status` of `INFO_REQUESTED` (otherwise
        `ERR_CLAIM_NOT_ACTIONABLE`), a `resubmission_count` strictly below 2, and a logical
        clock at or before `filing_deadline_at`."

        Design: Difficulty/priority_pair_validation_conflict/resubmit_temporal_deadline_error_wins_over_resubmission_cap
        """
        ctx = self._claim_with_both_resubmissions_spent()
        response = api_client.resubmit_claim(
            ctx["claim"]["id"],
            {"evidence_document_count": 5, "evidence_reference": "CASE-88-R3"},
            ctx["seller_headers"],
        )
        validate_error(response, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value)

        claim = read_claim(ctx["claim"]["id"])
        assert claim["status"] == "INFO_REQUESTED"
        assert claim["resubmission_count"] == 2

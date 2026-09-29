"""Transitions, forks and terminal states across the declared machines."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    USER_IDS,
    ApiErrorId,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

Json = Dict[str, Any]


class TestScreeningIsBornFromComplianceSubmission:
    def test_submission_opens_exactly_one_initiated_screening(self, api):
        """PRD §3.3: "The case is born with `status` `INITIATED`,
        `ruleset_version` 1, `denied_party_hits` 0, and with `eccn`,
        `decided_by_user_id`, `license_determination`, `export_license_id` and
        `cleared_at` all null."

        Design: Corner/state_machines/corner_screening_starts_in_initiated_created_by_submit_for_compliance
        """
        ctx = fx.order_with_lines(api)
        order = validate_success(api.submit_for_compliance(ctx["order_id"], OPS_ALICE))

        assert order["fulfillment_status"] == "COMPLIANCE_PENDING"
        assert order["settlement_status"] == "UNSECURED"
        assert order["ordered_goods_value_usd"] == approx_money(25000.00)

        listed, meta = validate_paginated(
            api.list_screenings(
                COMPLIANCE_CARL,
                {"export_order_id": ctx["order_id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        screening = listed[0]
        assert screening["status"] == "INITIATED"
        assert screening["ruleset_version"] == 1
        assert screening["denied_party_hits"] == 0
        assert screening["license_determination"] is None
        assert screening["export_license_id"] is None
        assert screening["cleared_at"] is None

    def test_submission_of_a_lineless_order_creates_no_screening(self, api):
        """PRD §3.2: "The order must have at least one shipment line — an empty
        order is refused with a 422 — and every line must have `quantity` strictly
        greater than zero."

        Design: Corner/state_machines/corner_submit_for_compliance_precondition_no_shipment_lines
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])

        validate_error(
            api.submit_for_compliance(order["id"], OPS_ALICE),
            ApiErrorId.ERR_NO_SHIPMENT_LINES.value,
        )

        assert fx.read_order(api, order["id"])["fulfillment_status"] == "DRAFT"
        _, meta = validate_paginated(
            api.list_screenings(
                COMPLIANCE_CARL,
                {"export_order_id": order["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0


class TestScreeningDecisionFork:
    def test_nlr_decision_clears_the_case_and_the_order_in_one_write(self, api):
        """PRD §3.3: "The case moves to `CLEARED`, `cleared_at` is stamped with the
        current logical clock, and the order moves to `COMPLIANCE_CLEARED`"

        Design: Corner/state_machines/corner_nlr_decision_clears_screening_and_order_in_one_write
        """
        ctx = fx.submitted_for_compliance(api)
        screening = validate_success(
            api.record_screening_decision(
                ctx["screening_id"],
                f.screening_decision_payload(),
                COMPLIANCE_CARL,
            )
        )

        assert screening["status"] == "CLEARED"
        assert screening["license_determination"] == "NLR"
        assert screening["decided_by_user_id"] == USER_IDS["comp_carl"]
        assert screening["cleared_at"] == "2026-08-01T00:00:00Z"
        assert screening["export_license_id"] is None

        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]),
            fulfillment="COMPLIANCE_CLEARED",
            settlement="UNSECURED",
        )
        _, meta = validate_paginated(
            api.list_licenses(
                COMPLIANCE_CARL,
                {
                    "export_control_screening_id": ctx["screening_id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 0

    def test_denied_party_hits_outrank_the_submitted_determination(self, api):
        """PRD §3.3: "A decision recording `denied_party_hits` strictly greater than
        zero also lands here regardless of the submitted determination"

        Design: Corner/state_machines/corner_denied_party_hits_override_nlr_determination_to_blocked
        """
        ctx = fx.submitted_for_compliance(api)
        screening = validate_success(
            api.record_screening_decision(
                ctx["screening_id"],
                f.screening_decision_payload(
                    denied_party_hits=2,
                    notes="Two denied-party name matches on the consignee",
                ),
                COMPLIANCE_CARL,
            )
        )

        assert screening["status"] == "BLOCKED"
        assert screening["denied_party_hits"] == 2
        assert screening["cleared_at"] is None

        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), fulfillment="COMPLIANCE_BLOCKED"
        )

    def test_clearing_with_a_licence_defers_the_value_charge(self, api):
        """PRD §3.3: "The charge fires when an order with determination
        `LICENSE_REQUIRED` enters `BOOKED`."

        Design: Corner/state_machines/corner_clear_with_license_defers_value_charge_until_booking
        """
        ctx = fx.licensed_cleared_order(api)

        assert ctx["screening"]["status"] == "CLEARED"
        assert ctx["screening"]["export_license_id"] == ctx["license_id"]
        assert ctx["screening"]["cleared_at"] == "2026-08-01T00:00:00Z"

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="COMPLIANCE_CLEARED")
        assert order["licensed_value_allocated_usd"] == approx_money(0.00)

        licence = fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert licence["status"] == "ACTIVE"
        assert licence["consumed_value_usd"] == approx_money(0.00)
        assert licence["remaining_value_usd"] == approx_money(50000.00)


class TestOrderCancellationIsTerminal:
    def test_second_cancel_is_refused_and_the_count_falls_only_once(self, api):
        """PRD §3.2: "Cancellation is terminal, decrements the buyer's
        `open_order_count` by one, and increments the order's `version` by one."

        Design: Corner/state_machines/corner_cancelled_order_is_terminal_and_second_cancel_is_rejected
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])
        fx.data(
            api.cancel_order(
                order["id"], {"reason": "Buyer withdrew the enquiry"}, OPS_ALICE
            )
        )

        validate_error(
            api.cancel_order(
                order["id"], {"reason": "Duplicate cancellation attempt"}, OPS_ALICE
            ),
            ApiErrorId.ERR_ORDER_STATE_INVALID.value,
        )

        assert fx.data(api.get_buyer(buyer["id"], COMPLIANCE_CARL))[
            "open_order_count"
        ] == 0
        assert_order_dimensions(
            fx.read_order(api, order["id"]),
            fulfillment="CANCELLED",
            settlement="UNSECURED",
        )


# ---------------------------------------------------------------------------
# The two ExportOrder dimensions move independently
# ---------------------------------------------------------------------------


def _credit_accepted_over_an_uninsured_order(api) -> Json:
    """Capture, review and accept a credit while no policy exists for the buyer."""
    ctx = fx.cleared_order(api)
    ctx = fx.captured_credit(api, ctx, lc_number="LC-2026-0001")
    ctx["version_at_capture"] = ctx["credit"]["version"]
    ctx = fx.opened_terms_review(api, ctx)
    ctx["submit_response"] = api.submit_terms_review(
        ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
    )
    return ctx


class TestCreditAcceptanceMovesOnlyTheMoneyDimension:
    def test_acceptance_leaves_the_physical_dimension_where_it_stood(self, api):
        """PRD §3.4: "The credit moves `UNDER_REVIEW` to `ACCEPTED`, its drawing
        bounds are recomputed, and the order's `settlement_status` moves
        `UNSECURED` to `LC_ACCEPTED`"

        Design: Corner/state_machines/corner_parallel_dimensions_lc_acceptance_moves_settlement_axis_only
        """
        ctx = _credit_accepted_over_an_uninsured_order(api)
        review = validate_success(ctx["submit_response"], 200)

        assert review["status"] == "SUBMITTED"
        assert review["recommendation"] == "ACCEPT"
        assert review["terms_risk_score"] == approx_money(0.00)
        assert review["finding_count"] == 0

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "ACCEPTED"
        assert credit["amendment_round"] == 0

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(
            order, fulfillment="COMPLIANCE_CLEARED", settlement="LC_ACCEPTED"
        )
        assert order["insured_exposure_usd"] == approx_money(0.00)
        assert fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))[
            "aggregate_exposure_usd"
        ] == approx_money(0.00)

    def test_amendment_walks_the_credit_and_the_money_axis_backwards(self, api):
        """PRD §3.4: "`max_drawable_usd` is `amount_usd` multiplied by the quantity
        one plus `tolerance_pct` divided by 100, rounded to two decimal places"

        Design: Corner/state_machines/corner_lc_amendment_cycle_reverts_credit_and_money_axis
        """
        ctx = _credit_accepted_over_an_uninsured_order(api)
        validate_success(ctx["submit_response"], 200)
        version_after_acceptance = fx.credit_version(api, ctx["lc_id"])
        assert version_after_acceptance > ctx["version_at_capture"]

        credit = validate_success(
            api.amend_credit(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": version_after_acceptance,
                    "amount_usd": 30000.00,
                    "tolerance_pct": 10.00,
                },
                OPS_ALICE,
            ),
            200,
        )
        assert credit["status"] == "RECEIVED"
        assert credit["amendment_round"] == 1
        assert credit["amount_usd"] == approx_money(30000.00)
        assert credit["max_drawable_usd"] == approx_money(33000.00)
        assert credit["min_drawable_usd"] == approx_money(27000.00)

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="UNSECURED")
        assert order["insured_exposure_usd"] == approx_money(0.00)


class TestRestrictedPartyCascadeUnwindsFreightAndLicence:
    def test_one_designation_unwinds_booking_sailing_licence_and_screening(self, api):
        """PRD §3.1: "For every order that moved, the order's screening moves from
        `CLEARED` back to `INITIATED`, its `ruleset_version` is incremented by one,
        and its `cleared_at` is reset to null."

        Design: Corner/state_machines/corner_restricted_party_flag_four_link_cascade_unwinds_booking_and_license
        """
        ctx = fx.licensed_cleared_order(
            api, license_overrides={"licensed_value_usd": 25000.00}
        )
        ctx = fx.booked_order(api, base=ctx)

        buyer = validate_success(
            api.patch_restricted_party_flag(
                ctx["buyer_id"],
                {
                    "restricted_party_flag": True,
                    "restricted_party_reason": "Added to the entity list on 2026-08-01",
                },
                COMPLIANCE_CARL,
            ),
            200,
        )
        assert buyer["restricted_party_flag"] is True
        assert (
            buyer["restricted_party_reason"] == "Added to the entity list on 2026-08-01"
        )

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="COMPLIANCE_BLOCKED")
        assert order["licensed_value_allocated_usd"] == approx_money(0.00)

        booking = fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))
        assert booking["status"] == "CANCELLED"
        assert booking["cancel_reason"] == "RESTRICTED_PARTY_CASCADE"

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["booked_weight_kg"] == approx_weight(0.000)
        assert sailing["status"] == "OPEN"

        licence = fx.data(api.get_license(ctx["license_id"], COMPLIANCE_CARL))
        assert licence["consumed_value_usd"] == approx_money(0.00)
        assert licence["remaining_value_usd"] == approx_money(25000.00)
        assert licence["status"] == "ACTIVE"

        screening = fx.data(api.get_screening(ctx["screening_id"], COMPLIANCE_CARL))
        assert screening["status"] == "INITIATED"
        assert screening["ruleset_version"] == 2
        assert screening["cleared_at"] is None


class TestBookingCancelReturnsTheSailingToOpen:
    def test_cancel_frees_a_full_sailing_and_pulls_the_order_back(self, api):
        """PRD §3.6: "the order returns from `BOOKED` to `COMPLIANCE_CLEARED`;
        `licensed_value_allocated_usd` is released to 0.00 and the license's ledger
        is recomputed"

        Design: Corner/state_machines/corner_booking_cancel_returns_sailing_from_full_to_open_exactly
        """
        ctx = fx.booked_order(
            api, sailing_overrides={"capacity_weight_kg": 1200.000}
        )
        assert fx.read_sailing(api, ctx["sailing_id"])["status"] == "FULL"

        booking = validate_success(
            api.cancel_booking(
                ctx["booking_id"],
                {"cancel_reason": "Carrier rolled the booking"},
                OPS_ALICE,
            ),
            200,
        )
        assert booking["status"] == "CANCELLED"
        assert booking["cancel_reason"] == "Carrier rolled the booking"
        assert booking["chargeable_weight_kg"] == approx_weight(1200.000)

        sailing = fx.read_sailing(api, ctx["sailing_id"])
        assert sailing["booked_weight_kg"] == approx_weight(0.000)
        assert sailing["status"] == "OPEN"

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="COMPLIANCE_CLEARED")
        assert order["provisional_seller_cost_usd"] == approx_money(584.00)
        assert order["provisional_buyer_cost_usd"] == approx_money(2816.25)


class TestBillOfLadingForksOnTheShippedQuantities:
    def test_a_sixty_percent_shipment_takes_the_short_shipped_branch(self, api):
        """PRD §3.6: "Issuance creates the `BILL_OF_LADING` document with `status`
        `ISSUED`, `revision` 1 and `on_board_date` stamped; writes each
        `shipped_quantity` onto its line and recomputes `shipped_goods_value_usd`"

        Design: Corner/state_machines/corner_bill_of_lading_short_shipment_branch_diverges_from_full_branch
        """
        ctx = fx.confirmed_booking(api, fx.booked_order(api))
        document = validate_success(
            api.issue_bill_of_lading(
                ctx["booking_id"],
                f.bill_of_lading_payload(
                    [f.shipped_line(ctx["line_ids"][0], 60.000)],
                    on_board_date="2026-08-01T00:00:00Z",
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert document["doc_type"] == "BILL_OF_LADING"
        assert document["status"] == "ISSUED"
        assert document["revision"] == 1
        assert document["on_board_date"] == "2026-08-01T00:00:00Z"

        assert fx.data(api.get_booking(ctx["booking_id"], OPS_ALICE))["status"] == "SHIPPED"

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, fulfillment="SHORT_SHIPPED")
        assert order["shipped_goods_value_usd"] == approx_money(15000.00)
        assert order["short_shipped_value_usd"] == approx_money(10000.00)
        assert order["final_seller_cost_usd"] == approx_money(542.00)
        assert order["final_buyer_cost_usd"] == approx_money(1850.00)
        assert order["cost_allocation_variance_usd"] == approx_money(-42.00)

        line = fx.data(api.get_shipment_line(ctx["line_ids"][0], OPS_ALICE))
        assert line["shipped_quantity"] == approx_weight(60.000)
        assert line["quantity"] == approx_weight(100.000)

        assert fx.read_sailing(api, ctx["sailing_id"])[
            "booked_weight_kg"
        ] == approx_weight(1200.000)


# ---------------------------------------------------------------------------
# The examination fork and the settlement cascade behind it
# ---------------------------------------------------------------------------


def _tender_lodged_with_the_invoice_alone(api) -> Json:
    """The whole happy path up to a PRESENTED tender carrying the invoice only."""
    ctx = fx.full_tender(api, credit_overrides={"lc_number": "LC-2026-0001"})
    return fx.lodged_presentation(api, ctx, document_ids=[ctx["invoice_id"]])


class TestSettlementBubblesThroughEveryLink:
    def test_settlement_closes_the_order_and_utilises_the_credit(self, api):
        """PRD §3.8: "Alongside the cascade, the credit moves from `ACCEPTED` to
        `UTILISED` when `drawn_amount_usd` reaches at least `min_drawable_usd`, and
        the order's `fulfillment_status` auto-advances from `SHIPPED` or
        `SHORT_SHIPPED` to `CLOSED` when that dimension's own preconditions hold."

        Design: Corner/state_machines/corner_settlement_bubbles_order_to_closed_and_credit_to_utilised
        """
        ctx = _tender_lodged_with_the_invoice_alone(api)
        ctx = fx.examined_presentation(api, ctx, [])

        presentation = validate_success(
            api.settle_presentation(
                ctx["presentation_id"], f.settlement_payload(24850.00), FINANCE_FRANK
            ),
            200,
        )
        assert presentation["status"] == "HONOURED"
        assert presentation["received_amount_usd"] == approx_money(24850.00)
        assert presentation["negotiable_amount_usd"] == approx_money(24850.00)

        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]),
            fulfillment="CLOSED",
            settlement="PAID",
        )

        credit = fx.read_credit(api, ctx["lc_id"])
        assert credit["status"] == "UTILISED"
        assert credit["drawn_amount_usd"] == approx_money(24850.00)

        assert fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))[
            "open_order_count"
        ] == 0


class TestExaminationDiscrepantBranch:
    def test_a_critical_finding_reverts_the_money_axis_and_is_persisted(self, api):
        """PRD §3.7: "When the examination raises **at least one** finding of
        `severity` `CRITICAL` or `MAJOR`, the presentation moves `PRESENTED` to
        `DISCREPANT`, `open_finding_count` is stored, and the order's
        `settlement_status` moves from `DOCS_PRESENTED` back to `LC_ACCEPTED`."

        Design: Corner/state_machines/corner_examine_discrepant_branch_reverts_money_axis_and_writes_finding
        """
        ctx = _tender_lodged_with_the_invoice_alone(api)

        presentation = validate_success(
            api.examine_presentation(
                ctx["presentation_id"],
                {"findings": [f.examination_finding()]},
                REVIEWER_BOB,
            ),
            200,
        )
        assert presentation["status"] == "DISCREPANT"
        assert presentation["examined_by_user_id"] == USER_IDS["rev_bob"]
        assert presentation["open_finding_count"] == 1
        assert presentation["presentation_round"] == 1
        assert presentation["examination_risk_score"] == approx_money(40.00)

        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]),
            fulfillment="SHIPPED",
            settlement="LC_ACCEPTED",
        )

        findings = fx.findings_for_presentation(api, ctx["presentation_id"])
        assert len(findings) == 1
        assert findings[0]["source"] == "DOCUMENT"
        assert findings[0]["cure_status"] == "OPEN"
        assert findings[0]["raised_in_round"] == 1
        assert findings[0]["lc_terms_review_id"] is None


# ---------------------------------------------------------------------------
# The bounded dispute negotiation loop
# ---------------------------------------------------------------------------


def _quality_dispute_opened_by_the_buyer(api) -> Json:
    ctx = fx.order_with_lines(api)
    ctx["dispute"] = fx.data(
        api.open_dispute(
            f.dispute_payload(ctx["order_id"], claimed_amount_usd=5000.00),
            ctx["buyer_headers"],
        )
    )
    ctx["dispute_id"] = ctx["dispute"]["id"]
    return ctx


class TestDisputeNegotiationLoop:
    def test_countering_a_case_with_no_offer_on_the_table_is_refused(self, api):
        """PRD §3.9: "A `ForeignBuyer`, who must be the order's own buyer, counters
        an `OFFERED` case with a `counter_amount_usd` that must be **strictly
        greater** than `current_offer_usd` and at most `claimed_amount_usd`."

        Design: Corner/state_machines/corner_counter_on_open_dispute_is_invalid_transition
        """
        ctx = _quality_dispute_opened_by_the_buyer(api)

        validate_error(
            api.counter_offer(
                ctx["dispute_id"], {"counter_amount_usd": 4500.00}, ctx["buyer_headers"]
            ),
            ApiErrorId.ERR_DISPUTE_STATE_INVALID.value,
        )

        dispute = fx.data(api.get_dispute(ctx["dispute_id"], FINANCE_FRANK))
        assert dispute["status"] == "OPEN"
        assert dispute["current_offer_usd"] is None
        assert dispute["negotiation_round"] == 0
        assert dispute["opened_by_role"] == "ForeignBuyer"

    def test_the_fourth_counter_escalates_instead_of_incrementing_the_round(self, api):
        """PRD §3.9: "When a counter arrives while `negotiation_round` already
        equals 3, the case is not rejected: it is forced from `COUNTERED` to
        `ESCALATED`, leaving `current_offer_usd` at its last value."

        Design: Corner/state_machines/corner_negotiation_loop_escalates_when_round_bound_reached
        """
        ctx = _quality_dispute_opened_by_the_buyer(api)
        for offer, counter in ((4000.00, 4500.00), (4200.00, 4400.00), (4300.00, 4350.00)):
            fx.data(
                api.make_offer(
                    ctx["dispute_id"], {"offer_amount_usd": offer}, FINANCE_FRANK
                )
            )
            fx.data(
                api.counter_offer(
                    ctx["dispute_id"],
                    {"counter_amount_usd": counter},
                    ctx["buyer_headers"],
                )
            )

        dispute = validate_success(
            api.counter_offer(
                ctx["dispute_id"], {"counter_amount_usd": 4360.00}, ctx["buyer_headers"]
            ),
            200,
        )
        assert dispute["status"] == "ESCALATED"
        assert dispute["negotiation_round"] == 3
        assert dispute["current_offer_usd"] == approx_money(4350.00)
        assert dispute["settlement_amount_usd"] is None

        _, meta = validate_paginated(
            api.list_disputes(
                FINANCE_FRANK,
                {
                    "export_order_id": ctx["order_id"],
                    "status": "ESCALATED",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1


class TestTradeDocumentTerminalStates:
    def test_issuing_an_already_issued_document_is_not_idempotent(self, api):
        """PRD §3.5: "Issuance moves the document to `ISSUED`, recomputes the
        order's `outstanding_receivable_usd` when the type is `COMMERCIAL_INVOICE`,
        and increments both the document's and the order's `version` by one."

        Design: Corner/state_machines/corner_second_issue_on_issued_document_is_rejected
        """
        ctx = fx.order_with_lines(api)
        invoice = fx.data(
            api.generate_document(f.document_payload(ctx["order_id"]), OPS_ALICE)
        )
        fx.data(api.issue_document(invoice["id"], OPS_ALICE))

        validate_error(
            api.issue_document(invoice["id"], OPS_ALICE),
            ApiErrorId.ERR_DOCUMENT_STATE_INVALID.value,
        )

        stored = fx.data(api.get_document(invoice["id"], OPS_ALICE))
        assert stored["status"] == "ISSUED"
        assert stored["revision"] == 1

        assert fx.read_order(api, ctx["order_id"])[
            "outstanding_receivable_usd"
        ] == approx_money(25000.00)

    def test_voiding_an_unlinked_draft_document_is_permitted(self, api):
        """PRD §3.5: "Voiding a `DRAFT` document requires that it have no links at
        all, and does nothing beyond recording the reason and bumping the
        document's `version`."

        Design: Corner/state_machines/corner_void_draft_document_without_links_is_permitted
        """
        ctx = fx.order_with_lines(api)
        invoice = fx.data(
            api.generate_document(f.document_payload(ctx["order_id"]), OPS_ALICE)
        )

        voided = validate_success(
            api.void_document(
                invoice["id"], {"void_reason": "Wrong consignee captured"}, OPS_ALICE
            ),
            200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "Wrong consignee captured"
        assert voided["revision"] == 1

        assert fx.read_order(api, ctx["order_id"])[
            "outstanding_receivable_usd"
        ] == approx_money(0.00)

        _, meta = validate_paginated(
            api.list_presentation_links(
                OPS_ALICE,
                {"trade_document_id": invoice["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0

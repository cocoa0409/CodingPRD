"""Co-op accrual dual variants, delivery cascade, and co-op claim lifecycle."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    get_success_data, make_contractor_headers, TEST_USERS, ApiErrorId,
    make_contractor, make_model, make_pool, get_contractor,
    create_draft_order, add_line, submit_order, ship_order, deliver_order,
    deliver_merchandise, setup_contractor_with_final_accrual,
    file_coop_claim, set_clock, get_pool,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


class TestProvisionalVsFinalDivergence:
    """Identical line data, two accrual variants: provisional counts the
    in-flight order, final counts only delivered merchandise.

    The delivered seed is 4,000,000 — below the SILVER threshold — so the
    contractor stays STANDARD and the in-flight order prices at full list
    (STANDARD receives no discount, PRD §3.1)."""

    def _setup_two_orders(self):
        contractor = make_contractor(license_number="LIC-001")
        order_a, _ = deliver_merchandise(contractor, 4_000_000, family_code="FAM-X1")
        return contractor, order_a

    def test_provisional_counts_inflight_final_counts_delivered_only(self, api):
        """PRD §3.9: "The **provisional** figure, `coop_accrual_provisional_cents`, covers lines on orders in `SUBMITTED`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, and `DELIVERED` — cancelled orders excluded — and is recomputed at submit, backorder, cancellation, and delivery."
        PRD §3.9: "The **final** figure, `coop_accrual_final_cents`, is the spendable balance: two percent of delivered lines only, minus the `approved_amount_cents` of the contractor's `PAID` claims."
        PRD §3.1: "A contractor's `ytd_purchase_cents` accumulates the merchandise totals of their orders that have reached `DELIVERED`, counting only orders whose `submitted_at` falls inside the current calendar year of the logical clock; cancelled and in-flight orders contribute nothing."

        Design: Difficulty/dual_variant_calc/coop_accrual_provisional_vs_final_divergence
        """
        contractor, _ = self._setup_two_orders()
        model_b = make_model(model_number="CU-5T", family_code="FAM-X2",
                             list_price_cents=5_000_000)
        order_b = create_draft_order(contractor)
        add_line(order_b["id"], contractor, equipment_model_id=model_b["id"], quantity=1)
        submit_order(order_b["id"], contractor)

        contractor = get_contractor(contractor["id"])
        assert contractor["coop_accrual_provisional_cents"] == 180_000, (
            f"2% of (4,000,000 delivered + 5,000,000 in flight) = 180000, "
            f"got {contractor['coop_accrual_provisional_cents']}")
        assert contractor["coop_accrual_final_cents"] == 80_000, (
            f"2% of delivered only = 80000, got {contractor['coop_accrual_final_cents']}")
        assert contractor["ytd_purchase_cents"] == 4_000_000

    def test_submit_raises_provisional_while_final_unmoved(self, api):
        """PRD §3.4: "Every reservation change is reflected in the contractor's provisional co-op accrual (§3.9), which counts lines on `SUBMITTED`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, and `DELIVERED` orders alike — a $100,000 submitted order raises the provisional figure by $2,000 while moving the final figure by nothing."

        Design: Difficulty/dual_variant_calc/coop_accrual_provisional_vs_final_divergence
        """
        contractor, _ = self._setup_two_orders()
        mid = get_contractor(contractor["id"])
        assert mid["coop_accrual_provisional_cents"] == 80_000
        assert mid["coop_accrual_final_cents"] == 80_000, (
            "with only the delivered order, both variants agree")

        model_b = make_model(model_number="CU-5T", family_code="FAM-X2",
                             list_price_cents=5_000_000)
        order_b = create_draft_order(contractor)
        add_line(order_b["id"], contractor, equipment_model_id=model_b["id"], quantity=1)
        submit_order(order_b["id"], contractor)

        after = get_contractor(contractor["id"])
        assert after["coop_accrual_provisional_cents"] == 180_000, (
            "the in-flight order raises only the provisional figure")
        assert after["coop_accrual_final_cents"] == 80_000, (
            "the final figure moves by nothing until delivery")


class TestDeliveryCascade:
    """Delivering the second order crosses the SILVER threshold and converges
    the two accrual variants."""

    def _setup(self):
        contractor = make_contractor(license_number="LIC-007")
        deliver_merchandise(contractor, 4_000_000, family_code="FAM-U1")
        model_b = make_model(model_number="CU-E7B", family_code="FAM-U2",
                             list_price_cents=1_000_000)
        order_b = create_draft_order(contractor)
        add_line(order_b["id"], contractor, equipment_model_id=model_b["id"], quantity=1)
        submit_order(order_b["id"], contractor)
        ship_order(order_b["id"])
        return contractor, order_b

    def test_delivery_recomputes_ytd_and_flips_tier(self, api):
        """PRD §3.4: "Delivery moves `SHIPPED` → `DELIVERED` and fires a three-step cascade on the contractor: first `ytd_purchase_cents` and the final co-op accrual are recomputed from delivered lines; then the tier is re-evaluated from the new year-to-date figure, and on a tier change the period caps of the contractor's pending co-op claims re-derive; finally the provisional accrual is recomputed with this order's lines now part of the delivered population."
        PRD §3.1: "Whenever an order is delivered the year-to-date figure is recomputed and the tier re-evaluated against inclusive thresholds: at least $50,000 (5,000,000 cents) earns `SILVER`, at least $200,000 (20,000,000 cents) earns `GOLD`, and at least $500,000 (50,000,000 cents) earns `PLATINUM`; below $50,000 the contractor remains `STANDARD`."

        Design: Difficulty/transitive_cascade/delivery_cascade_accrual_tier_provisional
        """
        contractor, order_b = self._setup()
        before = get_contractor(contractor["id"])
        assert before["ytd_purchase_cents"] == 4_000_000
        assert before["tier"] == "STANDARD", "setup: 4,000,000 is below the SILVER threshold"
        deliver_order(order_b["id"])
        after = get_contractor(contractor["id"])
        assert after["ytd_purchase_cents"] == 5_000_000
        assert after["tier"] == "SILVER", (
            "crossing exactly 5,000,000 on delivery flips STANDARD to SILVER")

    def test_delivery_converges_accrual_variants(self, api):
        """PRD §3.4: "Delivery moves `SHIPPED` → `DELIVERED` and fires a three-step cascade on the contractor: first `ytd_purchase_cents` and the final co-op accrual are recomputed from delivered lines; then the tier is re-evaluated from the new year-to-date figure, and on a tier change the period caps of the contractor's pending co-op claims re-derive; finally the provisional accrual is recomputed with this order's lines now part of the delivered population."
        PRD §3.9: "The **final** figure, `coop_accrual_final_cents`, is the spendable balance: two percent of delivered lines only, minus the `approved_amount_cents` of the contractor's `PAID` claims."

        Design: Difficulty/transitive_cascade/delivery_cascade_accrual_tier_provisional
        """
        contractor, order_b = self._setup()
        before = get_contractor(contractor["id"])
        assert before["coop_accrual_provisional_cents"] == 100_000, (
            "2% of (4,000,000 delivered + 1,000,000 shipped) before delivery")
        assert before["coop_accrual_final_cents"] == 80_000, (
            "2% of the 4,000,000 delivered only")
        deliver_order(order_b["id"])
        after = get_contractor(contractor["id"])
        assert after["coop_accrual_final_cents"] == 100_000
        assert after["coop_accrual_provisional_cents"] == 100_000, (
            "with every order delivered, both bases hold the same lines")


class TestCoopClaimConservation:
    """Money conservation: only a PAID claim debits the spendable balance."""

    def test_verify_then_reject_leaves_accrual_unchanged(self, api):
        """PRD §3.9: "Rejection (`REJECT`) is terminal, as is `PAID`: payment debits the contractor's `coop_accrual_final_cents` by the approved amount, which is what makes the final accrual a spendable balance."

        Design: Difficulty/compensating_invariant/accrual_balance_conserved_across_claim_and_reject
        """
        ctx = setup_contractor_with_final_accrual(10_000_000)
        contractor = ctx["contractor"]
        assert contractor["coop_accrual_final_cents"] == 200_000, "setup"
        claim = file_coop_claim(contractor, spend_cents=50_000,
                                invoice_reference="INV-AD-001")
        validate_success(api_client.coop_claim_decision(
            claim["id"], {"action": "VERIFY"}, ADMIN), 200)
        rejected = validate_success(api_client.coop_claim_decision(
            claim["id"], {"action": "REJECT"}, ADMIN), 200)
        assert rejected["status"] == "REJECTED"
        after = get_contractor(contractor["id"])
        assert after["coop_accrual_final_cents"] == 200_000, (
            "file-then-reject must not debit the spendable balance")
        assert after["coop_accrual_provisional_cents"] == 200_000

    def test_verify_computes_eligible_as_min_of_three(self, api):
        """PRD §3.9: "Verification (`VERIFY`) computes `eligible_amount_cents` as the smallest of three quantities: the claimed `spend_cents`, the contractor's current `coop_accrual_final_cents` at verification time, and the remaining cap for the claim's period — a period's cap being fifty percent of the final accrual for that period's window, reduced by amounts already claimed against the period."

        Design: Difficulty/compensating_invariant/accrual_balance_conserved_across_claim_and_reject
        """
        ctx = setup_contractor_with_final_accrual(10_000_000)
        contractor = ctx["contractor"]
        claim = file_coop_claim(contractor, spend_cents=50_000,
                                invoice_reference="INV-AD-002")
        assert claim["eligible_amount_cents"] == 0, "setup: claims open with zero eligible"
        verified = validate_success(api_client.coop_claim_decision(
            claim["id"], {"action": "VERIFY"}, ADMIN), 200)
        assert verified["status"] == "VERIFIED"
        assert verified["eligible_amount_cents"] == 50_000, (
            f"min(spend 50000, final accrual 200000, period cap 100000) == 50000, "
            f"got {verified['eligible_amount_cents']}")


def test_coop_approval_above_eligible_rejected(api):
    """PRD §3.9: "Approval (`APPROVE`) records an `approved_amount_cents` — empty until this point — that may not exceed the `eligible_amount_cents`, lest the decision be rejected with `ERR_ACCRUAL_EXCEEDED` (422)."

    Design: Corner/validations/coop_approval_above_eligible_rejected
    """
    ctx = setup_contractor_with_final_accrual(10_000_000)
    contractor = ctx["contractor"]
    claim = file_coop_claim(contractor, spend_cents=50_000,
                            invoice_reference="INV-A404")
    verified = validate_success(api_client.coop_claim_decision(
        claim["id"], {"action": "VERIFY"}, ADMIN), 200)
    assert verified["eligible_amount_cents"] == 50_000, "setup"
    res = api_client.coop_claim_decision(
        claim["id"], {"action": "APPROVE", "approved_amount_cents": 60_000}, ADMIN)
    validate_error(res, ApiErrorId.ERR_ACCRUAL_EXCEEDED)
    claim = get_success_data(api_client.get_coop_claim(claim["id"], ADMIN))
    assert claim["status"] == "VERIFIED"


def test_coop_resubmit_after_dispute_restores_submitted(api):
    """PRD §3.9: "Disputing (`DISPUTE`) hands the claim back: the contractor resubmits (`RESUBMIT`) with a corrected `spend_cents`, the claim returns to `SUBMITTED`, and `eligible_amount_cents` resets to zero until re-verified — the loop `SUBMITTED` → `VERIFIED` → `DISPUTED` → `SUBMITTED` may repeat."

    Design: Corner/state_machines/coop_claim_resubmit_loop_restores_submitted
    """
    ctx = setup_contractor_with_final_accrual(10_000_000)
    contractor = ctx["contractor"]
    claim = file_coop_claim(contractor, spend_cents=80_000,
                            invoice_reference="INV-D204")
    validate_success(api_client.coop_claim_decision(
        claim["id"], {"action": "VERIFY"}, ADMIN), 200)
    disputed = validate_success(api_client.coop_claim_decision(
        claim["id"], {"action": "DISPUTE"}, ADMIN), 200)
    assert disputed["status"] == "DISPUTED", "setup"
    resubmitted = validate_success(api_client.coop_claim_decision(
        claim["id"], {"action": "RESUBMIT", "spend_cents": 60_000},
        make_contractor_headers(contractor["id"])), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["spend_cents"] == 60_000
    assert resubmitted["eligible_amount_cents"] == 0, (
        "eligible resets to zero until re-verified")


def test_cancelled_order_excluded_from_both_accruals(api):
    """PRD §3.9: "The **provisional** figure, `coop_accrual_provisional_cents`, covers lines on orders in `SUBMITTED`, `BACKORDERED`, `ALLOCATED`, `SHIPPED`, and `DELIVERED` — cancelled orders excluded — and is recomputed at submit, backorder, cancellation, and delivery."
    PRD §3.9: "The **final** figure, `coop_accrual_final_cents`, is the spendable balance: two percent of delivered lines only, minus the `approved_amount_cents` of the contractor's `PAID` claims."

    Design: Corner/calculations/coop_accrual_input_set_filtering
    """
    set_clock("2026-08-05T00:00:00Z")
    contractor = make_contractor(license_number="LIC-C303")
    model = make_model(model_number="CU-F303", family_code="FAM-D",
                       list_price_cents=4_000_000)
    # Pool of 1 against a quantity-2 line sends the order to BACKORDERED, which
    # still accrues provisionally; closing the pool reverts it to SUBMITTED —
    # the cancellable state this assertion needs.
    pool = make_pool(family_code="FAM-D", total_qty=1)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=2)
    order = submit_order(order["id"], contractor)
    assert order["status"] == "BACKORDERED", "setup"
    mid = get_contractor(contractor["id"])
    assert mid["coop_accrual_provisional_cents"] == 160_000, (
        "setup: 2% of the 8,000,000 in-flight order (2 x 4,000,000) accrues "
        "provisionally")
    validate_success(api_client.close_allocation_pool(pool["id"], ADMIN), 200)
    cancelled = validate_success(api_client.cancel_order(
        order["id"], make_contractor_headers(contractor["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    after = get_contractor(contractor["id"])
    assert after["coop_accrual_provisional_cents"] == 0, (
        "cancelled orders are excluded from the provisional base")
    assert after["coop_accrual_final_cents"] == 0


def test_immediate_visibility_of_cascade_after_deliver(api):
    """PRD §2.9: "Cascades cross entity boundaries and are part of the contract. Delivering an order recomputes the contractor's year-to-date purchases, final co-op accrual, and tier; lapsing or voiding a warranty registration denies its open parts claims; a cylinder passing thirty days out in the field forces its holder's compliance standing down; completing a course grants one credit per attendee and refreshes each attendee's balance."

    Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
    """
    contractor = make_contractor(license_number="LIC-C900")
    model = make_model(model_number="CU-I900", family_code="FAM-M1",
                       list_price_cents=2_000_000)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
    submit_order(order["id"], contractor)
    ship_order(order["id"])
    delivered = deliver_order(order["id"])
    assert delivered["status"] == "DELIVERED", "setup"
    contractor = get_contractor(contractor["id"])
    assert contractor["ytd_purchase_cents"] == 2_000_000, (
        "the very next read reflects the delivery cascade")
    assert contractor["coop_accrual_final_cents"] == 40_000

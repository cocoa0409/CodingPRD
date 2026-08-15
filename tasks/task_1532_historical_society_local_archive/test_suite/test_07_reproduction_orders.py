"""Reproduction orders: dual-variant fee computation, tier/multiplier
interaction, academic discount evaluation order, deed gates, embargo, requote,
quota, payment, delivery citation, and the pay/refund ledger invariant."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_order_quote,
    create_order,
    get_accession,
    get_researcher,
    invoice_order,
    make_registrar_headers,
    make_researcher_headers,
    pay_order,
    set_clock,
    setup_approved_request,
    setup_available_item,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_accessioned,
    create_collection,
    create_item,
    create_published_finding_aid,
    create_zone,
    catalog_item,
    make_item_available,
)

RRS = {"X-User-ID": "rrs-1", "X-User-Role": "ReadingRoomStaff", "Content-Type": "application/json"}
ARCH = {"X-User-ID": "arch-1", "X-User-Role": "Archivist", "Content-Type": "application/json"}
REG = {"X-User-ID": "reg-1", "X-User-Role": "Registrar", "Content-Type": "application/json"}


def _order_ctx(purpose="PERSONAL", **item_kwargs):
    """AVAILABLE item + APPROVED request. Returns (ctx, researcher, request)."""
    ctx = setup_available_item(**item_kwargs)
    researcher, request = setup_approved_request([ctx["item"]["id"]],
                                                 purpose=purpose)
    return ctx, researcher, request


class TestQuoteInvoiceDivergence:

    def test_quote_and_invoice_diverge_on_page_basis(self):
        """PRD §3.7: "The pricing algorithm runs identically at quote time and
        at invoice time, differing only in the page count fed to it. First, the
        image component prices pages in three tiers — the first 50 pages at 35
        cents each, the next 150 pages at 25 cents each, and every page beyond
        200 at 15 cents each — multiplies the tier cost by the format
        multiplier, multiplies again by 1.5 when `rush` is true, and rounds half
        up to whole cents."
        PRD §3.7: "Staff then invoice the order with the true `actual_pages` (a
        positive count), moving `APPROVED → INVOICED` and storing the recomputed
        fee as `invoiced_fee_cents`."

        Design: Difficulty/dual_variant_calc/repro_fee_quote_vs_invoice_divergence
        """
        ctx, researcher, request = _order_ctx(
            appraised_value_cents=50000, item_format="MANUSCRIPT")
        item_id = ctx["item"]["id"]

        order = create_order(request["id"], researcher["id"], [item_id],
                             page_estimate=60)
        # Quoted from the estimate: 50*35 + 10*25
        assert order["quoted_fee_cents"] == 2000

        approve_order_quote(order["id"], researcher["id"])
        invoiced = invoice_order(order["id"], actual_pages=66)
        # Invoiced from actual pages: 50*35 + 16*25
        assert invoiced["invoiced_fee_cents"] == 2150
        assert invoiced["status"] == "INVOICED", (
            "2150 <= floor(2000 * 1.10) == 2200, so the requote gate is silent")
        assert invoiced["quoted_fee_cents"] != invoiced["invoiced_fee_cents"]

    def test_quote_stored_at_creation_invoice_null_until_invoiced(self):
        """PRD §3.7: "With the gates passed, the order is quoted and lands in
        `QUOTED` with `quoted_fee_cents` computed from `page_estimate`."
        PRD §3.7: "Staff then invoice the order with the true `actual_pages` (a
        positive count), moving `APPROVED → INVOICED` and storing the recomputed
        fee as `invoiced_fee_cents`."

        Design: Difficulty/dual_variant_calc/repro_fee_quote_vs_invoice_divergence
        """
        ctx, researcher, request = _order_ctx(
            appraised_value_cents=50000, item_format="MANUSCRIPT")
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)
        assert order["status"] == "QUOTED"
        assert order["quoted_fee_cents"] == 2000
        assert order["invoiced_fee_cents"] is None, (
            "the final fee does not exist until staff invoice the order")


class TestTieredFeeStraddle:

    def test_highres_rush_order_straddles_all_tiers(self):
        """PRD §3.7: "First, the image component prices pages in three tiers —
        the first 50 pages at 35 cents each, the next 150 pages at 25 cents
        each, and every page beyond 200 at 15 cents each — multiplies the tier
        cost by the format multiplier, multiplies again by 1.5 when `rush` is
        true, and rounds half up to whole cents."
        PRD §3.7: "The format drives pricing: `SCAN_STANDARD` carries a
        multiplier of 1.0, `SCAN_HIGHRES` 1.8, and `PRINT_PHOTOGRAPH` 2.5.
        License classes carry flat fees: `PERSONAL` adds nothing,
        `NONPROFIT_PUBLICATION` adds 1500 cents, and `COMMERCIAL_PUBLICATION`
        adds 7500 cents."

        Design: Difficulty/combinatorial_formula/tiered_fee_straddle_multipliers
        """
        ctx, researcher, request = _order_ctx(
            appraised_value_cents=20000, item_format="BOUND_VOLUME")
        # 210 pages: tier cost 50*35 + 150*25 + 10*15 = 5650;
        # image round_half_up(5650 * 1.8 * 1.5) = 15255; + 7500 license.
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], format="SCAN_HIGHRES",
                             page_estimate=210,
                             license_class="COMMERCIAL_PUBLICATION", rush=True)
        assert order["quoted_fee_cents"] == 22755, (
            f"expected 22755 (15255 + 7500); got {order['quoted_fee_cents']}")

    def test_minimum_fee_clamps_small_order(self):
        """PRD §3.7: "Fourth, the minimum order fee applies: the larger of 500
        cents and the discounted amount. Fifth and last, the license flat fee
        for the order's `license_class` is added."

        Design: Difficulty/combinatorial_formula/tiered_fee_straddle_multipliers
        """
        ctx, researcher, request = _order_ctx(
            appraised_value_cents=20000, item_format="BOUND_VOLUME")
        # 5 pages: image 5*35 = 175, clamped to the 500-cent minimum.
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], format="SCAN_STANDARD",
                             page_estimate=5)
        assert order["quoted_fee_cents"] == 500, (
            f"image 175 must clamp to the 500-cent minimum; got "
            f"{order['quoted_fee_cents']}")


class TestAcademicDiscountOrder:

    def test_academic_discount_applies_to_image_component_only(self):
        """PRD §3.7: "Second, the academic discount is decided: when the linked
        research request's `purpose` is `ACADEMIC` and the pre-discount image
        component is at least 5000 cents, the discount rate is 20 percent;
        otherwise it is zero. Third, the discounted amount is the image
        component multiplied by one minus the discount rate, rounded half up to
        whole cents. Fourth, the minimum order fee applies: the larger of 500
        cents and the discounted amount. Fifth and last, the license flat fee
        for the order's `license_class` is added. The evaluation order is pinned
        — the discount tier keys on the pre-discount component, the minimum
        applies after discounting, and the license flat is added last — because
        keying the discount on the post-discount amount, or applying the minimum
        before the discount, yields different cents; both are forbidden."

        Design: Difficulty/combinatorial_formula/academic_discount_evaluation_order
        """
        ctx, researcher, request = _order_ctx(
            purpose="ACADEMIC", appraised_value_cents=80000,
            item_format="PHOTOGRAPH")
        # image = round(5650 * 1.8 * 1.5) = 15255 (>= 5000 -> 20% off image
        # only): 12204; max(500, 12204); + 1500 license last.
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], format="SCAN_HIGHRES",
                             page_estimate=210,
                             license_class="NONPROFIT_PUBLICATION", rush=True)
        assert order["quoted_fee_cents"] == 13704, (
            f"expected 13704 (12204 + 1500); got {order['quoted_fee_cents']}")
        assert order["quoted_fee_cents"] != 13404, (
            "13404 would mean the license flat was discounted — forbidden")

    def test_personal_purpose_gets_no_discount(self):
        """PRD §3.7: "when the linked research request's `purpose` is
        `ACADEMIC` and the pre-discount image component is at least 5000 cents,
        the discount rate is 20 percent; otherwise it is zero."

        Design: Difficulty/combinatorial_formula/academic_discount_evaluation_order
        """
        ctx, researcher, request = _order_ctx(
            purpose="PERSONAL", appraised_value_cents=80000,
            item_format="PHOTOGRAPH")
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], format="SCAN_HIGHRES",
                             page_estimate=210,
                             license_class="NONPROFIT_PUBLICATION", rush=True)
        # No discount: 15255 + 1500.
        assert order["quoted_fee_cents"] == 16755, (
            f"PERSONAL purpose takes no discount; got "
            f"{order['quoted_fee_cents']}")


class TestDeedGates:

    def _two_deed_setup(self):
        """I1 under an accession whose deed restricts reproduction; I2 and I3
        under an accession whose deed requires a publication license. All three
        AVAILABLE; request APPROVED over [I1, I2] only."""
        zone = create_zone()
        collection = create_collection(zone["id"])
        a1, _d1 = create_accessioned(
            deed_fields={"reproduction_restricted": True},
            donor_contact="s@example.org")
        a2, _d2 = create_accessioned(
            deed_fields={"publication_license_required": True},
            donor_name="J. Doe", donor_contact="j@example.org",
            accession_date="2026-07-16", lot_appraised_value_cents=2000)
        create_published_finding_aid(collection["id"])
        i1 = create_item(a1["id"], collection["id"], title="I1")
        i2 = create_item(a2["id"], collection["id"], title="I2")
        i3 = create_item(a2["id"], collection["id"], title="I3")
        for it in (i1, i2, i3):
            catalog_item(it["id"])
            make_item_available(it["id"])
        researcher, request = setup_approved_request([i1["id"], i2["id"]])
        return researcher, request, i1, i2, i3

    def test_deed_restriction_and_license_gates(self):
        """PRD §3.7: "For each ordered item the system resolves the item's
        accession to its current `EXECUTED` deed through `current_deed_id` and
        applies three prohibitions: if that deed's `embargo_until` lies strictly
        after the current logical time, the order is rejected with
        `ERR_EMBARGO_ACTIVE`; if the deed's `reproduction_restricted` is true,
        with `ERR_DEED_REPRODUCTION_RESTRICTED`; and if the deed's
        `publication_license_required` is true while the order's `license_class`
        is `PERSONAL`, with `ERR_PUBLICATION_LICENSE_REQUIRED`. A `PERSONAL`
        order is the only class blocked by the license requirement; nonprofit
        and commercial publication classes satisfy it."
        PRD §3.7: "The `item_ids` array must be non-empty and every entry must
        be a member of the request's own `item_ids`; either failure is
        `ERR_ITEM_NOT_IN_REQUEST`."

        Design: Corner/validations/deed_restriction_and_license_gates
        """
        researcher, request, i1, i2, i3 = self._two_deed_setup()
        headers = make_researcher_headers(researcher["id"])

        resp1 = api_client.create_reproduction_order(
            {"research_request_id": request["id"], "item_ids": [i1["id"]],
             "format": "SCAN_STANDARD", "page_estimate": 10,
             "license_class": "PERSONAL", "rush": False}, headers)
        validate_error(resp1, ApiErrorId.ERR_DEED_REPRODUCTION_RESTRICTED)

        resp2 = api_client.create_reproduction_order(
            {"research_request_id": request["id"], "item_ids": [i2["id"]],
             "format": "SCAN_STANDARD", "page_estimate": 10,
             "license_class": "PERSONAL", "rush": False}, headers)
        validate_error(resp2, ApiErrorId.ERR_PUBLICATION_LICENSE_REQUIRED)

        # A publication-class license satisfies the requirement.
        ok = validate_success(api_client.create_reproduction_order(
            {"research_request_id": request["id"], "item_ids": [i2["id"]],
             "format": "SCAN_STANDARD", "page_estimate": 10,
             "license_class": "NONPROFIT_PUBLICATION", "rush": False}, headers),
            expected_status=201)
        # image 10*35 = 350 -> clamped to 500 minimum; + 1500 license.
        assert ok["quoted_fee_cents"] == 2000

        # I3 is not a member of the request's item set.
        resp3 = api_client.create_reproduction_order(
            {"research_request_id": request["id"], "item_ids": [i3["id"]],
             "format": "SCAN_STANDARD", "page_estimate": 10,
             "license_class": "NONPROFIT_PUBLICATION", "rush": False}, headers)
        validate_error(resp3, ApiErrorId.ERR_ITEM_NOT_IN_REQUEST)


class TestEmbargoGate:

    def test_embargoed_deed_blocks_order_until_expiry(self):
        """PRD §3.7: "if that deed's `embargo_until` lies strictly after the
        current logical time, the order is rejected with `ERR_EMBARGO_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/repro_order_blocked_by_deed_embargo
        """
        ctx = setup_available_item(
            deed_fields={"embargo_until": "2027-01-01T00:00:00Z"})
        researcher, request = setup_approved_request([ctx["item"]["id"]])

        # Logical clock at the 2026-08-01 default: embargo still in force.
        resp = api_client.create_reproduction_order(
            {"research_request_id": request["id"],
             "item_ids": [ctx["item"]["id"]], "format": "SCAN_STANDARD",
             "page_estimate": 60, "license_class": "PERSONAL", "rush": False},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_EMBARGO_ACTIVE)

    def test_embargo_boundary_equality_admits(self):
        """PRD §3.7: "if that deed's `embargo_until` lies strictly after the
        current logical time, the order is rejected with `ERR_EMBARGO_ACTIVE`"
        PRD §2.5: "The clock is driven exclusively through a `SystemAdmin`-only
        capability, `POST /_clock/set_current_utc`, whose request body carries a
        `to_iso8601` instant. The logical clock is set to that instant and may
        move forward or backward; this freedom is pinned behavior."

        Design: Difficulty/cross_entity_state_dependency/repro_order_blocked_by_deed_embargo
        """
        ctx = setup_available_item(
            deed_fields={"embargo_until": "2027-01-01T00:00:00Z"})
        researcher, request = setup_approved_request([ctx["item"]["id"]])

        # At exactly the embargo instant the gate opens (strictly-after only).
        set_clock("2027-01-01T00:00:00Z")
        order = validate_success(api_client.create_reproduction_order(
            {"research_request_id": request["id"],
             "item_ids": [ctx["item"]["id"]], "format": "SCAN_STANDARD",
             "page_estimate": 60, "license_class": "PERSONAL", "rush": False},
            make_researcher_headers(researcher["id"])), expected_status=201)
        assert order["status"] == "QUOTED"
        assert order["quoted_fee_cents"] == 2000


class TestRequoteGate:

    def test_requote_gate_boundary_and_rejection(self):
        """PRD §3.7: "The requote gate: the invoiced fee may not exceed the
        quoted fee increased by ten percent and rounded down to whole cents; a
        breach is rejected with `ERR_REQUOTE_REQUIRED` and the order stays
        `APPROVED`."
        PRD §3.7: "A successful invoice debits the allowance by
        `actual_pages`."

        Design: Corner/calculations/requote_gate_boundary_and_rejection
        """
        ctx, researcher, request = _order_ctx()
        item_id = ctx["item"]["id"]
        o1 = create_order(request["id"], researcher["id"], [item_id],
                          page_estimate=60)  # quoted 2000
        approve_order_quote(o1["id"], researcher["id"])
        o2 = create_order(request["id"], researcher["id"], [item_id],
                          page_estimate=60)
        approve_order_quote(o2["id"], researcher["id"])

        # Exactly at the cap: 68 pages -> 1750 + 18*25 = 2200 ==
        # floor(2000 * 1.10) -> admitted.
        invoiced1 = invoice_order(o1["id"], actual_pages=68)
        assert invoiced1["status"] == "INVOICED"
        assert invoiced1["invoiced_fee_cents"] == 2200

        # Beyond the cap: 210 pages -> 5650 > 2200 -> rejected, order unchanged.
        resp2 = api_client.invoice_order(o2["id"], {"actual_pages": 210}, RRS)
        validate_error(resp2, ApiErrorId.ERR_REQUOTE_REQUIRED)
        unchanged = validate_success(
            api_client.get_reproduction_order(o2["id"], RRS))
        assert unchanged["status"] == "APPROVED"
        assert unchanged["invoiced_fee_cents"] is None

        # O1's invoice debited the 500-page annual allowance by 68: 432 remain,
        # so a 433-page invoice on a third order fails the quota gate.
        o3 = create_order(request["id"], researcher["id"], [item_id],
                          page_estimate=433)
        approve_order_quote(o3["id"], researcher["id"])
        resp3 = api_client.invoice_order(o3["id"], {"actual_pages": 433}, RRS)
        validate_error(resp3, ApiErrorId.ERR_REPRO_QUOTA_EXCEEDED)


class TestInvoiceStatePriority:

    def test_invoice_quoted_order_state_error_precedes_quota(self):
        """PRD §2.8: "Checks are evaluated in the following sequence, and the
        first failing tier determines the response"
        PRD §2.8: "5. **Target state** — the target resource's own state machine
        permits the operation, else `ERR_INVALID_STATE`."
        PRD §2.8: "12. **Fiscal gates** — the annual page quota at invoice time
        (`ERR_REPRO_QUOTA_EXCEEDED`)"
        PRD §3.7: "Staff then invoice the order with the true `actual_pages` (a
        positive count), moving `APPROVED → INVOICED` and storing the recomputed
        fee as `invoiced_fee_cents`."

        Design: Difficulty/priority_pair_validation_conflict/invoice_state_error_beats_quota_fiscal
        """
        ctx, researcher, request = _order_ctx()
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)
        assert order["status"] == "QUOTED"

        # The order is QUOTED (state violation, tier 5) AND 600 pages would
        # breach the 500-page quota (fiscal violation, tier 12); the pinned
        # ordering surfaces the state error.
        resp = api_client.invoice_order(
            order["id"], {"actual_pages": 600}, RRS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_invoice_quoted_order_rejected_state_unchanged(self):
        """PRD §3.7: "Staff then invoice the order with the true `actual_pages`
        (a positive count), moving `APPROVED → INVOICED` and storing the
        recomputed fee as `invoiced_fee_cents`."
        PRD §2.8: "5. **Target state** — the target resource's own state machine
        permits the operation, else `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/invoice_state_error_beats_quota_fiscal
        """
        ctx, researcher, request = _order_ctx()
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)

        # Even with a quota-compliant page count, a QUOTED order cannot invoice.
        resp = api_client.invoice_order(order["id"], {"actual_pages": 60}, RRS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api_client.get_reproduction_order(order["id"], RRS))
        assert after["status"] == "QUOTED"
        assert after["invoiced_fee_cents"] is None


class TestQuota:

    def test_quota_exceeded_then_exact_boundary_invoice(self):
        """PRD §3.7: "The quota gate: each researcher has an annual allowance of
        500 reproduction pages per calendar year, measured in UTC, consumed by
        their orders in `INVOICED`, `PAID`, or `DELIVERED` status that were
        invoiced within the current calendar year — `REFUNDED` orders keep their
        debit and `QUOTED` or `APPROVED` orders consume nothing. If
        `actual_pages` strictly exceeds the remaining allowance the invoice is
        rejected with `ERR_REPRO_QUOTA_EXCEEDED`; landing exactly on the
        remaining allowance is permitted. A successful invoice debits the
        allowance by `actual_pages`."

        Design: Corner/errors/quota_exceeded_then_exact_boundary_invoice
        """
        ctx, researcher, request = _order_ctx()
        item_id = ctx["item"]["id"]
        order = create_order(request["id"], researcher["id"], [item_id],
                             page_estimate=600)
        assert order["quoted_fee_cents"] == 11500
        approve_order_quote(order["id"], researcher["id"])

        # 600 > 500 remaining: rejected; the order stays APPROVED.
        resp1 = api_client.invoice_order(
            order["id"], {"actual_pages": 600}, RRS)
        validate_error(resp1, ApiErrorId.ERR_REPRO_QUOTA_EXCEEDED)
        assert resp1.status_code == 402
        mid = validate_success(api_client.get_reproduction_order(order["id"], RRS))
        assert mid["status"] == "APPROVED"
        assert mid["invoiced_fee_cents"] is None

        # Exactly 500 pages == quota remaining: admitted. The invoiced fee is
        # tier(500) = 50*35 + 150*25 + 300*15 = 10000, within the requote
        # ceiling floor(11500 * 1.10) = 12650.
        invoiced = invoice_order(order["id"], actual_pages=500)
        assert invoiced["status"] == "INVOICED"
        assert invoiced["invoiced_fee_cents"] == 10000

        # The allowance is now exhausted: even one more page fails.
        order2 = create_order(request["id"], researcher["id"], [item_id],
                              page_estimate=1)
        approve_order_quote(order2["id"], researcher["id"])
        resp2 = api_client.invoice_order(order2["id"], {"actual_pages": 1}, RRS)
        validate_error(resp2, ApiErrorId.ERR_REPRO_QUOTA_EXCEEDED)


class TestPayment:

    def test_payment_amount_exact_match(self):
        """PRD §3.7: "Payment is exact-change only: the researcher pays with
        `amount_cents` equal to `invoiced_fee_cents` to the cent, else
        `ERR_PAYMENT_AMOUNT_MISMATCH`, moving `INVOICED → PAID` and adding the
        invoiced amount to the researcher's `total_charged_cents`."

        Design: Corner/errors/payment_amount_exact_match
        """
        ctx, researcher, request = _order_ctx()
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)
        approve_order_quote(order["id"], researcher["id"])
        invoice_order(order["id"], actual_pages=66)  # invoiced 2150

        resp = api_client.pay_order(
            order["id"], {"amount_cents": 2149},
            make_researcher_headers(researcher["id"]))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        assert resp.status_code == 402
        mid = validate_success(api_client.get_reproduction_order(order["id"], RRS))
        assert mid["status"] == "INVOICED"

        paid = pay_order(order["id"], researcher["id"], 2150)
        assert paid["status"] == "PAID"
        assert get_researcher(researcher["id"])["total_charged_cents"] == 2150


class TestPayRefundLedger:

    def test_pay_adds_invoiced_amount_to_ledger(self):
        """PRD §3.7: "Payment is exact-change only: the researcher pays with
        `amount_cents` equal to `invoiced_fee_cents` to the cent, else
        `ERR_PAYMENT_AMOUNT_MISMATCH`, moving `INVOICED → PAID` and adding the
        invoiced amount to the researcher's `total_charged_cents`."
        PRD §3.6: "The record begins `ACTIVE` with `no_show_strikes` at zero and
        `total_charged_cents` at zero — the latter being the running sum of
        `invoiced_fee_cents` across the researcher's paid and delivered
        reproduction orders, from which refunded orders contribute nothing (the
        refund flow of §3.7 unwinds the charge)."

        Design: Difficulty/compensating_invariant/pay_then_refund_restores_charge_ledger
        """
        ctx, researcher, request = _order_ctx()
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)
        approve_order_quote(order["id"], researcher["id"])
        invoice_order(order["id"], actual_pages=66)

        assert get_researcher(researcher["id"])["total_charged_cents"] == 0
        paid = pay_order(order["id"], researcher["id"], 2150)
        assert paid["status"] == "PAID"
        assert get_researcher(researcher["id"])["total_charged_cents"] == 2150

    def test_refund_subtracts_amount_restoring_ledger(self):
        """PRD §3.7: "Staff may instead refund a paid order (`PAID → REFUNDED`):
        the invoiced amount is subtracted back out of `total_charged_cents`,
        compensating the payment, but the annual page-quota debit is
        deliberately not released — this is pinned."

        Design: Difficulty/compensating_invariant/pay_then_refund_restores_charge_ledger
        """
        ctx, researcher, request = _order_ctx()
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)
        approve_order_quote(order["id"], researcher["id"])
        invoice_order(order["id"], actual_pages=66)
        pay_order(order["id"], researcher["id"], 2150)
        assert get_researcher(researcher["id"])["total_charged_cents"] == 2150

        refunded = validate_success(api_client.refund_order(order["id"], RRS))
        assert refunded["status"] == "REFUNDED"
        assert get_researcher(researcher["id"])["total_charged_cents"] == 0, (
            "pay + refund is a compensating pair: the ledger returns to zero")


class TestDeliveryCitation:

    def test_citation_checked_against_current_deed_at_delivery(self):
        """PRD §3.7: "Delivery then completes the order (`PAID → DELIVERED`)
        under a citation check evaluated against the deeds current at delivery
        time: the supplied `citation_acknowledgment_text` must be non-empty and,
        for every item on the order whose accession's current `EXECUTED` deed
        carries a non-null `required_citation_text`, must contain that exact
        text verbatim and case-sensitively, else `ERR_CITATION_MISMATCH`.
        Because the check reads the deed in force at delivery, an amended deed
        between payment and delivery changes what the acknowledgment must
        contain."

        Design: Corner/errors/citation_checked_against_current_deed_at_delivery
        """
        ctx = setup_available_item(
            deed_fields={"required_citation_text": "Citation A"})
        accession = ctx["accession"]
        researcher, request = setup_approved_request([ctx["item"]["id"]])
        order = create_order(request["id"], researcher["id"],
                             [ctx["item"]["id"]], page_estimate=60)
        approve_order_quote(order["id"], researcher["id"])
        invoice_order(order["id"], actual_pages=66)
        pay_order(order["id"], researcher["id"], 2150)

        # Amendment cycle supersedes deed A ("Citation A") with deed B.
        validate_success(api_client.amend_accession(accession["id"], REG))
        deed2 = validate_success(
            api_client.create_deed(accession["id"],
                                   {"required_citation_text": "Citation B"},
                                   REG),
            expected_status=201)
        current = get_accession(accession["id"])
        validate_success(api_client.execute_deed(
            deed2["id"], {"expected_accession_version": current["version"]},
            REG))

        # The superseded deed's text no longer satisfies the check.
        resp = api_client.deliver_order(
            order["id"], {"citation_acknowledgment_text": "I will cite: Citation A"},
            RRS)
        validate_error(resp, ApiErrorId.ERR_CITATION_MISMATCH)
        assert resp.status_code == 422
        mid = validate_success(api_client.get_reproduction_order(order["id"], RRS))
        assert mid["status"] == "PAID"

        # Text containing the current deed's required citation verbatim works.
        delivered = validate_success(api_client.deliver_order(
            order["id"],
            {"citation_acknowledgment_text": "I will cite: Citation B, box 3"},
            RRS))
        assert delivered["status"] == "DELIVERED"

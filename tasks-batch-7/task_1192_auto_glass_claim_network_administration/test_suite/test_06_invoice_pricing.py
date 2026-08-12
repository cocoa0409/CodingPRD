"""Invoice creation, agreement pricing, tax rounding, line-level fiscal gates."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_invoice, assert_invoice_conservation,
    create_invoice_payload, part_line, simple_line,
    make_shop_operator_headers,
    make_part,
    setup_work_order_completed,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestInvoiceCreationGates:
    def test_invoice_line_item_quantity_must_be_positive(self, api):
        """PRD §3.5: "Each line names its `line_type` (`PART`, `CALIBRATION`,
        `MOBILE_FEE`, or `MATERIALS`), a `quantity` of at least one, and the
        shop-billed `unit_price_cents`."
        PRD §2.8: "a missing required field, a wrong type, or an invalid enum
        value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invoice_line_item_quantity_must_be_positive
        """
        ctx = setup_work_order_completed()
        resp = api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([
                part_line(ctx["part"]["id"], 95000, quantity=0)]),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invoice_line_item_part_fk_not_found(self, api):
        """PRD §3.5: "For `PART` and `CALIBRATION` lines, the referenced catalog
        entry must exist (`ERR_PART_NOT_FOUND`)..."

        Design: Corner/entities/invoice_line_item_part_fk_not_found
        """
        from test_helpers import NON_EXISTENT_UUID
        ctx = setup_work_order_completed()
        resp = api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([
                part_line(NON_EXISTENT_UUID, 95000)]),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PART_NOT_FOUND)

    def test_discontinued_part_rejected_on_invoice(self, api):
        """PRD §3.5: "the referenced catalog entry ... must still be `AVAILABLE`
        — billing a `DISCONTINUED` part is rejected with `ERR_PART_DISCONTINUED`
        (HTTP 422)."

        Design: Corner/validations/discontinued_part_rejected_on_invoice
        """
        ctx = setup_work_order_completed()
        resp = api.update_part_catalog_entry(
            ctx["part"]["id"], {"status": "DISCONTINUED"}, ADMIN)
        validate_success(resp, 200)
        resp = api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([part_line(ctx["part"]["id"], 95000)]),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PART_DISCONTINUED)

    def test_mobile_fee_rejected_for_in_shop_work_order(self, api):
        """PRD §3.5: "A `MOBILE_FEE` line is permitted only when the work
        order's `service_mode` is `MOBILE` (else `ERR_MOBILE_FEE_NOT_ALLOWED`,
        HTTP 422)..."

        Design: Corner/validations/mobile_fee_rejected_for_in_shop_work_order
        """
        ctx = setup_work_order_completed(service_mode="IN_SHOP")
        resp = api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([
                part_line(ctx["part"]["id"], 95000),
                simple_line("MOBILE_FEE", 5000),
            ]),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_MOBILE_FEE_NOT_ALLOWED)

    def test_line_price_above_agreement_rejected(self, api):
        """PRD §3.5: "Whatever the line type, when the billed `unit_price_cents`
        exceeds the computed `agreement_unit_price_cents` the invoice is
        rejected with `ERR_LINE_PRICE_EXCEEDS_AGREEMENT` (HTTP 402)."

        Design: Corner/validations/line_price_above_agreement_rejected
        """
        # STANDARD shop, AFTERMARKET NAGS 100000 -> agreement 95000.
        ctx = setup_work_order_completed()
        over = api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([part_line(ctx["part"]["id"], 95001)]),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(over, ApiErrorId.ERR_LINE_PRICE_EXCEEDS_AGREEMENT)
        at_price = api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([part_line(ctx["part"]["id"], 95000)]),
            make_shop_operator_headers(ctx["shop"]["id"]))
        invoice = validate_success(at_price, 201)
        assert_invoice(invoice)
        assert invoice["status"] == "DRAFT"
        assert invoice["submitted_total_cents"] == 95000  # tax rate 0 bp

    def test_invoice_submit_empty_rejected(self, api):
        """PRD §3.5: "Submission requires the invoice to be in `DRAFT` or
        `DISPUTED` (else `ERR_INVOICE_NOT_SUBMITTABLE`), the acting shop to own
        the underlying work order, and at least one line item (an empty
        submission is rejected with `ERR_INVOICE_EMPTY`)."

        Design: Corner/state_machines/invoice_submit_empty_rejected
        """
        ctx = setup_work_order_completed()
        invoice = validate_success(api.create_invoice(
            ctx["work_order"]["id"], create_invoice_payload([]),
            make_shop_operator_headers(ctx["shop"]["id"])), 201)
        resp = api.submit_invoice(
            invoice["id"], {}, make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY)


# ---------------------------------------------------------------------------
# Difficulty: invoice line pricing — tier x origin x line-type combination
# ---------------------------------------------------------------------------

class TestInvoiceLinePricingCombination:
    def _setup_mobile_platinum(self):
        """KY zero-deductible/tax 600bp; PLATINUM mobile shop; MOBILE completed."""
        return setup_work_order_completed(
            state_code="KY", zero_deductible_windshield=True, tax_bp=600,
            service_mode="MOBILE",
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"incident_state_code": "KY",
                             "service_zip_code": "40201",
                             "estimated_repair_cost_cents": 300000},
            shop_overrides={"state_code": "KY", "service_zip_prefixes": ["402"],
                            "mobile_capable": True, "mobile_unit_count": 2,
                            "oem_certified": True, "agreement_tier": "PLATINUM"},
        )

    def _create_invoice(self, api, ctx, part_oem_id):
        return api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([
                part_line(ctx["part"]["id"], 75000),          # AM windshield
                part_line(part_oem_id, 120000, origin_claimed="OEM"),
                simple_line("MOBILE_FEE", 5000),
                simple_line("MATERIALS", 1125),
            ]),
            make_shop_operator_headers(ctx["shop"]["id"]))

    def test_agreement_prices_per_line_type_and_origin(self, api):
        """PRD §3.5: "The shop's `agreement_tier` determines the tier
        multiplier: 0.75 for `PLATINUM`, 0.85 for `PREFERRED`, and 0.95 for
        `STANDARD`. ... the line's `agreement_unit_price_cents` is the entry's
        `nags_list_price_cents` multiplied by the tier multiplier, except that
        an `OEM` entry takes a multiplier of exactly 1.00 (OEM glass receives
        no tier discount), rounded half-up to whole cents per line. A
        `MOBILE_FEE` line ... carries a flat `agreement_unit_price_cents` of
        5000 cents — no tier multiplier and no tax. A `MATERIALS` line carries
        an `agreement_unit_price_cents` of 1500 cents multiplied by the tier
        multiplier, rounded half-up."

        Design: Difficulty/combinatorial_formula/invoice_line_pricing_tier_origin_mode_a
        """
        ctx = self._setup_mobile_platinum()
        # default part is AM windshield NAGS 100000; add OEM windshield 120000.
        part_oem = make_part(part_number="OEM-WS-1", part_origin="OEM",
                             nags_list_price_cents=120000)
        invoice = validate_success(
            self._create_invoice(api, ctx, part_oem["id"]), 201)
        lines, _meta = validate_paginated(
            api.list_invoice_line_items(invoice["id"], ADMIN))
        by_type_origin = {}
        for ln in lines:
            key = (ln["line_type"], ln.get("origin_claimed"))
            by_type_origin[key] = ln
        # AFTERMARKET PART: round_half_up(100000 x 0.75) = 75000
        assert by_type_origin[("PART", "AFTERMARKET")]["agreement_unit_price_cents"] == 75000
        # OEM PART: multiplier 1.00 -> 120000 (no tier discount)
        assert by_type_origin[("PART", "OEM")]["agreement_unit_price_cents"] == 120000
        # MOBILE_FEE: flat 5000
        assert by_type_origin[("MOBILE_FEE", None)]["agreement_unit_price_cents"] == 5000
        # MATERIALS: round_half_up(1500 x 0.75) = 1125
        assert by_type_origin[("MATERIALS", None)]["agreement_unit_price_cents"] == 1125

    def test_invoice_totals_with_mixed_lines(self, api):
        """PRD §3.5: "The `tax_amount_cents` is that parts subtotal multiplied
        by the incident state's `glass_sales_tax_rate_bp` and divided by ten
        thousand, rounded half-up to whole cents — tax is computed once on the
        summed parts subtotal, and labor, calibration, and fee lines are
        untaxed. The `submitted_total_cents` is the sum of all line totals plus
        the tax."

        Design: Difficulty/combinatorial_formula/invoice_line_pricing_tier_origin_mode_a
        """
        ctx = self._setup_mobile_platinum()
        part_oem = make_part(part_number="OEM-WS-1", part_origin="OEM",
                             nags_list_price_cents=120000)
        invoice = validate_success(
            self._create_invoice(api, ctx, part_oem["id"]), 201)
        # parts subtotal 195000; tax = round_half_up(195000 x 600 / 10000) = 11700
        assert invoice["tax_amount_cents"] == 11700
        # 75000 + 120000 + 5000 + 1125 + 11700 = 212825
        assert invoice["submitted_total_cents"] == 212825
        assert_invoice_conservation(invoice)


# ---------------------------------------------------------------------------
# Difficulty: tax computed once on the summed parts subtotal (pinned order)
# ---------------------------------------------------------------------------

class TestInvoiceTaxPinnedOrder:
    def _setup(self):
        return setup_work_order_completed(
            state_code="CA", tax_bp=560,
            claim_overrides={"incident_state_code": "CA",
                             "service_zip_code": "90001",
                             "part_category": "SIDE_GLASS",
                             "estimated_repair_cost_cents": 80000},
            shop_overrides={"state_code": "CA", "service_zip_prefixes": ["900"]},
            part_overrides={"part_category": "SIDE_GLASS",
                            "nags_list_price_cents": 35140},
        )

    def test_tax_rounded_once_on_parts_subtotal(self, api):
        """PRD §2.6: "Invoice aggregation follows a pinned per-line-first order.
        Each line's total is derived from its unit price and quantity before any
        summation takes place, and the alternative order of summing first and
        rounding afterward is forbidden. The single rounding point inside
        invoice aggregation is the tax computation, which is applied once to the
        summed parts subtotal."

        Design: Difficulty/combinatorial_formula/invoice_tax_per_line_then_sum_mode_b
        """
        ctx = self._setup()
        invoice = validate_success(api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([
                part_line(ctx["part"]["id"], 33333),
                part_line(ctx["part"]["id"], 33333),
            ]),
            make_shop_operator_headers(ctx["shop"]["id"])), 201)
        # Tax once on summed subtotal: round_half_up(66666 x 560 / 10000) = 3733
        # (the forbidden per-line order would give 1867 + 1867 = 3734).
        assert invoice["tax_amount_cents"] == 3733
        assert invoice["submitted_total_cents"] == 70399

    def test_line_pricing_rounds_half_up_per_line(self, api):
        """PRD §2.6: "Agreement unit prices are rounded per line. The
        network-agreement unit price of each invoice line is rounded half-up to
        whole cents as it is computed, line by line, before any totals are
        assembled."

        Design: Difficulty/combinatorial_formula/invoice_tax_per_line_then_sum_mode_b
        """
        ctx = self._setup()
        invoice = validate_success(api.create_invoice(
            ctx["work_order"]["id"],
            create_invoice_payload([part_line(ctx["part"]["id"], 33333)]),
            make_shop_operator_headers(ctx["shop"]["id"])), 201)
        lines, _meta = validate_paginated(
            api.list_invoice_line_items(invoice["id"], ADMIN))
        assert len(lines) == 1
        # agreement = round_half_up(35140 x 0.95) = 33383; line total 33333 x 1.
        assert lines[0]["agreement_unit_price_cents"] == 33383
        assert lines[0]["line_total_cents"] == 33333

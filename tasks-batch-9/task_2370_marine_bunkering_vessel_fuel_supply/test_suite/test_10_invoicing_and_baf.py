"""Provisional invoicing: the bunker adjustment factor and the pinned rounding.

Two calculations meet on one invoice. The adjustment factor composes a base, a
three-step volatility ladder read off the grade's price history, a delivery-mode
premium, an emission-control premium and a tonnage tier discount, then clamps the
result. The amount then sums four components whose rounding order is pinned, so
the same inputs produce a different cent depending on whether the components or
the total are rounded.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CREDIT,
    api_client,
    assert_baf_pct_within_band,
    assert_final_is_provisional_less_credit,
    assert_invoice,
    assert_provisional_is_component_sum,
    build_delivered_order,
    build_provisional_invoice,
    create_invoice_payload,
    file_lab_analysis,
    issue_bdn,
    issue_invoice,
    raise_claim,
    raise_invoice,
    read_claim,
    read_customer,
    read_invoice,
    read_nomination,
    release_sample,
    submit_claim_decision,
    validate_error,
    validate_paginated,
)

TRUCK_ASSET = {"name": "Truck One", "asset_type": "TRUCK", "capacity_mt": 200.000}
TRUCK_STEM = {
    "vessel_imo": "9223344",
    "vessel_name": "MV Kore",
    "nominated_quantity_mt": 150.000,
    "delivery_mode": "TRUCK",
    "eca_documentation_ref": "CHG-2026-0002",
}
TRUCK_ORDER = {"planned_quantity_mt": 150.000}
TRUCK_FIGURES = {
    "barge_sounding_mt": 150.000,
    "vessel_sounding_mt": 149.600,
    "meter_mt": 149.900,
}


class TestBunkerAdjustmentFactor:
    """Five interacting inputs, a tier threshold and an outer clamp."""

    def test_factor_composes_all_five_inputs_on_the_middle_volatility_step(self):
        """PRD §3.9: "The prior quote is the quote for the same grade whose
        `quote_date` is the greatest value strictly earlier than the governing
        quote's `quote_date`, with ties again resolved in favour of the later
        `created_at`."
        PRD §3.9: "The volatility step contributes 0.000 while volatility is below
        0.05, contributes 0.010 once volatility reaches 0.05 but stays below 0.10,
        and contributes 0.020 once volatility reaches 0.10."
        PRD §3.9: "The mode premium contributes 0.015 when the nomination's
        `delivery_mode` is `TRUCK` and 0.005 when it is `BARGE`."
        PRD §3.9: "The emission-control premium contributes 0.010 when the delivery
        port lies inside an Emission Control Area and nothing otherwise."
        PRD §3.9: "`baf_usd` is the **already-rounded** `fuel_cost_usd` multiplied
        by `baf_pct`, rounded to two decimal places — the adjustment factor applies
        to the rounded fuel cost, not to the raw product."

        The grade moved from 705.00 to 745.50, a 5.7447 per cent step that lands on
        the middle rung of the ladder, and the basis of 1198.450 mt clears the
        tonnage tier, so the factor is 0.020 + 0.010 + 0.005 + 0.010 - 0.010.

        Design: Difficulty/combinatorial_formula/baf_pct_nonlinear_tier_composition
        """
        ctx = build_provisional_invoice()
        invoice = ctx["invoice"]

        assert_invoice(invoice)
        assert invoice["index_price_usd_per_mt"] == pytest.approx(745.50, abs=0.01), (
            "The 2026-08-10 quote governs the 2026-08-10T12:00:00Z pricing date, "
            f"got {invoice['index_price_usd_per_mt']}"
        )
        assert invoice["baf_pct"] == pytest.approx(0.0350, abs=0.00005), (
            "Base 0.020 plus middle volatility step 0.010 plus barge premium 0.005 "
            "plus emission-control premium 0.010 less the tier discount 0.010 must "
            f"give 0.0350, got {invoice['baf_pct']}"
        )
        assert invoice["baf_pct"] != pytest.approx(0.0450, abs=0.00005), (
            "0.0450 would mean the tier discount never fired and the raw factor was "
            "clamped at the ceiling"
        )
        assert invoice["baf_pct"] != pytest.approx(0.0250, abs=0.00005), (
            "0.0250 would mean the volatility step was read as 0.000 despite a "
            "5.7447 per cent move"
        )
        assert invoice["fuel_cost_usd"] == pytest.approx(893444.48, abs=0.01), (
            f"1198.450 mt at 745.50 rounds to 893444.48, got {invoice['fuel_cost_usd']}"
        )
        assert invoice["baf_usd"] == pytest.approx(31270.56, abs=0.01), (
            "The factor applies to the already-rounded fuel cost, giving 31270.56, "
            f"got {invoice['baf_usd']}"
        )
        assert invoice["eca_surcharge_usd"] == pytest.approx(5093.41, abs=0.01), (
            f"1198.450 mt at 4.25 per tonne rounds to 5093.41, got "
            f"{invoice['eca_surcharge_usd']}"
        )

    @pytest.mark.parametrize(
        "barge_sounding_mt, meter_mt, expected_basis, expected_baf_pct",
        [
            (1000.000, 1000.400, 1000.000, 0.0350),
            (999.000, 999.400, 999.000, 0.0450),
        ],
        ids=["at_the_tier_threshold", "one_tonne_below_the_threshold"],
    )
    def test_tier_discount_fires_only_from_one_thousand_tonnes(
        self, barge_sounding_mt, meter_mt, expected_basis, expected_baf_pct
    ):
        """PRD §3.9: "A tier discount of 0.010 is **subtracted** when the invoice's
        `quantity_basis_mt` is at least 1000.000 metric tonnes, and nothing is
        subtracted below that."
        PRD §3.9: "That raw figure is then clamped into the inclusive range from a
        floor of 0.010 to a ceiling of 0.045 — the clamp is applied first — and only
        then rounded to four decimal places to give `baf_pct`."

        Design: Difficulty/combinatorial_formula/baf_pct_nonlinear_tier_composition
        """
        ctx = build_provisional_invoice(
            figures={
                "barge_sounding_mt": barge_sounding_mt,
                "vessel_sounding_mt": 990.000,
                "meter_mt": meter_mt,
            }
        )
        invoice = ctx["invoice"]

        assert invoice["quantity_basis_mt"] == pytest.approx(expected_basis, abs=0.0005), (
            "The basis snapshots the agreed tonnage, expected "
            f"{expected_basis}, got {invoice['quantity_basis_mt']}"
        )
        assert invoice["baf_pct"] == pytest.approx(expected_baf_pct, abs=0.00005), (
            f"A basis of {expected_basis} mt must give a factor of {expected_baf_pct}, "
            f"got {invoice['baf_pct']}"
        )
        assert_baf_pct_within_band(invoice["baf_pct"])


class TestInvoiceComponentRounding:
    """Each component is rounded before the four are added."""

    def test_four_components_are_each_rounded_to_two_places(self):
        """PRD §3.9: "The invoice then has four components, and the rounding order
        among them is pinned: each component is rounded to two decimal places
        **first**, and the four already-rounded components are then added, without a
        further rounding of the sum."
        PRD §3.9: "`quantity_basis_mt` snapshots the order's `agreed_quantity_mt`."

        Design: Difficulty/combinatorial_formula/invoice_component_rounding_order_pinned
        """
        ctx = build_provisional_invoice()
        invoice = ctx["invoice"]

        assert invoice["quantity_basis_mt"] == pytest.approx(1198.450, abs=0.0005), (
            "The supplier's barge sounding is the settled basis, got "
            f"{invoice['quantity_basis_mt']}"
        )
        assert invoice["fuel_cost_usd"] == pytest.approx(893444.48, abs=0.01), (
            "1198.450 times 745.50 is 893444.475, which rounds half-up to "
            f"893444.48, got {invoice['fuel_cost_usd']}"
        )
        assert invoice["baf_usd"] == pytest.approx(31270.56, abs=0.01), (
            f"Expected 31270.56, got {invoice['baf_usd']}"
        )
        assert invoice["barging_fee_usd"] == pytest.approx(11385.28, abs=0.01), (
            "1198.450 times 9.50 is 11385.275, which rounds half-up to 11385.28, "
            f"got {invoice['barging_fee_usd']}"
        )
        assert invoice["eca_surcharge_usd"] == pytest.approx(5093.41, abs=0.01), (
            "1198.450 times 4.25 is 5093.4125, which rounds to 5093.41, got "
            f"{invoice['eca_surcharge_usd']}"
        )

    def test_provisional_total_is_the_sum_of_already_rounded_components(self):
        """PRD §2.10: "where a total is described as the sum of named components,
        **each component is rounded to two decimal places first and the
        already-rounded components are then added**"
        PRD §2.10: "Summing unrounded components and rounding once at the end is
        forbidden and produces a different cent."
        PRD §3.9: "`provisional_amount_usd` is the sum of those four rounded
        components."

        The unrounded components add to 941193.719125, which would round to
        941193.72; the rounded components add to 941193.73.

        Design: Difficulty/combinatorial_formula/invoice_component_rounding_order_pinned
        """
        ctx = build_provisional_invoice()
        invoice = ctx["invoice"]

        assert invoice["provisional_amount_usd"] == pytest.approx(941193.73, abs=0.001), (
            "Adding the four rounded components must give 941193.73, got "
            f"{invoice['provisional_amount_usd']}"
        )
        assert invoice["provisional_amount_usd"] != pytest.approx(941193.72, abs=0.001), (
            "941193.72 is the forbidden sum-then-round result, so the components "
            "were not rounded first"
        )
        assert_provisional_is_component_sum(invoice)

    def test_barging_fee_takes_the_greater_of_rate_product_and_floor(self):
        """PRD §3.9: "`barging_fee_usd` is the greater of two values: the quantity
        basis multiplied by the grade's `base_barging_rate_usd_per_mt` and rounded
        to two decimal places, or the grade's `min_barging_fee_usd` floor."

        At 1198.450 mt the rate product of 11385.28 beats the 2000.00 floor, so the
        floor must not be substituted for it.

        Design: Difficulty/combinatorial_formula/invoice_component_rounding_order_pinned
        """
        ctx = build_provisional_invoice()
        invoice = ctx["invoice"]

        assert invoice["barging_fee_usd"] == pytest.approx(11385.28, abs=0.01), (
            "The rate product governs whenever it exceeds the floor, got "
            f"{invoice['barging_fee_usd']}"
        )
        assert invoice["barging_fee_usd"] > ctx["grade"]["min_barging_fee_usd"], (
            "The rate product must beat the 2000.00 minimum fee at this tonnage"
        )

    def test_final_amount_opens_equal_to_the_provisional_total(self):
        """PRD §3.9: "The invoice copies `customer_id` from the nomination behind
        the order and opens in status `PROVISIONAL` with `issued_at` and `due_date`
        null and `claim_credit_usd` at 0.00."
        PRD §3.9: "`final_amount_usd` is `provisional_amount_usd` minus
        `claim_credit_usd`, rounded to two decimal places."

        Design: Difficulty/combinatorial_formula/invoice_component_rounding_order_pinned
        """
        ctx = build_provisional_invoice()
        invoice = ctx["invoice"]

        assert invoice["status"] == "PROVISIONAL", (
            f"A freshly raised invoice opens PROVISIONAL, got {invoice['status']}"
        )
        assert invoice["claim_credit_usd"] == pytest.approx(0.00, abs=0.01), (
            f"No remediation has been booked, got {invoice['claim_credit_usd']}"
        )
        assert invoice["final_amount_usd"] == pytest.approx(941193.73, abs=0.001), (
            "With no credit booked the final amount equals the provisional total, "
            f"got {invoice['final_amount_usd']}"
        )
        assert_final_is_provisional_less_credit(invoice)
        assert invoice["issued_at"] is None, (
            f"issued_at stays null until issuance, got {invoice['issued_at']}"
        )
        assert invoice["due_date"] is None, (
            f"due_date stays null until issuance, got {invoice['due_date']}"
        )


class TestBothClampsFireOnOneSmallTruckStem:
    """A tiny road delivery pushes the factor over its ceiling and the fee under
    its floor at the same time."""

    def test_the_factor_is_clamped_down_while_the_barging_fee_is_lifted(self):
        """PRD §3.9: "That raw figure is then clamped into the inclusive range from a
        floor of 0.010 to a ceiling of 0.045 — the clamp is applied first — and only then
        rounded to four decimal places to give `baf_pct`."
        PRD §3.9: "The mode premium contributes 0.015 when the nomination's
        `delivery_mode` is `TRUCK` and 0.005 when it is `BARGE`."
        PRD §3.9: "A tier discount of 0.010 is **subtracted** when the invoice's
        `quantity_basis_mt` is at least 1000.000 metric tonnes, and nothing is subtracted
        below that."
        PRD §3.9: "`barging_fee_usd` is the greater of two values: the quantity basis
        multiplied by the grade's `base_barging_rate_usd_per_mt` and rounded to two
        decimal places, or the grade's `min_barging_fee_usd` floor."
        PRD §3.9: "`eca_surcharge_usd` is the quantity basis multiplied by an
        emission-control surcharge of 4.25 dollars per metric tonne, rounded to two
        decimal places, when the delivery port lies inside an Emission Control Area; at
        any other port it is 0.00."

        150.000 mt by road into an emission-control port raises 0.020 + 0.010 + 0.015 +
        0.010 = 0.055 with no tier discount to take off, so the ceiling cuts it to
        0.0450; and the 1425.00 rate-based fee falls below the grade's 2000.00 floor, so
        the floor is substituted.

        Design: Corner/calculations/invoice_min_barging_fee_floor_and_baf_ceiling_clamp
        """
        ctx = build_delivered_order(
            asset=TRUCK_ASSET,
            nomination=TRUCK_STEM,
            order=TRUCK_ORDER,
            figures=TRUCK_FIGURES,
        )

        invoice = raise_invoice(ctx)

        assert_invoice(invoice)
        assert invoice["quantity_basis_mt"] == pytest.approx(150.000, abs=0.0005), (
            f"The basis snapshots the agreed tonnage, got {invoice['quantity_basis_mt']}"
        )
        assert invoice["index_price_usd_per_mt"] == pytest.approx(745.50, abs=0.01), (
            "The 2026-08-10 quote governs the 2026-08-10T12:00:00Z pricing date, got "
            f"{invoice['index_price_usd_per_mt']}"
        )
        assert invoice["baf_pct"] == pytest.approx(0.0450, abs=0.00005), (
            "A raw factor of 0.055 must be cut to the 0.045 ceiling, got "
            f"{invoice['baf_pct']}"
        )
        assert_baf_pct_within_band(invoice["baf_pct"])
        assert invoice["fuel_cost_usd"] == pytest.approx(111825.00, abs=0.01), (
            f"150.000 mt at 745.50 is 111825.00, got {invoice['fuel_cost_usd']}"
        )
        assert invoice["baf_usd"] == pytest.approx(5032.13, abs=0.01), (
            "111825.00 times 0.0450 is 5032.125, which rounds half-up to 5032.13, got "
            f"{invoice['baf_usd']}"
        )
        assert invoice["barging_fee_usd"] == pytest.approx(2000.00, abs=0.01), (
            "The 1425.00 rate product is below the grade's floor, so the floor "
            f"governs, got {invoice['barging_fee_usd']}"
        )
        assert invoice["eca_surcharge_usd"] == pytest.approx(637.50, abs=0.01), (
            f"150.000 mt at 4.25 per tonne is 637.50, got {invoice['eca_surcharge_usd']}"
        )
        assert invoice["provisional_amount_usd"] == pytest.approx(119494.63, abs=0.001), (
            "The four rounded components add to 119494.63, got "
            f"{invoice['provisional_amount_usd']}"
        )
        assert_provisional_is_component_sum(invoice)
        assert invoice["final_amount_usd"] == pytest.approx(119494.63, abs=0.001), (
            "With no credit booked the final amount equals the provisional total, got "
            f"{invoice['final_amount_usd']}"
        )
        assert invoice["status"] == "PROVISIONAL", (
            f"A freshly raised invoice opens PROVISIONAL, got {invoice['status']}"
        )
        assert invoice["due_date"] is None, (
            f"due_date stays null until issuance, got {invoice['due_date']}"
        )


class TestInvoiceLifecyclePreconditions:
    """Three refusals with three distinct ids on one invoice."""

    def test_a_second_invoice_on_the_same_order_is_refused(self):
        """PRD §3.9: "and no invoice in status `PROVISIONAL`, `ISSUED` or
        `CREDIT_APPLIED` may already exist for the order, or the request is rejected with
        `ERR_INVOICE_ALREADY_EXISTS` (HTTP 409)."
        PRD §3.9: "Invoices may be listed and filtered by `delivery_order_id`, by
        `customer_id` or by `status`."

        The first invoice is still `PROVISIONAL`, which is already enough to block a
        second one, and the refusal must leave exactly one invoice on the order.

        Design: Corner/validations/invoice_lifecycle_precondition_errors_rejected
        """
        ctx = build_delivered_order()
        first = raise_invoice(ctx)
        assert first["status"] == "PROVISIONAL", (
            f"The first invoice opens PROVISIONAL, got {first['status']}"
        )
        assert first["quantity_basis_mt"] == pytest.approx(1198.450, abs=0.0005), (
            f"The basis snapshots the agreed tonnage, got {first['quantity_basis_mt']}"
        )

        response = api_client.create_invoice(
            create_invoice_payload(ctx["order"]["id"]), CREDIT
        )

        validate_error(response, ApiErrorId.ERR_INVOICE_ALREADY_EXISTS)
        invoices, meta = validate_paginated(
            api_client.list_invoices(
                CREDIT, params={"delivery_order_id": ctx["order"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"The refused second invoice must not have been created, got "
            f"{meta['total_count']} invoices on the order"
        )
        assert invoices[0]["id"] == first["id"], (
            "The surviving invoice must be the first one, got "
            f"{invoices[0]['id']} rather than {first['id']}"
        )

    def test_issuance_needs_a_note_first_and_cannot_be_repeated(self):
        """PRD §3.9: "Issuing an invoice moves it `PROVISIONAL → ISSUED` and requires
        three conditions beyond the state check: the order's `logistics_status` must be
        `DELIVERED`, else `ERR_INVALID_ORDER_STATE`; the order's `measurement_status`
        must be `AGREED`, else `ERR_MEASUREMENT_NOT_AGREED`; and a bunker delivery note
        in status `ISSUED` must exist for the order, else `ERR_BDN_NOT_ISSUED` (HTTP
        409)."
        PRD §3.9: "Issuance stamps `issued_at` with the logical clock and derives
        `due_date` as `issued_at` plus the customer's `payment_terms_days` days."
        PRD §3.9: "An attempt to issue or void from a status that permits neither is
        rejected with `ERR_INVALID_INVOICE_STATE` (HTTP 409)."

        The invoice may be raised before the MARPOL note exists but may not be issued
        before it; once the note is there the same request succeeds, and a third
        attempt is refused on the invoice's own status.

        Design: Corner/validations/invoice_lifecycle_precondition_errors_rejected
        """
        ctx = build_delivered_order()
        invoice = raise_invoice(ctx)

        premature = api_client.issue_invoice(invoice["id"], CREDIT)

        validate_error(premature, ApiErrorId.ERR_BDN_NOT_ISSUED)
        still_provisional = read_invoice(ctx)
        assert still_provisional["status"] == "PROVISIONAL", (
            "The refused issuance must leave the status alone, got "
            f"{still_provisional['status']}"
        )
        assert still_provisional["issued_at"] is None, (
            f"issued_at must stay null, got {still_provisional['issued_at']}"
        )
        issue_bdn(ctx)

        issued = issue_invoice(ctx)

        assert issued["status"] == "ISSUED", (
            f"With the note in place the issuance must succeed, got {issued['status']}"
        )
        assert issued["issued_at"].startswith("2026-08-10T14:30:00"), (
            f"issued_at takes the logical clock, got {issued['issued_at']}"
        )
        assert issued["due_date"].startswith("2026-09-09T14:30:00"), (
            "30 payment-terms days after 2026-08-10T14:30:00Z is 2026-09-09T14:30:00Z, "
            f"got {issued['due_date']}"
        )
        repeat = api_client.issue_invoice(invoice["id"], CREDIT)
        validate_error(repeat, ApiErrorId.ERR_INVALID_INVOICE_STATE)
        assert read_nomination(ctx)["fulfillment_status"] == "CLOSED", (
            "The successful issuance must have closed the stem, got "
            f"{read_nomination(ctx)['fulfillment_status']}"
        )


class TestRemediationBookingNeedsAnIssuedInvoice:
    """A computed credit may be proposed against a provisional invoice but not booked."""

    def test_accepting_a_remediation_on_a_provisional_invoice_is_refused(self):
        """PRD §3.8: "Acceptance requires the invoice on the claim's delivery order to
        be in status `ISSUED`, or it is rejected with `ERR_INVOICE_NOT_ISSUED`."
        PRD §3.8: "Both decisions require a non-void invoice to exist on the claim's
        delivery order, or the decision is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP
        409)."
        PRD §3.8: "Acceptance books `credit_usd` and cascades three levels deep: the
        invoice's `claim_credit_usd` is increased by the claim's `credit_usd`, its
        `final_amount_usd` is recomputed, and its `status` moves `ISSUED →
        CREDIT_APPLIED`; that invoice mutation itself cascades a recompute of the
        customer's `outstanding_balance_usd`; and that recompute in turn cascades a
        re-derivation of the customer's `credit_status`."
        PRD §3.2: "invoices that are still `PROVISIONAL` and invoices that have been
        made `VOID` are excluded entirely."

        The proposal is admissible because the provisional invoice is non-void, and the
        credit is computed from it; booking that credit still has to wait for issuance,
        so none of the three cascade levels may move.

        Design: Corner/validations/accept_remediation_on_provisional_invoice_rejected
        """
        ctx = build_delivered_order()
        issue_bdn(ctx)
        raise_invoice(ctx)
        release_sample(ctx)
        raise_claim(ctx)
        file_lab_analysis(ctx)
        proposed = submit_claim_decision(ctx, "PROPOSE",
                                        remediation_type="PRICE_ALLOWANCE")
        assert proposed["status"] == "REMEDIATION_PROPOSED", (
            f"The proposal must have been accepted, got {proposed['status']}"
        )
        assert proposed["credit_usd"] > 0.00, (
            "The proposal computes the credit even against a provisional invoice, got "
            f"{proposed['credit_usd']}"
        )

        response = api_client.accept_remediation(ctx["claim"]["id"], CREDIT)

        validate_error(response, ApiErrorId.ERR_INVOICE_NOT_ISSUED)
        claim = read_claim(ctx)
        assert claim["status"] == "REMEDIATION_PROPOSED", (
            f"The refused booking must leave the claim proposed, got {claim['status']}"
        )
        assert claim["accepted_by_user_id"] is None, (
            f"No acceptor may be recorded, got {claim['accepted_by_user_id']}"
        )
        assert claim["version"] == proposed["version"], (
            f"A refused booking must not move the version, expected "
            f"{proposed['version']}, got {claim['version']}"
        )
        invoice = read_invoice(ctx)
        assert invoice["status"] == "PROVISIONAL", (
            f"The invoice must stay provisional, got {invoice['status']}"
        )
        assert invoice["claim_credit_usd"] == pytest.approx(0.00, abs=0.01), (
            f"No credit may be booked, got {invoice['claim_credit_usd']}"
        )
        assert invoice["final_amount_usd"] == pytest.approx(
            invoice["provisional_amount_usd"], abs=0.001
        ), (
            "With no credit booked the final amount equals the provisional total, got "
            f"{invoice['final_amount_usd']} against "
            f"{invoice['provisional_amount_usd']}"
        )
        assert read_customer(ctx)["outstanding_balance_usd"] == pytest.approx(
            0.00, abs=0.01
        ), (
            "A provisional invoice is outside the receivable, got "
            f"{read_customer(ctx)['outstanding_balance_usd']}"
        )

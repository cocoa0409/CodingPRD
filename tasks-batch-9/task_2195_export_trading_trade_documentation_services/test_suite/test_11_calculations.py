"""Scores, premiums, waterfalls and the eight cost buckets at their exact figures."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    FINANCE_FRANK,
    OPS_ALICE,
    REVIEWER_BOB,
    ApiErrorId,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

Json = Dict[str, Any]

TWO_MAJOR_EXPIRY_FINDINGS = (
    {
        "code": "EXPIRY_UNWORKABLE",
        "severity": "MAJOR",
        "clause_ref": "EXPIRY",
        "detail": "Expiry date leaves no presentation margin",
    },
    {
        "code": "LATE_PRESENTATION",
        "severity": "MAJOR",
        "clause_ref": "EXPIRY",
        "detail": "Place of expiry is not stated",
    },
)


def _review_with_findings(api, findings) -> Json:
    """A credit under review carrying the given terms findings."""
    ctx = fx.order_with_lines(api)
    ctx = fx.captured_credit(api, ctx, lc_number="LC-2026-0001")
    ctx = fx.opened_terms_review(api, ctx)
    for finding in findings:
        fx.data(
            api.raise_terms_finding(
                ctx["review_id"], f.terms_finding_payload(**finding), REVIEWER_BOB
            )
        )
    return ctx


class TestTermsScoreBoundaries:
    def test_a_score_of_exactly_forty_five_refuses_accept_but_admits_amend(self, api):
        """PRD §3.4: "A `recommendation` incompatible with the computed score — an
        `ACCEPT` at a score of 45.00 or above, or an `ACCEPT` or `AMEND` at a score
        of 60.00 or above, where only `REJECT` is permitted — is refused with a
        409."

        Design: Corner/calculations/corner_terms_risk_score_exactly_at_accept_ceiling_blocks_accept
        """
        ctx = _review_with_findings(api, TWO_MAJOR_EXPIRY_FINDINGS)

        validate_error(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
            ),
            ApiErrorId.ERR_RECOMMENDATION_NOT_PERMITTED.value,
        )
        assert fx.data(api.get_terms_review(ctx["review_id"], REVIEWER_BOB))[
            "status"
        ] == "DRAFTING"

        review = validate_success(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "AMEND"}, REVIEWER_BOB
            ),
            200,
        )
        assert review["status"] == "SUBMITTED"
        assert review["recommendation"] == "AMEND"
        assert review["terms_risk_score"] == approx_money(45.00)
        assert review["finding_count"] == 2

        assert fx.read_credit(api, ctx["lc_id"])["status"] == "AMENDMENT_REQUESTED"
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="UNSECURED"
        )

    def test_a_score_of_exactly_sixty_leaves_only_reject_open(self, api):
        """PRD §3.4: "**`REJECT`** requires either at least one finding with
        `severity` `CRITICAL` and `cure_status` `OPEN`, or a score **at or above
        60.00**."

        Design: Corner/calculations/corner_terms_risk_score_at_reject_floor_permits_only_reject
        """
        ctx = _review_with_findings(
            api,
            [
                {
                    "code": "AMOUNT_MISMATCH",
                    "severity": "CRITICAL",
                    "clause_ref": "AMOUNT",
                    "detail": "Credit amount is below the order value",
                }
            ],
        )

        validate_error(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "AMEND"}, REVIEWER_BOB
            ),
            ApiErrorId.ERR_RECOMMENDATION_NOT_PERMITTED.value,
        )

        review = validate_success(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "REJECT"}, REVIEWER_BOB
            ),
            200,
        )
        assert review["terms_risk_score"] == approx_money(60.00)
        assert review["recommendation"] == "REJECT"

        assert fx.read_credit(api, ctx["lc_id"])["status"] == "REJECTED"

        findings = fx.findings_for_review(api, ctx["review_id"])
        assert len(findings) == 1
        assert findings[0]["source"] == "TERMS"
        assert findings[0]["cure_status"] == "OPEN"


class TestPremiumTiersAndFeeBranches:
    def test_a_limit_exactly_on_the_tier_one_ceiling_waives_the_fee(self, api):
        """PRD §3.8: "Compute the base premium as `credit_limit_usd` multiplied by
        `insured_pct` divided by 100, multiplied by the tier rate divided by 100,
        multiplied by the rating multiplier — rounded to two decimal places
        **once**, at the end of that product."

        Design: Corner/calculations/corner_premium_tier_1_upper_bound_inclusive_with_fee_waived
        """
        buyer = fx.create_buyer(api)
        policy = validate_success(
            api.create_policy(
                f.policy_payload(
                    buyer["id"],
                    policy_number="POL-2026-0001",
                    credit_limit_usd=250000.00,
                    insured_pct=90.00,
                    deductible_usd=5000.00,
                ),
                FINANCE_FRANK,
            ),
            201,
        )

        assert policy["exposure_tier"] == "TIER_1"
        assert policy["premium_usd"] == approx_money(1912.50)
        assert policy["status"] == "ACTIVE"
        assert policy["utilized_usd"] == approx_money(0.00)
        assert policy["available_limit_usd"] == approx_money(250000.00)
        assert policy["indemnified_total_usd"] == approx_money(0.00)

        assert fx.data(api.get_buyer(buyer["id"], COMPLIANCE_CARL))[
            "aggregate_exposure_usd"
        ] == approx_money(0.00)

    def test_a_tier_two_basis_adds_the_percentage_fee_above_its_floor(self, api):
        """PRD §3.8: "Otherwise it is the greater of 250.00 USD and 0.10 percent of
        `credit_limit_usd` rounded to two decimal places."

        Design: Corner/calculations/corner_premium_tier_2_adds_percentage_fee_above_floor
        """
        buyer = fx.create_buyer(api)
        policy = validate_success(
            api.create_policy(
                f.policy_payload(
                    buyer["id"],
                    policy_number="POL-2026-0002",
                    credit_limit_usd=300000.00,
                    insured_pct=90.00,
                    deductible_usd=7500.00,
                ),
                FINANCE_FRANK,
            ),
            201,
        )

        assert policy["exposure_tier"] == "TIER_2"
        assert policy["premium_usd"] == approx_money(3405.00)
        assert policy["available_limit_usd"] == approx_money(300000.00)
        assert policy["status"] == "ACTIVE"


class TestSettlementWaterfallOnTheUninsuredBranch:
    def test_the_whole_settlement_falls_through_to_the_seller_credit_note(self, api):
        """PRD §3.9: "On the **uninsured** branch, bucket 2 is exactly 0.00 and
        bucket 3 takes the whole remainder after bucket 1."

        Design: Corner/calculations/corner_settlement_waterfall_uninsured_pushes_remainder_to_credit_note
        """
        ctx = fx.order_with_lines(api)
        dispute = fx.data(
            api.open_dispute(
                f.dispute_payload(ctx["order_id"], claimed_amount_usd=5000.00),
                ctx["buyer_headers"],
            )
        )
        fx.data(
            api.make_offer(dispute["id"], {"offer_amount_usd": 5000.00}, FINANCE_FRANK)
        )

        settled = validate_success(
            api.accept_dispute(dispute["id"], ctx["buyer_headers"]), 200
        )
        assert settled["status"] == "SETTLED"
        assert settled["settlement_amount_usd"] == approx_money(5000.00)
        assert settled["receivable_offset_usd"] == approx_money(0.00)
        assert settled["insurance_indemnity_usd"] == approx_money(0.00)
        assert settled["seller_credit_note_usd"] == approx_money(5000.00)
        assert (
            settled["receivable_offset_usd"]
            + settled["insurance_indemnity_usd"]
            + settled["seller_credit_note_usd"]
        ) == approx_money(5000.00)
        assert settled["credit_insurance_policy_id"] is None

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="UNSECURED")
        assert order["outstanding_receivable_usd"] == approx_money(0.00)


# ---------------------------------------------------------------------------
# The invoice totalling chain over three equal lines
# ---------------------------------------------------------------------------

THREE_EQUAL_LINES = [
    {
        "line_no": 1,
        "goods_description": "Valve body",
        "quantity": 10.000,
        "unit_price_usd": 100.0000,
        "net_weight_kg": 350.000,
        "gross_weight_kg": 400.000,
        "package_count": 20,
    },
    {
        "line_no": 2,
        "goods_description": "Valve bonnet",
        "quantity": 10.000,
        "unit_price_usd": 100.0000,
        "net_weight_kg": 350.000,
        "gross_weight_kg": 400.000,
        "package_count": 20,
    },
    {
        "line_no": 3,
        "goods_description": "Valve stem",
        "quantity": 10.000,
        "unit_price_usd": 100.0000,
        "net_weight_kg": 350.000,
        "gross_weight_kg": 400.000,
        "package_count": 20,
    },
]

CIF_EUR_ORDER = {
    "incoterm": "CIF",
    "incoterm_named_place": "CIF Busan",
    "invoice_currency": "EUR",
    "fx_rate_usd_to_invoice": 0.912500,
}


class TestInvoiceApportionmentAndSingleFxConversion:
    def test_the_indivisible_freight_pool_puts_its_residual_on_line_one(self, api):
        """PRD §3.5: "`declared_total_invoice_currency` is `declared_total_usd`
        multiplied by the order's `fx_rate_usd_to_invoice`, rounded to two decimal
        places."

        Design: Corner/calculations/corner_invoice_freight_apportionment_residual_lands_on_tie_break_line
        """
        ctx = fx.cleared_order(
            api, order_overrides=CIF_EUR_ORDER, lines=THREE_EQUAL_LINES
        )
        ctx = fx.booked_order(
            api,
            base=ctx,
            sailing_overrides={
                "capacity_weight_kg": 100000.000,
                "tariff_rate_per_1000kg_usd": 305.00,
            },
        )

        invoice = validate_success(
            api.generate_document(f.document_payload(ctx["order_id"]), OPS_ALICE), 201
        )
        assert invoice["declared_total_usd"] == approx_money(3776.50)
        assert invoice["declared_total_invoice_currency"] == approx_money(3446.06)
        assert invoice["total_gross_weight_kg"] == approx_weight(1200.000)
        assert invoice["total_package_count"] == 60

        lines = [
            fx.data(api.get_shipment_line(line_id, OPS_ALICE))
            for line_id in ctx["line_ids"]
        ]
        assert lines[0]["apportioned_freight_usd"] == approx_money(233.84)
        assert lines[1]["apportioned_freight_usd"] == approx_money(233.83)
        assert lines[2]["apportioned_freight_usd"] == approx_money(233.83)
        assert sum(line["apportioned_freight_usd"] for line in lines) == approx_money(
            701.50
        )
        for line in lines:
            assert line["line_extended_usd"] == approx_money(1000.00)
            assert line["line_net_usd"] == approx_money(1000.00)


class TestContainerMinimumLiftsTheFreightUnits:
    def test_a_dry_forty_minimum_charges_freight_on_fifteen_tonnes(self, api):
        """PRD §3.6: "The chargeable weight is the greater of the weight basis and
        the container minimum. The freight-unit count is that chargeable weight in
        kilograms divided by 1000, rounded **up** to the next whole number."

        Design: Corner/calculations/corner_container_minimum_weight_lifts_freight_units_step_function
        """
        ctx = fx.cleared_order(api)
        sailing = fx.create_sailing(api)

        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    ctx["order_id"],
                    sailing["id"],
                    sailing["version"],
                    container_type="DRY_40",
                ),
                OPS_ALICE,
            ),
            201,
        )
        assert booking["chargeable_weight_kg"] == approx_weight(15000.000)

        order = fx.read_order(api, ctx["order_id"])
        assert order["provisional_seller_cost_usd"] == approx_money(1130.00)
        assert order["provisional_buyer_cost_usd"] == approx_money(8016.25)
        assert (
            order["provisional_seller_cost_usd"] + order["provisional_buyer_cost_usd"]
        ) == approx_money(9146.25)

        assert fx.read_sailing(api, sailing["id"])[
            "booked_weight_kg"
        ] == approx_weight(1200.000)


class TestIncotermAndZoneMoveDifferentBuckets:
    def test_cif_into_zone_three_hands_freight_and_marine_cover_to_the_seller(
        self, api
    ):
        """PRD §3.6: "**Main carriage**: the greater of 450.00 USD and the sailing's
        `tariff_rate_per_1000kg_usd` multiplied by the zone multiplier multiplied by
        the freight-unit count, rounded to two decimal places."

        Design: Corner/calculations/corner_cif_zone_3_seller_bucket_set_absorbs_freight_and_marine_premium
        """
        ctx = fx.cleared_order(
            api,
            buyer_overrides={
                "legal_name": "Emirates Valve Trading LLC",
                "country_code": "AE",
            },
            order_overrides={
                "incoterm": "CIF",
                "incoterm_named_place": "CIF Jebel Ali",
                "destination_country_code": "AE",
                "destination_zone": "ZONE_3",
            },
        )
        sailing = fx.create_sailing(
            api,
            carrier_scac="MAEU",
            vessel_name="MV Gulf Runner",
            port_of_discharge="AEJEA",
            destination_zone="ZONE_3",
            capacity_weight_kg=100000.000,
        )

        booking = validate_success(
            api.create_booking(
                f.booking_payload(ctx["order_id"], sailing["id"], sailing["version"]),
                OPS_ALICE,
            ),
            201,
        )
        assert booking["chargeable_weight_kg"] == approx_weight(1200.000)

        order = fx.read_order(api, ctx["order_id"])
        assert order["provisional_seller_cost_usd"] == approx_money(1490.25)
        assert order["provisional_buyer_cost_usd"] == approx_money(2030.00)
        assert order["final_seller_cost_usd"] == approx_money(0.00)
        assert order["final_buyer_cost_usd"] == approx_money(0.00)
        assert order["cost_allocation_variance_usd"] == approx_money(0.00)


# ---------------------------------------------------------------------------
# The exposure ledger identity across a charge and its release
# ---------------------------------------------------------------------------


class TestExposureLedgerIdentity:
    def test_a_charge_that_lands_exactly_on_zero_headroom_exhausts_then_reactivates(
        self, api
    ):
        """PRD §3.8: "the policy becomes `EXHAUSTED` when `available_limit_usd` is
        **exactly** 0.00 and stays `ACTIVE` otherwise."

        Design: Corner/calculations/corner_insured_exposure_charge_then_release_conserves_limit_identity
        """
        ctx = fx.order_with_lines(api)
        policy = fx.create_policy(
            api,
            ctx["buyer_id"],
            policy_number="POL-2026-0003",
            credit_limit_usd=25000.00,
        )
        ctx = fx.accepted_credit(api, ctx, lc_number="LC-2026-0003")

        charged = fx.read_policy(api, policy["id"])
        assert charged["utilized_usd"] == approx_money(25000.00)
        assert charged["available_limit_usd"] == approx_money(0.00)
        assert charged["status"] == "EXHAUSTED"
        assert (
            charged["utilized_usd"] + charged["available_limit_usd"]
        ) == approx_money(25000.00)

        credit = validate_success(
            api.amend_credit(
                ctx["lc_id"],
                {
                    "expected_letter_of_credit_version": fx.credit_version(
                        api, ctx["lc_id"]
                    ),
                    "amount_usd": 26000.00,
                },
                OPS_ALICE,
            ),
            200,
        )
        assert credit["status"] == "RECEIVED"
        assert credit["amendment_round"] == 1
        assert credit["amount_usd"] == approx_money(26000.00)
        assert credit["max_drawable_usd"] == approx_money(28600.00)
        assert credit["min_drawable_usd"] == approx_money(23400.00)

        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="UNSECURED")
        assert order["insured_exposure_usd"] == approx_money(0.00)

        released = fx.read_policy(api, policy["id"])
        assert released["utilized_usd"] == approx_money(0.00)
        assert released["available_limit_usd"] == approx_money(25000.00)
        assert released["status"] == "ACTIVE"

        assert fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))[
            "aggregate_exposure_usd"
        ] == approx_money(0.00)
        assert fx.data(api.get_terms_review(ctx["review_id"], REVIEWER_BOB))[
            "status"
        ] == "SUPERSEDED"

    def test_a_policy_short_of_headroom_leaves_the_order_uninsured(self, api):
        """PRD §3.8: "When the candidate set is **empty** — no active in-window
        policy has enough headroom — nothing is charged and no error is raised."

        Design: Corner/calculations/corner_uninsured_passthrough_when_no_policy_has_enough_headroom
        """
        ctx = fx.order_with_lines(api)
        policy = fx.create_policy(
            api,
            ctx["buyer_id"],
            policy_number="POL-2026-0004",
            credit_limit_usd=20000.00,
        )
        ctx = fx.captured_credit(api, ctx, lc_number="LC-2026-0004")
        ctx = fx.opened_terms_review(api, ctx)

        review = validate_success(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
            ),
            200,
        )
        assert review["recommendation"] == "ACCEPT"
        assert review["terms_risk_score"] == approx_money(0.00)
        assert review["finding_count"] == 0

        assert fx.read_credit(api, ctx["lc_id"])["status"] == "ACCEPTED"
        order = fx.read_order(api, ctx["order_id"])
        assert_order_dimensions(order, settlement="LC_ACCEPTED")
        assert order["insured_exposure_usd"] == approx_money(0.00)

        untouched = fx.read_policy(api, policy["id"])
        assert untouched["utilized_usd"] == approx_money(0.00)
        assert untouched["available_limit_usd"] == approx_money(20000.00)
        assert untouched["status"] == "ACTIVE"
        assert untouched["premium_usd"] == approx_money(153.00)

        assert fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))[
            "aggregate_exposure_usd"
        ] == approx_money(0.00)

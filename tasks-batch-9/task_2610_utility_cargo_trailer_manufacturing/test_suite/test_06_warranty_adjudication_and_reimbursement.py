"""Warranty adjudication: coverage variants, rounding order and the info loop.

Every reimbursement figure here is the arithmetic of PRD 3.9 evaluated in the
order that section pins: the parts subtotal one line at a time, the labor
amount at the dealer's live rate, the freight waiver, and finally the coverage
factor decided from whole days past the trailer's 730-day expiry.
"""

import pytest

import test_helpers as H
from test_helpers import SALES_ADMIN, validate_error, validate_paginated, validate_success


class TestCoverageVariantPair:
    def test_a_failure_on_the_expiry_instant_reimburses_the_gross_amount_in_full(self, api):
        """Zero days past expiry keeps the claim inside the warranty window.

        PRD 3.9: "When that figure is zero or negative, meaning the failure
        happened on or before expiry, `coverage_variant` is `IN_WARRANTY_FULL`
        and `coverage_factor` is 1.00, so the reimbursement equals the gross
        amount exactly."

        Design: Difficulty/dual_variant_calc/warranty_in_warranty_full_versus_goodwill_prorated
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        assert staged["unit"]["warranty_start_date"] is not None
        H.assert_instant(staged["unit"]["warranty_start_date"], H.WARRANTY_START_AUG_05)
        H.set_clock(api, H.CLOCK_2028_AUG_20)
        claim = H.file_claim(
            api,
            staged["unit"]["id"],
            plant["dealer"]["id"],
            claim_ref=H.CLAIM_REF_IN_WARRANTY,
            failure_date=H.FAILURE_ON_EXPIRY,
        )

        approved = H.review_claim(api, claim["id"], H.ClaimDecision.APPROVE)

        assert approved["coverage_variant"] == H.CoverageVariant.IN_WARRANTY_FULL
        assert approved["coverage_factor"] == pytest.approx(1.00, abs=0.01)
        H.assert_money(approved["labor_cents"], H.CLAIM_LABOR_CENTS)
        H.assert_money(approved["parts_subtotal_cents"], H.CLAIM_PARTS_SUBTOTAL_CENTS)
        H.assert_money(approved["freight_cents"], H.CLAIM_FREIGHT_CENTS)
        H.assert_money(approved["reimbursement_total_cents"], H.CLAIM_GROSS_CENTS)
        assert approved["status"] == H.ClaimStatus.APPROVED
        assert approved["part_line_count"] == 2

    def test_a_failure_ten_days_past_expiry_reimburses_three_quarters_of_the_same_gross(self, api):
        """Identical hours and identical part lines reimburse strictly less past expiry.

        PRD 3.9: "Because the goodwill factors bite on the whole gross figure,
        identical labor hours and identical part lines reimburse strictly less
        outside the warranty window than inside it."

        Design: Difficulty/dual_variant_calc/warranty_in_warranty_full_versus_goodwill_prorated
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_2028_AUG_20)
        in_warranty = H.file_claim(
            api,
            staged["unit"]["id"],
            plant["dealer"]["id"],
            claim_ref=H.CLAIM_REF_IN_WARRANTY,
            failure_date=H.FAILURE_ON_EXPIRY,
        )
        in_warranty = H.review_claim(api, in_warranty["id"], H.ClaimDecision.APPROVE)
        goodwill = H.file_claim(
            api,
            staged["unit"]["id"],
            plant["dealer"]["id"],
            claim_ref=H.CLAIM_REF_GOODWILL,
            failure_date=H.FAILURE_10_DAYS_PAST_EXPIRY,
        )

        goodwill = H.review_claim(api, goodwill["id"], H.ClaimDecision.APPROVE)

        assert goodwill["coverage_variant"] == H.CoverageVariant.GOODWILL_PRORATED
        assert goodwill["coverage_factor"] == pytest.approx(0.75, abs=0.01)
        H.assert_money(goodwill["labor_cents"], H.CLAIM_LABOR_CENTS)
        H.assert_money(goodwill["parts_subtotal_cents"], H.CLAIM_PARTS_SUBTOTAL_CENTS)
        H.assert_money(goodwill["reimbursement_total_cents"], H.CLAIM_GOODWILL_75_CENTS)
        assert (
            in_warranty["reimbursement_total_cents"] - goodwill["reimbursement_total_cents"]
            == H.COVERAGE_DELTA_FULL_MINUS_GOODWILL_CENTS
        )
        assert goodwill["status"] == H.ClaimStatus.APPROVED


class TestPartsMarkupRoundingOrder:
    def test_the_markup_rounds_per_line_before_the_quantity_multiplies(self, api):
        """5398 and 911 marked up, rounded, then multiplied gives 22235.

        PRD 3.9: "for each entry of `part_lines`, the line's `unit_cost_cents`
        is marked up by thirty hundredths — a 30 percent parts markup, so the
        exact value is the cost multiplied by one and three tenths — that single
        marked-up figure is rounded half up to whole cents, the rounded figure
        is **then** multiplied by the line's `quantity`, and only then is the
        result added into `parts_subtotal_cents`."

        Design: Difficulty/combinatorial_formula/warranty_parts_markup_rounds_per_line_before_quantity
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_2028_OCT_15)
        claim = H.file_claim(
            api,
            staged["unit"]["id"],
            plant["dealer"]["id"],
            claim_ref=H.CLAIM_REF_ROUNDING,
            failure_date=H.FAILURE_58_DAYS_PAST_EXPIRY,
        )

        approved = H.review_claim(api, claim["id"], H.ClaimDecision.APPROVE)

        H.assert_money(approved["parts_subtotal_cents"], H.CLAIM_PARTS_SUBTOTAL_CENTS)
        assert (
            approved["parts_subtotal_cents"] != H.CLAIM_PARTS_SUM_THEN_ROUND_ONCE_CENTS
        ), "summing the raw marked-up values and rounding once is the wrong answer"
        assert (
            approved["parts_subtotal_cents"] != H.CLAIM_PARTS_QUANTITY_THEN_ROUND_CENTS
        ), "multiplying by quantity before rounding the line is the wrong answer"
        H.assert_money(approved["labor_cents"], H.CLAIM_LABOR_CENTS)
        H.assert_money(approved["freight_cents"], H.CLAIM_FREIGHT_CENTS)

    def test_the_coverage_multiplication_rounds_half_up_on_an_exact_tie(self, api):
        """A 49535 gross at 0.50 lands on 24767.5 and must settle at 24768.

        PRD 3.9: "`reimbursement_total_cents` is the gross amount multiplied by
        `coverage_factor`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/warranty_parts_markup_rounds_per_line_before_quantity
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_2028_OCT_15)
        claim = H.file_claim(
            api,
            staged["unit"]["id"],
            plant["dealer"]["id"],
            claim_ref=H.CLAIM_REF_ROUNDING,
            failure_date=H.FAILURE_58_DAYS_PAST_EXPIRY,
        )

        approved = H.review_claim(api, claim["id"], H.ClaimDecision.APPROVE)

        assert approved["coverage_variant"] == H.CoverageVariant.GOODWILL_PRORATED
        assert approved["coverage_factor"] == pytest.approx(0.50, abs=0.01)
        H.assert_money(approved["reimbursement_total_cents"], H.CLAIM_GOODWILL_50_CENTS)
        assert approved["status"] == H.ClaimStatus.APPROVED


class TestInformationRequestLoop:
    def test_the_loop_counter_never_resets_across_two_resubmissions(self, api):
        """Each request raises the round and each resubmission retains it.

        PRD 3.9: "resubmission moves the claim `INFO_REQUESTED` → `SUBMITTED`,
        retains `info_request_round` exactly as it stands — the loop counter
        never resets — and recomputes `part_line_count` from whatever
        `part_lines` now holds."

        Design: Difficulty/non_linear_state_machine/warranty_info_request_loop_terminates_in_denial
        """
        plant = H.setup_plant(api)
        staged = H.claim_submitted(
            plant, api, claim_clock=H.CLOCK_2028_AUG_20, claim_ref=H.CLAIM_REF_LOOP
        )
        claim_id = staged["claim"]["id"]
        assert staged["claim"]["info_request_round"] == 0

        first_request = H.review_claim(api, claim_id, H.ClaimDecision.REQUEST_INFO)
        first_answer = H.resubmit_claim(api, claim_id, plant["dealer"]["id"])
        second_request = H.review_claim(api, claim_id, H.ClaimDecision.REQUEST_INFO)
        second_answer = H.resubmit_claim(api, claim_id, plant["dealer"]["id"])

        assert first_request["status"] == H.ClaimStatus.INFO_REQUESTED
        assert first_request["info_request_round"] == 1
        assert first_answer["status"] == H.ClaimStatus.SUBMITTED
        assert first_answer["info_request_round"] == 1
        assert second_request["status"] == H.ClaimStatus.INFO_REQUESTED
        assert second_request["info_request_round"] == 2
        assert second_answer["status"] == H.ClaimStatus.SUBMITTED
        assert second_answer["info_request_round"] == 2
        assert second_answer["part_line_count"] == 2
        H.assert_no_money_computed(second_answer)

    def test_a_third_information_request_denies_the_claim_instead_of_looping(self, api):
        """The bounded loop terminates in DENIED at round three.

        PRD 3.9: "When a third information request is attempted — that is, when
        `info_request_round` already stands at 2 — the loop terminates instead of
        continuing: `info_request_round` is raised to 3, the claim moves
        `SUBMITTED` → `DENIED`, and `denial_reason` is recorded as
        `INFO_REQUEST_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/warranty_info_request_loop_terminates_in_denial
        """
        plant = H.setup_plant(api)
        staged = H.claim_submitted(
            plant, api, claim_clock=H.CLOCK_2028_AUG_20, claim_ref=H.CLAIM_REF_LOOP
        )
        claim_id = staged["claim"]["id"]
        H.review_claim(api, claim_id, H.ClaimDecision.REQUEST_INFO)
        H.resubmit_claim(api, claim_id, plant["dealer"]["id"])
        H.review_claim(api, claim_id, H.ClaimDecision.REQUEST_INFO)
        H.resubmit_claim(api, claim_id, plant["dealer"]["id"])

        denied = H.review_claim(api, claim_id, H.ClaimDecision.REQUEST_INFO)

        assert denied["status"] == H.ClaimStatus.DENIED
        assert denied["info_request_round"] == 3
        assert denied["denial_reason"] == H.DENIAL_INFO_REQUEST_LIMIT
        H.assert_no_money_computed(denied)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_money(dealer["warranty_receivable_cents"], 0)


class TestClaimGatedOnDelivery:
    def test_a_claim_against_a_stocked_trailer_reports_the_delivery_gate(self, api):
        """With no warranty_start_date the delivery gate answers first.

        PRD 3.9: "The trailer must already have been delivered — its
        `build_status` must be `SHIPPED` and its `warranty_start_date` must not
        be null — and a claim against an undelivered trailer is refused with
        `ERR_UNIT_NOT_DELIVERED`."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_blocked_until_unit_reaches_shipped
        """
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api)
        H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])
        assert staged["unit"]["warranty_start_date"] is None

        response = api.create_claim(
            H.claim_payload(
                staged["unit"]["id"],
                plant["dealer"]["id"],
                claim_ref=H.CLAIM_REF_EARLY,
                failure_date=H.FAILURE_BEFORE_DELIVERY,
            ),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_UNIT_NOT_DELIVERED)
        claims, _meta = validate_paginated(
            api.list_claims(params={"unit_id": staged["unit"]["id"]}, headers=SALES_ADMIN)
        )
        assert claims == []

    def test_the_same_claim_is_accepted_once_the_trailer_has_shipped(self, api):
        """Delivery stamps the warranty clock and opens the claim endpoint.

        PRD 3.8: "The trailer moves `build_status` `ALLOCATED` → `SHIPPED`, which
        is terminal, and its `warranty_start_date` is stamped with the same
        logical instant — the trailer's warranty runs for 730 days from that
        moment, so its expiry is that instant plus 730 days."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_blocked_until_unit_reaches_shipped
        """
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])
        refused = api.create_claim(
            H.claim_payload(
                staged["unit"]["id"],
                plant["dealer"]["id"],
                claim_ref=H.CLAIM_REF_EARLY,
                failure_date=H.FAILURE_BEFORE_DELIVERY,
            ),
            headers=SALES_ADMIN,
        )
        validate_error(refused, H.ERR_UNIT_NOT_DELIVERED)
        H.allocate_order(api, order["id"], plant["dealer"]["id"])
        H.set_clock(api, H.CLOCK_AUG_05)
        H.deliver_order(api, order["id"])
        H.set_clock(api, H.CLOCK_SEP_01)

        response = api.create_claim(
            H.claim_payload(
                staged["unit"]["id"],
                plant["dealer"]["id"],
                claim_ref=H.CLAIM_REF_1,
                failure_date=H.CLAIM_FAILURE_DATE_IN_WARRANTY,
            ),
            headers=SALES_ADMIN,
        )

        claim = validate_success(response, expected_status=201)
        shipped_unit = H.read_unit(api, staged["unit"]["id"])
        assert shipped_unit["build_status"] == H.BuildStatus.SHIPPED
        H.assert_instant(shipped_unit["warranty_start_date"], H.WARRANTY_START_AUG_05)
        assert claim["status"] == H.ClaimStatus.SUBMITTED
        assert claim["part_line_count"] == 2
        assert claim["info_request_round"] == 0
        H.assert_no_money_computed(claim)

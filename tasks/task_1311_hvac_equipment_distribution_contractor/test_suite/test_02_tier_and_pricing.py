"""Dealer tier thresholds, order-line pricing bases, and pre-buy rounding."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, make_contractor_headers, TEST_USERS, ApiErrorId,
    make_contractor, make_model, make_prebuy_program, get_contractor,
    create_draft_order, add_line, submit_order, seed_delivered_volume,
    deliver_merchandise,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


class TestSilverTierBoundary:
    def test_tier_silver_boundary_exact(self, api):
        """PRD §3.1: "Whenever an order is delivered the year-to-date figure is recomputed and the tier re-evaluated against inclusive thresholds: at least $50,000 (5,000,000 cents) earns `SILVER`, at least $200,000 (20,000,000 cents) earns `GOLD`, and at least $500,000 (50,000,000 cents) earns `PLATINUM`; below $50,000 the contractor remains `STANDARD`."

        Design: Difficulty/boundary_precision_check/tier_threshold_exact_silver_boundary
        """
        contractor = make_contractor(license_number="LIC-011A")
        deliver_merchandise(contractor, 5_000_000, family_code="FAM-P")
        contractor = get_contractor(contractor["id"])
        assert contractor["ytd_purchase_cents"] == 5_000_000
        assert contractor["tier"] == "SILVER"

    def test_tier_one_cent_below_silver_stays_standard(self, api):
        """PRD §3.1: "Whenever an order is delivered the year-to-date figure is recomputed and the tier re-evaluated against inclusive thresholds: at least $50,000 (5,000,000 cents) earns `SILVER`, at least $200,000 (20,000,000 cents) earns `GOLD`, and at least $500,000 (50,000,000 cents) earns `PLATINUM`; below $50,000 the contractor remains `STANDARD`."

        Design: Difficulty/boundary_precision_check/tier_threshold_exact_silver_boundary
        """
        contractor = make_contractor(license_number="LIC-011B")
        deliver_merchandise(contractor, 4_999_999, family_code="FAM-P")
        contractor = get_contractor(contractor["id"])
        assert contractor["ytd_purchase_cents"] == 4_999_999
        assert contractor["tier"] == "STANDARD"


class TestListBasisVsPrebuyBasis:
    """Same model, same GOLD contractor: tier-discounted list basis vs pre-buy list basis."""

    def _setup_gold_contractor_with_model(self):
        contractor = make_contractor(license_number="LIC-002")
        deliver_merchandise(contractor, 20_000_000, family_code="FAM-Y-SEED")
        contractor = get_contractor(contractor["id"])
        assert contractor["tier"] == "GOLD", "setup: contractor must be GOLD"
        model = make_model(model_number="HP-1M", equipment_type="HEAT_PUMP",
                           refrigerant_type="R454B", family_code="FAM-Y",
                           list_price_cents=1_000_000)
        program = make_prebuy_program(name="FALL-PREBUY", family_code="FAM-Y")
        return contractor, model, program

    def test_list_basis_unit_price_uses_gold_tier_discount(self, api):
        """PRD §3.1: "Tier determines the discount applied to list prices when order lines are priced for non-pre-buy orders: `STANDARD` receives no discount, `SILVER` three percent, `GOLD` five percent, and `PLATINUM` seven percent, with the discounted unit price rounded half-up to the nearest cent."
        PRD §3.4: "Pricing is entirely server-side: the line's `unit_price_cents` is resolved from the contractor's tier discount — or, when the order carries a `prebuy_program_id`, from pre-buy terms, under which the unit price is simply the model's `list_price_cents` with no tier discount applied — and any client-supplied price is ignored."

        Design: Difficulty/dual_variant_calc/unit_price_list_basis_vs_prebuy_basis_divergence
        """
        contractor, model, _ = self._setup_gold_contractor_with_model()
        order = create_draft_order(contractor)
        line = add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        submit_order(order["id"], contractor)
        lines, _ = validate_paginated(api.list_order_lines(order["id"], ADMIN))
        priced = [l for l in lines if l["id"] == line["id"]][0]
        assert priced["unit_price_cents"] == 950_000, (
            f"GOLD 5% off 1,000,000 list must price at 950000, got {priced['unit_price_cents']}")

    def test_prebuy_basis_unit_price_is_full_list_with_line_discount(self, api):
        """PRD §3.4: "Pricing is entirely server-side: the line's `unit_price_cents` is resolved from the contractor's tier discount — or, when the order carries a `prebuy_program_id`, from pre-buy terms, under which the unit price is simply the model's `list_price_cents` with no tier discount applied — and any client-supplied price is ignored."
        PRD §3.4: "The line's `line_discount_cents` and `line_total_cents` follow the pre-buy rounding discipline whenever a program applies: the line's gross (unit price times quantity) is multiplied by the program's `discount_pct` and rounded half-up to the cent **per line**, and the line total is the gross minus that discount."

        Design: Difficulty/dual_variant_calc/unit_price_list_basis_vs_prebuy_basis_divergence
        """
        contractor, model, program = self._setup_gold_contractor_with_model()
        order = create_draft_order(contractor, prebuy_program_id=program["id"])
        line = add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        submit_order(order["id"], contractor)
        lines, _ = validate_paginated(api.list_order_lines(order["id"], ADMIN))
        priced = [l for l in lines if l["id"] == line["id"]][0]
        assert priced["unit_price_cents"] == 1_000_000, (
            f"pre-buy pricing suppresses the tier discount; expected 1000000, got {priced['unit_price_cents']}")
        assert priced["line_discount_cents"] == 100_000, (
            f"10% pre-buy discount on 1,000,000 gross is 100000, got {priced['line_discount_cents']}")
        assert priced["line_total_cents"] == 900_000


class TestPrebuyPerLineRounding:
    """Mode: discount rounded per line, then summed — never summed then discounted."""

    def _setup_rounding_order(self):
        contractor = make_contractor(license_number="LIC-003")
        model = make_model(model_number="CU-333", refrigerant_type="R410A",
                           family_code="FAM-Z", list_price_cents=333_333)
        program = make_prebuy_program(name="ROUNDING-PREBUY", family_code="FAM-Z")
        order = create_draft_order(contractor, prebuy_program_id=program["id"])
        for _ in range(3):
            add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        submit_order(order["id"], contractor)
        return get_success_data(api_client.get_order(order["id"], ADMIN))

    def test_prebuy_discount_rounded_per_line_then_summed(self, api):
        """PRD §3.4: "Every line addition recomputes the order's `subtotal_cents` (the sum of line grosses), `discount_cents` (the sum of line discounts), and `total_cents` (subtotal minus discount), and increments the order's `version`; computing discounts against a summed order total instead of per line is forbidden."
        PRD §2.7: "Where a computation produces a fractional cent, the value is rounded **half-up to the nearest whole cent**, and the point at which rounding occurs is pinned per calculation: pre-buy line discounts are rounded per line before any summation (computing the discount on a summed total is forbidden); tier-discounted unit prices are rounded per unit price; an order's pre-buy deposit is rounded once, on the summed order total; co-op accrual is rounded once at the aggregate level, never per line; warranty coverage amounts are rounded per coverage component; and a rebate's thirty-percent cost ceiling is rounded before the lesser-of comparison that uses it."

        Design: Difficulty/combinatorial_formula/prebuy_discount_per_line_rounding_then_sum
        """
        order = self._setup_rounding_order()
        assert order["subtotal_cents"] == 999_999
        assert order["discount_cents"] == 99_999, (
            "per-line rounding gives 3 x 33333 = 99999; sum-then-round would give 100000")
        assert order["total_cents"] == 900_000

    def test_prebuy_deposit_rounded_once_on_summed_total(self, api):
        """PRD §3.4: "On acceptance the server stamps `submitted_at` from the logical clock, re-resolves every line's pricing under the order's terms, recomputes the order totals, and — for pre-buy orders — derives `deposit_due_cents` as the order total multiplied by the program's `deposit_pct`, rounded half-up to the cent once on the summed total; non-pre-buy orders keep a deposit of zero."

        Design: Difficulty/combinatorial_formula/prebuy_discount_per_line_rounding_then_sum
        """
        order = self._setup_rounding_order()
        assert order["total_cents"] == 900_000
        assert order["deposit_due_cents"] == 225_000, (
            f"deposit is round_half_up(900000 * 0.25) = 225000, got {order['deposit_due_cents']}")
        lines, _ = validate_paginated(api.list_order_lines(order["id"], ADMIN))
        assert len(lines) == 3
        for line in lines:
            assert line["line_discount_cents"] == 33_333, (
                f"each line's discount rounds half-up from 33333.3 to 33333, got {line['line_discount_cents']}")


class TestOrderOccAndVersioning:
    def test_order_patch_stale_version_rejected(self, api):
        """PRD §2.6: "Updating a draft order — the endpoint `PATCH /orders/{id}` — requires the request body to carry `expected_order_version`, the value of the order's `version` the client last observed. If that value no longer matches the order's current `version` — because the draft has legitimately changed since the client read it, for example a line was added or the pre-buy program was swapped — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a draft state it has not observed."

        Design: Corner/endpoints/order_patch_occ_stale_version_conflict
        """
        contractor = make_contractor(license_number="LIC-C500")
        headers = make_contractor_headers(contractor["id"])
        model = make_model(model_number="CU-O500", family_code="FAM-Y8",
                           list_price_cents=500_000)
        program = make_prebuy_program(name="P-OCC", family_code="FAM-Y8")
        order = create_draft_order(contractor)
        stale_version = order["version"]
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        current = get_success_data(api.get_order(order["id"], headers))
        current_version = current["version"]
        assert current_version != stale_version, "setup: line addition must bump the version"

        stale_res = api.patch_order(
            order["id"], {"expected_order_version": stale_version,
                          "prebuy_program_id": program["id"]}, headers)
        validate_error(stale_res, ApiErrorId.ERR_STALE_VERSION)

        ok_res = api.patch_order(
            order["id"], {"expected_order_version": current_version,
                          "prebuy_program_id": program["id"]}, headers)
        patched = validate_success(ok_res, 200)
        assert patched["version"] == current_version + 1

    def test_order_version_increments_on_each_mutation(self, api):
        """PRD §2.5: "`version` — an integer starting at its initial value and incrementing by exactly 1 on every mutation of the resource."
        PRD §3.4: "Every line addition recomputes the order's `subtotal_cents` (the sum of line grosses), `discount_cents` (the sum of line discounts), and `total_cents` (subtotal minus discount), and increments the order's `version`; computing discounts against a summed order total instead of per line is forbidden."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        contractor = make_contractor(license_number="LIC-C800")
        model = make_model(model_number="CU-V800", family_code="FAM-R1",
                           list_price_cents=500_000)
        order = create_draft_order(contractor)
        created_version = order["version"]
        add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=1)
        submit_order(order["id"], contractor)
        final = get_success_data(api.get_order(
            order["id"], make_contractor_headers(contractor["id"])))
        assert final["version"] == created_version + 2, (
            f"line add (+1) and submit (+1) must move version from {created_version} "
            f"to {created_version + 2}, got {final['version']}")

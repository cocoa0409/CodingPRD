"""Invoicing: provisional vs final billing basis, average-rate tier selection,
binding scrap-credit cap, surcharge pinning, finalization gating, and invoice
terminal states (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_deviation,
    certify_order,
    cut_billets,
    get_success_data,
    inspect_and_ship_all,
    install_die,
    new_alloy,
    new_certified_heat,
    new_die_set,
    new_forge_run,
    new_furnace,
    new_invoice,
    new_ready_charge,
    new_ready_charges,
    new_surcharge_index,
    new_work_center,
    new_work_order,
    open_trim_ticket,
    order_parts,
    record_heat,
    record_trim,
    setup_production_ctx,
    setup_shipped_ctx,
    start_run,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
FORGE = TEST_USERS["forge_operator_headers"]
QE = TEST_USERS["quality_engineer_headers"]
SP = TEST_USERS["sales_planner_headers"]


class TestProvisionalVsFinalPricing:
    def test_invoice_provisional_pricing_and_pin(self, api):
        """PRD §3.8: "While `PROVISIONAL`, the billing basis
        `billable_weight_lbs` is the estimate `estimated_net_weight_lbs`,
        computed as `ordered_qty` times `part_net_weight_lbs`."
        PRD §3.8: "Creation pins the surcharge index for the order's alloy and
        the logical clock's current month into the invoice's
        `surcharge_index_id` — a version pin retained unchanged through
        finalization — and when no index exists for that alloy and month,
        creation fails with `ERR_SURCHARGE_INDEX_MISSING`."
        PRD §3.8: "At provisional time there are typically no accepted tickets
        yet, so the scrap credit is zero."

        Ten parts at 40.00 lbs estimate 400.00 lbs = 0.200 t, billed entirely
        at the tier-1 rate: base 400000 + alloy 50000 + energy 45000 - 0 =
        495000 cents.

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_pricing
        """
        alloy = new_alloy()
        index = new_surcharge_index(alloy["id"])
        wo = new_work_order(alloy["id"], "WO-1", ordered_qty=10)
        invoice = new_invoice(wo["id"])
        assert invoice["status"] == "PROVISIONAL"
        assert invoice["estimated_net_weight_lbs"] == pytest.approx(400.00, abs=1e-9)
        assert invoice["billable_weight_lbs"] == pytest.approx(400.00, abs=1e-9)
        assert invoice["billable_tons"] == pytest.approx(0.200, abs=1e-9)
        assert invoice["tier_rate_cents_per_ton"] == 2000000
        assert invoice["base_amount_cents"] == 400000
        assert invoice["alloy_surcharge_cents"] == 50000
        assert invoice["energy_surcharge_cents"] == 45000
        assert invoice["scrap_credit_cents"] == 0
        assert invoice["total_cents"] == 495000
        assert invoice["surcharge_index_id"] == index["id"], (
            "the surcharge index is pinned at provisional creation"
        )

    def test_invoice_final_pricing_after_shipment(self, api):
        """PRD §3.8: "The `actual_shipped_net_weight_lbs` — the sum of
        `net_weight_lbs` over the order's `SHIPPED` parts — becomes the
        `billable_weight_lbs`, the scrap credit now draws on the actual
        accepted tickets, the pinned `surcharge_index_id` is retained
        unchanged, and the invoice moves from `PROVISIONAL` to `FINAL`."
        PRD §3.8: "The `total_cents` is the base plus the alloy surcharge plus
        the energy surcharge minus the scrap credit, with every component
        rounded to whole cents first and only then summed."

        The provisional invoice (created before production at 495000 cents)
        reprices on actuals: 430.00 shipped lbs = 0.215 t -> base 430000,
        alloy 53750, energy 48375, scrap 6300 (42.00 flash lbs * 150, under
        the 21500 cap) -> total 525825.

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_pricing
        """
        alloy = new_alloy()
        index = new_surcharge_index(alloy["id"])
        wo = new_work_order(alloy["id"], "WO-1", ordered_qty=10)
        provisional = new_invoice(wo["id"])
        assert provisional["total_cents"] == 495000
        # Full production: 10 parts forged, trimmed at 430.00 net, certified,
        # inspected, shipped.
        heat = new_certified_heat(alloy["id"], "H-1001")
        billets = cut_billets(heat["id"], 20.0, 10)
        furnace = new_furnace()
        charge = new_ready_charge(furnace["id"], [b["id"] for b in billets])
        die = new_die_set("DIE-10")
        wc = new_work_center("WC-1")
        install_die(die["id"], wc["id"])
        run = new_forge_run(wo["id"], die["id"], planned_qty=10,
                            work_center_id=wc["id"])
        start_run(run["id"])
        record_heat(run["id"], charge["id"], [b["id"] for b in billets],
                    parts_good=10)
        get_success_data(api.finish_forging(run["id"], FORGE))
        ticket = open_trim_ticket(run["id"])
        recorded = record_trim(ticket["id"], 480.00, 430.00, 8.00)
        assert recorded["status"] == "ACCEPTED"
        certify_order(wo["id"])
        inspect_and_ship_all(wo["id"])
        final = get_success_data(api.finalize_invoice(provisional["id"], SP))
        assert final["status"] == "FINAL"
        assert final["billable_tons"] == pytest.approx(0.215, abs=1e-9)
        assert final["base_amount_cents"] == 430000
        assert final["alloy_surcharge_cents"] == 53750
        assert final["energy_surcharge_cents"] == 48375
        assert final["scrap_credit_cents"] == 6300
        assert final["total_cents"] == 525825
        assert final["total_cents"] != provisional["total_cents"], (
            "the same formula on a different billing basis must move the total"
        )
        assert final["surcharge_index_id"] == index["id"], (
            "the pinned surcharge index is retained unchanged at finalization"
        )


class TestTieredTotalWithBindingScrapCap:
    def _setup_heavy_order(self, api):
        """Ten 850-lb billets consumed in two heats of one run; trim gross
        8100 / net 6000 / pierce 300 (flash 1800 lbs, 22.22% > 12%
        allowance); order fully certified and shipped."""
        alloy = new_alloy()
        new_surcharge_index(alloy["id"])
        heat = new_certified_heat(alloy["id"], "H-1201")
        billets = cut_billets(heat["id"], 340.0, 10)
        furnace = new_furnace()
        ids = [b["id"] for b in billets]
        charges = new_ready_charges(
            furnace["id"],
            [
                (ids[:5], "2026-08-02T08:00:00Z", "2026-08-02T11:00:00Z"),
                (ids[5:], "2026-08-02T12:00:00Z", "2026-08-02T15:00:00Z"),
            ],
        )
        die = new_die_set("DIE-12", 300, 2, "BLK-9")
        wc = new_work_center("WC-1")
        install_die(die["id"], wc["id"])
        wo = new_work_order(
            alloy["id"], "WO-3", ordered_qty=10, customer_name="HeavyInd",
            part_number="PN-600", part_net_weight_lbs=600.00,
            billet_weight_lbs=850.00)
        run = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                            "2026-08-03T12:00:00Z", 10, work_center_id=wc["id"])
        start_run(run["id"])
        record_heat(run["id"], charges[0]["id"], ids[:5], parts_good=5)
        record_heat(run["id"], charges[1]["id"], ids[5:], parts_good=5)
        get_success_data(api.finish_forging(run["id"], FORGE))
        ticket = open_trim_ticket(run["id"])
        return alloy, heat, wo, run, ticket

    def test_flagged_trim_deviation_acceptance(self, api):
        """PRD §3.6: "A ratio strictly greater than the allowance yields
        `FLAGGED`; a ratio exactly equal to the allowance is still
        `ACCEPTED`."
        PRD §3.6: "A `FLAGGED` ticket is not dead: a `QualityEngineer` may
        approve the deviation by supplying a non-empty `deviation_reason`,
        which is recorded on the ticket (it remains null on tickets never
        deviation-approved), and the approval applies the same part allocation
        and work-order bubble-up as a direct accept."

        Flash 1800.00 on 8100.00 gross is 22.22% > 12.0% -> FLAGGED, then
        deviation-approved to ACCEPTED with 600.00 net per part.

        Design: Difficulty/combinatorial_formula/invoice_tiered_total_with_binding_scrap_cap
        """
        alloy, heat, wo, run, ticket = self._setup_heavy_order(api)
        recorded = record_trim(ticket["id"], 8100.00, 6000.00, 300.00)
        assert recorded["flash_scrap_lbs"] == pytest.approx(1800.00, abs=1e-9)
        assert recorded["status"] == "FLAGGED", (
            f"22.22%% flash strictly exceeds the 12.0%% allowance, got "
            f"{recorded['status']}"
        )
        approved = approve_deviation(ticket["id"], "customer-approved overflash")
        assert approved["status"] == "ACCEPTED"
        assert approved["deviation_reason"] == "customer-approved overflash"
        parts = order_parts(wo["id"])
        for part in parts:
            assert part["status"] == "TRIMMED"
            assert part["net_weight_lbs"] == pytest.approx(600.00, abs=1e-9)
        wo_after = get_success_data(api.get_work_order(wo["id"], SP))
        assert wo_after["status"] == "PRODUCED"

    def test_final_invoice_tiered_total_scrap_cap_binds(self, api):
        """PRD §3.8: "The `scrap_credit_cents` is the lesser of two figures,
        each rounded half-up to whole cents: the total accepted flash pounds —
        the summed `flash_scrap_lbs` over the `ACCEPTED` trim tickets of the
        order's runs — multiplied by `scrap_recovery_rate_cents_per_lb`, or
        five percent of the base amount."
        PRD §3.8: "The tier rate `tier_rate_cents_per_ton` is an average rate
        applied to the whole tonnage, not a marginal one: tonnage at or below
        `price_tier1_limit_tons` prices entirely at `price_tier1_cents_per_ton`;
        tonnage above that but at or below `price_tier2_limit_tons` prices
        entirely at `price_tier2_cents_per_ton`; anything beyond prices
        entirely at `price_tier3_cents_per_ton`."

        6000.00 shipped lbs = 3.000 t -> tier 2 over the whole tonnage:
        base 5400000, alloy 750000, energy 615000; the 5%-of-base cap
        (270000) binds over the raw flash credit -> total 6495000.

        Design: Difficulty/combinatorial_formula/invoice_tiered_total_with_binding_scrap_cap
        """
        alloy, heat, wo, run, ticket = self._setup_heavy_order(api)
        recorded = record_trim(ticket["id"], 8100.00, 6000.00, 300.00)
        assert recorded["status"] == "FLAGGED"
        approve_deviation(ticket["id"], "customer-approved overflash")
        certify_order(wo["id"])
        inspect_and_ship_all(wo["id"])
        invoice = new_invoice(wo["id"])
        final = get_success_data(api.finalize_invoice(invoice["id"], SP))
        assert final["billable_tons"] == pytest.approx(3.000, abs=1e-9)
        assert final["tier_rate_cents_per_ton"] == 1800000, (
            "3.000 t prices the whole tonnage at the tier-2 average rate"
        )
        assert final["base_amount_cents"] == 5400000
        assert final["alloy_surcharge_cents"] == 750000
        assert final["energy_surcharge_cents"] == 615000
        assert final["scrap_credit_cents"] == 270000, (
            f"min(1800.00 lbs * 150 = 270000 raw, 5%% * 5400000 = 270000 cap) "
            f"= 270000, got {final['scrap_credit_cents']}"
        )
        assert final["total_cents"] == 6495000


class TestTierBoundaryAverageRate:
    def test_invoice_tier_boundary_average_rate(self, api):
        """PRD §3.8: "Billable tonnage `billable_tons` is the billable weight
        divided by two thousand pounds per ton, rounded half-up to three
        decimal places."
        PRD §3.8: "The tier rate `tier_rate_cents_per_ton` is an average rate
        applied to the whole tonnage, not a marginal one: tonnage at or below
        `price_tier1_limit_tons` prices entirely at `price_tier1_cents_per_ton`;
        tonnage above that but at or below `price_tier2_limit_tons` prices
        entirely at `price_tier2_cents_per_ton`; anything beyond prices
        entirely at `price_tier3_cents_per_ton`."

        2000.00 estimated lbs = 1.000 t bills entirely at tier 1 (inclusive
        bound); 2002.00 lbs = 1.001 t bills entirely at tier 2.

        Design: Corner/calculations/calc_invoice_tier_boundary_average_rate
        """
        alloy = new_alloy()
        new_surcharge_index(alloy["id"])
        wo_a = new_work_order(alloy["id"], "WO-42", ordered_qty=50,
                              part_net_weight_lbs=40.00)
        wo_b = new_work_order(alloy["id"], "WO-43", ordered_qty=50,
                              part_net_weight_lbs=40.04)
        inv_a = new_invoice(wo_a["id"])
        assert inv_a["billable_tons"] == pytest.approx(1.000, abs=1e-9)
        assert inv_a["tier_rate_cents_per_ton"] == 2000000, (
            "1.000 t sits at the inclusive tier-1 limit"
        )
        assert inv_a["base_amount_cents"] == 2000000
        assert inv_a["total_cents"] == 2475000
        inv_b = new_invoice(wo_b["id"])
        assert inv_b["billable_tons"] == pytest.approx(1.001, abs=1e-9)
        assert inv_b["tier_rate_cents_per_ton"] == 1800000, (
            "1.001 t prices ALL tons at tier 2 (average rate, no marginal split)"
        )
        assert inv_b["base_amount_cents"] == 1801800
        assert inv_b["total_cents"] == 2257255


class TestFinalizeGating:
    def _setup_produced_uncertified(self, api):
        """Production through PRODUCED with the auto-cert left PENDING; all
        parts inspected and shipped; provisional invoice created."""
        ctx = setup_production_ctx(qty=10, trim_gross=480.00, trim_net=430.00,
                                   trim_pierce=8.00, order_number="WO-15")
        inspect_and_ship_all(ctx["wo"]["id"])
        # PRD §3.8: invoice creation pins the surcharge index for the order's
        # alloy and the logical clock's current month (2026-08 here) — it must
        # exist first.
        new_surcharge_index(ctx["alloy"]["id"])
        invoice = new_invoice(ctx["wo"]["id"])
        return ctx, invoice

    def test_finalize_produced_order_not_certified(self, api):
        """PRD §3.8: "It requires the order to stand `CERTIFIED`
        (`ERR_ORDER_NOT_CERTIFIED`) and no part of the order to remain in
        `FORGED`, `TRIMMED`, or `INSPECTED` (`ERR_ORDER_NOT_FULLY_SHIPPED`)."

        The order is PRODUCED with its cert still PENDING; every part is
        shipped, so only the certification gate fails.

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_order_certified
        """
        ctx, invoice = self._setup_produced_uncertified(api)
        wo = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo["status"] == "PRODUCED"
        resp = api.finalize_invoice(invoice["id"], SP)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CERTIFIED, 409)
        after = get_success_data(api.get_invoice(invoice["id"], SP))
        assert after["status"] == "PROVISIONAL"

    def test_finalize_released_order_not_certified(self, api):
        """PRD §3.8: "It requires the order to stand `CERTIFIED`
        (`ERR_ORDER_NOT_CERTIFIED`) and no part of the order to remain in
        `FORGED`, `TRIMMED`, or `INSPECTED` (`ERR_ORDER_NOT_FULLY_SHIPPED`)."

        A freshly RELEASED order with no production at all fails the same
        gate.

        Design: Difficulty/cross_entity_state_dependency/finalize_requires_order_certified
        """
        alloy = new_alloy()
        new_surcharge_index(alloy["id"])
        wo = new_work_order(alloy["id"], "WO-15B", ordered_qty=10)
        invoice = new_invoice(wo["id"])
        assert invoice["status"] == "PROVISIONAL"
        resp = api.finalize_invoice(invoice["id"], SP)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CERTIFIED, 409)
        after = get_success_data(api.get_invoice(invoice["id"], SP))
        assert after["status"] == "PROVISIONAL"


class TestInvoiceTerminalStates:
    def test_mark_paid_provisional_rejected(self, api):
        """PRD §3.8: "Marking a `FINAL` invoice paid moves it to `PAID` and
        closes the loop, transitioning the order from `CERTIFIED` to
        `CLOSED`."
        PRD §2.10: "Source-state validity for the requested transition
        (`ERR_INVALID_STATE_TRANSITION`, alongside the dedicated state-flavored
        codes `ERR_CHARGE_NOT_READY`, `ERR_PART_NOT_INSPECTED`, and
        `ERR_RUN_NO_HEATS`)."

        Mark-paid is defined from FINAL; a PROVISIONAL invoice is refused.

        Design: Corner/state_machines/mark_paid_provisional_rejected
        """
        alloy = new_alloy()
        new_surcharge_index(alloy["id"])
        wo = new_work_order(alloy["id"], "WO-24", ordered_qty=2)
        invoice = new_invoice(wo["id"])
        assert invoice["status"] == "PROVISIONAL"
        resp = api.mark_invoice_paid(invoice["id"], SP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_invoice(invoice["id"], SP))
        assert after["status"] == "PROVISIONAL"

    def test_void_paid_invoice_rejected(self, api):
        """PRD §3.8: "A `PROVISIONAL` invoice may instead be voided to `VOID`.
        Marking a `FINAL` invoice paid moves it to `PAID` and closes the loop,
        transitioning the order from `CERTIFIED` to `CLOSED`."

        Void is defined from PROVISIONAL only: once the invoice is PAID (and
        the order CLOSED by the bubble-up), voiding is refused. The chain also
        pins the final arithmetic: 86.00 shipped lbs = 0.043 t -> base 86000 +
        alloy 10750 + energy 9675 - scrap 1800 = 104625 cents.

        Design: Corner/state_machines/void_paid_invoice_rejected
        """
        ctx = setup_shipped_ctx(qty=2)  # trim 100/86/2 -> 43.00 net per part
        assert ctx["ticket"]["status"] == "ACCEPTED", (
            "flash exactly 12.00%% equals the allowance and passes"
        )
        wo_mid = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo_mid["status"] == "CERTIFIED"
        # PRD §3.8: invoice creation pins the surcharge index for the order's
        # alloy and the logical clock's current month (2026-08 here) — it must
        # exist first.
        new_surcharge_index(ctx["alloy"]["id"])
        invoice = new_invoice(ctx["wo"]["id"])
        final = get_success_data(api.finalize_invoice(invoice["id"], SP))
        assert final["total_cents"] == 104625, (
            f"base 86000 + alloy 10750 + energy 9675 - scrap 1800 = 104625, "
            f"got {final['total_cents']}"
        )
        paid = get_success_data(api.mark_invoice_paid(invoice["id"], SP))
        assert paid["status"] == "PAID"
        wo_closed = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo_closed["status"] == "CLOSED", (
            "marking the FINAL invoice paid must close the CERTIFIED order"
        )
        resp = api.void_invoice(invoice["id"], SP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_invoice(invoice["id"], SP))
        assert after["status"] == "PAID"
        wo_final = get_success_data(api.get_work_order(ctx["wo"]["id"], SP))
        assert wo_final["status"] == "CLOSED"

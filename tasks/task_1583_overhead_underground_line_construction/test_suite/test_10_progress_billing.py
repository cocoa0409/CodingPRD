"""Progress billing: billing-preview variants, the overrun tier split, pinned
per-line rounding, the invoice revision cycle, validation precedence, pool
conservation, period overlap, the billable-units gate, and work-package OCC."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_entry,
    create_assignment_payload,
    create_bid_item_payload,
    create_crew_payload,
    create_draft_contract,
    create_draft_invoice,
    create_equipment_payload,
    create_invoice_payload,
    create_work_package_payload,
    fresh_work_package_version,
    get_success_data,
    report_production,
    setup_field_scenario,
    transition_invoice_to,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
INSPECTOR = TEST_USERS["utility_inspector_headers"]

PERIOD = ("2026-08-01", "2026-08-31")


def _preview_scenario(api):
    """60 ACCEPTED + 50 SUBMITTED units on a bid item priced 50.00 (est 100,
    overrun 40.00), under the default contract percentages."""
    scenario = setup_field_scenario(
        contract_overrides={"contract_number": "C-100"},
        bid_item_overrides={"item_code": "OH-POLE-35",
                            "description": "35ft pole set", "unit": "EACH",
                            "unit_price": 50.00, "estimated_quantity": 100,
                            "overrun_rate": 40.00},
        wp_overrides={"name": "Feeder F-12 rebuild", "location": "Rte 9 MP 3-5"},
        crew_overrides={"crew_code": "CR-1", "base_rate_per_hour": 60.00},
        equipment_overrides={"equipment_code": "EQ-1", "daily_rate": 120.00})
    asg_id = scenario["assignment"]["id"]
    bid_id = scenario["bid_item"]["id"]
    e1 = report_production(asg_id, bid_id, "2026-08-04", 60)
    accept_entry(scenario["work_package"]["id"], e1["id"], )
    report_production(asg_id, bid_id, "2026-08-05", 50)  # stays SUBMITTED
    return scenario


def _preview(api, work_package_id, variant):
    return validate_success(api.get_billing_preview(
        work_package_id, PM,
        params={"period_start": PERIOD[0], "period_end": PERIOD[1],
                "variant": variant}))


def _line_for(invoice_like, bid_item_id):
    for line in invoice_like["lines"]:
        if line["bid_item_id"] == bid_item_id:
            return line
    raise AssertionError(f"No line found for bid item {bid_item_id}")


class TestBillingPreviewVariants:
    def test_billing_preview_final_counts_accepted_only(self, api):
        """PRD §3.9: "Passing the `variant` parameter as `provisional` widens the
        eligible-units basis to count `SUBMITTED` entries alongside `ACCEPTED`
        ones, so identical production data yields a larger preview total whenever
        un-inspected entries exist; without that value the preview uses the final
        basis."
        PRD §3.9: "The eligible units are the sum of `quantity_reported` over the
        bid item's `ACCEPTED` entries whose `work_date` falls inside the invoice
        period, both ends inclusive."
        Final basis: only the 60 ACCEPTED units bill — 60 x 50.00 = 3000.00,
        retainage 300.00, amount due 2700.00.

        Design: Difficulty/dual_variant_calc/billing_preview_provisional_vs_final
        """
        scenario = _preview_scenario(api)
        preview = _preview(api, scenario["work_package"]["id"], "final")
        line = _line_for(preview, scenario["bid_item"]["id"])
        assert line["in_schedule_units"] == 60
        assert line["overrun_units"] == 0
        assert preview["subtotal"] == pytest.approx(3000.00, abs=0.01), (
            "Final basis counts only the 60 ACCEPTED units at 50.00")
        assert preview["retainage_amount"] == pytest.approx(300.00, abs=0.01)
        assert preview["amount_due"] == pytest.approx(2700.00, abs=0.01)

    def test_billing_preview_provisional_widens_basis(self, api):
        """PRD §3.9: "Passing the `variant` parameter as `provisional` widens the
        eligible-units basis to count `SUBMITTED` entries alongside `ACCEPTED`
        ones, so identical production data yields a larger preview total whenever
        un-inspected entries exist; without that value the preview uses the final
        basis."
        Provisional basis: 60 ACCEPTED + 50 SUBMITTED = 110 units, exactly at
        the 110-unit in-schedule threshold (110% of 100), all billed at 50.00 —
        subtotal 5500.00, retainage 550.00, amount due 4950.00.

        Design: Difficulty/dual_variant_calc/billing_preview_provisional_vs_final
        """
        scenario = _preview_scenario(api)
        wp_id = scenario["work_package"]["id"]
        provisional = _preview(api, wp_id, "provisional")
        line = _line_for(provisional, scenario["bid_item"]["id"])
        assert line["in_schedule_units"] == 110, (
            "110 units land exactly on the 110-unit threshold, all in-schedule")
        assert line["overrun_units"] == 0
        assert provisional["subtotal"] == pytest.approx(5500.00, abs=0.01)
        assert provisional["retainage_amount"] == pytest.approx(550.00, abs=0.01)
        assert provisional["amount_due"] == pytest.approx(4950.00, abs=0.01)

        final = _preview(api, wp_id, "final")
        assert provisional["subtotal"] - final["subtotal"] == pytest.approx(
            2500.00, abs=0.01), (
            "Identical production data yields a larger provisional total "
            "whenever un-inspected entries exist")


def _overrun_scenario(api):
    """120 ACCEPTED units on a bid item priced 50.00 (est 100, overrun 40.00):
    threshold floor(100 x 1.10) = 110, so the line splits 110 / 10."""
    scenario = setup_field_scenario(
        contract_overrides={"contract_number": "C-300"},
        bid_item_overrides={"item_code": "OH-WIRE-1/0", "description": "1/0 ACSR",
                            "unit": "LF", "unit_price": 50.00,
                            "estimated_quantity": 100, "overrun_rate": 40.00},
        wp_overrides={"name": "Line ext L-9", "location": "County Rd 42"},
        crew_overrides={"crew_code": "CR-9"},
        equipment_overrides={"equipment_code": "EQ-9", "kind": "DIGGER_DERRICK",
                             "daily_rate": 200.00})
    entry = report_production(scenario["assignment"]["id"],
                              scenario["bid_item"]["id"], "2026-08-04", 120)
    accept_entry(scenario["work_package"]["id"], entry["id"])
    return scenario


class TestOverrunTierSplit:
    def test_overrun_tier_split_line_values(self, api):
        """PRD §3.9: "the threshold, in whole units, is the largest whole number
        not exceeding `estimated_quantity` multiplied by the contract's
        `overrun_threshold_pct` — one hundred ten percent of the estimate by
        default. The prior cumulative accepted quantity — the bid item's
        `accepted_quantity` minus this period's eligible units — positions the
        boundary. `in_schedule_units` is then the larger of zero and the smaller
        of the billable quantity and the threshold minus the prior cumulative
        accepted quantity; `overrun_units` is whatever of the billable quantity
        remains. The `overrun_rate_applied` is the bid item's `overrun_rate`
        when one is set, otherwise its base `unit_price`; the `in_schedule_rate`
        is always the base `unit_price`."
        120 billable units split into 110 in-schedule at 50.00 plus 10 overrun
        at 40.00.

        Design: Difficulty/combinatorial_formula/overrun_tier_split_pricing
        """
        scenario = _overrun_scenario(api)
        invoice = create_draft_invoice(scenario["work_package"]["id"], *PERIOD)
        line = _line_for(invoice, scenario["bid_item"]["id"])
        assert line["in_schedule_units"] == 110
        assert line["overrun_units"] == 10
        assert line["in_schedule_rate"] == pytest.approx(50.00, abs=0.01)
        assert line["overrun_rate_applied"] == pytest.approx(40.00, abs=0.01)
        assert line["extension_amount"] == pytest.approx(5900.00, abs=0.01), (
            "110 x 50.00 + 10 x 40.00 = 5500.00 + 400.00 = 5900.00")

    def test_overrun_tier_split_invoice_totals(self, api):
        """PRD §3.9: "On submission the lines and the computed `subtotal`,
        `retainage_amount`, and `amount_due` freeze, and each bid item's
        `billed_quantity` rises by its line's total units, debiting the billable
        pool of §2.8."
        PRD §3.9: "The `retainage_amount` is the `subtotal` multiplied by the
        contract's `retainage_pct`, rounded half-up to two decimal places, and
        the `amount_due` is the `subtotal` minus the `retainage_amount`."
        Subtotal 5900.00, retainage 590.00 (0.10), amount due 5310.00.

        Design: Difficulty/combinatorial_formula/overrun_tier_split_pricing
        """
        scenario = _overrun_scenario(api)
        invoice = create_draft_invoice(scenario["work_package"]["id"], *PERIOD)
        submitted = transition_invoice_to(invoice["id"], "SUBMITTED", PM)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["subtotal"] == pytest.approx(5900.00, abs=0.01)
        assert submitted["retainage_amount"] == pytest.approx(590.00, abs=0.01)
        assert submitted["amount_due"] == pytest.approx(5310.00, abs=0.01)


class TestPerLineRoundingOrder:
    def _scenario(self, api):
        """Two bid items at 33.335, each with 3 ACCEPTED units this period."""
        contract = create_draft_contract(contract_number="C-301")
        bid_a = get_success_data(api.create_bid_item(
            contract["id"],
            create_bid_item_payload(item_code="UG-BORE-A",
                                    description="Directional bore A",
                                    unit="LF", unit_price=33.335,
                                    estimated_quantity=1000), PM))
        bid_b = get_success_data(api.create_bid_item(
            contract["id"],
            create_bid_item_payload(item_code="UG-BORE-B",
                                    description="Directional bore B",
                                    unit="LF", unit_price=33.335,
                                    estimated_quantity=1000), PM))
        get_success_data(api.transition_contract(contract["id"],
                                                 {"to": "ACTIVE"}, PM))
        wp = get_success_data(api.create_work_package(
            contract["id"],
            create_work_package_payload(name="UG circuit U-3",
                                        location="Downtown grid"), PM))
        get_success_data(api.transition_work_package(wp["id"],
                                                     {"to": "MOBILIZED"}, PM))
        crew = get_success_data(api.create_crew(
            create_crew_payload(crew_code="CR-U", crew_type="UNDERGROUND",
                                base_rate_per_hour=58.00), PM))
        equipment = get_success_data(api.create_equipment(
            create_equipment_payload(equipment_code="EQ-T1", kind="TRENCHER",
                                     daily_rate=180.00), PM))
        asg = get_success_data(api.create_assignment(
            wp["id"], create_assignment_payload(crew["id"], equipment["id"]),
            FOREMAN))
        get_success_data(api.transition_work_package(wp["id"],
                                                     {"to": "IN_PROGRESS"}, PM))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-03T12:00:00Z"}, PM))
        asg = get_success_data(api.transition_assignment(
            asg["id"], {"to": "ACTIVE"}, FOREMAN))
        ea = report_production(asg["id"], bid_a["id"], "2026-08-04", 3)
        accept_entry(wp["id"], ea["id"])
        eb = report_production(asg["id"], bid_b["id"], "2026-08-05", 3)
        accept_entry(wp["id"], eb["id"])
        return wp, bid_a, bid_b

    def test_per_line_rounding_half_up_extensions(self, api):
        """PRD §2.7: "All monetary amounts in the system — unit prices, line
        extensions, retainage, invoice totals, and storm premium pay — are
        computed with decimal arithmetic and rounded half-up to exactly two
        decimal places. Rounding is always applied per component before any
        summation: each invoice line's extension is rounded before lines are
        summed, and each premium-pay component is rounded before components are
        added."
        Each line: round(3 x 33.335, 2, half-up) = round(100.005) = 100.01.

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum
        """
        wp, bid_a, bid_b = self._scenario(api)
        invoice = create_draft_invoice(wp["id"], *PERIOD)
        for bid in (bid_a, bid_b):
            line = _line_for(invoice, bid["id"])
            assert line["in_schedule_units"] == 3
            assert line["overrun_units"] == 0
            assert line["extension_amount"] == pytest.approx(100.01, abs=0.001), (
                "round(3 x 33.335, 2, HALF_UP) = 100.01 per line")

    def test_subtotal_sums_rounded_lines(self, api):
        """PRD §3.9: "Totals follow a pinned rounding order: lines first, then
        the sum. The `subtotal` is the sum of the already-rounded per-line
        `extension_amount` values, with no further rounding applied. Rounding
        only after summation is forbidden: two lines of 100.005 round to 100.01
        each and total 200.02, whereas summing the raw values to 200.01 and
        rounding once would yield 200.01 — the pinned order always produces
        200.02. The `retainage_amount` is the `subtotal` multiplied by the
        contract's `retainage_pct`, rounded half-up to two decimal places, and
        the `amount_due` is the `subtotal` minus the `retainage_amount`."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum
        """
        wp, bid_a, bid_b = self._scenario(api)
        invoice = create_draft_invoice(wp["id"], *PERIOD)
        submitted = transition_invoice_to(invoice["id"], "SUBMITTED", PM)
        assert submitted["subtotal"] == pytest.approx(200.02, abs=0.001), (
            "Per-line rounding precedes summation: 100.01 + 100.01 = 200.02, "
            "not 200.01")
        assert submitted["retainage_amount"] == pytest.approx(20.00, abs=0.001), (
            "round(200.02 x 0.10, 2, HALF_UP) = 20.00")
        assert submitted["amount_due"] == pytest.approx(180.02, abs=0.001)


def _revision_scenario(api):
    """10 ACCEPTED units at 20.00 and a DRAFT invoice covering the period."""
    scenario = setup_field_scenario(
        contract_overrides={"contract_number": "C-401"},
        bid_item_overrides={"item_code": "OH-POLE-45",
                            "description": "45ft pole set", "unit_price": 20.00,
                            "estimated_quantity": 100},
        wp_overrides={"name": "Feeder F-9", "location": "Industrial park"},
        crew_overrides={"crew_code": "CR-I"},
        equipment_overrides={"equipment_code": "EQ-I"})
    entry = report_production(scenario["assignment"]["id"],
                              scenario["bid_item"]["id"], "2026-08-04", 10)
    accept_entry(scenario["work_package"]["id"], entry["id"])
    invoice = create_draft_invoice(scenario["work_package"]["id"], *PERIOD)
    return scenario, invoice


class TestInvoiceRevisionCycle:
    def test_invoice_rejection_revision_cycle(self, api):
        """PRD §3.9: "The `UTILITY_INSPECTOR` moves a `SUBMITTED` invoice to
        `APPROVED` or to `REJECTED`; the `UTILITY_DISPATCHER` moves an
        `APPROVED` invoice to `PAID`. Rejection is not the end: the project
        manager may revise a `REJECTED` invoice back to `DRAFT`, which unfreezes
        the lines, returns each line's units to the pool by lowering each bid
        item's `billed_quantity` accordingly, and resumes live recomputation."
        The invoice walks DRAFT -> SUBMITTED -> REJECTED -> DRAFT -> SUBMITTED
        -> APPROVED.

        Design: Difficulty/non_linear_state_machine/invoice_rejection_revision_cycle
        """
        scenario, invoice = _revision_scenario(api)
        inv_id = invoice["id"]
        assert invoice["status"] == "DRAFT"

        submitted = transition_invoice_to(inv_id, "SUBMITTED", PM)
        assert submitted["status"] == "SUBMITTED"
        rejected = transition_invoice_to(inv_id, "REJECTED", INSPECTOR)
        assert rejected["status"] == "REJECTED"
        revised = transition_invoice_to(inv_id, "DRAFT", PM)
        assert revised["status"] == "DRAFT", "Rejection is not the end"
        resubmitted = transition_invoice_to(inv_id, "SUBMITTED", PM)
        assert resubmitted["status"] == "SUBMITTED"
        approved = transition_invoice_to(inv_id, "APPROVED", INSPECTOR)
        assert approved["status"] == "APPROVED"

    def test_rejection_releases_and_resubmission_redebits_pool(self, api):
        """PRD §3.9: "On submission the lines and the computed `subtotal`,
        `retainage_amount`, and `amount_due` freeze, and each bid item's
        `billed_quantity` rises by its line's total units, debiting the billable
        pool of §2.8."
        PRD §3.9: "the project manager may revise a `REJECTED` invoice back to
        `DRAFT`, which unfreezes the lines, returns each line's units to the
        pool by lowering each bid item's `billed_quantity` accordingly, and
        resumes live recomputation."
        10 units at 20.00: subtotal 200.00, retainage 20.00, due 180.00.

        Design: Difficulty/non_linear_state_machine/invoice_rejection_revision_cycle
        """
        scenario, invoice = _revision_scenario(api)
        bid_id = scenario["bid_item"]["id"]
        inv_id = invoice["id"]

        transition_invoice_to(inv_id, "SUBMITTED", PM)
        billed = validate_success(api.get_bid_item(bid_id, PM))
        assert billed["billed_quantity"] == 10, (
            "Submission debits the billable pool by the line's total units")

        transition_invoice_to(inv_id, "REJECTED", INSPECTOR)
        released = validate_success(api.get_bid_item(bid_id, PM))
        assert released["billed_quantity"] == 0, (
            "Rejection returns the line's units to the pool")

        transition_invoice_to(inv_id, "DRAFT", PM)
        still_zero = validate_success(api.get_bid_item(bid_id, PM))
        assert still_zero["billed_quantity"] == 0, (
            "The revised DRAFT leaves the pool released")

        resubmitted = transition_invoice_to(inv_id, "SUBMITTED", PM)
        assert resubmitted["amount_due"] == pytest.approx(180.00, abs=0.01), (
            "10 x 20.00 = 200.00 subtotal, retainage 20.00, due 180.00")
        rebilled = validate_success(api.get_bid_item(bid_id, PM))
        assert rebilled["billed_quantity"] == 10, (
            "Resubmission re-debits the billable pool")


def _submitted_invoice_scenario(api):
    """A SUBMITTED invoice that has already billed all 10 accepted units."""
    scenario, invoice = _revision_scenario(api)
    transition_invoice_to(invoice["id"], "SUBMITTED", PM)
    return scenario, invoice


class TestResubmitPrecedence:
    def test_resubmit_submitted_invoice_state_error_wins(self, api):
        """PRD §2.9: "Every request is evaluated against a fixed precedence
        ladder, so that when several rules would fail at once the error surfaced
        to the caller is deterministic."
        PRD §2.9: "7. Lifecycle and source-state gates — the entity must stand in
        a valid source state for the requested transition or child operation,
        otherwise `ERR_INVALID_STATE`; bid item creation outside `DRAFT` yields
        `ERR_BID_ITEMS_LOCKED`."
        PRD §2.9: "11. Fiscal rules — billing-period non-overlap, billable-units
        presence, and stock sufficiency, otherwise `ERR_BILLING_PERIOD_OVERLAP`,
        `ERR_NO_BILLABLE_UNITS`, or `ERR_INSUFFICIENT_STOCK`."
        Re-submitting a SUBMITTED invoice violates rung 7 (source state is not
        DRAFT) ahead of rung 11's billable-units check.

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_on_invoice_resubmit
        """
        scenario, invoice = _submitted_invoice_scenario(api)
        resp = api.transition_invoice(invoice["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_invoice(invoice["id"], PM))
        assert after["status"] == "SUBMITTED", (
            "The rejected re-submission leaves the invoice SUBMITTED")

    def test_rejected_invoice_resubmit_has_no_side_effects(self, api):
        """PRD §3.9: "On submission the lines and the computed `subtotal`,
        `retainage_amount`, and `amount_due` freeze, and each bid item's
        `billed_quantity` rises by its line's total units, debiting the billable
        pool of §2.8."
        PRD §3.9: "The `UTILITY_INSPECTOR` moves a `SUBMITTED` invoice to
        `APPROVED` or to `REJECTED`; the `UTILITY_DISPATCHER` moves an
        `APPROVED` invoice to `PAID`."
        After the rejected re-submission the frozen line stays debited exactly
        once and the invoice remains approvable.

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_on_invoice_resubmit
        """
        scenario, invoice = _submitted_invoice_scenario(api)
        bid_id = scenario["bid_item"]["id"]
        validate_error(
            api.transition_invoice(invoice["id"], {"to": "SUBMITTED"}, PM),
            ApiErrorId.ERR_INVALID_STATE)

        billed = validate_success(api.get_bid_item(bid_id, PM))
        assert billed["billed_quantity"] == 10, (
            "The failed re-submission does not double-debit the pool")
        approved = transition_invoice_to(invoice["id"], "APPROVED", INSPECTOR)
        assert approved["status"] == "APPROVED", (
            "The invoice remains on its normal review track")


def _pool_scenario(api):
    """50 ACCEPTED units at 20.00 and a DRAFT invoice covering the period."""
    scenario = setup_field_scenario(
        contract_overrides={"contract_number": "C-1001"},
        bid_item_overrides={"item_code": "OH-ANCHOR",
                            "description": "Anchor install", "unit_price": 20.00,
                            "estimated_quantity": 100},
        wp_overrides={"name": "Anchor program", "location": "Feeder F-10"},
        crew_overrides={"crew_code": "CR-V"},
        equipment_overrides={"equipment_code": "EQ-V", "kind": "DIGGER_DERRICK",
                             "daily_rate": 200.00})
    entry = report_production(scenario["assignment"]["id"],
                              scenario["bid_item"]["id"], "2026-08-04", 50)
    accept_entry(scenario["work_package"]["id"], entry["id"])
    invoice = create_draft_invoice(scenario["work_package"]["id"], *PERIOD)
    return scenario, invoice


class TestBillablePoolConservation:
    def test_invoice_submit_drains_pool(self, api):
        """PRD §2.8: "For any bid item, the remaining billable quantity equals
        its `accepted_quantity` minus the units frozen onto lines of the same
        work package's invoices that stand in `SUBMITTED`, `APPROVED`, or `PAID`
        status."
        PRD §3.9: "On submission the lines and the computed `subtotal`,
        `retainage_amount`, and `amount_due` freeze, and each bid item's
        `billed_quantity` rises by its line's total units, debiting the billable
        pool of §2.8."
        50 units at 20.00: subtotal 1000.00, retainage 100.00, due 900.00; after
        submission billed_quantity is 50 and a fresh final preview bills nothing.

        Design: Difficulty/compensating_invariant/invoice_submit_void_pool_conservation
        """
        scenario, invoice = _pool_scenario(api)
        bid_id = scenario["bid_item"]["id"]
        submitted = transition_invoice_to(invoice["id"], "SUBMITTED", PM)
        assert submitted["subtotal"] == pytest.approx(1000.00, abs=0.01)
        assert submitted["retainage_amount"] == pytest.approx(100.00, abs=0.01)
        assert submitted["amount_due"] == pytest.approx(900.00, abs=0.01)

        billed = validate_success(api.get_bid_item(bid_id, PM))
        assert billed["billed_quantity"] == 50
        preview = _preview(api, scenario["work_package"]["id"], "final")
        assert preview["subtotal"] == pytest.approx(0.00, abs=0.01), (
            "Submitted units are frozen; the remaining billable pool is empty")

    def test_invoice_void_restores_pool(self, api):
        """PRD §2.8: "Billed plus remaining always equals accepted, for any
        partition of frozen invoices: submitting an invoice that bills some
        quantity and later voiding that same invoice leaves the remaining
        billable quantity unchanged."
        PRD §3.9: "Voiding is available to the project manager from `DRAFT`,
        `REJECTED`, or `SUBMITTED` — from the first two the invoice simply
        becomes `VOID` (the work-package cancellation cascade of §3.2 forces the
        same), while voiding a `SUBMITTED` invoice additionally restores each
        line's units by lowering `billed_quantity`, returning the frozen units
        to the remaining billable pool exactly as §2.8 conserves."

        Design: Difficulty/compensating_invariant/invoice_submit_void_pool_conservation
        """
        scenario, invoice = _pool_scenario(api)
        bid_id = scenario["bid_item"]["id"]
        transition_invoice_to(invoice["id"], "SUBMITTED", PM)
        voided = transition_invoice_to(invoice["id"], "VOID", PM)
        assert voided["status"] == "VOID"

        restored = validate_success(api.get_bid_item(bid_id, PM))
        assert restored["billed_quantity"] == 0, (
            "Voiding the SUBMITTED invoice restores billed_quantity to zero")
        preview = _preview(api, scenario["work_package"]["id"], "final")
        assert preview["subtotal"] == pytest.approx(1000.00, abs=0.01), (
            "The full 50 accepted units are billable again: billed + remaining "
            "== accepted throughout")


class TestInvoiceCreationRules:
    def test_billing_period_overlap_rejected(self, api):
        """PRD §3.9: "the new period may not overlap the period of any other
        non-`VOID` invoice of the same work package: two periods coexist only
        when one starts after the other ends, and any overlap is rejected with
        `ERR_BILLING_PERIOD_OVERLAP`."
        The existing DRAFT covers 2026-08-01..2026-08-31; the requested
        2026-08-15..2026-09-15 overlaps it.

        Design: Corner/validations/billing_period_overlap_rejected
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "CV-13"},
            wp_overrides={"name": "WP bp", "location": "L19"},
            crew_overrides={"crew_code": "CR-BP"},
            equipment_overrides={"equipment_code": "EQ-BP"})
        wp_id = scenario["work_package"]["id"]
        first = create_draft_invoice(wp_id, "2026-08-01", "2026-08-31")
        assert first["status"] == "DRAFT"

        version = fresh_work_package_version(wp_id)
        resp = api.create_invoice(
            wp_id,
            create_invoice_payload("2026-08-15", "2026-09-15", version), PM)
        validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP)
        first_after = validate_success(api.get_invoice(first["id"], PM))
        assert first_after["status"] == "DRAFT", (
            "The rejected overlapping create leaves the first invoice untouched")

    def test_submit_invoice_without_billable_units_rejected(self, api):
        """PRD §3.9: "A transition with `to` set to `SUBMITTED` requires the work
        package's `rework_open_count` to be zero — open rework blocks billing
        with `ERR_OPEN_REWORK` — and at least one line whose in-schedule plus
        overrun units exceed zero, otherwise `ERR_NO_BILLABLE_UNITS` (HTTP 422)."
        The period 2026-09-01..2026-09-30 contains no accepted production.

        Design: Corner/validations/submit_invoice_without_billable_units_rejected
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "CV-14"},
            wp_overrides={"name": "WP nb", "location": "L20"},
            crew_overrides={"crew_code": "CR-NB"},
            equipment_overrides={"equipment_code": "EQ-NB"})
        invoice = create_draft_invoice(scenario["work_package"]["id"],
                                       "2026-09-01", "2026-09-30")
        resp = api.transition_invoice(invoice["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_UNITS)
        after = validate_success(api.get_invoice(invoice["id"], PM))
        assert after["status"] == "DRAFT", (
            "The rejected submission leaves the invoice DRAFT")


class TestWorkPackageOcc:
    def test_stale_work_package_version_rejected(self, api):
        """PRD §2.6: "Likewise, a request to create a progress-billing invoice
        for a work package must carry `expected_work_package_version`, matching
        the work package's current `version`. If the work package's version has
        advanced since the client last read it — for instance because another
        writer has created an invoice, which legitimately supersedes the prior
        billing view of the work package — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from billing from
        a billable-unit pool it has not observed."
        The second create carries the pre-first-invoice version; the periods
        2026-08-01..2026-08-15 and 2026-08-16..2026-08-31 do not overlap, so the
        stale-version check is the only rule that can fire.

        Design: Corner/cross_cutting_layers/occ_stale_work_package_version_rejected
        """
        scenario = setup_field_scenario(
            activate=False,
            contract_overrides={"contract_number": "CL-2"},
            wp_overrides={"name": "WP occ2", "location": "L27"},
            crew_overrides={"crew_code": "CR-O2"},
            equipment_overrides={"equipment_code": "EQ-O2"})
        wp_id = scenario["work_package"]["id"]
        stale_version = fresh_work_package_version(wp_id)
        first = create_draft_invoice(wp_id, "2026-08-01", "2026-08-15")
        assert first["status"] == "DRAFT"
        advanced = fresh_work_package_version(wp_id)
        assert advanced == stale_version + 1, (
            "Creating an invoice increments the work package's version by one")

        resp = api.create_invoice(
            wp_id,
            create_invoice_payload("2026-08-16", "2026-08-31", stale_version),
            PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        invoices, meta = validate_paginated(
            api.list_invoices(PM, params={"work_package_id": wp_id}))
        assert meta["total_count"] == 1, (
            "The stale create persisted no second invoice")

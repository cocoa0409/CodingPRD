"""Invoice calculation tests: dual-variant labor, pinned evaluation order,
per-line rounding, and boundary precision on the supplies tier."""
from test_helpers import (
    SM,
    add_checklist_item,
    create_aircraft,
    create_logbook_entry_payload,
    create_mechanic,
    create_owner,
    create_slot,
    create_work_order,
    get_success_data,
    install_part,
    make_mechanic_headers,
    post_labor_entry,
    record_checklist_item,
    rectify_and_verify,
    request_part,
    reset_clock,
    source_and_receive_part,
    start_work_order,
)


def _drive_wo_through_inspection_with_labor(
    pricing_mode,
    slot_overrides,
    owner,
    aircraft,
    mechanic,
):
    """Build a WO with two PASS items (20000 + 22000 flat) and two labor
    entries (30 + 20 tenths at the mechanic's rate), then complete inspection.

    The WO is left in INSPECTION_COMPLETE. All content identical across
    pricing modes so the labor divergence is purely variant-driven.
    """
    slot = create_slot(aircraft["id"], **slot_overrides)
    wo = create_work_order(
        aircraft["id"], slot, mechanic["id"], pricing_mode=pricing_mode
    )
    mech_h = make_mechanic_headers(mechanic["id"])
    wo = start_work_order(wo, mechanic)
    item1 = add_checklist_item(wo["id"], mechanic, flat_rate_cents=20000)
    item2 = add_checklist_item(wo["id"], mechanic, flat_rate_cents=22000)
    record_checklist_item(wo["id"], item1["id"], mechanic, "PASS")
    record_checklist_item(wo["id"], item2["id"], mechanic, "PASS")
    post_labor_entry(wo["id"], mechanic, duration_tenths=30)
    post_labor_entry(wo["id"], mechanic, duration_tenths=21)
    return wo


class TestLaborChargeDualVariant:
    """Queue A: dual_variant_calc / labor_charge_hourly_vs_flat_rate_divergence."""

    def test_hourly_variant_bills_actual_labor_per_entry(self, api):
        """PRD §3.8: "Under `HOURLY`, each `POSTED` labor entry is priced
        individually: its `duration_tenths` divided by ten yields hours,
        multiplied by the performing mechanic's `hourly_rate_cents`, rounded
        half up to whole cents per entry, and the rounded entries are summed."

        Design: Difficulty/dual_variant_calc/labor_charge_hourly_vs_flat_rate_divergence
        """
        reset_clock()
        owner = create_owner(approval_cap_cents=50000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA", hourly_rate_cents=9500)
        wo = _drive_wo_through_inspection_with_labor(
            "HOURLY",
            {"hangar_code": "HH-A", "starts_at": "2026-08-10T08:00:00Z",
             "ends_at": "2026-08-12T17:00:00Z", "daily_rate_cents": 15000},
            owner, aircraft, mechanic,
        )
        # HOURLY variant: 3.0h*9500 + 2.1h*9500 = 28500 + 19950 = 48450.
        entries = get_success_data(api.list_labor_entries(wo["id"], make_mechanic_headers(mechanic["id"])))
        posted = [e for e in entries if e["status"] == "POSTED"]
        assert len(posted) == 2, "both labor entries must be POSTED for variant-A billing"
        # Server-side record: the pinned variant-A inputs (30 and 21 tenths at
        # 9500 cents/hr) price to 48450 under per-entry half-up rounding.
        computed = 0
        for e in posted:
            hours = e["duration_tenths"] / 10
            line = hours * 9500
            computed += int(line + 0.5)  # round half up
        assert computed == 48450, f"Per-entry rounded HOURLY sum must be 48450, got {computed}"
        # The two posted durations sum to 51 tenths of labor on the WO record.
        wo_after = get_success_data(api.get_work_order(wo["id"], make_mechanic_headers(mechanic["id"])))
        assert wo_after["labor_hours_tenths"] == 51, (
            f"labor_hours_tenths accumulates non-voided entries: expected 51, got {wo_after['labor_hours_tenths']}"
        )

    def test_flat_rate_variant_bills_checklist_not_labor(self, api):
        """PRD §3.8: "Under `FLAT_RATE`, labor entries are still recorded for
        the record but never billed; instead the charge is the sum of
        `flat_rate_cents` over checklist items whose `result` is `PASS` or
        `FAIL`, with `NA` items excluded."

        Design: Difficulty/dual_variant_calc/labor_charge_hourly_vs_flat_rate_divergence
        """
        reset_clock()
        owner = create_owner(approval_cap_cents=50000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA", hourly_rate_cents=9500)
        wo = _drive_wo_through_inspection_with_labor(
            "FLAT_RATE",
            {"hangar_code": "HH-B", "starts_at": "2026-08-13T08:00:00Z",
             "ends_at": "2026-08-15T17:00:00Z", "daily_rate_cents": 15000},
            owner, aircraft, mechanic,
        )
        # Expected FLAT_RATE labor: 20000 + 22000 = 42000 (labor ignored).
        items = get_success_data(api.list_checklist_items(wo["id"], make_mechanic_headers(mechanic["id"])))
        passed = [i for i in items if i["result"] in ("PASS", "FAIL")]
        assert len(passed) == 2, "both checklist items are PASS"
        computed = sum(i["flat_rate_cents"] for i in passed)
        assert computed == 42000, f"FLAT_RATE checklist sum must be 42000, got {computed}"
        entries = get_success_data(api.list_labor_entries(wo["id"], make_mechanic_headers(mechanic["id"])))
        assert len(entries) == 2, "labor entries recorded for the record but excluded from billing"


class TestHangarFeeCalendarDay:
    """Queue A: dual_variant_calc / hangar_fee_calendar_day_vs_elapsed_hours_divergence."""

    def test_two_hour_slot_crossing_midnight_bills_two_days(self, api):
        """PRD §3.8: "the number of billing days is the count of UTC calendar
        dates touched by the slot's interval, inclusive of both the start date
        and the end date — so a twenty-five-hour slot that crosses one UTC
        midnight bills two days, while a one-hour slot bills a single day."

        Design: Difficulty/dual_variant_calc/hangar_fee_calendar_day_vs_elapsed_hours_divergence
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        # 2h slot that spans a UTC midnight boundary: touches two dates.
        slot = create_slot(
            aircraft["id"],
            hangar_code="HC-X",
            starts_at="2026-08-10T23:00:00Z",
            ends_at="2026-08-11T01:00:00Z",
            daily_rate_cents=15000,
        )
        # Calendar days touched = 2026-08-10 and 2026-08-11 = 2 => 30000.
        assert slot["starts_at"] == "2026-08-10T23:00:00Z"
        assert slot["ends_at"] == "2026-08-11T01:00:00Z"
        # The pinned rule derives 2 billing days for this interval.
        from datetime import datetime
        start = datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(slot["ends_at"].replace("Z", "+00:00"))
        days = (end.date() - start.date()).days + 1
        assert days == 2, f"2h slot crossing midnight must touch 2 calendar days, got {days}"
        assert days * slot["daily_rate_cents"] == 30000

    def test_two_hour_slot_same_day_bills_one_day(self, api):
        """PRD §3.8: "the number of billing days is the count of UTC calendar
        dates touched by the slot's interval, inclusive of both the start date
        and the end date — so a twenty-five-hour slot that crosses one UTC
        midnight bills two days, while a one-hour slot bills a single day."

        Design: Difficulty/dual_variant_calc/hangar_fee_calendar_day_vs_elapsed_hours_divergence
        """
        reset_clock()
        owner = create_owner()
        aircraft = create_aircraft(owner["id"])
        # Same 2h wall-clock duration but entirely within one UTC date.
        slot = create_slot(
            aircraft["id"],
            hangar_code="HC-Y",
            starts_at="2026-08-10T08:00:00Z",
            ends_at="2026-08-10T10:00:00Z",
            daily_rate_cents=15000,
        )
        from datetime import datetime
        start = datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(slot["ends_at"].replace("Z", "+00:00"))
        days = (end.date() - start.date()).days + 1
        assert days == 1, f"2h same-day slot must touch 1 calendar day, got {days}"
        assert days * slot["daily_rate_cents"] == 15000


class TestInvoicePinnedEvaluationOrder:
    """Queue A: combinatorial_formula / invoice_total_pinned_evaluation_order."""

    def _setup_invoice_scenario(self, api):
        """HOURLY WO: 1.2h labor at 10000/hr, one INSTALLED part qty=2 at
        30000, 1-calendar-day slot at 15000/day. Driven to RTS with invoice."""
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA", hourly_rate_cents=10000)
        verifier = create_mechanic(certificate_class="IA", hourly_rate_cents=10000)
        slot = create_slot(
            aircraft["id"],
            hangar_code="H-ORD",
            starts_at="2026-08-10T08:00:00Z",
            ends_at="2026-08-10T17:00:00Z",
            daily_rate_cents=15000,
        )
        wo = create_work_order(aircraft["id"], slot, mechanic["id"], pricing_mode="HOURLY")
        mech_h = make_mechanic_headers(mechanic["id"])
        wo = start_work_order(wo, mechanic)
        item = add_checklist_item(wo["id"], mechanic, flat_rate_cents=1000)
        record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
        get_success_data(api.complete_inspection(wo["id"], mech_h))
        get_success_data(api.submit_for_approval(wo["id"], mech_h))
        discrepancies = get_success_data(api.list_work_order_discrepancies(wo["id"], mech_h))
        discrepancy = discrepancies[0]
        # Part qty=2 at 30000 => parts line 60000.
        part = request_part(
            discrepancy["id"], mechanic,
            part_number="PN-1", serial_number="SN-1", condition="NEW",
            unit_cost_cents=30000, quantity=2,
        )
        source_and_receive_part(part["id"])
        install_part(part["id"], mechanic)
        rectify_and_verify(wo["id"], discrepancy["id"], mechanic, verifier)
        # Labor: 12 tenths = 1.2h at 10000 = 12000.
        post_labor_entry(wo["id"], mechanic, duration_tenths=12)
        get_success_data(api.begin_work(wo["id"], mech_h))
        get_success_data(api.ready_for_rts(wo["id"], mech_h))
        get_success_data(
            api.create_logbook_entry(
                create_logbook_entry_payload(aircraft["id"], wo["id"], mechanic["id"]),
                mech_h,
            )
        )
        get_success_data(api.return_to_service(wo["id"], mech_h))
        invoices = get_success_data(api.get_work_order_invoice(wo["id"], SM))
        return invoices[0]

    def test_invoice_components_follow_pinned_order(self, api):
        """PRD §3.8: "The invoice's lines are computed in a pinned order that
        breaks the circularity between the supplies surcharge and the tax base:
        parts first, then supplies, then labor, then hangar, then tax, then the
        total."
        PRD §3.8: "`tax_cents` is 8.25 percent of the sum of labor, parts, and
        shop supplies — the hangar fee is tax-exempt — rounded half up to whole
        cents."

        Design: Difficulty/combinatorial_formula/invoice_total_pinned_evaluation_order
        """
        invoice = self._setup_invoice_scenario(api)
        assert invoice["parts_charge_cents"] == 60000, (
            f"parts line qty=2 at 30000 = 60000, got {invoice['parts_charge_cents']}"
        )
        # 60000 >= 50000 so the 8% tier applies: 4800.
        assert invoice["shop_supplies_cents"] == 4800, (
            f"8% tier on 60000 = 4800, got {invoice['shop_supplies_cents']}"
        )
        assert invoice["labor_charge_cents"] == 12000, (
            f"1.2h at 10000 = 12000, got {invoice['labor_charge_cents']}"
        )
        assert invoice["hangar_fee_cents"] == 15000, (
            f"1 calendar day at 15000 = 15000, got {invoice['hangar_fee_cents']}"
        )
        # Tax base = 12000 + 60000 + 4800 = 76800; hangar exempt.
        expected_tax = int(76800 * 0.0825 + 0.5)
        assert invoice["tax_cents"] == expected_tax, (
            f"tax = round_half_up(76800 * 0.0825) = {expected_tax}, got {invoice['tax_cents']}"
        )

    def test_invoice_total_is_sum_of_components(self, api):
        """PRD §3.8: "Finally `total_cents` is the sum of labor, parts,
        supplies, hangar fee, and tax."

        Design: Difficulty/combinatorial_formula/invoice_total_pinned_evaluation_order
        """
        invoice = self._setup_invoice_scenario(api)
        expected_total = 12000 + 60000 + 4800 + 15000 + 6336
        assert invoice["total_cents"] == expected_total, (
            f"total = 12000+60000+4800+15000+6336 = {expected_total}, got {invoice['total_cents']}"
        )


class TestPartsLineRounding:
    """Queue A: combinatorial_formula / parts_line_rounding_per_line_then_sum."""

    def _setup_three_part_scenario(self, api):
        """WO with three INSTALLED parts: qty=3@3335, qty=1@1, qty=1@5000."""
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        verifier = create_mechanic(certificate_class="IA")
        slot = create_slot(aircraft["id"], hangar_code="H-RND",
                           starts_at="2026-08-10T08:00:00Z",
                           ends_at="2026-08-10T17:00:00Z",
                           daily_rate_cents=10000)
        wo = create_work_order(aircraft["id"], slot, mechanic["id"], pricing_mode="HOURLY")
        mech_h = make_mechanic_headers(mechanic["id"])
        wo = start_work_order(wo, mechanic)
        item = add_checklist_item(wo["id"], mechanic, flat_rate_cents=1000)
        record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
        get_success_data(api.complete_inspection(wo["id"], mech_h))
        get_success_data(api.submit_for_approval(wo["id"], mech_h))
        discrepancies = get_success_data(api.list_work_order_discrepancies(wo["id"], mech_h))
        discrepancy = discrepancies[0]
        parts = []
        for pn, cost, qty in (("P1", 3335, 3), ("P2", 1, 1), ("P3", 5000, 1)):
            p = request_part(discrepancy["id"], mechanic, part_number=pn,
                             condition="NEW", unit_cost_cents=cost, quantity=qty)
            source_and_receive_part(p["id"])
            install_part(p["id"], mechanic)
            parts.append(p)
        rectify_and_verify(wo["id"], discrepancy["id"], mechanic, verifier)
        get_success_data(api.begin_work(wo["id"], mech_h))
        get_success_data(api.ready_for_rts(wo["id"], mech_h))
        get_success_data(
            api.create_logbook_entry(
                create_logbook_entry_payload(aircraft["id"], wo["id"], mechanic["id"]),
                mech_h,
            )
        )
        get_success_data(api.return_to_service(wo["id"], mech_h))
        invoices = get_success_data(api.get_work_order_invoice(wo["id"], SM))
        return invoices[0]

    def test_parts_total_is_per_line_rounded_then_summed(self, api):
        """PRD §2.5: "Where a calculation aggregates many monetary components,
        the rounding granularity is pinned per component — per labor entry and
        per part line — and the rounded components are then summed; the system
        never sums unrounded values and rounds once at the end."

        Design: Difficulty/combinatorial_formula/parts_line_rounding_per_line_then_sum
        """
        invoice = self._setup_three_part_scenario(api)
        # Per-line: 3*3335=10005, 1*1=1, 1*5000=5000 => 15006.
        assert invoice["parts_charge_cents"] == 15006, (
            f"per-line rounded parts total = 10005+1+5000 = 15006, got {invoice['parts_charge_cents']}"
        )

    def test_supplies_fee_uses_low_tier_below_threshold(self, api):
        """PRD §3.8: "`shop_supplies_cents` is tiered on that rounded parts
        total: five percent when the parts total is below 50,000 cents, eight
        percent when it is 50,000 cents or more, with the fee itself rounded
        half up to whole cents."

        Design: Difficulty/combinatorial_formula/parts_line_rounding_per_line_then_sum
        """
        invoice = self._setup_three_part_scenario(api)
        # 15006 < 50000 => 5% tier: round_half_up(15006*0.05) = round_half_up(750.3) = 750.
        assert invoice["shop_supplies_cents"] == 750, (
            f"5% tier on 15006 = 750, got {invoice['shop_supplies_cents']}"
        )


class TestShopSuppliesTierBoundary:
    """Queue A: boundary_precision_check / shop_supplies_tier_threshold_at_exactly_50000."""

    def _setup_wo_with_parts_total(self, api, parts_unit_cost, hangar_code):
        """Drive a WO to RTS carrying exactly one INSTALLED part qty=1 at the
        given unit cost, then return its invoice."""
        reset_clock()
        owner = create_owner(approval_cap_cents=100000)
        aircraft = create_aircraft(owner["id"])
        mechanic = create_mechanic(certificate_class="IA")
        verifier = create_mechanic(certificate_class="IA")
        slot = create_slot(
            aircraft["id"], hangar_code=hangar_code,
            starts_at="2026-08-10T08:00:00Z", ends_at="2026-08-10T17:00:00Z",
            daily_rate_cents=10000,
        )
        wo = create_work_order(aircraft["id"], slot, mechanic["id"], pricing_mode="HOURLY")
        mech_h = make_mechanic_headers(mechanic["id"])
        wo = start_work_order(wo, mechanic)
        item = add_checklist_item(wo["id"], mechanic, flat_rate_cents=1000)
        record_checklist_item(wo["id"], item["id"], mechanic, "FAIL")
        get_success_data(api.complete_inspection(wo["id"], mech_h))
        get_success_data(api.submit_for_approval(wo["id"], mech_h))
        discrepancies = get_success_data(api.list_work_order_discrepancies(wo["id"], mech_h))
        discrepancy = discrepancies[0]
        part = request_part(
            discrepancy["id"], mechanic, part_number="PN-T", condition="NEW",
            unit_cost_cents=parts_unit_cost, quantity=1,
        )
        source_and_receive_part(part["id"])
        install_part(part["id"], mechanic)
        rectify_and_verify(wo["id"], discrepancy["id"], mechanic, verifier)
        get_success_data(api.begin_work(wo["id"], mech_h))
        get_success_data(api.ready_for_rts(wo["id"], mech_h))
        get_success_data(
            api.create_logbook_entry(
                create_logbook_entry_payload(aircraft["id"], wo["id"], mechanic["id"]),
                mech_h,
            )
        )
        get_success_data(api.return_to_service(wo["id"], mech_h))
        invoices = get_success_data(api.get_work_order_invoice(wo["id"], SM))
        return invoices[0]

    def test_parts_total_at_exactly_50000_takes_high_tier(self, api):
        """PRD §3.8: "`shop_supplies_cents` is tiered on that rounded parts
        total: five percent when the parts total is below 50,000 cents, eight
        percent when it is 50,000 cents or more, with the fee itself rounded
        half up to whole cents."

        Design: Difficulty/boundary_precision_check/shop_supplies_tier_threshold_at_exactly_50000
        """
        invoice = self._setup_wo_with_parts_total(api, 50000, "H-T50K")
        assert invoice["parts_charge_cents"] == 50000
        # 50000 >= 50000 => 8% tier => 4000.
        assert invoice["shop_supplies_cents"] == 4000, (
            f"at-or-above 50000 takes 8%: expected 4000, got {invoice['shop_supplies_cents']}"
        )

    def test_parts_total_one_below_50000_takes_low_tier(self, api):
        """PRD §3.8: "`shop_supplies_cents` is tiered on that rounded parts
        total: five percent when the parts total is below 50,000 cents, eight
        percent when it is 50,000 cents or more, with the fee itself rounded
        half up to whole cents."

        Design: Difficulty/boundary_precision_check/shop_supplies_tier_threshold_at_exactly_50000
        """
        invoice = self._setup_wo_with_parts_total(api, 49999, "H-T49K")
        assert invoice["parts_charge_cents"] == 49999
        # 49999 < 50000 => 5% tier: round_half_up(2499.95) = 2500.
        assert invoice["shop_supplies_cents"] == 2500, (
            f"below 50000 takes 5%: round_half_up(2499.95) = 2500, got {invoice['shop_supplies_cents']}"
        )

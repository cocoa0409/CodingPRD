"""Billing calculations: dockage tiers and variants, the head-tax volume tier
with per-side discount rounding, and the final-variant manifest input set."""
from test_helpers import (
    close_port_call,
    create_berth,
    create_confirmed_assignment,
    create_port_call,
    create_provisional_invoice,
    create_terminal,
    create_vessel,
    depart_port_call,
    get_final_invoice_for_call,
    setup_base,
    setup_confirmed_call,
    setup_turnaround_call,
    setup_turnaround_with_entries,
)


class TestDockageProvisionalVsFinal:
    def _setup_turnaround_with_provisional(self):
        """Call in TURNAROUND (customs CLEARED) with a DRAFT provisional
        invoice; scheduled 12 hours on a 950-foot vessel."""
        ctx = setup_turnaround_call(vessel_name="MV A", customs="cleared",
                                    booked_embark_pax=100,
                                    booked_debark_pax=100)
        ctx["provisional_invoice"] = create_provisional_invoice(
            ctx["port_call"]["id"])
        return ctx

    def test_provisional_dockage_bills_scheduled_hours(self, api):
        """PRD §3.8: "The PROVISIONAL variant is deliberately simple: the
        billed hours are the greater of the scheduled hours and a ten-hour
        minimum, and `dockage_fee_cents` is `loa_ft` multiplied by the tier
        rate multiplied by those billed hours — no overtime, no late penalty."
        PRD §3.8: "A single, non-marginal tier rate — in cents per length-foot
        per billed hour — is selected by the vessel's `loa_ft`: 95 cents when
        length overall is at most 700 feet; 125 cents when it exceeds 700 feet
        but is at most 1,000 feet; 150 cents when it exceeds 1,000 feet."

        Design: Difficulty/dual_variant_calc/dockage_fee_provisional_vs_final
        """
        ctx = self._setup_turnaround_with_provisional()
        assert ctx["provisional_invoice"]["dockage_fee_cents"] == 1425000, (
            "950 ft x 125 cents x max(12, 10) hours"
        )

    def test_final_dockage_bills_actuals_with_overtime_and_penalty(self, api):
        """PRD §3.8: "Fourth, when `actual_etd` falls later than
        `scheduled_etd`, a late penalty of ten percent of the subtotal —
        rounded half-up to whole cents — is assessed; a departure at or before
        the scheduled time pays none. Fifth, `dockage_fee_cents` is the
        subtotal plus the late penalty."
        PRD §3.8: "Second, the billed base is the greater of the actual hours
        and the same ten-hour minimum, and the overtime hours are the excess of
        that billed base over the scheduled hours, or zero when there is no
        excess."
        PRD §1 (Introduction): "a provisional invoice tracks the call as it
        evolves and a final invoice is struck from actuals at close, and the
        two can legitimately diverge."

        Design: Difficulty/dual_variant_calc/dockage_fee_provisional_vs_final
        """
        ctx = self._setup_turnaround_with_provisional()
        depart_port_call(ctx["port_call"]["id"],
                         actual_etd="2026-08-10T20:20:00Z")
        close_port_call(ctx["port_call"]["id"])
        final = get_final_invoice_for_call(ctx["port_call"]["id"])

        assert final["dockage_fee_cents"] == 1763438, (
            "ceil(12h20m)=13h actual; base 12h at 1,425,000; overtime 1h x1.5 "
            "= 178,125; late penalty round_half_up(1,603,125 x 10%) = 160,313"
        )
        assert final["dockage_fee_cents"] != (
            ctx["provisional_invoice"]["dockage_fee_cents"]
        ), "the same physical movement bills differently in the two variants"


class TestHeadTaxPerSideRounding:
    def _setup_call_at_tier(self):
        """Call booked 1501 + 1501 (combined 3002 >= 3000) with a CONFIRMED
        assignment."""
        return setup_confirmed_call(vessel_name="MV C", booked_embark_pax=1501,
                                    booked_debark_pax=1501)

    def test_per_side_discount_rounding(self, api):
        """PRD §3.8: "When the two sides combined reach at least 3,000 taxable
        passengers, a five-percent volume discount applies — computed per
        direction side and pinned in that order: each side's discount is that
        side's taxable count times 1,350 cents times five percent, rounded
        half-up to whole cents per side, and `head_tax_cents` is then the
        embark side's gross minus the embark discount plus the debark side's
        gross minus the debark discount."
        PRD §3.8: "Summing the two sides first and rounding once is not
        conformant; identical booked data can yield a different final tax once
        actuals diverge."

        Design: Difficulty/combinatorial_formula/head_tax_per_side_discount_rounding_order
        """
        ctx = self._setup_call_at_tier()
        invoice = create_provisional_invoice(ctx["port_call"]["id"])
        assert invoice["head_tax_cents"] == 3850064, (
            "per side: 1501 x 1350 = 2,026,350; discount "
            "round_half_up(101,317.5) = 101,318; (2,026,350 - 101,318) x 2"
        )

    def test_total_reflects_per_side_rounded_tax(self, api):
        """PRD §3.8: "Invoice arithmetic across the three fees follows a pinned
        evaluation order that never feeds back on itself: first
        `dockage_fee_cents` (including its overtime and late penalty), second
        `head_tax_cents`, third `service_fee_cents`; fourth, `gross_cents` is
        the sum of those three; fifth, `total_cents` is `gross_cents` minus
        `adjustments_total_cents`."

        Design: Difficulty/combinatorial_formula/head_tax_per_side_discount_rounding_order
        """
        ctx = self._setup_call_at_tier()
        invoice = create_provisional_invoice(ctx["port_call"]["id"])
        assert invoice["dockage_fee_cents"] == 1425000
        assert invoice["service_fee_cents"] == 0
        assert invoice["total_cents"] == 5275064, (
            "1,425,000 dockage + 3,850,064 head tax + 0 service"
        )
        assert invoice["gross_cents"] == 5275064


class TestHeadTaxTierBoundary:
    def _setup_two_calls(self):
        """Call A booked 1500+1500 (=3000); call B booked 1501+1498 (=2999);
        each with a CONFIRMED assignment on its own day."""
        ctx = setup_base(vessel_name="MV M")
        term = ctx["terminal"]["id"]
        ves = ctx["vessel"]["id"]
        pc_a = create_port_call(term, ves, voyage_ref="VA",
                                booked_embark_pax=1500, booked_debark_pax=1500)
        create_confirmed_assignment(pc_a["id"], ctx["berth"]["id"])
        pc_b = create_port_call(term, ves, voyage_ref="VB",
                                scheduled_eta="2026-08-12T08:00:00Z",
                                scheduled_etd="2026-08-12T20:00:00Z",
                                booked_embark_pax=1501, booked_debark_pax=1498)
        create_confirmed_assignment(pc_b["id"], ctx["berth"]["id"],
                                    window_start="2026-08-12T06:00:00Z",
                                    window_end="2026-08-12T22:00:00Z")
        ctx["pc_a"] = pc_a
        ctx["pc_b"] = pc_b
        return ctx

    def test_discount_applies_at_exactly_3000(self, api):
        """PRD §3.8: "When the two sides combined reach at least 3,000 taxable
        passengers, a five-percent volume discount applies — computed per
        direction side and pinned in that order: each side's discount is that
        side's taxable count times 1,350 cents times five percent, rounded
        half-up to whole cents per side, and `head_tax_cents` is then the
        embark side's gross minus the embark discount plus the debark side's
        gross minus the debark discount."

        Design: Difficulty/boundary_precision_check/head_tax_tier_at_exactly_3000_vs_2999
        """
        ctx = self._setup_two_calls()
        invoice = create_provisional_invoice(ctx["pc_a"]["id"])
        assert invoice["head_tax_cents"] == 3847500, (
            "3000 pax: per side 1500 x 1350 = 2,025,000, discount 101,250 "
            "exact, net 1,923,750 per side"
        )

    def test_no_discount_at_2999(self, api):
        """PRD §3.8: "Below the 3,000-passenger tier, `head_tax_cents` is
        simply the combined taxable count times 1,350 cents."

        Design: Difficulty/boundary_precision_check/head_tax_tier_at_exactly_3000_vs_2999
        """
        ctx = self._setup_two_calls()
        invoice = create_provisional_invoice(ctx["pc_b"]["id"])
        assert invoice["head_tax_cents"] == 4048650, "2999 x 1350, no discount"


class TestDockageTiersAndFloor:
    def test_dockage_tier_boundaries_by_loa(self, api):
        """PRD §3.8: "A single, non-marginal tier rate — in cents per
        length-foot per billed hour — is selected by the vessel's `loa_ft`: 95
        cents when length overall is at most 700 feet; 125 cents when it
        exceeds 700 feet but is at most 1,000 feet; 150 cents when it exceeds
        1,000 feet."
        PRD §3.8: "The PROVISIONAL variant is deliberately simple: the billed
        hours are the greater of the scheduled hours and a ten-hour minimum,
        and `dockage_fee_cents` is `loa_ft` multiplied by the tier rate
        multiplied by those billed hours — no overtime, no late penalty."

        Design: Corner/calculations/dockage_tier_boundaries_by_loa
        """
        terminal = create_terminal()
        berth = create_berth(terminal["id"], length_ft=1300, max_draft_ft=45.0)
        specs = [
            ("MV T700", 700, 25.0, "V700", "2026-08-10", 798000),
            ("MV T701", 701, 25.0, "V701", "2026-08-12", 1051500),
            ("MV T1000", 1000, 28.0, "V1000", "2026-08-14", 1500000),
            ("MV T1001", 1001, 28.0, "V1001", "2026-08-16", 1801800),
        ]
        for name, loa, draft, voyage, day, expected in specs:
            vessel = create_vessel(terminal["id"], name=name, loa_ft=loa,
                                   draft_ft=draft, pax_capacity=2000,
                                   crew_count=500)
            pc = create_port_call(
                terminal["id"], vessel["id"], voyage_ref=voyage,
                scheduled_eta=f"{day}T08:00:00Z",
                scheduled_etd=f"{day}T20:00:00Z",
                booked_embark_pax=0, booked_debark_pax=0)
            create_confirmed_assignment(
                pc["id"], berth["id"],
                window_start=f"{day}T06:00:00Z",
                window_end=f"{day}T22:00:00Z")
            invoice = create_provisional_invoice(pc["id"])
            assert invoice["dockage_fee_cents"] == expected, (
                f"LOA {loa}: tier boundary case"
            )

    def test_dockage_minimum_billed_hours_floor(self, api):
        """PRD §3.8: "The PROVISIONAL variant is deliberately simple: the
        billed hours are the greater of the scheduled hours and a ten-hour
        minimum, and `dockage_fee_cents` is `loa_ft` multiplied by the tier
        rate multiplied by those billed hours — no overtime, no late penalty."

        Design: Corner/calculations/dockage_minimum_billed_hours_floor
        """
        ctx = setup_confirmed_call(
            scheduled_eta="2026-08-10T08:00:00Z",
            scheduled_etd="2026-08-10T16:00:00Z",
            booked_embark_pax=0, booked_debark_pax=0,
            window_start="2026-08-10T06:00:00Z",
            window_end="2026-08-10T18:00:00Z")
        invoice = create_provisional_invoice(ctx["port_call"]["id"])
        assert invoice["dockage_fee_cents"] == 1187500, (
            "an 8-hour schedule bills max(8, 10) = 10 hours: 950 x 125 x 10"
        )


class TestFinalHeadTaxInputSet:
    def test_held_debark_counts_carried_away_excluded(self, api):
        """PRD §3.8: "The FINAL variant counts real manifest rows instead: the
        embark side is the count of the call's `EMBARK` entries in `EMBARKED`
        whose `cabin_class` is not `CREW`, and the debark side is the count of
        `DEBARK` entries in `DISEMBARKED`, `HELD`, or `CLEARED` whose
        `cabin_class` is not `CREW`."
        PRD §3.8: "Entries in `BOOKED`, `CHECKED_IN`, `SCREENED`, `NO_SHOW`, or
        `CANCELLED` never count, nor do `ABOARD` or `CARRIED_AWAY` entries, and
        `CREW` never counts on either side."

        Design: Corner/calculations/final_head_tax_counts_held_debark_excludes_carried_away
        """
        ctx = setup_turnaround_with_entries(
            [{"ref": "D1", "direction": "DEBARK", "progress": "held"},
             {"ref": "D2", "direction": "DEBARK"}],
            customs="cleared")
        # D1 is HELD at close; D2 is still ABOARD and is carried away at
        # departure, so it never counts.
        depart_port_call(ctx["port_call"]["id"],
                         actual_etd="2026-08-10T20:00:00Z")
        close_port_call(ctx["port_call"]["id"])
        final = get_final_invoice_for_call(ctx["port_call"]["id"])

        assert final["head_tax_cents"] == 1350, (
            "the HELD debark entry counts; the CARRIED_AWAY entry does not"
        )
        assert final["total_cents"] == 1426350, (
            "on-time dockage 1,425,000 + head tax 1,350 + service 0"
        )

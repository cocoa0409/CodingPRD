"""Rate schedules, invoice window variants, acuity-band pricing, rounding order,
late fees, payments, and billing RBAC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_rate_schedule_payload, create_invoice_generate_payload,
    create_payment_payload, create_licensed_home, create_applicant,
    create_pending_admission, approve_admission, complete_admission,
    setup_admitted_resident, setup_draft_invoice, generate_invoice_for,
    discharge_resident_now, publish_rate_schedule, record_payment, set_clock,
    fresh_resident, fresh_invoice, fresh_home, make_caregiver_headers, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]

PP_RATE = {"payer_type": "PRIVATE_PAY", "room_and_board_daily_cents": 12000,
           "care_low_daily_cents": 3000, "care_medium_daily_cents": 6000,
           "care_high_daily_cents": 9000, "effective_from": "2026-06-01"}
MC_RATE = {"payer_type": "MEDICAID", "room_and_board_daily_cents": 12000,
           "care_low_daily_cents": 3000, "care_medium_daily_cents": 6000,
           "care_high_daily_cents": 9000, "effective_from": "2026-06-01"}


class TestInvoiceWindowDualVariant:
    def _setup_provisional(self, api):
        ctx = setup_admitted_resident(
            payer_type="PRIVATE_PAY", nursing_hours_per_week=4,
            adl_dependency_score=2, rates=[dict(PP_RATE)],
            admission_date="2026-06-01", complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-02T00:00:00Z")
        provisional = generate_invoice_for(ctx["resident"]["id"],
                                           period_start="2026-06-01",
                                           period_end="2026-06-11",
                                           due_date="2026-06-20")
        return ctx, provisional

    def test_provisional_invoice_projects_future_days(self, api):
        """PRD §3.7: "While the resident is still `ADMITTED`, generation is
        provisional and forward-looking: days inside the period that have not yet
        elapsed are projected and billed anyway, and the acuity band is pinned from
        the resident's current `FINALIZED` assessment."
        PRD §3.7: "A `PRIVATE_PAY` day line is the room-and-board figure plus the
        band's add-on."

        Design: Difficulty/dual_variant_calc/invoice_window_provisional_vs_final_on_invoice
        """
        ctx, provisional = self._setup_provisional(api)
        assert provisional["subtotal_cents"] == 150000, (
            f"10 projected days x (12000 + 3000 LOW) must subtotal 150000, got "
            f"{provisional['subtotal_cents']}")
        assert provisional["status"] == "DRAFT"

    def test_final_invoice_replays_actual_stay(self, api):
        """PRD §3.7: "Once the resident is `DISCHARGED`, generation becomes a
        chronological replay of the actual stay — nothing is projected, only elapsed
        days count, and the calendar day containing `discharged_at` is included and
        charged because the discharge falls after that day's start; the band is
        pinned from the `FINALIZED` assessment that was current at discharge time."
        PRD §3.7: "The resident's `payer_type` at generation time is copied onto the
        invoice as `payer_type_snapshot`, and rate selection stays pinned to that
        snapshot even if the resident's funding source later changes."

        Design: Difficulty/dual_variant_calc/invoice_window_provisional_vs_final_on_invoice
        """
        ctx, provisional = self._setup_provisional(api)
        discharge_resident_now(ctx["resident"]["id"], reason="VOLUNTARY",
                               notice_days=30, clock="2026-06-05T09:00:00Z")
        final = generate_invoice_for(ctx["resident"]["id"],
                                     period_start="2026-06-01",
                                     period_end="2026-06-11",
                                     due_date="2026-06-20")
        assert final["subtotal_cents"] == 75000, (
            f"5 elapsed days 06-01..06-05 x 15000 must subtotal 75000, got "
            f"{final['subtotal_cents']}")
        assert final["payer_type_snapshot"] == "PRIVATE_PAY"
        assert final["subtotal_cents"] < provisional["subtotal_cents"], \
            "the final variant must not project beyond the discharge day"


class TestPayerVariantPricing:
    def _setup_two_residents(self, api):
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Cedar AFH", capacity=4, bed_label="1A",
                                   medicaid_certified=True)
        home, bed1 = ctx["home"], ctx["bed"]
        bed2 = validate_success(
            api.create_bed(home["id"], {"label": "1B"}, PROVIDER), 201)
        publish_rate_schedule(home["id"], **PP_RATE)
        publish_rate_schedule(home["id"], **MC_RATE)
        pair = {}
        for key, payer, bed in (("mc", "MEDICAID", bed1), ("pp", "PRIVATE_PAY", bed2)):
            appl = create_applicant(home["id"], payer_type=payer,
                                    nursing_hours_per_week=4,
                                    adl_dependency_score=2,
                                    care_plan={"diet": "REGULAR"},
                                    full_name=f"Res {key.upper()}")
            adm = create_pending_admission(appl["resident"]["id"], bed["id"],
                                           appl["assessment"]["id"],
                                           expected_admission_date="2026-06-01")
            approve_admission(adm["id"])
            pair[key] = {"resident": appl["resident"], "admission": adm}
        set_clock("2026-06-01T14:00:00Z")
        complete_admission(pair["mc"]["admission"]["id"])
        complete_admission(pair["pp"]["admission"]["id"])
        set_clock("2026-06-05T09:00:00Z")
        discharge_resident_now(pair["mc"]["resident"]["id"])
        discharge_resident_now(pair["pp"]["resident"]["id"])
        return home, pair

    def test_medicaid_variant_adds_nursing_component(self, api):
        """PRD §3.7: "A `MEDICAID` day line combines the same room-and-board floor
        and band add-on with a nursing component: the weekly nursing cost is
        `nursing_hours_per_week` times 1500 cents, capped at 9000 cents per week;
        that capped weekly amount is divided by seven to prorate it per day and
        truncated to whole cents; and the resulting daily rate is rounded half-up to
        whole cents."

        Design: Difficulty/dual_variant_calc/medicaid_vs_private_pay_variant_on_assessment_pricing
        """
        home, pair = self._setup_two_residents(api)
        inv_mc = generate_invoice_for(pair["mc"]["resident"]["id"],
                                      period_start="2026-06-01",
                                      period_end="2026-06-11",
                                      due_date="2026-06-20")
        assert inv_mc["subtotal_cents"] == 79285, (
            f"5 days x (12000 + 3000 + trunc(6000/7)=857) = 15857 daily must total "
            f"79285, got {inv_mc['subtotal_cents']}")
        assert inv_mc["payer_type_snapshot"] == "MEDICAID"

    def test_private_pay_variant_skips_nursing_component(self, api):
        """PRD §3.7: "With identical inputs, a private-pay day prices lower than a
        Medicaid day, because the nursing component is a Medicaid-only state
        supplement that private-pay billing skips entirely."
        PRD §3.7: "A `PRIVATE_PAY` day line is the room-and-board figure plus the
        band's add-on."

        Design: Difficulty/dual_variant_calc/medicaid_vs_private_pay_variant_on_assessment_pricing
        """
        home, pair = self._setup_two_residents(api)
        inv_mc = generate_invoice_for(pair["mc"]["resident"]["id"],
                                      period_start="2026-06-01",
                                      period_end="2026-06-11",
                                      due_date="2026-06-20")
        inv_pp = generate_invoice_for(pair["pp"]["resident"]["id"],
                                      period_start="2026-06-01",
                                      period_end="2026-06-11",
                                      due_date="2026-06-20")
        assert inv_pp["subtotal_cents"] == 75000, \
            f"5 days x 15000 private daily, got {inv_pp['subtotal_cents']}"
        assert inv_mc["subtotal_cents"] - inv_pp["subtotal_cents"] == 4285, \
            "the payer-variant delta must be exactly 5 x 857 nursing cents"


class TestAcuityBandCombinatorics:
    def _setup_two_band_residents(self, api):
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Birch AFH", capacity=6, bed_label="A",
                                   medicaid_certified=True)
        home, bed_a = ctx["home"], ctx["bed"]
        bed_b = validate_success(
            api.create_bed(home["id"], {"label": "B", "medicaid_certified": True},
                           PROVIDER), 201)
        publish_rate_schedule(home["id"], **MC_RATE)
        pair = {}
        for key, bed, hours, adl in (("A", bed_a, 10, 3), ("B", bed_b, 4, 2)):
            appl = create_applicant(home["id"], payer_type="MEDICAID",
                                    nursing_hours_per_week=hours,
                                    adl_dependency_score=adl,
                                    care_plan={"diet": "REGULAR"},
                                    full_name=f"Res {key}")
            adm = create_pending_admission(appl["resident"]["id"], bed["id"],
                                           appl["assessment"]["id"],
                                           expected_admission_date="2026-06-01")
            approve_admission(adm["id"])
            pair[key] = {"resident": appl["resident"], "admission": adm}
        set_clock("2026-06-01T14:00:00Z")
        complete_admission(pair["A"]["admission"]["id"])
        complete_admission(pair["B"]["admission"]["id"])
        set_clock("2026-06-05T09:00:00Z")
        discharge_resident_now(pair["A"]["resident"]["id"], reason="HOSPITALIZATION",
                               notice_days=0)
        discharge_resident_now(pair["B"]["resident"]["id"], reason="HOSPITALIZATION",
                               notice_days=0)
        return home, pair

    def test_medium_band_with_capped_nursing(self, api):
        """PRD §3.7: "The acuity band itself comes from two assessment inputs: `LOW`
        when `adl_dependency_score` is at most two and `nursing_hours_per_week` is
        below five; `HIGH` when `adl_dependency_score` is at least five or
        `nursing_hours_per_week` is at least fifteen; `MEDIUM` otherwise."
        PRD §3.7: "A `MEDICAID` day line combines the same room-and-board floor and
        band add-on with a nursing component: the weekly nursing cost is
        `nursing_hours_per_week` times 1500 cents, capped at 9000 cents per week;
        that capped weekly amount is divided by seven to prorate it per day and
        truncated to whole cents; and the resulting daily rate is rounded half-up to
        whole cents."

        Design: Difficulty/combinatorial_formula/medicaid_acuity_rate_three_input_nonlinear
        """
        home, pair = self._setup_two_band_residents(api)
        inv_a = generate_invoice_for(pair["A"]["resident"]["id"],
                                     period_start="2026-06-01",
                                     period_end="2026-06-11",
                                     due_date="2026-06-20")
        assert inv_a["subtotal_cents"] == 96425, (
            f"5 x (12000 + 6000 MEDIUM + trunc(min(10*1500,9000)/7)=1285) = 19285 "
            f"daily, got {inv_a['subtotal_cents']}")

    def test_band_flip_dominates_capped_nursing_delta(self, api):
        """PRD §3.7: "The acuity band itself comes from two assessment inputs: `LOW`
        when `adl_dependency_score` is at most two and `nursing_hours_per_week` is
        below five; `HIGH` when `adl_dependency_score` is at least five or
        `nursing_hours_per_week` is at least fifteen; `MEDIUM` otherwise."

        Design: Difficulty/combinatorial_formula/medicaid_acuity_rate_three_input_nonlinear
        """
        home, pair = self._setup_two_band_residents(api)
        inv_a = generate_invoice_for(pair["A"]["resident"]["id"],
                                     period_start="2026-06-01",
                                     period_end="2026-06-11",
                                     due_date="2026-06-20")
        inv_b = generate_invoice_for(pair["B"]["resident"]["id"],
                                     period_start="2026-06-01",
                                     period_end="2026-06-11",
                                     due_date="2026-06-20")
        assert inv_b["subtotal_cents"] == 79285, \
            f"5 x (12000 + 3000 LOW + trunc(6000/7)=857), got {inv_b['subtotal_cents']}"
        assert inv_a["subtotal_cents"] - inv_b["subtotal_cents"] == 17140, (
            "band jump (3000/day) must dominate the capped nursing delta (428/day)")


class TestInvoiceRoundingOrder:
    def test_per_line_truncation_then_sum(self, api):
        """PRD §2.8: "Invoice line amounts are each rounded to whole cents first, and
        the invoice `subtotal_cents` is the sum of those already-rounded line amounts
        — round per line, then sum. A final daily Medicaid rate is rounded half-up to
        whole cents, with its nursing component truncated to whole cents before being
        summed into the rate."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
        """
        ctx = setup_admitted_resident(
            payer_type="MEDICAID", nursing_hours_per_week=4, adl_dependency_score=2,
            medicaid_certified=True, rates=[dict(MC_RATE)],
            admission_date="2026-06-01", complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-02T00:00:00Z")
        invoice = generate_invoice_for(ctx["resident"]["id"],
                                       period_start="2026-06-01",
                                       period_end="2026-06-08",
                                       due_date="2026-06-20")
        assert invoice["subtotal_cents"] == 110999, (
            f"7 x 15857 per-line truncation must give 110999, got "
            f"{invoice['subtotal_cents']}")

    def test_sum_then_round_alternative_rejected(self, api):
        """PRD §2.8: "Invoice line amounts are each rounded to whole cents first, and
        the invoice `subtotal_cents` is the sum of those already-rounded line amounts
        — round per line, then sum. A final daily Medicaid rate is rounded half-up to
        whole cents, with its nursing component truncated to whole cents before being
        summed into the rate."
        PRD §3.7: "Invoice generation by a `Provider` takes `period_start`,
        `period_end` (which must be after `period_start`), a `due_date`, and the OCC
        field `expected_resident_version` described in §2.7, and produces a `DRAFT`
        invoice."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
        """
        ctx = setup_admitted_resident(
            payer_type="MEDICAID", nursing_hours_per_week=4, adl_dependency_score=2,
            medicaid_certified=True, rates=[dict(MC_RATE)],
            admission_date="2026-06-01", complete_clock="2026-06-01T14:00:00Z")
        set_clock("2026-06-02T00:00:00Z")
        invoice = generate_invoice_for(ctx["resident"]["id"],
                                       period_start="2026-06-01",
                                       period_end="2026-06-08",
                                       due_date="2026-06-20")
        assert invoice["subtotal_cents"] != 111000, (
            "111000 is the sum-then-round outcome; the pinned order is truncate per "
            "line, then sum")
        assert invoice["status"] == "DRAFT"

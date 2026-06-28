"""Calculation and pricing claims: credit-pack tiered pricing, the intro
mobility-assessment composite, membership freeze proration, and the dual-variant
no-show / late-cancel fee.

All money is integer cents, round-half-up, with pinned rounding order (PRD §2.9).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    ApiErrorId,
    fixtures,
    factories,
    make_member_headers,
    make_front_desk_headers,
    make_studio_manager_headers,
    make_flexologist_headers,
)

FD = make_front_desk_headers()
SM = make_studio_manager_headers()


# ===========================================================================
# credit_pack_price — tiered discount, pinned order (discount -> round -> fee)
# ===========================================================================

class TestCreditPackPricing:
    def test_credit_pack_price_ten_credit_tier(self, api):
        """PRD §3.8: "a discount fraction is chosen by pack size: 0.15 when `pack_credits` is at least 20, otherwise 0.10 when it is at least 10, otherwise 0.05 when it is at least 5, otherwise 0.00."
        PRD §3.8: "Finally, a flat processing fee of 300 cents is added to the rounded discounted subtotal to produce `price_cents`."

        base=4500, credits=10 -> subtotal 45000, 10% tier -> 40500, +300 = 40800.

        Design: Difficulty/combinatorial_formula/credit_pack_price_tiered_three_inputs
        """
        loc = fixtures.create_location(name="Pack Loc")
        mem = fixtures.create_member(loc["id"], full_name="Pat", email="pat@x.com")
        resp = api.create_credit_pack(
            factories.create_credit_pack_payload(
                mem["id"], loc["id"], pack_credits=10, base_unit_price_cents=4500,
                expires_utc="2027-01-01T00:00:00Z"),
            make_member_headers(mem["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["price_cents"] == 40800, f"expected 40800, got {data['price_cents']}"
        assert data["status"] == "ACTIVE"
        assert data["available_credits"] == 10

    def test_credit_pack_price_twenty_credit_tier_pinned_order(self, api):
        """PRD §3.8: "a discount fraction is chosen by pack size: 0.15 when `pack_credits` is at least 20, otherwise 0.10 when it is at least 10, otherwise 0.05 when it is at least 5, otherwise 0.00."
        PRD §3.8: "The discounted subtotal is the subtotal multiplied by one minus that discount fraction, and this discounted subtotal is rounded half-up to whole cents at this step — before anything else is added. Finally, a flat processing fee of 300 cents is added to the rounded discounted subtotal to produce `price_cents`."

        base=333, credits=20 -> subtotal 6660, 15% tier -> 5661.0 -> round 5661,
        +300 = 5961 (pinned discount -> round -> fee order).

        Design: Difficulty/combinatorial_formula/credit_pack_price_tiered_three_inputs
        """
        loc = fixtures.create_location(name="Pack Loc 20")
        mem = fixtures.create_member(loc["id"], full_name="Vol", email="vol@x.com")
        resp = api.create_credit_pack(
            factories.create_credit_pack_payload(
                mem["id"], loc["id"], pack_credits=20, base_unit_price_cents=333,
                expires_utc="2027-01-01T00:00:00Z"),
            make_member_headers(mem["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["price_cents"] == 5961, f"expected 5961, got {data['price_cents']}"
        assert data["available_credits"] == 20

    def test_credit_pack_price_tier_boundary_five_vs_four(self, api):
        """PRD §3.8: "a discount fraction is chosen by pack size: 0.15 when `pack_credits` is at least 20, otherwise 0.10 when it is at least 10, otherwise 0.05 when it is at least 5, otherwise 0.00."
        PRD §3.8: "Finally, a flat processing fee of 300 cents is added to the rounded discounted subtotal to produce `price_cents`."

        base=1000: 4 credits (no discount) -> 4000+300=4300; 5 credits (5% tier)
        -> 4750+300=5050. Tier boundary lands exactly at 5 credits.

        Design: Corner/calculations/credit_pack_tier_boundary_5_vs_4_credits
        """
        loc = fixtures.create_location(name="Tier")
        mem = fixtures.create_member(loc["id"], full_name="Tm", email="tm@x.com")
        hdr = make_member_headers(mem["id"])
        p4 = validate_success(api.create_credit_pack(
            factories.create_credit_pack_payload(
                mem["id"], loc["id"], pack_credits=4, base_unit_price_cents=1000,
                expires_utc="2027-01-01T00:00:00Z"), hdr), expected_status=201)
        p5 = validate_success(api.create_credit_pack(
            factories.create_credit_pack_payload(
                mem["id"], loc["id"], pack_credits=5, base_unit_price_cents=1000,
                expires_utc="2027-01-01T00:00:00Z"), hdr), expected_status=201)
        assert p4["price_cents"] == 4300, f"4-credit pack expected 4300, got {p4['price_cents']}"
        assert p5["price_cents"] == 5050, f"5-credit pack expected 5050, got {p5['price_cents']}"


# ===========================================================================
# intro_assessment_score — sum-then-round-once composite
# ===========================================================================

class TestIntroAssessment:
    def test_assessment_round_once_yields_foundation(self, api):
        """PRD §3.4: "The composite multiplies the shoulder sub-score by 0.30, the hip sub-score by 0.30, the spine sub-score by 0.25, and the ankle sub-score by 0.15 (weights that sum to one), sums the four products in exact decimal, and then rounds half-up exactly once to an integer composite."
        PRD §3.4: "A composite of at least 80 yields `ADVANCED`; otherwise a composite of at least 60 yields `INTERMEDIATE`; otherwise the tier is `FOUNDATION`."

        Sub-scores (55,55,55,55): terms 16.5+16.5+13.75+8.25=55.0 -> round once
        = 55 -> FOUNDATION (the naive round-each-then-sum would give 56).

        Design: Difficulty/combinatorial_formula/assessment_round_once_vs_sum_of_rounded_terms
        """
        s = fixtures.setup_base_studio(open_minute_of_day=0, close_minute_of_day=1440,
                                       certified=True)
        loc, flex, table = s["loc"], s["flex"], s["table"]
        svc_intro, mem = s["svc_intro"], s["member"]
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=1,
                                           base_unit_price_cents=100)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc_intro["id"], flex["id"],
                                     table, "2026-04-11T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_success(api.confirm_booking(bk["id"], FD))
        fixtures.set_clock("2026-04-11T10:30:00Z")
        completed = validate_success(api.complete_booking(
            bk["id"], make_flexologist_headers(flex["id"]),
            factories.intro_assessment_payload(shoulder=55, hip=55, spine=55, ankle=55)))
        assert completed["schedule_status"] == "COMPLETED"
        member = validate_success(api.get_member(mem["id"], FD))
        assert member["mobility_tier"] == "FOUNDATION", (
            f"expected FOUNDATION, got {member['mobility_tier']}")
        assert member["intro_completed"] is True

    def test_assessment_completion_flips_intro_and_sets_tier(self, api):
        """PRD §3.4: "On completing an intro booking the system flips the member's `intro_completed` to true and computes the member's `mobility_tier` from a weighted composite of those four sub-scores."
        PRD §3.4: "A composite of at least 80 yields `ADVANCED`; otherwise a composite of at least 60 yields `INTERMEDIATE`; otherwise the tier is `FOUNDATION`."

        Sub-scores (90,85,80,70): 27.0+25.5+20.0+10.5=83.0 -> 83 >= 80 -> ADVANCED.

        Design: Difficulty/combinatorial_formula/assessment_round_once_vs_sum_of_rounded_terms
        """
        s = fixtures.setup_base_studio(open_minute_of_day=0, close_minute_of_day=1440,
                                       certified=True)
        loc, flex, table = s["loc"], s["flex"], s["table"]
        svc_intro, mem = s["svc_intro"], s["member"]
        pack = fixtures.create_credit_pack(mem["id"], loc["id"], pack_credits=1,
                                           base_unit_price_cents=100)
        bk = fixtures.create_booking(mem["id"], loc["id"], svc_intro["id"], flex["id"],
                                     table, "2026-04-11T10:00:00Z", "CREDIT_PACK", pack["id"])
        validate_success(api.confirm_booking(bk["id"], FD))
        fixtures.set_clock("2026-04-11T10:30:00Z")
        validate_success(api.complete_booking(
            bk["id"], make_flexologist_headers(flex["id"]),
            factories.intro_assessment_payload(shoulder=90, hip=85, spine=80, ankle=70)))
        member = validate_success(api.get_member(mem["id"], FD))
        assert member["intro_completed"] is True
        assert member["mobility_tier"] == "ADVANCED", (
            f"expected ADVANCED, got {member['mobility_tier']}")


# ===========================================================================
# membership_freeze_proration — CALENDAR_30 (denominator always 30)
# ===========================================================================

class TestFreezeProration:
    def test_freeze_credit_uses_calendar_30_denominator(self, api):
        """PRD §3.7: "then multiplying the `monthly_fee_cents` by those frozen days, dividing by a fixed denominator of 30 days in exact decimal, and rounding half-up once to whole cents; each freeze in a cycle adds its credit to the running `freeze_credit_cents`."
        PRD §3.7: "The denominator is always 30 regardless of the actual length of the billing cycle."

        10-day freeze, monthly_fee_cents=12000, cycle anchored in May (31 days):
        12000*10/30 = 4000 (CALENDAR_30); the divergent 12000*10/31=3871 is wrong.

        Design: Difficulty/dual_variant_calc/freeze_proration_calendar30_vs_actual_cycle_on_membership
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, mem = s["loc"], s["member"]
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        resp = api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-05T00:00:00Z", "2026-05-15T00:00:00Z",
                                     ship["version"]),
            make_member_headers(mem["id"]))
        data = validate_success(resp)
        assert data["status"] == "FROZEN"
        assert data["freeze_credit_cents"] == 4000, (
            f"expected 4000 (CALENDAR_30), got {data['freeze_credit_cents']}")

    def test_freeze_credit_scales_with_frozen_days(self, api):
        """PRD §3.7: "then multiplying the `monthly_fee_cents` by those frozen days, dividing by a fixed denominator of 30 days in exact decimal, and rounding half-up once to whole cents; each freeze in a cycle adds its credit to the running `freeze_credit_cents`."

        A 3-day freeze (05-10..05-13, span of 3 whole days, ceiling = 3) on
        monthly_fee_cents=9000: 9000*3/30 = 900.

        Design: Difficulty/dual_variant_calc/freeze_proration_calendar30_vs_actual_cycle_on_membership
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-05-01T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440)
        loc, mem = s["loc"], s["member"]
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PLUS",
                                          monthly_fee_cents=9000, included_credits=6,
                                          rollover_cap=2)
        resp = api.freeze_membership(
            ship["id"],
            factories.freeze_payload("2026-05-10T00:00:00Z", "2026-05-13T00:00:00Z",
                                     ship["version"]),
            make_member_headers(mem["id"]))
        data = validate_success(resp)
        assert data["status"] == "FROZEN"
        assert data["freeze_credit_cents"] == 900, (
            f"expected 900, got {data['freeze_credit_cents']}")


# ===========================================================================
# no_show_fee — dual variant: NO_SHOW flat vs LATE_CANCEL prorated
# ===========================================================================

class TestNoShowFeeDualVariant:
    def test_no_show_flat_vs_late_cancel_prorated_on_same_booking_terms(self, api):
        """PRD §3.5: "On a no-show the fee written to fee_charged_cents is the
        flat no_show_fee_cents configured on the location, independent of the
        service price. On a late cancellation the fee is the booking's
        snapshotted list_price_cents multiplied by the location's
        late_cancel_pct, rounded half-up to whole cents."

        Same service (list_price_cents=6500), Location no_show_fee_cents=5000,
        late_cancel_pct=0.50: LATE_CANCEL -> round_half_up(6500*0.50)=3250;
        NO_SHOW -> flat 5000. The two fees differ.

        Design: Difficulty/dual_variant_calc/no_show_fee_flat_vs_prorated_on_booking
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            n_tables=2, no_show_fee_cents=5000, late_cancel_pct=0.50, cancel_window_hours=12)
        loc, flex = s["loc"], s["flex"]
        t1, t2 = s["tables"][0], s["tables"][1]
        mem = s["member"]
        svc = fixtures.create_service(loc["id"], name="50m Stretch", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6500)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        bA = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                               t1, "2026-04-13T10:00:00Z", "MEMBERSHIP", ship["id"])
        bB = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                               t2, "2026-04-14T10:00:00Z", "MEMBERSHIP", ship["id"])
        # LATE_CANCEL bA: clock inside the 12h window before 04-13T10:00Z
        fixtures.set_clock("2026-04-12T23:00:00Z")
        late = validate_success(api.cancel_booking(bA["id"], FD))
        assert late["schedule_status"] == "LATE_CANCELLED"
        assert late["fee_charged_cents"] == 3250, (
            f"late-cancel fee expected 3250, got {late['fee_charged_cents']}")
        # NO_SHOW bB: advance past its session_end and sweep
        fixtures.set_clock("2026-04-14T11:30:00Z")
        validate_success(api.no_show_sweep(SM))
        no_show = validate_success(api.get_booking(bB["id"], FD))
        assert no_show["schedule_status"] == "NO_SHOW"
        assert no_show["fee_charged_cents"] == 5000, (
            f"no-show fee expected 5000, got {no_show['fee_charged_cents']}")
        assert late["fee_charged_cents"] != no_show["fee_charged_cents"]

    def test_late_cancel_fee_is_prorated_from_list_price(self, api):
        """PRD §3.5: "On a late cancellation the fee is the booking's snapshotted `list_price_cents` multiplied by the location's `late_cancel_pct`, rounded half-up to whole cents — so the late-cancel fee scales with the booked service price while the no-show fee does not."

        list_price_cents=6500, late_cancel_pct=0.50 -> round_half_up(3250.0)=3250.

        Design: Difficulty/dual_variant_calc/no_show_fee_flat_vs_prorated_on_booking
        """
        s = fixtures.setup_intro_completed_member(
            clock="2026-04-10T00:00:00Z", open_minute_of_day=0, close_minute_of_day=1440,
            no_show_fee_cents=5000, late_cancel_pct=0.50, cancel_window_hours=12)
        loc, flex, table, mem = s["loc"], s["flex"], s["table"], s["member"]
        svc = fixtures.create_service(loc["id"], name="50m Stretch", kind="ASSISTED_STRETCH",
                                      duration_minutes=50, credit_cost=2, list_price_cents=6500)
        ship = fixtures.create_membership(mem["id"], loc["id"], tier="PRO",
                                          monthly_fee_cents=12000, included_credits=8,
                                          rollover_cap=4)
        fixtures.set_clock("2026-04-12T00:00:00Z")
        bk = fixtures.create_confirmed_booking(mem["id"], loc["id"], svc["id"], flex["id"],
                                               table, "2026-04-13T10:00:00Z", "MEMBERSHIP", ship["id"])
        fixtures.set_clock("2026-04-12T23:00:00Z")
        late = validate_success(api.cancel_booking(bk["id"], FD))
        assert late["schedule_status"] == "LATE_CANCELLED"
        assert late["fee_charged_cents"] == 3250, (
            f"expected prorated 3250, got {late['fee_charged_cents']}")

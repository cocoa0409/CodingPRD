"""Difficulty queue: dual-variant calculations (BED pair, provisional vs final)
and combinatorial formulas (planning charge, fraction dose allocation, claim
discount pinned order)."""
import pytest
from datetime import date, timedelta

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    validate_paginated,
    ApiErrorId, TEST_USERS,
    create_plan_payload, create_dose_constraint_payload,
    create_physics_check_payload, create_chart_review_payload,
    create_fraction_session_payload,
    setup_patient, setup_machine, setup_course,
    setup_treatment_ready_linac, setup_on_treatment,
    book_session, deliver_session, weekday_slot,
)

SCHED = TEST_USERS["scheduler_headers"]
ONC_A = TEST_USERS["oncologist_headers"]
ONC_B = TEST_USERS["oncologist_b_headers"]
DOS_A = TEST_USERS["dosimetrist_headers"]
PHYS_A = TEST_USERS["physicist_headers"]
PHYS_B = TEST_USERS["physicist_b_headers"]
RTT_A = TEST_USERS["therapist_headers"]
BILL = TEST_USERS["billing_headers"]


def _deliver_n(ctx, days, start=date(2026, 8, 3), igrt=False):
    """Book + deliver one session per entry in `days` (list of dates)."""
    out = []
    for d in days:
        s_t, e_t = weekday_slot(d)
        sess = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                            ctx["linac"]["id"], s_t, e_t, igrt=igrt if igrt else None)
        out.append(deliver_session(sess["id"]))
    return out


class TestBedNominalVsActual:
    # IMRT 2000/10 -> dose_per_fraction 200 cGy = 2 Gy. 10 deliveries:
    # 2026-08-03..07 and 2026-09-14..18. Span = 46 days > 28.
    DAYS_FIRST = [date(2026, 8, 3) + timedelta(days=i) for i in range(5)]
    DAYS_SECOND = [date(2026, 9, 14) + timedelta(days=i) for i in range(5)]

    def _setup_protracted_course(self):
        ctx = setup_treatment_ready_linac(mrn="MRN-BED-1", technique="IMRT",
                                          total_dose=2000, fractions=10,
                                          patient_weight=80.0)
        _deliver_n(ctx, self.DAYS_FIRST)
        get_success_data(api_client.create_chart_review(
            ctx["course"]["id"], create_chart_review_payload(outcome="PASS"), PHYS_A))
        _deliver_n(ctx, self.DAYS_SECOND)
        return ctx

    def test_bed_pair_diverges_after_protracted_course(self):
        """PRD §3.1 (nominal): "take the per-fraction dose in gray (the course's
        current `dose_per_fraction_cGy` divided by one hundred), and compute the
        planned fraction count multiplied by that gray figure, multiplied by the
        quantity one plus that same gray figure divided by ten".
        PRD §3.7 (actual): "the system subtracts a repopulation penalty of 0.6
        gray per whole day by which the whole-day span between the earliest and
        latest delivered session start times exceeds twenty-eight days".
        Nominal: 10*2*(1+0.2) = 24.000. Actual: 24.000 - 0.6*(46-28) = 13.200.

        Design: Difficulty/dual_variant_calc/bed_nominal_vs_actual_after_protracted_course
        """
        ctx = self._setup_protracted_course()
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["bed_nominal_gy"] == pytest.approx(24.000, abs=1e-6)
        assert course["bed_actual_gy"] == pytest.approx(13.200, abs=1e-6)

    def test_protracted_course_delivery_counters(self):
        """PRD §3.7: "`delivered_fractions` increments by one,
        `delivered_dose_cGy` grows by the delivered amount". After 10 deliveries
        of 200 cGy each the counters read 10 and 2000 respectively.

        Design: Difficulty/dual_variant_calc/bed_nominal_vs_actual_after_protracted_course
        """
        ctx = self._setup_protracted_course()
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["delivered_fractions"] == 10
        assert course["delivered_dose_cGy"] == 2000


class TestProvisionalVsFinal:
    def _setup_billing_case(self):
        """IMRT 5000/5; approved plan (1 target); claim opened after approval;
        3 delivered + 1 NO_SHOW. Incurred = 65000 + 2*25000 + 210000 +
        3*32000 + 12000 + 5000 = 438000."""
        ctx = setup_treatment_ready_linac(mrn="MRN-BILL-1", technique="IMRT",
                                          total_dose=5000, fractions=5,
                                          patient_weight=70.0,
                                          immobilization="VACUUM_CRADLE",
                                          contour_overrides={"target_volumes": ["PTV"],
                                                             "oar_structures": []})
        claim = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        ctx["claim"] = claim
        sessions = []
        for d in (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)):
            s_t, e_t = weekday_slot(d)
            sess = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                                ctx["linac"]["id"], s_t, e_t)
            sessions.append(deliver_session(sess["id"]))
        ns_t, ne_t = weekday_slot(date(2026, 8, 6))
        no_show = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                               ctx["linac"]["id"], ns_t, ne_t)
        get_success_data(api_client.no_show_fraction(no_show["id"], RTT_A))
        ctx["sessions"] = sessions
        return ctx

    def test_provisional_includes_projection_final_does_not(self):
        """PRD §3.9: "`provisional_total_cents`, a forward-looking estimate ...
        the sum of the amounts on existing lines, plus a projection equal to the
        number of undelivered planned fractions — the course's
        `planned_fractions` minus its `delivered_fractions`, floored at zero —
        multiplied by the bare `FRACTION_DELIVERY` rate for the course's
        technique." 438000 + (5-3)*32000 = 502000.

        Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_settlement
        """
        ctx = self._setup_billing_case()
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        assert claim["provisional_total_cents"] == 502000

    def test_finalize_computes_gross_discount_final(self):
        """PRD §3.9: "first, `gross_total_cents` is the sum over all charge
        lines; second, the payer tier is tested against that gross — the
        discount applies only when the gross is strictly more than 1,500,000
        cents; ... fourth, `discount_cents` is five percent of that base ... —
        zero when the tier is not met; fifth, `final_total_cents` is the gross
        minus the discount." Gross 438000 <= 1500000 so discount 0, final 438000.

        Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_settlement
        """
        ctx = self._setup_billing_case()
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, BILL))
        assert fin["status"] == "FINALIZED"
        assert fin["gross_total_cents"] == 438000
        assert fin["discount_cents"] == 0
        assert fin["final_total_cents"] == 438000


class TestPlanningChargeInteraction:
    def _setup_sbrt_three_target(self):
        """SBRT 3000/5, 3 target volumes; plan approved; claim opened after
        PRIMARY PASS so the second PASS appends PLANNING live."""
        ctx = setup_treatment_ready_linac(mrn="MRN-COMB-A", technique="SBRT",
                                          total_dose=3000, fractions=5,
                                          patient_weight=90.0,
                                          immobilization="BODY_FRAME",
                                          contour_overrides={
                                              "target_volumes": ["PTV1", "PTV2", "PTV3"],
                                              "oar_structures": ["LungL"]})
        ctx["claim"] = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        return ctx

    def test_planning_line_amount_uses_tier_and_multiplier(self):
        """PRD §3.5: "The planning charge is tiered: take the number of target
        volumes on the plan's pinned contour set, form a multiplier of one plus
        one-quarter times the number of volumes beyond the first, and multiply
        it by the technique base — 90,000 cents for `THREE_DCRT`, 210,000 cents
        for `IMRT`, 300,000 cents for `SBRT`. An initial plan bills that product
        rounded half up to a whole cent."
        SBRT base 300000, 3 targets -> multiplier 1.5 -> 450000.

        Design: Difficulty/combinatorial_formula/planning_charge_technique_target_count_interaction
        """
        ctx = self._setup_sbrt_three_target()
        lines = validate_paginated(
            api_client.list_charge_lines(ctx["claim"]["id"], BILL))[0]
        planning = [l for l in lines if l["code"] == "PLANNING"]
        assert len(planning) == 1, "exactly one PLANNING line"
        assert planning[0]["amount_cents"] == 450000

    def test_claim_gross_includes_simulation_checks_planning(self):
        """PRD §3.9: "`gross_total_cents` is always the sum of `amount_cents`
        over the claim's lines". SIMULATION 65000 + 2 x PHYSICS_CHECK 25000 +
        PLANNING 450000 = 565000.

        Design: Difficulty/combinatorial_formula/planning_charge_technique_target_count_interaction
        """
        ctx = self._setup_sbrt_three_target()
        lines = validate_paginated(
            api_client.list_charge_lines(ctx["claim"]["id"], BILL))[0]
        codes = [l["code"] for l in lines]
        assert codes.count("SIMULATION") == 1
        assert codes.count("PHYSICS_CHECK") == 2
        assert sum(l["amount_cents"] for l in lines) == 565000
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        assert claim["gross_total_cents"] == 565000


class TestFractionDoseAllocation:
    def _setup_5005_case(self):
        """THREE_DCRT 5005/4 -> base 1251, final carries 1252."""
        ctx = setup_treatment_ready_linac(mrn="MRN-COMB-B", technique="THREE_DCRT",
                                          total_dose=5005, fractions=4,
                                          intent="PALLIATIVE", diagnosis_code="C18",
                                          patient_weight=65.0,
                                          immobilization="NONE",
                                          contour_overrides={"target_volumes": ["PTV"],
                                                             "oar_structures": ["Rectum"]})
        return ctx

    def test_non_final_fractions_carry_base(self):
        """PRD §3.4: "the base is the target divided by the fraction count,
        rounded half up to a whole centigray — and this is the value the plan's
        `dose_per_fraction_cGy` stores. Every fraction except the last is
        allocated the base". For 5005/4: base 1251 on fractions 1-3.

        Design: Difficulty/combinatorial_formula/fraction_dose_allocation_remainder_on_last
        """
        ctx = self._setup_5005_case()
        assert ctx["plan"]["dose_per_fraction_cGy"] == 1251
        doses = []
        for d in (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)):
            s_t, e_t = weekday_slot(d)
            sess = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                                ctx["linac"]["id"], s_t, e_t)
            doses.append(deliver_session(sess["id"])["dose_delivered_cGy"])
        assert doses == [1251, 1251, 1251]

    def test_final_fraction_carries_remainder(self):
        """PRD §3.4: "the final fraction carries the remainder, namely the
        target minus the base multiplied by one fewer than the fraction count.
        ... a 5,005 cGy target over four fractions must allocate 1251, 1251,
        1251, and 1252, never a uniformly rounded series." After the fourth
        delivery the course's delivered_dose_cGy sums exactly to 5005.

        Design: Difficulty/combinatorial_formula/fraction_dose_allocation_remainder_on_last
        """
        ctx = self._setup_5005_case()
        last_dose = None
        for d in (date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6)):
            s_t, e_t = weekday_slot(d)
            sess = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                                ctx["linac"]["id"], s_t, e_t)
            last_dose = deliver_session(sess["id"])["dose_delivered_cGy"]
        assert last_dose == 1252
        course = get_success_data(api_client.get_course(ctx["course"]["id"], ONC_A))
        assert course["delivered_dose_cGy"] == 5005


class TestClaimDiscountPinnedOrder:
    def _setup_discount_case(self):
        """SBRT 3600/18, 1 target; 18 fractions all igrt_planned=true delivered
        on weekdays 2026-08-03..26; claim opened after approval."""
        ctx = setup_treatment_ready_linac(mrn="MRN-COMB-C", technique="SBRT",
                                          total_dose=3600, fractions=18,
                                          patient_weight=82.0,
                                          immobilization="BODY_FRAME",
                                          contour_overrides={"target_volumes": ["PTV"],
                                                             "oar_structures": ["Cord"]})
        ctx["claim"] = get_success_data(api_client.create_claim(ctx["course"]["id"], BILL))
        days = [date(2026, 8, 3) + timedelta(days=i) for i in range(26)]
        days = [d for d in days if d.weekday() < 5][:18]
        assert len(days) == 18
        for idx, d in enumerate(days):
            s_t, e_t = weekday_slot(d)
            sess = book_session(ctx["course"]["id"], ctx["plan"]["id"],
                                ctx["linac"]["id"], s_t, e_t, igrt=True)
            deliver_session(sess["id"])
            if (idx + 1) in (5, 10, 15):
                get_success_data(api_client.create_chart_review(
                    ctx["course"]["id"], create_chart_review_payload(outcome="PASS"), PHYS_A))
        return ctx

    def test_discount_base_excludes_one_time_lines(self):
        """PRD §3.9: "third, the discount base is the sum over lines whose
        `code` is `FRACTION_DELIVERY` or `IGRT` and nothing else, so one-time
        lines (simulation, planning, physics check, first-fraction setup,
        no-show fee) are never discounted; fourth, `discount_cents` is five
        percent of that base, rounded half up to a whole cent".
        Base = 18*55000 + 18*7500 = 1125000; discount = round_half_up(56250.0) = 56250.

        Design: Difficulty/combinatorial_formula/claim_discount_gross_tier_then_delivery_subset
        """
        ctx = self._setup_discount_case()
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, BILL))
        assert fin["discount_cents"] == 56250

    def test_tier_tested_on_gross_and_final_is_gross_minus_discount(self):
        """PRD §3.9: "first, `gross_total_cents` is the sum over all charge
        lines; second, the payer tier is tested against that gross — the
        discount applies only when the gross is strictly more than 1,500,000
        cents; ... fifth, `final_total_cents` is the gross minus the discount."
        Gross = 65000 + 50000 + 300000 + 12000 + 990000 + 135000 = 1552000 >
        1500000, so final = 1552000 - 56250 = 1495750.

        Design: Difficulty/combinatorial_formula/claim_discount_gross_tier_then_delivery_subset
        """
        ctx = self._setup_discount_case()
        claim = get_success_data(api_client.get_claim(ctx["claim"]["id"], BILL))
        fin = validate_success(api_client.finalize_claim(
            claim["id"], {"expected_claim_version": claim["version"]}, BILL))
        assert fin["status"] == "FINALIZED"
        assert fin["gross_total_cents"] == 1552000
        assert fin["final_total_cents"] == 1495750

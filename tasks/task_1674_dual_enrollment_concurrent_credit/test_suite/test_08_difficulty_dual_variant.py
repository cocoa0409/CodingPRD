"""Difficulty rule dual_variant_calc: the same domain events feed two different
calculation variants — the two GPA scales on the Student side and the
estimate-vs-settled refund pair on the Invoice side (PRD 3.7, 3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_transcript_entry,
    get_student,
    refund_invoice,
    setup_dual_course_posted_scenario,
    setup_mismatch_withdraw_scenario,
    validate_error,
)


class TestGpaCollegeVsHsDivergenceSameGrades:
    def test_dual_scales_yield_different_gpas_for_identical_grades(self, api):
        """PRD 3.8: "The college variant writes `college_gpa` and uses a 4.0 scale —
        `A` is 4, `B` is 3, `C` is 2, `D` is 1, `F` is 0 — with `W` excluded from
        numerator and denominator entirely, so a `W` does not move the college
        GPA."
        PRD 3.8: "The high school variant writes `hs_gpa` and uses a dual-credit
        weighted 5.0 scale — `A` is 5, `B` is 4, `C` is 3, `D` is 2, `F` is 0, `W`
        is 0 — with `W` included at 0 points and its `credit_value` counted in the
        denominator, so a `W` drags the high school GPA down."
        PRD 3.8: "Both GPAs are rounded half-up to three decimal places."

        Design: Difficulty/dual_variant_calc/gpa_college_vs_hs_divergence_same_grades
        """
        ctx = setup_dual_course_posted_scenario()
        student = get_student(ctx["student"]["id"])
        # College variant: (4 x 3 + 3 x 4) / (3 + 4) = 24/7, rounded half-up.
        assert student["college_gpa"] == pytest.approx(3.429, abs=1e-9), (
            f"Expected college_gpa 3.429 (24/7 round-half-up), got "
            f"{student['college_gpa']}"
        )
        # HS variant over the SAME two letter grades: (5 x 1.0 + 4 x 1.0) / 2.
        assert student["hs_gpa"] == pytest.approx(4.5, abs=1e-9), (
            f"Expected hs_gpa 4.500 (9/2 on the 5.0 dual-credit scale), got "
            f"{student['hs_gpa']}"
        )

    def test_grade_points_differ_per_institution_for_identical_grade(self, api):
        """PRD 3.8: "Each entry's `grade_points` is the quality-point value for its
        institution and grade multiplied by its `credit_value`."
        PRD 3.8: "a `COMPLETED` enrollment produces one `COLLEGE` entry whose
        `credit_value` is the course's `college_credit_hours` and one `HIGH_SCHOOL`
        entry whose `credit_value` is the course's `hs_credit_units`, both in
        `PENDING` status with the grade copied from the enrollment."

        Design: Difficulty/dual_variant_calc/gpa_college_vs_hs_divergence_same_grades
        """
        ctx = setup_dual_course_posted_scenario()
        college_entry = ctx["math_entry_college"]
        hs_entry = ctx["math_entry_hs"]
        assert_transcript_entry(college_entry)
        assert_transcript_entry(hs_entry)
        # The identical grade A earns 4 x 3 = 12 on the college scale and
        # 5 x 1.0 = 5.0 on the high-school scale.
        assert college_entry["grade"] == "A" and hs_entry["grade"] == "A"
        assert college_entry["credit_value"] == 3
        assert hs_entry["credit_value"] == 1.0
        assert college_entry["grade_points"] == pytest.approx(12, abs=1e-9)
        assert hs_entry["grade_points"] == pytest.approx(5.0, abs=1e-9)
        assert college_entry["status"] == "POSTED" and hs_entry["status"] == "POSTED"


class TestRefundProvisionalVsSettledDivergence:
    def test_withdraw_in_mismatch_window_stores_billed_estimate(self, api):
        """PRD 3.5: "The invoice is settled per §3.7 with a `refund_pct` of 50 when
        the clock reads at or before the college term's `drop_deadline` and 0
        otherwise — note that the college calendar alone governs the 50-percent
        compensation even though the high school calendar may have been what forced
        the withdraw, which is the cross-calendar mismatch window."
        PRD 3.7: "`refund_estimate_cents` is `tuition_total_cents` multiplied by
        `refund_pct` and divided by 100, rounded half-up."
        PRD 3.7: "When `refund_pct` is 100 the invoice's `status` moves to `VOIDED`;
        when it is 50 the status is unchanged."

        Design: Difficulty/dual_variant_calc/refund_provisional_vs_settled_divergence
        """
        ctx = setup_mismatch_withdraw_scenario(pay_family=True)
        invoice = ctx["invoice"]
        assert ctx["withdrawn"]["status"] == "WITHDRAWN"
        assert invoice["refund_pct"] == 50, (
            f"2026-09-12 <= college drop 2026-09-15: mismatch compensation earns "
            f"50, got {invoice['refund_pct']}"
        )
        # Estimate variant reads the BILLED shares: 120000 x 50%.
        assert invoice["refund_estimate_cents"] == 60000
        assert invoice["est_state_refund_cents"] == 45000
        assert invoice["est_district_refund_cents"] == 0
        assert invoice["est_family_refund_cents"] == 15000
        assert invoice["status"] == "PARTIALLY_PAID", (
            f"A 50-percent withdraw leaves the status unchanged, got "
            f"{invoice['status']}"
        )
        assert invoice["refund_status"] == "DUE", (
            "pct > 0 with 30000 cents of payments makes the refund DUE"
        )

    def test_settled_refund_uses_paid_amounts_not_billed_shares(self, api, bursar_headers):
        """PRD 3.7: "The settled `refund_paid_cents` is computed from amounts
        actually paid, not billed shares: it is the rounded state refund plus the
        rounded district refund plus a family remainder, where the rounded state
        refund is `paid_state_cents` multiplied by the percentage and divided by
        100 rounded half-up, the rounded district refund is `paid_district_cents`
        multiplied by the percentage and divided by 100 rounded half-up, and the
        family remainder is `paid_state_cents` plus `paid_district_cents` plus
        `paid_family_cents`, multiplied by the percentage and divided by 100 and
        rounded half-up, minus the rounded state refund, minus the rounded district
        refund."
        PRD 3.7: "When the invoice is fully paid the settled amount equals the
        estimate; when partially paid the settled amount is at most the estimate
        and the two diverge."

        Design: Difficulty/dual_variant_calc/refund_provisional_vs_settled_divergence
        """
        ctx = setup_mismatch_withdraw_scenario(pay_family=True)
        invoice = ctx["invoice"]
        assert invoice["refund_estimate_cents"] == 60000  # billed-side reading

        settled = refund_invoice(invoice["id"])
        # Settled variant reads the PAID amounts: only the family paid (30000),
        # so the refund is 15000 — not the 60000 billed-side estimate.
        assert settled["refund_paid_cents"] == 15000, (
            f"Expected settled refund 15000 (paid_total 30000 x 50%; state paid "
            f"0), got {settled['refund_paid_cents']}"
        )
        assert settled["refund_status"] == "PROCESSED"
        assert settled["status"] == "PARTIALLY_PAID"

        second = api.refund_invoice(invoice["id"], bursar_headers)
        validate_error(second, ApiErrorId.ERR_REFUND_NOT_DUE.value)

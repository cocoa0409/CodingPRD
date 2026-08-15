"""Tuition pricing: provisional vs final variants, tiered formula, rounding order,
early-bird strict boundary."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_open_year_with_section,
    create_family, create_student, enroll_students_sequential,
    enroll_student_fresh, issue_invoice_fresh, get_invoice,
    get_family,
)

ADMIN = TEST_USERS["admin_headers"]


class TestTieredFormula:
    def test_member_and_non_member_branches_with_rounding(self):
        """PRD §3.3: "The base rate is the year's `member_tuition_cents` when the
        family's `membership_status` is `MEMBER`, otherwise
        `non_member_tuition_cents`... The discounted figure is the base multiplied by
        one minus that fraction, rounded half up to whole cents. Finally, if the
        enrollment's `created_at` is strictly earlier than the year's
        `early_bird_deadline`, the result is multiplied by one minus
        `early_bird_pct` and rounded half up to whole cents a second time".

        Design: Difficulty/combinatorial_formula/enrollment_net_tuition_tiered_branch_rounding
        """
        ctx = setup_open_year_with_section(grade="G1", hebrew_level="INTERMEDIATE",
                                           capacity=10)
        section = ctx["section"]
        fam_n = create_family(membership_status="NON_MEMBER")
        n1 = create_student(fam_n["id"], grade="G1", hebrew_level="INTERMEDIATE")
        fam_m = create_family(membership_status="MEMBER")
        m1 = create_student(fam_m["id"], grade="G1", hebrew_level="INTERMEDIATE")
        m2 = create_student(fam_m["id"], grade="G1", hebrew_level="INTERMEDIATE")
        m3 = create_student(fam_m["id"], grade="G1", hebrew_level="INTERMEDIATE")

        # All enrollments happen at the default logical clock 2026-08-01, strictly
        # before the 2026-08-15 early-bird deadline.
        e_n1 = enroll_student_fresh(section["id"], n1["id"])
        assert e_n1["estimated_tuition_cents"] == 111000  # 120000 * 0.925
        e_m1, e_m2, e_m3 = enroll_students_sequential(
            section["id"], [m1["id"], m2["id"], m3["id"]]
        )
        assert e_m1["estimated_tuition_cents"] == 67063  # 72500 -> 67062.5 half-up
        assert e_m2["estimated_tuition_cents"] == 60356  # 65250 -> 60356.25
        assert e_m3["estimated_tuition_cents"] == 53650  # 58000 -> 53650

    def test_sibling_rank_tiers_progress(self):
        """PRD §3.3: "The sibling discount fraction is the element of the year's
        `sibling_discount_pcts` array at the index given by the smaller of the
        `sibling_rank` and the array's last index".

        Design: Difficulty/combinatorial_formula/enrollment_net_tuition_tiered_branch_rounding
        """
        ctx = setup_open_year_with_section(grade="G1", hebrew_level="INTERMEDIATE",
                                           capacity=10)
        section = ctx["section"]
        fam = create_family()
        kids = [
            create_student(fam["id"], grade="G1", hebrew_level="INTERMEDIATE")
            for _ in range(2)
        ]
        e1, e2 = enroll_students_sequential(section["id"], [k["id"] for k in kids])
        # rank 0: no sibling discount; rank 1: 10% tier.
        assert e1["sibling_rank"] == 0
        assert e2["sibling_rank"] == 1
        assert e1["estimated_tuition_cents"] == 67063
        assert e2["estimated_tuition_cents"] == 60356


class TestProvisionalVsFinal:
    def test_frozen_estimate_vs_final_line_after_sibling_withdrawal(self):
        """PRD §3.3: "This provisional number is frozen on the enrollment and later
        serves as the base for withdrawal credits; the invoice-time recomputation in
        §3.6 runs the same formula against the ranking as it exists at issue, and
        because withdrawals shift siblings' ranks, the final figure may differ from
        the frozen estimate." §3.3: "`WITHDRAWN` enrollments are excluded".
        PRD §3.6: "Its `line_items` array carries one entry per billable enrollment".

        Design: Difficulty/dual_variant_calc/tuition_provisional_estimate_vs_final_invoice_line
        """
        ctx = setup_open_year_with_section(capacity=10)
        section, year = ctx["section"], ctx["year"]
        family = create_family()
        kids = [create_student(family["id"]) for _ in range(3)]
        e_a, e_b, e_c = enroll_students_sequential(
            section["id"], [k["id"] for k in kids]
        )
        # Frozen provisional figures (ranks 0, 1, 2 at creation).
        assert e_a["estimated_tuition_cents"] == 67063
        assert e_b["estimated_tuition_cents"] == 60356
        assert e_c["estimated_tuition_cents"] == 53650

        # Withdraw the middle child BEFORE any invoice issue.
        get_success_data(api_client.withdraw_enrollment(e_b["id"], ADMIN))

        invoice = issue_invoice_fresh(family["id"], year["id"])
        lines = {li["enrollment_id"]: li["line_cents"] for li in invoice["line_items"]}
        # The withdrawn enrollment carries no line.
        assert e_b["id"] not in lines
        assert lines[e_a["id"]] == 67063
        # Rank shift: third child recomputes at rank 1 -> 60356, not frozen 53650.
        assert lines[e_c["id"]] == 60356
        assert invoice["gross_cents"] == 127419
        assert invoice["activity_fee_cents"] == 5000
        assert invoice["total_due_cents"] == 132419
        assert invoice["balance_cents"] == 132419
        assert invoice["status"] == "ISSUED"
        assert invoice["kind"] == "TUITION"

    def test_provisional_frozen_even_when_final_differs(self):
        """PRD §3.3: "This provisional number is frozen on the enrollment";
        §3.6: "each entry naming the `enrollment_id`, the `student_id`, and a
        `line_cents` figure computed by re-running the §3.3 tuition formula against
        the sibling ranking as it stands at issue time".

        Design: Difficulty/dual_variant_calc/tuition_provisional_estimate_vs_final_invoice_line
        """
        ctx = setup_open_year_with_section(capacity=10)
        section, year = ctx["section"], ctx["year"]
        family = create_family()
        kids = [create_student(family["id"]) for _ in range(3)]
        e_a, e_b, e_c = enroll_students_sequential(
            section["id"], [k["id"] for k in kids]
        )
        get_success_data(api_client.withdraw_enrollment(e_b["id"], ADMIN))
        issue_invoice_fresh(family["id"], year["id"])
        # The enrollment record still shows the frozen provisional estimate.
        e_c_now = get_success_data(api_client.get_enrollment(e_c["id"], ADMIN))
        assert e_c_now["estimated_tuition_cents"] == 53650


class TestPerLineRounding:
    def test_round_per_line_then_sum(self):
        """PRD §3.6: "The `gross_cents` is the sum of those already-rounded lines."
        PRD §2.6: "tuition lines are rounded per line and then summed, never summed
        unrounded and rounded once at the end."

        Design: Corner/calculations/invoice_per_line_rounding_then_sum
        """
        # member_tuition 72501 yields fractional cents, exposing rounding order.
        ctx = setup_open_year_with_section(member_tuition_cents=72501)
        section, year = ctx["section"], ctx["year"]
        family = create_family()
        k1 = create_student(family["id"])
        k2 = create_student(family["id"])
        e1, e2 = enroll_students_sequential(section["id"], [k1["id"], k2["id"]])
        invoice = issue_invoice_fresh(family["id"], year["id"])
        lines = {li["enrollment_id"]: li["line_cents"] for li in invoice["line_items"]}
        # rank0: round_half_up(72501 * 0.925) = round_half_up(67063.425) = 67063
        assert lines[e1["id"]] == 67063
        # rank1: round_half_up(72501*0.90)=65251 -> round_half_up(65251*0.925)=60357
        assert lines[e2["id"]] == 60357
        # Sum of pre-rounded lines; sum-then-round would give 127421.
        assert invoice["gross_cents"] == 127420


class TestEarlyBirdBoundary:
    def test_strict_before_deadline(self):
        """PRD §2.9: "the early-bird rule is strictly-before: an enrollment
        qualifies for the discount only when its `created_at` is strictly earlier
        than the year's `early_bird_deadline`; an enrollment created at exactly the
        deadline instant does not qualify."

        Design: Corner/calculations/early_bird_deadline_strict_boundary
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        family = create_family()
        st_early = create_student(family["id"])
        st_late = create_student(family["id"])
        # One second before the 2026-08-15T00:00:00Z deadline.
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-08-14T23:59:59Z"}, ADMIN)
        )
        e_early = enroll_student_fresh(section["id"], st_early["id"])
        assert e_early["estimated_tuition_cents"] == 67063
        # Exactly AT the deadline: fails the strict < test -> no early-bird factor.
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, ADMIN)
        )
        e_late = enroll_student_fresh(section["id"], st_late["id"])
        # rank1 after_sibling = round_half_up(72500 * 0.90) = 65250, no 0.925 factor.
        assert e_late["estimated_tuition_cents"] == 65250

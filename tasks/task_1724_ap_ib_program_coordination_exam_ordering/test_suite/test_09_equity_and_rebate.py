"""Program growth & equity reporting and the pinned per-line rebate rounding
order (PRD §2.6, §3.8).
"""
from test_helpers import (
    COORD,
    cancel_registration,
    get_cycle,
    make_course,
    make_open_cycle,
    make_registration,
    make_student,
    validate_success,
)


class TestEquityReport:
    def test_participation_rates_gap_and_growth(self, api):
        """PRD §3.8: "For each subgroup `GEN`, `FRL`, `IEP`, and `ELL` that has
        at least one student, the report counts the students in the subgroup,
        counts the distinct students of the subgroup holding at least one
        registration in this cycle whose `registration_status` is not
        `CANCELLED`, and computes the subgroup's participation rate as 100
        times the participant count divided by the student count, rounded
        half-up to one decimal place."
        PRD §3.8: "When the optional `compare_to_cycle_id` parameter is
        supplied, `growth_exams` is this cycle's `total_exams` minus the
        comparison cycle's total; otherwise `growth_exams` is null."
        PRD §3.8: "The `access_gap_pct` is the difference between the highest
        and lowest subgroup participation rates, rounded half-up to one decimal
        place."

        Design: Corner/calculations/equity_report_rates_gap_and_growth
        """
        prior = make_open_cycle(name="CYCLE-2026")
        current = make_open_cycle(name="CYCLE-2027")
        course_prior = make_course(
            prior["id"], subject_code="AP_CALC_AB", exam_fee_cents=9800
        )
        course_current = make_course(
            current["id"], subject_code="AP_CALC_BC", exam_fee_cents=9800
        )
        gen = [
            make_student(full_name=f"G {i}", subgroup_code="GEN")
            for i in range(4)
        ]
        frl = [
            make_student(full_name=f"F {i}", subgroup_code="FRL")
            for i in range(4)
        ]
        # Prior cycle: one exam (GEN student #4).
        make_registration(gen[3]["id"], course_prior["id"])
        # Current cycle: 3 of 4 GEN and 1 of 4 FRL participate.
        for student in gen[:3]:
            make_registration(student["id"], course_current["id"])
        make_registration(frl[0]["id"], course_current["id"])

        res = api.get_equity_report(
            current["id"], COORD, params={"compare_to_cycle_id": prior["id"]}
        )
        report = validate_success(res, 200)
        # GEN 3/4 = 75.0 and FRL 1/4 = 25.0; the gap is their difference.
        assert report["total_exams"] == 4
        assert report["growth_exams"] == 3  # 4 - 1 in the prior cycle
        assert report["access_gap_pct"] == 50.0
        # Only subgroups with at least one student appear (GEN and FRL here).
        assert isinstance(report["subgroups"], list)
        assert len(report["subgroups"]) == 2


class TestRebateRoundingOrder:
    def test_rebate_rounds_per_line_then_sums(self, api):
        """PRD §2.6: "The **school rebate** is computed per registration first
        and summed second. Each registration's rebate line is the
        registration's net fee multiplied by the cycle's rebate rate and
        rounded half-up to integer cents; the cycle's rebate is the sum of
        those per-line amounts. Summing net fees first and rounding once is a
        rejected alternative that yields different cents — for example, three
        net fees of 1050 cents at a 9% rate produce per-line rebates of 95
        cents each (285 total), whereas sum-then-round would produce 284."

        Design: Difficulty/combinatorial_formula/rebate_per_line_rounding_mode_b
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], subject_code="AP_MICRO", exam_fee_cents=1050)
        students = [make_student(full_name=f"Stu {i}") for i in range(3)]
        for student in students:
            make_registration(student["id"], course["id"])
        # Per line: round_half_up(1050 * 900 / 10000) = round_half_up(94.5) = 95.
        # Pinned order: 3 x 95 = 285. Sum-then-round (284) is rejected.
        assert get_cycle(cycle["id"])["rebate_cents"] == 285

    def test_rebate_recomputes_when_a_line_drops_out(self, api):
        """PRD §3.3: "Anything that changes a registration's `net_fee_cents` —
        creation, cancellation, or an application decision — recomputes the
        rebate."
        PRD §3.3: "The cycle's `rebate_cents` is the sum, over every
        registration in the cycle whose `registration_status` is not
        `CANCELLED`, of that registration's rebate line"

        Design: Difficulty/combinatorial_formula/rebate_per_line_rounding_mode_b
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"], subject_code="AP_MICRO", exam_fee_cents=1050)
        students = [make_student(full_name=f"Stu {i}") for i in range(3)]
        registrations = [
            make_registration(s["id"], course["id"]) for s in students
        ]
        assert get_cycle(cycle["id"])["rebate_cents"] == 285
        # A cancelled registration drops out of the rebate input set.
        cancel_registration(registrations[2]["id"])
        assert get_cycle(cycle["id"])["rebate_cents"] == 190  # 2 x 95

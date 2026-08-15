"""Eligibility match scoring: STRICT vs HOLISTIC variants and recompute."""
from test_helpers import (
    TEST_USERS,
    assert_score_equals,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_student,
    get_success_data,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]

# The PRD's worked dual-variant example: NEED program, min GPA 300, income
# ceiling 10000000, residency CA, required tag FIRST_GEN, majors [STEM];
# student with self-reported GPA 280 (gap 20), income 2000000, CA, FIRST_GEN.
NEED_PROGRAM = {
    "program_type": "NEED",
    "min_gpa_hundredths": 300,
    "max_household_income_cents": 10000000,
    "required_residency_state": "CA",
    "required_tags": ["FIRST_GEN"],
    "eligible_majors": ["STEM"],
    "award_amount_cents": 1000000,
}
STUDENT_SPEC = {
    "gpa_hundredths": 280,
    "household_income_cents": 2000000,
    "efc_cents": 1000000,
    "cost_of_attendance_cents": 3000000,
    "residency_state": "CA",
    "intended_major": "STEM",
    "tags": ["FIRST_GEN"],
}


class TestStrictVsHolisticZeroGate:
    """Same student data, two programs differing only in match_policy."""

    def _applications(self):
        student = create_student(**STUDENT_SPEC)
        donor = create_donor()
        fund = create_fund(committed_cents=10000000)
        strict = create_open_program(
            donor["id"], fund["id"], **{**NEED_PROGRAM, "match_policy": "STRICT"}
        )
        holistic = create_open_program(
            donor["id"], fund["id"], **{**NEED_PROGRAM, "match_policy": "HOLISTIC"}
        )
        app_strict = create_draft_application(student["id"], strict["id"])
        app_holistic = create_draft_application(student["id"], holistic["id"])
        return app_strict, app_holistic

    def test_strict_variant_zero_gates_provisional_score(self, api):
        """PRD §3.4: "Under `STRICT`, any hard-criterion miss — GPA below the
        minimum, income above the ceiling, residency mismatch, any required
        tag absent, or the major gate — forces the total score to exactly
        0.00."
        PRD §3.4: "At creation it produces the `provisional_match_score` from
        the student's self-reported `gpa_hundredths`."

        Design: Difficulty/dual_variant_calc/eligibility_strict_vs_holistic_zero_gate
        """
        app_strict, _ = self._applications()
        assert_score_equals(
            app_strict["provisional_match_score"], 0.00,
            "STRICT provisional score with GPA 280 < min 300",
        )

    def test_holistic_variant_grants_partial_credit(self, api):
        """PRD §3.4: "The GPA component is 100 when the GPA input meets or
        exceeds the program's `min_gpa_hundredths`; under a `HOLISTIC` match
        policy, a GPA input falling short of the minimum by at most 20
        hundredths — two tenths of a GPA point — still earns 50; otherwise
        the component is 0."
        PRD §3.4: "A `NEED` program weights GPA at 0.20, income at 0.50,
        residency at 0.10, and tags at 0.20."
        PRD §3.4: "Under `HOLISTIC`, partial credit applies and there is no
        zero-gate, so identical student data can yield, for example, 90.00
        under a holistic policy against 0.00 under a strict one."

        Design: Difficulty/dual_variant_calc/eligibility_strict_vs_holistic_zero_gate
        """
        _, app_holistic = self._applications()
        # NEED weights: .20*50 (gpa gap exactly 20 -> partial 50) + .50*100
        # (income 2000000 <= 10000000) + .10*100 (CA == CA) + .20*100 (1/1 tag)
        # = 90.00.
        assert_score_equals(
            app_holistic["provisional_match_score"], 90.00,
            "HOLISTIC provisional score with partial GPA credit",
        )


class TestVerifiedScoreRecomputeOnSubmit:
    def test_verified_gpa_replaces_self_reported_at_submit(self, api):
        """PRD §3.4: "At submit it produces the `verified_match_score`,
        recomputed with `verified_gpa_hundredths` when that has been set and
        with `gpa_hundredths` otherwise — so the same application can
        legitimately carry a provisional score of 90.00 and a verified score
        of 80.00 once the registrar's figure replaces the self-reported one."
        PRD §3.1: "Optional at registration are `verified_gpa_hundredths` —
        the registrar-verified GPA, which stays null until verification and
        may only ever be set by a coordinator through the student update
        operation".

        Design: Corner/calculations/calc_verified_score_recompute_on_submit
        """
        student = create_student(**STUDENT_SPEC)
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(
            donor["id"], fund["id"], **{**NEED_PROGRAM, "match_policy": "HOLISTIC"}
        )
        app = create_draft_application(student["id"], program["id"])
        assert_score_equals(app["provisional_match_score"], 90.00)

        get_success_data(
            api.patch_student(student["id"], {"verified_gpa_hundredths": 250}, COORD)
        )
        submitted = validate_success(api.submit_application(app["id"], COORD))
        # Verified GPA 250: gap 50 > 20 -> GPA component 0 under HOLISTIC;
        # .20*0 + .50*100 + .10*100 + .20*100 = 80.00.
        assert_score_equals(submitted["verified_match_score"], 80.00)
        assert submitted["status"] == "SUBMITTED", "HOLISTIC has no zero-gate"

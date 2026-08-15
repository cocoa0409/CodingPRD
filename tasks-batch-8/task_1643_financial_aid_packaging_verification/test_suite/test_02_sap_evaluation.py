"""Satisfactory Academic Progress evaluation: the STANDARD and TRANSFER
variants, the 6,667-basis-point pace floor, and the zero-attempted degenerate
edge (PRD §3.2)."""
from test_helpers import TEST_USERS, register_student, validate_success

OFFICER = TEST_USERS["aid_officer_headers"]


class TestSapStandardVsTransferVariant:
    def test_standard_variant_failing_pace_maps_to_warning(self, api):
        """PRD §3.2: "When `transfer_credits` is omitted or zero, the STANDARD variant runs and only the student's as-reported cumulative credits are used. When `transfer_credits` is greater than zero, the TRANSFER variant runs: the transfer credits are added to both the attempted and the completed figures before the pace division, which can flip a failing pace to passing — thirty completed of forty-five attempted yields 6,666 basis points and fails, while adding twelve transfer credits to both figures yields forty-two of fifty-seven, or 7,368 basis points, which passes."
        PRD §3.2: "If any gate fails and the prior status is `NOT_EVALUATED` or `GOOD_STANDING`, the student drops to `WARNING`."

        Design: Difficulty/dual_variant_calc/sap_standard_vs_transfer_variant_divergence
        """
        student = register_student(
            "333445555", full_name="Sam Transfer", email="sam@example.edu",
            dependency_status="INDEPENDENT", grade_level=2,
            cumulative_attempted_credits=45, cumulative_completed_credits=30,
            gpa_hundredths=250)

        resp = api.evaluate_sap(student["id"], {}, OFFICER)
        evaluated = validate_success(resp)
        # STANDARD variant: floor(30 * 10000 / 45) = 6666 bps < 6667 -> fail.
        assert evaluated["sap_status"] == "WARNING"

    def test_transfer_variant_passing_pace_maps_to_good_standing(self, api):
        """PRD §3.2: "When `transfer_credits` is omitted or zero, the STANDARD variant runs and only the student's as-reported cumulative credits are used. When `transfer_credits` is greater than zero, the TRANSFER variant runs: the transfer credits are added to both the attempted and the completed figures before the pace division, which can flip a failing pace to passing — thirty completed of forty-five attempted yields 6,666 basis points and fails, while adding twelve transfer credits to both figures yields forty-two of fifty-seven, or 7,368 basis points, which passes."
        PRD §3.2: "If all three gates pass and the prior status is `NOT_EVALUATED`, `GOOD_STANDING`, or `WARNING`, the student becomes `GOOD_STANDING`."

        Design: Difficulty/dual_variant_calc/sap_standard_vs_transfer_variant_divergence
        """
        student = register_student(
            "333445555", full_name="Sam Transfer", email="sam@example.edu",
            dependency_status="INDEPENDENT", grade_level=2,
            cumulative_attempted_credits=45, cumulative_completed_credits=30,
            gpa_hundredths=250)
        first = validate_success(api.evaluate_sap(student["id"], {}, OFFICER))
        assert first["sap_status"] == "WARNING"

        resp = api.evaluate_sap(student["id"], {"transfer_credits": 12}, OFFICER)
        evaluated = validate_success(resp)
        # TRANSFER variant: floor((30+12) * 10000 / (45+12)) = 7368 bps >= 6667.
        assert evaluated["sap_status"] == "GOOD_STANDING"


class TestSapPaceBoundary:
    def test_pace_one_bps_below_floor_fails(self, api):
        """PRD §3.2: "The quantitative pace is computed in basis points: effective completed credits multiplied by ten thousand, divided by effective attempted credits using integer division (so the quotient is floored); if effective attempted credits are zero, the pace is treated as the full ten thousand basis points. The pace passes when it is at least 6,667 basis points, that is, 66.67 percent."
        PRD §3.2: "If any gate fails and the prior status is `NOT_EVALUATED` or `GOOD_STANDING`, the student drops to `WARNING`."

        Design: Difficulty/boundary_precision_check/sap_pace_boundary_6666_vs_6667
        """
        student = register_student(
            "333445555", full_name="Pace Fail", email="pf@example.edu",
            dependency_status="INDEPENDENT", grade_level=2,
            cumulative_attempted_credits=300, cumulative_completed_credits=200,
            gpa_hundredths=250)

        resp = api.evaluate_sap(student["id"], {}, OFFICER)
        evaluated = validate_success(resp)
        # floor(200 * 10000 / 300) = 6666 bps: one basis point under the floor.
        assert evaluated["sap_status"] == "WARNING"

    def test_zero_attempted_credits_treated_as_full_pace(self, api):
        """PRD §3.2: "if effective attempted credits are zero, the pace is treated as the full ten thousand basis points."
        PRD §3.2: "If all three gates pass and the prior status is `NOT_EVALUATED`, `GOOD_STANDING`, or `WARNING`, the student becomes `GOOD_STANDING`."

        Design: Difficulty/boundary_precision_check/sap_pace_boundary_6666_vs_6667
        """
        student = register_student(
            "123456789", full_name="Pace Zero", email="pz@example.edu",
            dependency_status="INDEPENDENT",
            cumulative_attempted_credits=0, cumulative_completed_credits=0,
            gpa_hundredths=250)

        resp = api.evaluate_sap(student["id"], {}, OFFICER)
        evaluated = validate_success(resp)
        assert evaluated["sap_status"] == "GOOD_STANDING"

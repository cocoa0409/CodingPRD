"""Acuity scoring variants and the banding boundary."""

import pytest

from test_helpers.assertions import (
    assert_assessment_math,
    assert_nurse_load,
)


HAROLD = {
    "full_name": "Harold Pike",
    "dob": "1948-09-10",
    "sex": "MALE",
    "pregnancy_status": "NOT_APPLICABLE",
    "phone": "+14155550101",
    "mrn": "MRN-0002",
}
CALLER = {
    "caller_name": "Harold Pike",
    "caller_phone": "+14155550101",
    "caller_state_code": "CA",
    "caller_relationship": "SELF",
    "reason_text": "chest tightness",
}


@pytest.fixture
def two_calls_one_patient(world):
    """One 77-year-old patient with two assigned calls on the same nurse."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        protocol={
            "code": "CHEST_PAIN",
            "base_severity": 62,
            "pregnancy_sensitive": False,
            "emergency_override": False,
            "min_disposition_level": "HOME_CARE",
        },
    )
    patient = world.create_patient("harold", **HAROLD)
    calls = []
    for reason in ("chest tightness", "chest tightness returned"):
        call = world.open_call(**dict(CALLER, reason_text=reason))
        world.match_patient(call["id"], patient["id"])
        world.record_consent(call["id"], consent_given_by="Harold Pike")
        calls.append(world.assign_nurse(call["id"], "nurse_a"))
    return calls


class TestProvisionalVersusConfirmedAcuity:
    def test_provisional_mode_scores_from_the_stated_age(
        self, world, two_calls_one_patient
    ):
        """PRD §3.5: "In `PROVISIONAL` mode the score reads the caller's own
        words: `age_years_used` is set to the supplied `stated_age_years`, and
        `pregnancy_status_used` is set to whatever `pregnancy_status` the
        practice recorded on the patient's chart."

        Design: Difficulty/dual_variant_calc/acuity_provisional_stated_age_vs_confirmed_dob_crosses_emergency_band
        """
        call = two_calls_one_patient[0]
        assessment = world.create_provisional_assessment(
            call["id"], "nurse_a", stated_age_years=60, red_flag_count=2
        )

        assert_assessment_math(
            assessment,
            age_years_used=60,
            age_modifier_points=0,
            pregnancy_modifier_points=0,
            red_flag_points=16,
            acuity_score=78,
        )
        assert assessment["pregnancy_status_used"] == "NOT_APPLICABLE", (
            "provisional mode must use the charted pregnancy status"
        )

    def test_confirmed_mode_recomputes_the_age_from_the_chart_date_of_birth(
        self, world, two_calls_one_patient
    ):
        """PRD §3.5: "Scored in confirmed mode against a chart date of birth of
        1948-09-10 with the clock at 2026-08-03, the scored age is 77, which
        earns the twelve-point geriatric modifier, and with two red flags the
        score is 90."

        Design: Difficulty/dual_variant_calc/acuity_provisional_stated_age_vs_confirmed_dob_crosses_emergency_band
        """
        call = two_calls_one_patient[1]
        assessment = world.create_assessment(
            call["id"],
            "nurse_a",
            red_flag_count=2,
            confirmed_pregnancy_status="NOT_APPLICABLE",
        )

        assert_assessment_math(
            assessment,
            age_years_used=77,
            age_modifier_points=12,
            pregnancy_modifier_points=0,
            red_flag_points=16,
            acuity_score=90,
        )

    def test_the_two_variants_recommend_different_levels_for_the_same_caller(
        self, world, two_calls_one_patient
    ):
        """PRD §3.5: "a caller who says "sixty" but whose chart date of birth is
        1948-09-10 scores 78 provisionally and 90 once confirmed, which is the
        difference between an emergency-department referral and a 911 transfer."

        Design: Difficulty/dual_variant_calc/acuity_provisional_stated_age_vs_confirmed_dob_crosses_emergency_band
        """
        provisional_call, confirmed_call = two_calls_one_patient

        provisional = world.create_provisional_assessment(
            provisional_call["id"], "nurse_a", stated_age_years=60, red_flag_count=2
        )
        confirmed = world.create_assessment(
            confirmed_call["id"],
            "nurse_a",
            red_flag_count=2,
            confirmed_pregnancy_status="NOT_APPLICABLE",
        )

        provisional_disposition = world.create_disposition(
            provisional_call["id"], provisional["id"], "ED_NOW", "nurse_a"
        )
        confirmed_disposition = world.create_disposition(
            confirmed_call["id"], confirmed["id"], "EMERGENCY_911", "nurse_a"
        )

        assert provisional_disposition["recommended_level"] == "ED_NOW", (
            "an acuity of 78 bands to ED_NOW"
        )
        assert confirmed_disposition["recommended_level"] == "EMERGENCY_911", (
            "an acuity of 90 bands to EMERGENCY_911"
        )
        assert provisional_disposition["is_override"] is False, (
            "final_level equal to recommended_level is not an override"
        )
        assert confirmed_disposition["is_override"] is False, (
            "final_level equal to recommended_level is not an override"
        )

    def test_only_the_confirmed_variant_raises_the_warm_transfer_hold(
        self, world, two_calls_one_patient
    ):
        """PRD §3.6: "When the `final_level` is `EMERGENCY_911`, the first hop
        sets the call's `requires_warm_transfer` to true".

        Design: Difficulty/dual_variant_calc/acuity_provisional_stated_age_vs_confirmed_dob_crosses_emergency_band
        """
        provisional_call, confirmed_call = two_calls_one_patient

        provisional = world.create_provisional_assessment(
            provisional_call["id"], "nurse_a", stated_age_years=60, red_flag_count=2
        )
        world.create_disposition(
            provisional_call["id"], provisional["id"], "ED_NOW", "nurse_a"
        )
        confirmed = world.create_assessment(
            confirmed_call["id"],
            "nurse_a",
            red_flag_count=2,
            confirmed_pregnancy_status="NOT_APPLICABLE",
        )
        world.create_disposition(
            confirmed_call["id"], confirmed["id"], "EMERGENCY_911", "nurse_a"
        )

        assert world.call(provisional_call["id"])["requires_warm_transfer"] is False, (
            "an ED_NOW disposition raises no warm-transfer hold"
        )
        assert world.call(confirmed_call["id"])["requires_warm_transfer"] is True, (
            "an EMERGENCY_911 disposition raises the warm-transfer hold"
        )


class TestAcuityBandingBoundary:
    """The 85/84 boundary between the emergency and ED bands."""

    @pytest.fixture
    def two_severity_calls(self, world):
        world.bootstrap(
            clock="2026-08-03T14:30:00Z",
            protocol={
                "code": "SEVERITY_61",
                "title": "Boundary Protocol Sixty One",
                "base_severity": 61,
                "pregnancy_sensitive": False,
                "emergency_override": False,
                "min_disposition_level": "HOME_CARE",
            },
        )
        world.create_protocol(
            "sixty",
            code="SEVERITY_60",
            title="Boundary Protocol Sixty",
            base_severity=60,
            pregnancy_sensitive=False,
            emergency_override=False,
            min_disposition_level="HOME_CARE",
        )
        calls = []
        for _ in range(2):
            call = world.call_through_assignment("nurse_a")
            calls.append(call)
        return calls

    def test_base_sixty_one_with_three_red_flags_scores_exactly_eighty_five(
        self, world, two_severity_calls
    ):
        """PRD §3.5: "a protocol with `base_severity` 61 and three red flags
        scores exactly 85, as does the same protocol with four red flags,
        because of the red-flag cap."

        Design: Difficulty/boundary_precision_check/acuity_exactly_85_recommends_emergency_while_84_recommends_ed_now
        """
        call = two_severity_calls[0]
        assessment = world.create_assessment(
            call["id"], "nurse_a", "protocol", red_flag_count=3
        )

        assert_assessment_math(
            assessment,
            age_years_used=36,
            age_modifier_points=0,
            pregnancy_modifier_points=0,
            red_flag_points=24,
            acuity_score=85,
        )

        disposition = world.create_disposition(
            call["id"], assessment["id"], "EMERGENCY_911", "nurse_a"
        )
        assert disposition["recommended_level"] == "EMERGENCY_911", (
            "a score of exactly 85 bands to EMERGENCY_911"
        )
        assert world.call(call["id"])["requires_warm_transfer"] is True

    def test_base_sixty_with_three_red_flags_scores_eighty_four_and_bands_lower(
        self, world, two_severity_calls
    ):
        """PRD §3.6: "A score of exactly 85 bands to `EMERGENCY_911` and a score
        of 84 bands to `ED_NOW`."

        Design: Difficulty/boundary_precision_check/acuity_exactly_85_recommends_emergency_while_84_recommends_ed_now
        """
        call = two_severity_calls[1]
        assessment = world.create_assessment(
            call["id"], "nurse_a", "sixty", red_flag_count=3
        )

        assert_assessment_math(
            assessment,
            age_years_used=36,
            age_modifier_points=0,
            pregnancy_modifier_points=0,
            red_flag_points=24,
            acuity_score=84,
        )

        disposition = world.create_disposition(
            call["id"], assessment["id"], "ED_NOW", "nurse_a"
        )
        assert disposition["recommended_level"] == "ED_NOW", (
            "a score of 84 bands to ED_NOW"
        )
        assert world.call(call["id"])["requires_warm_transfer"] is False, (
            "only an EMERGENCY_911 final level raises the warm-transfer hold"
        )

    def test_one_emergency_of_two_leaves_the_nurse_on_rotation(
        self, world, two_severity_calls
    ):
        """PRD §3.2: "it becomes `OFF_ROTATION` as soon as
        `pending_high_risk_count` reaches `high_risk_cap`, and it returns to
        `ON_ROTATION` as soon as the count falls back below the cap."

        Design: Difficulty/boundary_precision_check/acuity_exactly_85_recommends_emergency_while_84_recommends_ed_now
        """
        emergency_call, ed_call = two_severity_calls

        emergency_assessment = world.create_assessment(
            emergency_call["id"], "nurse_a", "protocol", red_flag_count=3
        )
        world.create_disposition(
            emergency_call["id"],
            emergency_assessment["id"],
            "EMERGENCY_911",
            "nurse_a",
        )
        ed_assessment = world.create_assessment(
            ed_call["id"], "nurse_a", "sixty", red_flag_count=3
        )
        world.create_disposition(
            ed_call["id"], ed_assessment["id"], "ED_NOW", "nurse_a"
        )

        assert_nurse_load(
            world.nurse("nurse_a"), active=2, high_risk=1, eligibility="ON_ROTATION"
        )

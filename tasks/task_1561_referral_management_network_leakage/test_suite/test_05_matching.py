"""Specialist matching: weighted scoring, eligibility filters, tie-breaks, assignment."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_referral, accept_referral, assign_specialist,
    create_booked_referral, set_clock, get_referral,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _auto_match(api, referral_id):
    return validate_success(api.auto_match(referral_id, COORD))


class TestWeightedScoring:
    def _setup_weighted_scenario(self, api):
        """S1 PREFERRED but fully utilized (1/1); S2 STANDARD with region match;
        S3 PREFERRED but not accepting new patients. Patient region NORTH."""
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        s1 = create_specialist(name="S1", npi="1000000001", base_region="SOUTH",
                               weekly_capacity=1)
        s2 = create_specialist(name="S2", npi="1000000002", base_region="NORTH",
                               weekly_capacity=10)
        s3 = create_specialist(name="S3", npi="1000000003", base_region="NORTH",
                               weekly_capacity=10, accepts_new_patients=False)
        create_participation(s1["id"], plan["id"], tier="PREFERRED")
        create_participation(s2["id"], plan["id"], tier="STANDARD")
        create_participation(s3["id"], plan["id"], tier="PREFERRED")
        provider = create_provider()
        patient = create_patient(plan["id"], region="NORTH")
        # One booked appointment pushes S1's utilization to 1/1 = 1.0 (>= 0.8).
        create_booked_referral(provider["id"], patient["id"], s1["id"],
                               "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
                               diagnosis_code="I10")
        subject = create_referral(provider["id"], patient["id"], diagnosis_code="I20")
        accept_referral(subject["id"])
        return plan, provider, patient, s1, s2, s3, subject

    def test_weighted_score_combination(self, api):
        """PRD §3.5: "The score starts at a base of 50. A candidate whose matching
        participation `tier` is `PREFERRED` gains 25 points; a `STANDARD` tier gains
        10 instead. A candidate whose panel utilization — the ratio of
        `booked_appointments_count` to `weekly_capacity`, compared as an exact
        rational — has reached at least 0.8 loses 15 points; the threshold is
        inclusive, so a panel at exactly 0.8 utilization takes the penalty. Urgency
        adds 20 points for a `STAT` referral, 10 for `URGENT`, and nothing for
        `ROUTINE`. A specialist whose `base_region` matches the patient's `region`
        (compared case-sensitively) gains 5 points."
        PRD §3.5: "On success the referral's `target_specialist_id` is set to the
        winner and `match_score` records the winning score."

        Design: Difficulty/combinatorial_formula/specialty_match_score_weighted
        """
        plan, provider, patient, s1, s2, s3, subject = self._setup_weighted_scenario(api)
        matched = _auto_match(api, subject["id"])
        # S2: 50 + 10 STANDARD + 0 utilization + 0 ROUTINE + 5 region = 65.
        assert matched["match_score"] == 65, (
            f"S2 must score 65 (50 base + 10 STANDARD + 5 region); got {matched['match_score']}"
        )

    def test_selection_winner_and_eligibility_exclusion(self, api):
        """PRD §3.5: "A candidate must satisfy five eligibility conditions to enter
        the pool at all: the specialist's `specialty` equals the referral's
        `specialty`; the specialist's `status` is `ACTIVE`; `accepts_new_patients` is
        true; for a `STAT`-urgency referral `accepts_urgent` must also be true; and an
        `ACTIVE` participation row must exist joining that specialist to the
        referral's `insurance_plan_id` with a window covering the current date".
        PRD §3.5: "The winner is the candidate with the highest score".

        Design: Difficulty/combinatorial_formula/specialty_match_score_weighted
        """
        plan, provider, patient, s1, s2, s3, subject = self._setup_weighted_scenario(api)
        matched = _auto_match(api, subject["id"])
        # S1 (PREFERRED but utilization 1.0) scores 50 + 25 - 15 = 60; S3 is excluded
        # by accepts_new_patients == false; S2 (65) wins despite the lower tier.
        assert matched["target_specialist_id"] == s2["id"], (
            "S2 (65) must beat S1 (60) and S3 (ineligible: accepts_new_patients false)"
        )


class TestUtilizationThresholdAndTiebreak:
    def test_utilization_penalty_at_exact_threshold_and_tiebreak(self, api):
        """PRD §3.5: "A candidate whose panel utilization — the ratio of
        `booked_appointments_count` to `weekly_capacity`, compared as an exact
        rational — has reached at least 0.8 loses 15 points; the threshold is
        inclusive, so a panel at exactly 0.8 utilization takes the penalty."
        PRD §3.5: "The winner is the candidate with the highest score; ties break in
        favor of the specialist whose `created_at` is earliest."

        Design: Corner/calculations/utilization_penalty_at_exact_threshold_and_tiebreak
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        s1 = create_specialist(name="S1", npi="1000000001", base_region="NORTH",
                               weekly_capacity=5)  # created first
        s2 = create_specialist(name="S2", npi="1000000002", base_region="NORTH",
                               weekly_capacity=10)
        create_participation(s1["id"], plan["id"], tier="PREFERRED")
        create_participation(s2["id"], plan["id"], tier="STANDARD")
        provider = create_provider()
        patient = create_patient(plan["id"], region="NORTH")
        # Four bookings on S1 -> utilization 4/5 == 0.8 exactly -> penalty applies.
        for i, start in enumerate(("10", "12", "14", "16")):
            create_booked_referral(
                provider["id"], patient["id"], s1["id"],
                f"2026-08-02T{start}:00:00Z", f"2026-08-02T{int(start) + 1:02d}:00:00Z",
                diagnosis_code=f"I1{i}",
            )
        subject = create_referral(provider["id"], patient["id"], diagnosis_code="I25")
        accept_referral(subject["id"])

        matched = _auto_match(api, subject["id"])
        # S1: 50 + 25 PREFERRED - 15 utilization + 5 region = 65.
        # S2: 50 + 10 STANDARD + 5 region = 65. Tie -> earliest created_at wins (S1).
        assert matched["target_specialist_id"] == s1["id"], (
            "Tie at 65 must break to the earlier-created specialist S1"
        )
        assert matched["match_score"] == 65, (
            "match_score 65 (not 80) proves the -15 penalty fired at exactly 0.8"
        )

    def test_match_tiebreak_created_at_when_scores_equal(self, api):
        """PRD §3.5: "The winner is the candidate with the highest score; ties break
        in favor of the specialist whose `created_at` is earliest."

        Design: Corner/calculations/match_tiebreak_created_at_when_scores_equal
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        s1 = create_specialist(name="S1", npi="1000000001", base_region="NORTH")
        s2 = create_specialist(name="S2", npi="1000000002", base_region="NORTH")
        create_participation(s1["id"], plan["id"], tier="STANDARD")
        create_participation(s2["id"], plan["id"], tier="STANDARD")
        provider = create_provider()
        patient = create_patient(plan["id"], region="NORTH")
        subject = create_referral(provider["id"], patient["id"])
        accept_referral(subject["id"])

        matched = _auto_match(api, subject["id"])
        # Both: 50 + 10 STANDARD + 0 + 0 + 5 region = 65; S1 created first wins.
        assert matched["match_score"] == 65
        assert matched["target_specialist_id"] == s1["id"]


class TestSelectorEligibility:
    def test_auto_match_empty_pool_rejected(self, api):
        """PRD §3.5: "If the eligibility filter empties the pool, the call fails with
        `ERR_NO_ELIGIBLE_SPECIALIST` (HTTP 422) and the referral is left unchanged."

        Design: Corner/cross_cutting_complexity_layers/auto_match_empty_pool_rejected
        """
        plan = create_plan()
        # Only an ORTHOPEDICS specialist exists; the referral is CARDIOLOGY.
        create_specialist(name="SO", npi="1000000009", specialty="ORTHOPEDICS")
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"], specialty="CARDIOLOGY")
        accept_referral(referral["id"])

        res = api.auto_match(referral["id"], COORD)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_SPECIALIST, expected_status=422)
        after = get_referral(referral["id"])
        assert after["target_specialist_id"] is None
        assert after["status"] == "ACCEPTED"

    def test_stat_urgency_requires_accepts_urgent(self, api):
        """PRD §3.5: "for a `STAT`-urgency referral `accepts_urgent` must also be
        true" (eligibility condition).
        PRD §3.5: "Urgency adds 20 points for a `STAT` referral, 10 for `URGENT`,
        and nothing for `ROUTINE`."

        Design: Corner/cross_cutting_complexity_layers/stat_urgency_requires_accepts_urgent_eligibility
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        s1 = create_specialist(name="S1", npi="1000000001", accepts_urgent=False)
        s2 = create_specialist(name="S2", npi="1000000002", accepts_urgent=True)
        create_participation(s1["id"], plan["id"], tier="PREFERRED")
        create_participation(s2["id"], plan["id"], tier="STANDARD")
        provider = create_provider()
        patient = create_patient(plan["id"], region="NORTH")
        referral = create_referral(provider["id"], patient["id"], urgency="STAT",
                                   diagnosis_code="I21")
        accept_referral(referral["id"])

        matched = _auto_match(api, referral["id"])
        assert matched["target_specialist_id"] == s2["id"], (
            "S1 is excluded entirely by accepts_urgent=false despite PREFERRED tier"
        )
        # S2: 50 + 10 STANDARD + 0 + 20 STAT + 5 region = 85.
        assert matched["match_score"] == 85


class TestManualAssignment:
    def test_specialty_mismatch_on_assign(self, api):
        """PRD §3.5: "Manual assignment is the alternative: a `ReferralCoordinator`
        supplies a `specialist_id`, and the system sets `target_specialist_id` to it
        while leaving `match_score` null. The same consistency rules apply as at
        booking — the specialist must exist (`ERR_SPECIALIST_NOT_FOUND`), must be
        `ACTIVE` and accepting new patients, and must share the referral's
        `specialty` or the request fails with `ERR_SPECIALTY_MISMATCH`."

        Design: Corner/validations/specialty_mismatch_on_assign
        """
        plan = create_plan()
        ortho = create_specialist(name="SO", npi="1000000009", specialty="ORTHOPEDICS")
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"], specialty="CARDIOLOGY")
        accept_referral(referral["id"])

        res = api.assign_specialist(referral["id"], {"specialist_id": ortho["id"]}, COORD)
        validate_error(res, ApiErrorId.ERR_SPECIALTY_MISMATCH, expected_status=422)
        assert get_referral(referral["id"])["target_specialist_id"] is None

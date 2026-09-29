"""Formulas whose answer depends on several independent inputs at once.

The weekly entitlement combines a grade-band base, a diagnosis factor, a
duration bonus, a special-education floor and a hard cap; the reconciliation
settlement combines a verified figure, a weekly entitlement and a service-week
count. Each test below pins which term is the binding one.
"""

import pytest

from test_helpers import (
    MIDDLE_IN_HOME_RULE,
    PA_HEADERS,
    api_client,
    log_session_delivered,
    open_case,
    read_case,
    register_student,
    review_certification,
    schedule_session,
    set_clock,
    setup_active_case,
    setup_catalogue,
    submit_certification,
    validate_success,
    verify_session,
)

HIGH_IN_HOME_RULE = {
    "grade_band": "HIGH",
    "delivery_mode": "IN_HOME",
    "base_weekly_minutes": 420,
    "cap_weekly_minutes": 600,
    "min_session_minutes": 30,
    "max_session_minutes": 150,
    "max_daily_minutes": 300,
    "min_gap_minutes": 15,
    "travel_buffer_minutes": 30,
}

MIDDLE_HYBRID_RULE = {
    "grade_band": "MIDDLE",
    "delivery_mode": "HYBRID",
    "base_weekly_minutes": 320,
    "cap_weekly_minutes": 340,
    "min_session_minutes": 20,
    "max_session_minutes": 120,
    "max_daily_minutes": 240,
    "min_gap_minutes": 15,
    "travel_buffer_minutes": 30,
}


def _iep_high_school_case_awaiting_review() -> dict:
    """A grade-11 IEP student whose submitted certification is PSYCHIATRIC over a
    45-day expected absence."""
    rules = setup_catalogue(rules=[HIGH_IN_HOME_RULE])
    student = register_student(
        student_number="S-0011",
        full_name="Rosa Vale",
        grade_level=11,
        campus_code="HS-01",
        special_ed_status="IEP",
        iep_service_minutes_weekly=700,
    )
    case = open_case(student["id"], delivery_mode="IN_HOME")
    certification = submit_certification(
        case["id"],
        physician_npi="1234567892",
        diagnosis_category="PSYCHIATRIC",
        certified_start_date="2026-09-07",
        certified_end_date="2026-10-22",
        expected_absence_days=45,
        signature_date="2026-09-01",
    )
    return {"rule": rules[0], "case": case, "certification": certification}


def _hybrid_middle_school_case_awaiting_review() -> dict:
    """A grade-6 non-special-education student whose submitted certification is
    MEDICAL_CHRONIC over a 30-day expected absence on a hybrid case."""
    rules = setup_catalogue(rules=[MIDDLE_HYBRID_RULE])
    student = register_student(
        student_number="S-0012",
        full_name="Nils Haas",
        grade_level=6,
        campus_code="MS-03",
    )
    case = open_case(student["id"], delivery_mode="HYBRID")
    certification = submit_certification(
        case["id"],
        physician_npi="1234567893",
        diagnosis_category="MEDICAL_CHRONIC",
        certified_start_date="2026-09-07",
        certified_end_date="2026-10-07",
        expected_absence_days=30,
        signature_date="2026-09-01",
    )
    return {"rule": rules[0], "case": case, "certification": certification}


def _case_with_six_hundred_verified_minutes() -> dict:
    """An ACTIVE / ACCRUING case with five verified 120-minute sessions spread over
    two ISO weeks, with the clock parked at 2026-09-20T00:00:00Z."""
    bundle = setup_active_case(
        rules=[MIDDLE_IN_HOME_RULE],
        certification={
            "expected_absence_days": 30,
            "certified_start_date": "2026-09-07",
            "certified_end_date": "2026-10-07",
            "signature_date": "2026-09-01",
        },
        safety_review={"hazard_findings": ["UNLIT_ACCESS"], "escort_available": False},
    )
    days = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-14", "2026-09-15"]
    subjects = ["MATH", "ELA", "MATH", "ELA", "MATH"]
    sessions = [
        schedule_session(
            bundle["case"]["id"],
            bundle["primary_assignment"]["id"],
            scheduled_start=f"{day}T09:00:00Z",
            scheduled_end=f"{day}T11:00:00Z",
            delivery_mode="IN_HOME",
            subject=subject,
        )
        for day, subject in zip(days, subjects)
    ]
    set_clock("2026-09-16T18:00:00Z")
    for session in sessions:
        log_session_delivered(session["id"], bundle["teacher"]["id"], 120)
    for session in sessions:
        verify_session(session["id"])
    set_clock("2026-09-20T00:00:00Z")
    bundle["sessions"] = sessions
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


class TestSpedFloorDominatesTheEntitlementFormula:
    """A 700-minute IEP floor overrides a discounted base plus its duration bonus."""

    def test_iep_floor_beats_the_psychiatric_discount_and_the_duration_bonus(self):
        """420 base minutes discounted to 336 and bonused to 366 still lose to the
        420-minute special-education floor, and the 600-minute cap never binds.

        The PRD states: "When the student's `special_ed_status` is `IEP`, the floor
        is the student's `iep_service_minutes_weekly` multiplied by 0.60 and rounded
        half up to a whole minute; for any other special-education status the floor
        is 0. The entitlement is then the larger of the adjusted entitlement and the
        floor, and that larger value is finally clamped down to the rule's
        `cap_weekly_minutes` if it exceeds it."

        Design: Difficulty/combinatorial_formula/entitlement_sped_floor_dominates_psychiatric_dx_factor_and_duration_bonus
        """
        bundle = _iep_high_school_case_awaiting_review()

        review_certification(bundle["certification"]["id"], "ACCEPT")
        case = read_case(bundle["case"]["id"])

        assert case["entitlement_rule_id"] == bundle["rule"]["id"], (
            "the HIGH / IN_HOME published rule is the one that matches"
        )
        assert case["weekly_entitled_minutes"] == 420, (
            "700 IEP minutes at 0.60 is 420, which dominates the 366-minute "
            "diagnosis-and-bonus figure"
        )
        assert case["diagnosis_category"] == "PSYCHIATRIC", (
            "the case absorbs the accepted certification's diagnosis category"
        )

    def test_acceptance_makes_the_certification_current_and_the_case_eligible(self):
        """Accepting the certification turns it ACCEPTED and current, advances the
        case to ELIGIBLE, and recomputes the accepted-certification count to one.

        The PRD states: "On acceptance the certification's `status` becomes
        `ACCEPTED` and its `is_current` becomes true, and any certification of the
        same case that previously held `is_current` true is moved to `SUPERSEDED`
        with its `is_current` set false; exactly one accepted certification per case
        is current at any moment."

        Design: Difficulty/combinatorial_formula/entitlement_sped_floor_dominates_psychiatric_dx_factor_and_duration_bonus
        """
        bundle = _iep_high_school_case_awaiting_review()

        accepted = review_certification(bundle["certification"]["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["is_current"] is True

        case = read_case(bundle["case"]["id"])
        assert case["service_status"] == "ELIGIBLE", (
            "the case advances from PENDING_CERT_REVIEW to ELIGIBLE on acceptance"
        )
        assert case["certification_count"] == 1, (
            "certification_count counts this case's ACCEPTED certifications"
        )


class TestCapClampsTheHybridEntitlement:
    """A 340-minute ceiling clips a 350-minute unclamped result."""

    def test_cap_clamps_the_base_plus_bonus_result(self):
        """320 base minutes at a 1.00 factor plus the 30-minute bonus reaches 350 and
        is clamped down to the rule's 340-minute ceiling.

        The PRD states: "In other words: take the greater of adjusted entitlement and
        floor, then take the lesser of that result and the cap."

        Design: Difficulty/combinatorial_formula/entitlement_cap_clamps_hybrid_base_plus_duration_bonus
        """
        bundle = _hybrid_middle_school_case_awaiting_review()

        review_certification(bundle["certification"]["id"], "ACCEPT")
        case = read_case(bundle["case"]["id"])

        assert case["entitlement_rule_id"] == bundle["rule"]["id"], (
            "the MIDDLE / HYBRID published rule is the one that matches"
        )
        assert case["weekly_entitled_minutes"] == 340, (
            "the unclamped 350 minutes is clipped to cap_weekly_minutes 340"
        )

    def test_case_absorbs_the_accepted_certified_window(self):
        """Acceptance copies the certified window onto the case as it advances to
        ELIGIBLE.

        The PRD states: "The case then advances from `PENDING_CERT_REVIEW` to
        `ELIGIBLE` and absorbs the accepted document: the case's
        `diagnosis_category`, `certified_start_date` and `certified_end_date` are
        copied from the accepted certification, and `certification_count` is
        recomputed as the number of that case's certifications whose `status` is
        `ACCEPTED`."

        Design: Difficulty/combinatorial_formula/entitlement_cap_clamps_hybrid_base_plus_duration_bonus
        """
        bundle = _hybrid_middle_school_case_awaiting_review()

        review_certification(bundle["certification"]["id"], "ACCEPT")
        case = read_case(bundle["case"]["id"])

        assert case["certified_start_date"] == "2026-09-07"
        assert case["certified_end_date"] == "2026-10-07"
        assert case["service_status"] == "ELIGIBLE"


class TestRecaptureTierSelection:
    """Three quantities combine into a ratio that picks one of four bands."""

    def test_ratio_of_zero_point_seven_seven_recaptures_ten_percent(self):
        """600 verified minutes against a 780-minute entitled total is a 0.77 ratio,
        which recaptures ten percent of the 180-minute shortfall.

        The PRD states: "A ratio of 0.90 or above recaptures nothing. A ratio below
        0.90 but at least 0.75 recaptures ten percent. A ratio below 0.75 but at
        least 0.50 recaptures twenty-five percent. A ratio below 0.50 forfeits."

        Design: Difficulty/combinatorial_formula/recapture_tier_selection_from_ratio_zero_point_seven_seven
        """
        bundle = _case_with_six_hundred_verified_minutes()

        reconciled = validate_success(
            api_client.reconcile_case_funding(bundle["case"]["id"], PA_HEADERS)
        )
        assert reconciled["delivery_ratio_pct"] == pytest.approx(0.77, abs=0.01), (
            "600 divided by 780 is 0.7692, which rounds half up to 0.77"
        )
        assert reconciled["recapture_minutes"] == 18, (
            "ten percent of the 180-minute shortfall is 18 minutes"
        )
        assert reconciled["net_apportionment_minutes"] == 582, (
            "600 raw final minutes less 18 recaptured minutes"
        )
        assert reconciled["funding_status"] == "RECONCILED", (
            "a non-forfeit band moves the funding posture ACCRUING to RECONCILED"
        )

    def test_raw_final_figure_and_entitled_total_feed_the_ratio(self):
        """No ISO week exceeds 390 minutes, so the whole 600 minutes survives the walk
        and is measured against two service weeks.

        The PRD states: "The entitled total is the case's `weekly_entitled_minutes`
        multiplied by service weeks."

        Design: Difficulty/combinatorial_formula/recapture_tier_selection_from_ratio_zero_point_seven_seven
        """
        bundle = _case_with_six_hundred_verified_minutes()
        case_id = bundle["case"]["id"]

        assert bundle["case"]["reported_apportionment_minutes"] == 600, (
            "five sessions credited 120 minutes each"
        )

        summary = validate_success(api_client.get_funding_summary(case_id, PA_HEADERS))
        assert summary["service_weeks"] == 2, (
            "two elapsed weeks is the lesser of the elapsed and window counts"
        )
        assert summary["entitled_total_minutes"] == 780, "390 minutes over two weeks"

        reconciled = validate_success(
            api_client.reconcile_case_funding(case_id, PA_HEADERS)
        )
        assert reconciled["final_apportionment_minutes"] == 600, (
            "360 minutes in ISO week 37 and 240 in ISO week 38 both fit under the "
            "390-minute weekly entitlement"
        )

"""Enrollment submission, certification, tuition cap, and Yellow Ribbon
waterfall — PRD §3.6, §3.7."""
from __future__ import annotations

import pytest

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certify_enrollment,
    create_enrollment,
    create_enrollment_payload,
    create_school,
    create_veteran,
    current_clock,
    grant_claim_for_veteran,
    iso_utc,
    make_va_clerk_headers,
    make_veteran_headers,
    setup_certified_enrollment,
    setup_veteran_with_granted_claim,
    utc_midnight,
    validate_error,
    validate_success,
)


# ===========================================================================
# Term-range validity — PRD §3.6
# ===========================================================================
class TestTermRange:

    def test_term_end_before_term_start_rejected(self, api):
        """PRD §3.6: "term_end MUST be strictly greater than term_start;
        an empty or inverted range is rejected with
        ERR_INVALID_TERM_RANGE."
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        term_start = iso_utc(utc_midnight(base + timedelta(days=120)))
        term_end = iso_utc(utc_midnight(base))
        resp = api.create_enrollment(
            create_enrollment_payload(
                veteran_id=vet["id"],
                school_id=school["id"],
                term_start=term_start,
                term_end=term_end,
                tuition_charged=10000.00,
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM_RANGE.value)

    def test_term_end_equal_to_term_start_rejected(self, api):
        """PRD §3.6: "term_end MUST be strictly greater than term_start"
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        same = iso_utc(utc_midnight(base))
        resp = api.create_enrollment(
            create_enrollment_payload(
                veteran_id=vet["id"],
                school_id=school["id"],
                term_start=same,
                term_end=same,
                tuition_charged=10000.00,
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM_RANGE.value)


# ===========================================================================
# Enrollment overlap — PRD §3.6
# ===========================================================================
class TestEnrollmentOverlap:

    def test_adjacent_enrollments_allowed_half_open_interval(self, api):
        """PRD §3.6: "Because the interval is half-open, an enrollment
        ending exactly at midnight on the day a successor begins is
        treated as non-overlapping."

        # difficulty: resource_temporal_overlap/enrollment_term_half_open_overlap
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)

        a_start = iso_utc(utc_midnight(base))
        a_end = iso_utc(utc_midnight(base + timedelta(days=90)))
        b_start = a_end  # adjacency at midnight
        b_end = iso_utc(utc_midnight(base + timedelta(days=180)))

        create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=a_start, term_end=a_end,
            tuition_charged=10000.00,
        )
        # Adjacent enrollment must be allowed.
        resp = api.create_enrollment(
            create_enrollment_payload(
                veteran_id=vet["id"],
                school_id=school["id"],
                term_start=b_start,
                term_end=b_end,
                tuition_charged=10000.00,
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_overlapping_enrollments_rejected(self, api):
        """PRD §3.6: "The system additionally enforces that this
        veteran has no other enrollment in SUBMITTED, CERTIFIED, or
        ACTIVE whose half-open interval [term_start, term_end) overlaps
        the new one — overlap is rejected with ERR_ENROLLMENT_OVERLAP."

        # difficulty: resource_temporal_overlap/enrollment_term_half_open_overlap
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        a_start = iso_utc(utc_midnight(base))
        a_end = iso_utc(utc_midnight(base + timedelta(days=90)))
        # 1-day overlap (ends one day after the first ends... overlap by
        # the day a_end-1 to a_end which is inside [a_start, a_end)).
        b_start = iso_utc(utc_midnight(base + timedelta(days=89)))
        b_end = iso_utc(utc_midnight(base + timedelta(days=180)))

        create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=a_start, term_end=a_end,
            tuition_charged=10000.00,
        )
        resp = api.create_enrollment(
            create_enrollment_payload(
                veteran_id=vet["id"],
                school_id=school["id"],
                term_start=b_start,
                term_end=b_end,
                tuition_charged=10000.00,
            ),
            make_veteran_headers(vet["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_OVERLAP.value)


# ===========================================================================
# Certification + tuition cap — PRD §3.7
# ===========================================================================
class TestCertificationGate:

    def test_certify_with_non_honorable_discharge_rejected(self, api):
        """PRD §3.7: "the owning veteran's discharge_status MUST be
        HONORABLE — any other discharge status is rejected with
        ERR_INELIGIBLE_DISCHARGE."
        """
        from test_helpers import certify_enrollment as _ce  # noqa: F401
        # Veteran with GENERAL discharge (not HONORABLE).
        from test_helpers.fixtures import create_veteran as _cv
        vet = _cv(
            aggregate_active_duty_days=1100,
            discharge_status="GENERAL",
        )
        # We still need a granted claim so combined_rating > 0; but the
        # certification itself only requires HONORABLE. The claim itself
        # isn't gated on HONORABLE. So we can skip granting; we only need
        # an enrollment in SUBMITTED.
        school = create_school(program_type="PUBLIC_IN_STATE")
        base = current_clock().date() + timedelta(days=30)
        enrollment = create_enrollment(
            veteran_id=vet["id"], school_id=school["id"],
            term_start=iso_utc(utc_midnight(base)),
            term_end=iso_utc(utc_midnight(base + timedelta(days=120))),
            tuition_charged=10000.00,
        )
        resp = api.certify_enrollment(
            enrollment["id"], TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INELIGIBLE_DISCHARGE.value)


class TestTuitionPayableCompute:

    def test_public_in_state_full_tier(self, api):
        """PRD §3.7: "a PUBLIC_IN_STATE school is treated as effectively
        uncapped (a sentinel ceiling of 100000.00 dollars per term is
        used, which exceeds plausible in-state tuition) ... That capped
        figure is then multiplied by the veteran's
        post_911_eligibility_tier expressed as a fraction (so a tier of
        100 means multiply by 1.00 ... The final product is rounded
        half-up to two decimal places exactly once".

        Tuition 5000 charged, tier 100, public-in-state cap 100000 ->
        min(5000, 100000) * 1.00 = 5000.00.
        """
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        certified = bundle["enrollment"]
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_tuition_payable"] == pytest.approx(
            5000.00, abs=0.01,
        )

    def test_private_national_tier_80_pin_sum_then_round(self, api):
        """PRD §3.7: "a PRIVATE_NATIONAL or FOREIGN school caps at
        13041.34 dollars per term ... The final product is rounded
        half-up to two decimal places exactly once, at the very end —
        rounding the cap before the multiplication is not equivalent
        and is not what the system does."

        730 days -> tier 80; charged 20000 -> min(20000, 13041.34) *
        0.80 = 10433.072 -> 10433.07 (half-up at 2dp).

        # difficulty: combinatorial_formula/tuition_payable_rounding_order_pinned
        """
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=730,  # tier 80
            program_type="PRIVATE_NATIONAL",
            tuition_charged=20000.00,
        )
        certified = bundle["enrollment"]
        assert certified["status"] == "CERTIFIED"
        # 13041.34 * 0.80 = 10433.072 -> round half-up 2dp = 10433.07.
        assert certified["certified_tuition_payable"] == pytest.approx(
            10433.07, abs=0.01,
        )

    def test_voc_tech_cap_applied(self, api):
        """PRD §3.7: "a VOC_TECH school caps at 6520.67 dollars per
        term."

        Charged 10000, tier 100 -> min(10000, 6520.67) * 1.00 = 6520.67.
        """
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,
            program_type="VOC_TECH",
            tuition_charged=10000.00,
        )
        certified = bundle["enrollment"]
        assert certified["certified_tuition_payable"] == pytest.approx(
            6520.67, abs=0.01,
        )

    def test_tier_zero_yields_zero_payable(self, api):
        """PRD §3.7: "a tier of 0 means multiply by 0.00."
        """
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=50,  # tier 0
            program_type="PUBLIC_IN_STATE",
            tuition_charged=5000.00,
        )
        certified = bundle["enrollment"]
        assert certified["certified_tuition_payable"] == pytest.approx(
            0.00, abs=0.01,
        )


# ===========================================================================
# Yellow Ribbon waterfall — PRD §3.7
# ===========================================================================
class TestYellowRibbonWaterfall:

    def test_yellow_ribbon_tier_100_capped_by_school_cap(self, api):
        """PRD §3.7: "The school's contribution is the smaller of two
        ceilings: the school's per-year cap yellow_ribbon_max_per_year,
        and half of the tuition gap floored to whole cents ... The VA's
        match (va_match) is exactly equal to the school's contribution
        ... The student's remaining responsibility
        (student_responsibility) is the tuition gap minus the school
        contribution minus the VA match".

        Tuition 20000, cap 13041.34, gap 6958.66. School cap 2000 (less
        than 3479.33 half). school = 2000, va = 2000, student = 2958.66.
        Tuition payable = 13041.34.

        # difficulty: combinatorial_formula/yellow_ribbon_circular_evaluation_pinned
        """
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=1100,  # tier 100
            program_type="PRIVATE_NATIONAL",
            yellow_ribbon_enrolled=True,
            yellow_ribbon_max_per_year=2000.00,
            tuition_charged=20000.00,
        )
        enrollment = bundle["enrollment"]
        assert enrollment["certified_tuition_payable"] == pytest.approx(
            13041.34, abs=0.01,
        )
        # Fetch the YellowRibbonContribution.
        resp = api.get_yellow_ribbon(
            enrollment["id"], TEST_USERS["va_clerk_headers"],
        )
        yr = validate_success(resp)
        assert yr["tuition_gap"] == pytest.approx(6958.66, abs=0.01)
        assert yr["school_contribution"] == pytest.approx(2000.00, abs=0.01)
        assert yr["va_match"] == pytest.approx(2000.00, abs=0.01)
        assert yr["student_responsibility"] == pytest.approx(2958.66, abs=0.01)

    def test_yellow_ribbon_tier_below_100_collapses_to_student(self, api):
        """PRD §3.7: "There is a critical eligibility gate: a Yellow
        Ribbon match is only available when the veteran's
        post_911_eligibility_tier equals 100; if it is below 100 (or
        if the veteran is not on the GI Bill at all), the school's
        contribution and the VA match are both forced to 0.00 and the
        entire tuition gap is rounded half-up and assigned as the
        student's responsibility."
        """
        # 730 days -> tier 80; charged 20000; cap 13041.34; gap 6958.66.
        # Tier 80 -> school=0, va=0, student=6958.66.
        bundle = setup_certified_enrollment(
            granted_rating=10,
            aggregate_active_duty_days=730,  # tier 80
            program_type="PRIVATE_NATIONAL",
            yellow_ribbon_enrolled=True,
            yellow_ribbon_max_per_year=2000.00,
            tuition_charged=20000.00,
        )
        enrollment = bundle["enrollment"]
        # Tuition payable at tier 80: 13041.34 * 0.80 = 10433.07.
        assert enrollment["certified_tuition_payable"] == pytest.approx(
            10433.07, abs=0.01,
        )
        resp = api.get_yellow_ribbon(
            enrollment["id"], TEST_USERS["va_clerk_headers"],
        )
        yr = validate_success(resp)
        assert yr["school_contribution"] == pytest.approx(0.00, abs=0.01)
        assert yr["va_match"] == pytest.approx(0.00, abs=0.01)
        # gap = 20000 - 13041.34 = 6958.66 (since cap math uses
        # max_per_term, not tier-adjusted figure, per PRD §3.7 'the
        # difference between tuition_charged and the cap').
        assert yr["student_responsibility"] == pytest.approx(
            6958.66, abs=0.01,
        )

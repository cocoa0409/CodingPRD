"""Instructor fee calculation (PRD §3.6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    drive_session_to_completed,
    iso_utc,
    run_sweep,
    setup_completed_enrollment,
    setup_open_session,
    validate_success,
)


SESSION_START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
SESSION_END_4H = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
ENROLL_DEADLINE = datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc)


def _fee_from(resp_data: dict) -> float:
    """Extract the total fee from the /instructor-fee response.

    PRD §3.6: "The instructor fee ... When the instructor's
    instructor_type is EXTERNAL, the total is the base_fee plus the
    instructor's travel_cost (added after the base_fee has already
    been rounded). When the instructor_type is INTERNAL, the total is
    zero regardless of the instructor's hourly_rate."

    PRD does not pin a specific field name for the total, so we
    accept any of {total, total_fee, fee, payable, amount, total_cents}
    that resolves to a numeric. If none is present, the test should
    surface that as a failure."""
    for k in ("total", "total_fee", "fee", "payable", "amount"):
        if k in resp_data and isinstance(resp_data[k], (int, float)):
            return float(resp_data[k])
    raise AssertionError(
        "PRD §3.6: GET /sessions/{id}/instructor-fee must return a numeric "
        "total field; none of {total, total_fee, fee, payable, amount} "
        f"present in response data {resp_data!r}"
    )


# ===========================================================================
# External — tier 1 boundary (PRD §3.6)
# ===========================================================================
class TestInstructorFeeExternalTier1:

    def test_external_two_hour_session_pays_tier_one(
        self, api, training_admin_headers,
    ):
        """PRD §3.6: "when effective_hours falls in the inclusive
        range from 0.5 to 2.0 the multiplier is 1.00 ... base_fee is
        computed as hourly_rate (from the pinned snapshot frozen at
        session creation) multiplied by effective_hours multiplied by
        the tier multiplier, and the result is rounded half-up to
        two decimal places ... when the instructor's instructor_type
        is EXTERNAL, the total is the base_fee plus the instructor's
        travel_cost."

        Claim: duration=2.0, hourly_rate=200, travel_cost=50,
        EXTERNAL -> total = round(200*2.0*1.00, 2) + 50 = 450.00.
        """
        ctx = setup_completed_enrollment(
            duration_hours=2.0, credit_value=2.0,
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=False,
            start_at=SESSION_START,
            end_at=SESSION_START + timedelta(hours=2),
            enrollment_deadline=ENROLL_DEADLINE,
        )
        resp = api.get_instructor_fee(ctx["session"]["id"],
                                      training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert _fee_from(data) == pytest.approx(450.00, abs=0.01), (
            f"Expected fee=450.00, got {data}"
        )


# ===========================================================================
# External — tier 2 (PRD §3.6) — duration above 2.0 hits 0.95 multiplier
# ===========================================================================
class TestInstructorFeeExternalTier2:

    def test_external_two_point_five_hour_session_pays_tier_two(
        self, api, training_admin_headers,
    ):
        """PRD §3.6: "when it is strictly greater than 2.0 and at or
        below 5.0 the multiplier is 0.95 ... the result is rounded
        half-up to two decimal places ... total is the base_fee plus
        the instructor's travel_cost."

        Claim: duration=2.5, hourly_rate=200, travel_cost=50,
        EXTERNAL -> total = round(200*2.5*0.95, 2) + 50 = 475.00 + 50
        = 525.00.
        """
        ctx = setup_completed_enrollment(
            duration_hours=2.5, credit_value=2.5,
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=False,
            start_at=SESSION_START,
            end_at=SESSION_START + timedelta(hours=2, minutes=30),
            enrollment_deadline=ENROLL_DEADLINE,
        )
        resp = api.get_instructor_fee(ctx["session"]["id"],
                                      training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert _fee_from(data) == pytest.approx(525.00, abs=0.01), (
            f"Expected fee=525.00, got {data}"
        )


# ===========================================================================
# Internal — zero fee (PRD §3.6)
# ===========================================================================
class TestInstructorFeeInternal:

    def test_internal_fee_is_zero_regardless_of_duration(
        self, api, training_admin_headers,
    ):
        """PRD §3.6: "When the instructor_type is INTERNAL, the total
        is zero regardless of the instructor's hourly_rate — internal
        time is tracked but not paid out."

        Claim: INTERNAL instructor -> total = 0.
        """
        # Build a session with an INTERNAL instructor. The
        # setup_completed_enrollment helper accepts instructor_type
        # indirectly through setup_open_session; here we wire it
        # explicitly by constructing the open session ourselves.
        env = setup_open_session(
            duration_hours=4.0, credit_value=4.0,
            instructor_type="INTERNAL",
            start_at=SESSION_START, end_at=SESSION_END_4H,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # Advance past end_at and complete (no enrollments needed for the
        # fee endpoint to compute).
        advance_clock_to(SESSION_END_4H + timedelta(minutes=1))
        run_sweep()
        # Complete; ignore the (empty) cascade.
        api.complete_session(env["session"]["id"], training_admin_headers)
        resp = api.get_instructor_fee(env["session"]["id"],
                                      training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert _fee_from(data) == pytest.approx(0.0, abs=0.01), (
            f"Expected fee=0 for INTERNAL instructor, got {data}"
        )

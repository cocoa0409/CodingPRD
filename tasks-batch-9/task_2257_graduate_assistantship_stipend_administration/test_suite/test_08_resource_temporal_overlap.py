"""Date-window collisions where the inclusive-versus-exclusive choice decides.

Appointment windows are inclusive at both ends, so touching on one day counts as
overlapping; pay-period coverage is half-open, so touching on one day does not.
The two scenarios put those opposite conventions side by side.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEPT_ADMIN,
    GS_ADMIN,
    MONTHLY_PERIODS_AUTUMN_2026,
    api_client,
    build_term_frame,
    fund_wholly_from,
    make_appointment,
    make_funding_source,
    make_pay_period,
    make_student,
    make_term,
    pay_period_payload,
    read_appointment,
    read_student,
    read_term,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Appointment windows: both ends of the intersection test are inclusive
# --------------------------------------------------------------------------- #


def _build_touching_and_disjoint_successors():
    """One submitted appointment ending 2026-11-30 and two drafted candidates.

    The first candidate starts on 2026-11-30 — the incumbent's very last day — and
    the second starts on 2026-12-01, one day later.  Each is 50 percent effort
    against a default 75 percent cap, so a single day of overlap is the difference
    between 100 and 50 percent aggregate effort.
    """
    frame = build_term_frame(
        department={"code": "MUSI", "name": "Music"},
        term={
            "term_code": "OVL2026", "term_start": "2026-09-01",
            "term_end": "2026-12-31", "tax_calendar_year": 2026,
            "session_type": "IN_SESSION", "proration_method": "CALENDAR_DAY",
            "remission_drop_deadline": "2026-11-15",
        },
        policy={
            "assistantship_type": "RESEARCH", "degree_level": "DOCTORAL",
            "min_fte_monthly_stipend_cents": 400000,
            "per_credit_tuition_cents": 50000,
            "max_remission_cents_per_term": 500000,
            "term_insurance_premium_cents": 0,
        },
        pay_periods=MONTHLY_PERIODS_AUTUMN_2026,
    )
    student = make_student(
        student_number="GS-OVL-001", full_name="Ovl Student",
        degree_level="DOCTORAL", cumulative_gpa=3.60, enrolled_credit_hours=0,
    )
    source = make_funding_source(
        frame["department_id"], source_code="NSF-OVL-01", source_type="GRANT",
        authorized_amount_cents=10000000,
    )

    def _draft(start_date, end_date):
        appointment = make_appointment(
            student["id"], frame["department_id"], frame["term_id"],
            assistantship_type="RESEARCH", effort_pct=50,
            start_date=start_date, end_date=end_date,
            monthly_stipend_cents=200000,
        )
        fund_wholly_from(appointment["id"], source["id"])
        return appointment

    incumbent = _draft("2026-09-01", "2026-11-30")
    validate_success(api_client.submit_appointment(incumbent["id"], DEPT_ADMIN))
    touching = _draft("2026-11-30", "2026-12-31")
    disjoint = _draft("2026-12-01", "2026-12-31")
    return {
        "student_id": student["id"],
        "incumbent_id": incumbent["id"],
        "touching_id": touching["id"],
        "disjoint_id": disjoint["id"],
    }


def test_appointments_touching_on_a_single_day_breach_the_effort_cap():
    """A one-day overlap is an overlap, so the aggregate reaches 100 percent.

    PRD: "The overlapping set is every other appointment of the same student —
    excluding the candidate itself — that is in a counted state and whose
    `start_date` falls on or before the candidate's `end_date` while its
    `end_date` falls on or after the candidate's `start_date`; both ends of that
    intersection test are inclusive, so two appointments that merely touch on a
    single day do overlap." PRD: "Then the **aggregate effort cap**: the student's
    `total_effort_pct` computed with this appointment included must not exceed the
    student's `effort_cap_pct`, with a value exactly equal to the cap passing and
    anything above rejected as `ERR_OVER_APPOINTMENT`."

    Design: Difficulty/resource_temporal_overlap/over_appointment_on_single_day_inclusive_window_touch
    """
    world = _build_touching_and_disjoint_successors()

    response = api_client.submit_appointment(world["touching_id"], DEPT_ADMIN)

    validate_error(response, ApiErrorId.ERR_OVER_APPOINTMENT.value, 422)

    rejected = read_appointment(world["touching_id"])
    assert rejected["lifecycle_status"] == "DRAFT"
    assert rejected["total_stipend_cents"] == 0
    assert rejected["duration_days"] == 32, (
        "2026-11-30 through 2026-12-31 inclusive is 32 days"
    )


def test_an_appointment_starting_the_next_day_submits_and_prorates_alone():
    """Moving the start one day later removes the overlap entirely.

    PRD: "The aggregate `total_effort_pct` is the candidate's `effort_pct` plus
    the sum of `effort_pct` over that overlapping set. The
    `assigned_hours_per_week` figure is that aggregate divided by 100, multiplied
    by 40, rounded half up to one decimal place."

    Design: Difficulty/resource_temporal_overlap/over_appointment_on_single_day_inclusive_window_touch
    """
    world = _build_touching_and_disjoint_successors()
    api_client.submit_appointment(world["touching_id"], DEPT_ADMIN)

    accepted = validate_success(
        api_client.submit_appointment(world["disjoint_id"], DEPT_ADMIN)
    )

    assert accepted["lifecycle_status"] == "SUBMITTED"
    assert accepted["duration_days"] == 31, (
        "2026-12-01 through 2026-12-31 inclusive is 31 days"
    )
    assert accepted["projected_pay_period_count"] == 1, (
        "only the December pay period intersects the window"
    )
    assert accepted["total_stipend_cents"] == 200000

    incumbent = read_appointment(world["incumbent_id"])
    assert incumbent["projected_pay_period_count"] == 3
    assert incumbent["total_stipend_cents"] == 600000

    student = read_student(world["student_id"])
    assert student["total_effort_pct"] == 50, (
        "the two surviving appointments never share a day"
    )
    assert float(student["assigned_hours_per_week"]) == pytest.approx(20.0, abs=0.01)


# --------------------------------------------------------------------------- #
# Pay-period coverage: half-open, so adjacency is allowed
# --------------------------------------------------------------------------- #


def _build_planning_term_with_september():
    """A PLANNING term whose calendar so far holds only September."""
    term = make_term(
        term_code="PPO2026", term_start="2026-09-01", term_end="2026-12-31",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-11-15",
    )
    first = make_pay_period(
        term["id"], 1, "2026-09-01", "2026-10-01", "2026-10-05"
    )
    return term, first


def test_a_pay_period_starting_on_the_previous_periods_end_date_is_accepted():
    """Exact adjacency under half-open semantics is explicitly allowed.

    PRD: "A new period must not overlap an existing period of the same term;
    overlap is judged under half-open semantics, so the request is rejected with
    `ERR_PAY_PERIOD_OVERLAP` when the new period's `period_start` falls before an
    existing period's `period_end_exclusive` **and** that existing period's
    `period_start` falls before the new period's `period_end_exclusive`. Exact
    adjacency — a new period starting on the very date an existing period stops
    covering — is explicitly allowed." PRD: "Two counts are derived at creation
    and stored: `calendar_day_count`, the number of whole days from `period_start`
    up to but excluding `period_end_exclusive`, and `workday_count`, the number of
    Monday-through-Friday dates in that same half-open range."

    Design: Difficulty/resource_temporal_overlap/pay_period_half_open_adjacency_allowed_overlap_rejected
    """
    term, first = _build_planning_term_with_september()

    second = validate_success(api_client.create_pay_period(
        pay_period_payload(term["id"], 2, "2026-10-01", "2026-11-01",
                           "2026-11-05"),
        GS_ADMIN,
    ), expected_status=201)

    assert second["period_start"] == "2026-10-01", (
        "the new period starts on the day the previous one stopped covering"
    )
    assert second["calendar_day_count"] == 31, "October 2026 has 31 days"
    assert second["workday_count"] == 22, "October 2026 has 22 weekdays"
    assert second["status"] == "OPEN"

    assert first["calendar_day_count"] == 30, "September 2026 has 30 days"
    assert first["workday_count"] == 22, "September 2026 has 22 weekdays"


def test_a_pay_period_starting_one_day_early_overlaps_and_is_rejected():
    """Starting on 2026-09-30 reaches back into September and is refused.

    PRD: "23. **Pay period overlap** — `ERR_PAY_PERIOD_OVERLAP` (409), guarding
    pay-period creation." PRD: "Each accepted period recomputes the term's
    `pay_period_count`, which is simply the number of pay periods whose `term_id`
    is that term."

    Design: Difficulty/resource_temporal_overlap/pay_period_half_open_adjacency_allowed_overlap_rejected
    """
    term, _ = _build_planning_term_with_september()
    validate_success(api_client.create_pay_period(
        pay_period_payload(term["id"], 2, "2026-10-01", "2026-11-01",
                           "2026-11-05"),
        GS_ADMIN,
    ), expected_status=201)

    response = api_client.create_pay_period(
        pay_period_payload(term["id"], 3, "2026-09-30", "2026-10-15",
                           "2026-10-20"),
        GS_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_PAY_PERIOD_OVERLAP.value, 409)

    periods, meta = validate_paginated(api_client.list_term_pay_periods(
        term["id"], GS_ADMIN, {"limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 2, "the overlapping period was never stored"
    assert [p["sequence_no"] for p in periods] == [1, 2]

    stored_term = read_term(term["id"])
    assert stored_term["pay_period_count"] == 2
    assert stored_term["status"] == "PLANNING"

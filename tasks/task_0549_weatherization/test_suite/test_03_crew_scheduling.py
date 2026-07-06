"""Crew scheduling: overlap, dwelling-buffer, capacity, the install side effect,
and crew-day conservation on cancel."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_crew_assignment_payload,
    new_dwelling,
    new_job,
    new_crew,
    setup_crew_double_booked_precondition,
    setup_dwelling_window_precondition,
    setup_scheduled_assignment,
)


def test_overlapping_window_same_crew_rejected(api, program_admin_headers):
    """PRD 3.5: "the requested window may not overlap any window of another
    assignment for the same crew that is currently `SCHEDULED`, or the request
    fails with `ERR_CREW_DOUBLE_BOOKED`".

    Design: Difficulty/resource_temporal_overlap/crew_double_booked_half_open_overlap
    """
    ctx = setup_crew_double_booked_precondition()
    payload = create_crew_assignment_payload(
        ctx["job_b"]["id"], ctx["crew"]["id"],
        scheduled_start_date="2026-06-05T00:00:00Z", scheduled_end_date="2026-06-12T00:00:00Z",
    )
    res = api.create_crew_assignment(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)


def test_double_book_leaves_committed_days_unchanged(api, program_admin_headers):
    """PRD 3.5: "`committed_days`, the sum of `duration_days` over that crew's
    assignments currently in `SCHEDULED` status".

    Design: Difficulty/resource_temporal_overlap/crew_double_booked_half_open_overlap
    """
    ctx = setup_crew_double_booked_precondition()
    payload = create_crew_assignment_payload(
        ctx["job_b"]["id"], ctx["crew"]["id"],
        scheduled_start_date="2026-06-05T00:00:00Z", scheduled_end_date="2026-06-12T00:00:00Z",
    )
    api.create_crew_assignment(payload, program_admin_headers)
    crew = validate_success(api.get_crew(ctx["crew"]["id"], program_admin_headers))
    assert crew["committed_days"] == 9


def test_dwelling_window_gap_below_buffer_rejected(api, program_admin_headers):
    """PRD 3.5: "the requested window may not fall too close to a `SCHEDULED`
    assignment belonging to a *different* job at the *same* dwelling —
    specifically, if fewer than 2 whole days separate the two windows, the
    request fails with `ERR_DWELLING_WINDOW_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/dwelling_window_conflict_buffer_gap
    """
    ctx = setup_dwelling_window_precondition()
    payload = create_crew_assignment_payload(
        ctx["job_b"]["id"], ctx["crew2"]["id"],
        scheduled_start_date="2026-06-06T00:00:00Z", scheduled_end_date="2026-06-10T00:00:00Z",
    )
    res = api.create_crew_assignment(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_DWELLING_WINDOW_CONFLICT)


def test_dwelling_conflict_leaves_second_crew_uncommitted(api, program_admin_headers):
    """PRD 3.5: "`committed_days`, the sum of `duration_days` over that crew's
    assignments currently in `SCHEDULED` status".

    Design: Difficulty/resource_temporal_overlap/dwelling_window_conflict_buffer_gap
    """
    ctx = setup_dwelling_window_precondition()
    payload = create_crew_assignment_payload(
        ctx["job_b"]["id"], ctx["crew2"]["id"],
        scheduled_start_date="2026-06-06T00:00:00Z", scheduled_end_date="2026-06-10T00:00:00Z",
    )
    api.create_crew_assignment(payload, program_admin_headers)
    crew2 = validate_success(api.get_crew(ctx["crew2"]["id"], program_admin_headers))
    assert crew2["committed_days"] == 0


def test_cancel_assignment_releases_committed_days(api, program_admin_headers):
    """PRD 3.5: "it moves the assignment to `CANCELLED` and releases its
    reservation, subtracting `duration_days` back out of the crew's
    `committed_days` so the ledger returns to its pre-assignment value."

    Design: Difficulty/compensating_invariant/crew_days_conserved_on_assignment_cancel
    """
    ctx = setup_scheduled_assignment(capacity_days=20, start="2026-06-01T00:00:00Z", end="2026-06-05T00:00:00Z")
    res = api.cancel_crew_assignment(ctx["assignment"]["id"], program_admin_headers)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    crew = validate_success(api.get_crew(ctx["crew"]["id"], program_admin_headers))
    assert crew["committed_days"] == 0


def test_cancel_assignment_restores_available_days(api, program_admin_headers):
    """PRD 3.5: "`available_days`, which is `capacity_days` minus
    `committed_days`."

    Design: Difficulty/compensating_invariant/crew_days_conserved_on_assignment_cancel
    """
    ctx = setup_scheduled_assignment(capacity_days=20, start="2026-06-01T00:00:00Z", end="2026-06-05T00:00:00Z")
    api.cancel_crew_assignment(ctx["assignment"]["id"], program_admin_headers)
    crew = validate_success(api.get_crew(ctx["crew"]["id"], program_admin_headers))
    assert crew["available_days"] == 20


def test_first_assignment_sets_job_install_scheduled(api, program_admin_headers):
    """PRD 3.5: "As a side effect, if the target job's `install_status` is still
    `PLANNED`, this — the first scheduled assignment for the job — moves the
    job's `install_status` from `PLANNED` to `SCHEDULED` and advances the job's
    `version`." PRD 3.5: "The assignment's `duration_days` is computed as the
    whole number of days between start and end."

    Design: Corner/state_machines/crew_assignment_sets_install_scheduled_side_effect
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    crew = new_crew(name="Crew O", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=20)
    payload = create_crew_assignment_payload(
        job["id"], crew["id"],
        scheduled_start_date="2026-06-01T00:00:00Z", scheduled_end_date="2026-06-04T00:00:00Z",
    )
    assignment = validate_success(api.create_crew_assignment(payload, program_admin_headers), 201)
    assert assignment["status"] == "SCHEDULED"
    assert assignment["duration_days"] == 3
    job_after = validate_success(api.get_job(job["id"], program_admin_headers))
    assert job_after["install_status"] == "SCHEDULED"


def test_crew_assignment_invalid_date_window_rejected(api, program_admin_headers):
    """PRD 3.5: "The `scheduled_end_date` must be strictly after the
    `scheduled_start_date`, or the request fails with `ERR_INVALID_DATE_WINDOW`
    (422)."

    Design: Corner/validations/crew_assignment_invalid_date_window_returns_422
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    crew = new_crew(name="Crew R", crew_size=3, skills=["ATTIC_INSULATION"], capacity_days=20)
    payload = create_crew_assignment_payload(
        job["id"], crew["id"],
        scheduled_start_date="2026-06-05T00:00:00Z", scheduled_end_date="2026-06-01T00:00:00Z",
    )
    res = api.create_crew_assignment(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_DATE_WINDOW)


def test_crew_capacity_exceeded_rejected(api, program_admin_headers):
    """PRD 3.5: "adding this assignment's `duration_days` to the crew's current
    `committed_days` may not exceed the crew's `capacity_days`, or the request
    fails with `ERR_CREW_CAPACITY_EXCEEDED`."

    Design: Corner/validations/crew_capacity_exceeded_returns_conflict
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"], rebate_budget_cap_cents=100_000)
    crew = new_crew(name="Crew S", crew_size=2, skills=["ATTIC_INSULATION"], capacity_days=3)
    payload = create_crew_assignment_payload(
        job["id"], crew["id"],
        scheduled_start_date="2026-06-01T00:00:00Z", scheduled_end_date="2026-06-06T00:00:00Z",
    )
    res = api.create_crew_assignment(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)
    crew_after = validate_success(api.get_crew(crew["id"], program_admin_headers))
    assert crew_after["committed_days"] == 0

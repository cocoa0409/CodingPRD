"""Crew scheduling: half-open interval overlap, adjacency tolerance, capacity,
and window validity.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
    factories as f,
)

ADMIN = TEST_USERS["ops_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ─── Difficulty: resource_temporal_overlap ───────────────────────────────────
def test_crew_interior_overlap_rejected(api):
    """PRD §3.8: "The proposed window must not overlap another non-terminal install
    job — one in `SCHEDULED` or `IN_PROGRESS` status — already booked on the same
    crew, where overlap is judged on the half-open interval so that an adjacent
    end-equals-start pairing is allowed; an overlap is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_window_interior_overlap_rejected
    """
    crew = fx.create_crew(name="Shared Crew")
    ctx1 = fx.setup_deposit_paid_project(variant="STANDARD")
    p1 = ctx1["project"]["id"]
    fx.create_install_job(p1, crew["id"], "2026-04-22T09:00:00Z", "2026-04-22T17:00:00Z")
    ctx2 = fx.setup_deposit_paid_project(variant="STANDARD")
    p2 = ctx2["project"]["id"]
    # 13:00-21:00 overlaps the interior of 09:00-17:00.
    resp = api_client.create_install_job(
        p2,
        f.create_install_job_payload(crew["id"], "2026-04-22T13:00:00Z", "2026-04-22T21:00:00Z"),
        SCHED,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)
    project2 = validate_success(api_client.get_project(p2, ADMIN))
    assert project2["workflow_status"] == "DEPOSIT_PAID"


def test_crew_overlap_does_not_advance_second_project(api):
    """PRD §3.8: "The proposed window must not overlap another non-terminal install
    job — one in `SCHEDULED` or `IN_PROGRESS` status — already booked on the same
    crew, where overlap is judged on the half-open interval so that an adjacent
    end-equals-start pairing is allowed; an overlap is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_window_interior_overlap_rejected
    """
    crew = fx.create_crew(name="Shared Crew Dup")
    ctx1 = fx.setup_deposit_paid_project(variant="STANDARD")
    p1 = ctx1["project"]["id"]
    fx.create_install_job(p1, crew["id"], "2026-04-22T09:00:00Z", "2026-04-22T17:00:00Z")
    ctx2 = fx.setup_deposit_paid_project(variant="STANDARD")
    p2 = ctx2["project"]["id"]
    # A window fully contained inside the existing one also overlaps.
    resp = api_client.create_install_job(
        p2,
        f.create_install_job_payload(crew["id"], "2026-04-22T10:00:00Z", "2026-04-22T12:00:00Z"),
        SCHED,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)
    from test_helpers import validate_paginated
    jobs, _ = validate_paginated(api_client.list_install_jobs(p2, ADMIN))
    assert jobs == [], "no install job is created for the second project"


def test_crew_adjacent_window_allowed(api):
    """PRD §3.8: "The window is half-open: an install whose end exactly equals the
    next install's start does not overlap."
    PRD §3.8: "where overlap is judged on the half-open interval so that an
    adjacent end-equals-start pairing is allowed; an overlap is rejected with
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/crew_window_adjacent_touch_allowed
    """
    crew = fx.create_crew(name="Shared Crew 2")
    ctx1 = fx.setup_deposit_paid_project(variant="STANDARD")
    p1 = ctx1["project"]["id"]
    fx.create_install_job(p1, crew["id"], "2026-04-23T09:00:00Z", "2026-04-23T17:00:00Z")
    ctx2 = fx.setup_deposit_paid_project(variant="STANDARD")
    p2 = ctx2["project"]["id"]
    # Back-to-back: starts exactly when the prior window ends.
    job = validate_success(
        api_client.create_install_job(
            p2,
            f.create_install_job_payload(crew["id"], "2026-04-23T17:00:00Z", "2026-04-24T01:00:00Z"),
            SCHED,
        ),
        expected_status=201,
    )
    assert job["status"] == "SCHEDULED"
    project2 = validate_success(api_client.get_project(p2, ADMIN))
    assert project2["workflow_status"] == "SCHEDULED"


def test_crew_window_before_existing_allowed(api):
    """PRD §3.8: "The window is half-open: an install whose end exactly equals the
    next install's start does not overlap."
    PRD §3.8: "A successful scheduling creates the install job in `SCHEDULED`
    status, copies the project's `billable_area_sqft` onto the job's
    `install_area_sqft`, advances the project's workflow dimension from
    `DEPOSIT_PAID` to `SCHEDULED`, and increments the project's `version`."

    Design: Difficulty/resource_temporal_overlap/crew_window_adjacent_touch_allowed
    """
    crew = fx.create_crew(name="Shared Crew 3")
    ctx1 = fx.setup_deposit_paid_project(variant="STANDARD")
    p1 = ctx1["project"]["id"]
    fx.create_install_job(p1, crew["id"], "2026-04-23T09:00:00Z", "2026-04-23T17:00:00Z")
    ctx2 = fx.setup_deposit_paid_project(variant="STANDARD")
    p2 = ctx2["project"]["id"]
    # The new window ends exactly when the existing one starts — adjacency, allowed.
    job = validate_success(
        api_client.create_install_job(
            p2,
            f.create_install_job_payload(crew["id"], "2026-04-23T01:00:00Z", "2026-04-23T09:00:00Z"),
            SCHED,
        ),
        expected_status=201,
    )
    assert job["status"] == "SCHEDULED"
    assert job["install_area_sqft"] == 648.0


# ─── Corner: validations ─────────────────────────────────────────────────────
def test_invalid_window_end_equals_start_rejected(api):
    """PRD §3.8: "The `scheduled_end` must be strictly after the `scheduled_start`;
    a non-positive window is rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_window_end_not_after_start
    """
    ctx = fx.setup_deposit_paid_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    crew = fx.create_crew(name="Win Crew")
    resp = api_client.create_install_job(
        pid,
        f.create_install_job_payload(crew["id"], "2026-05-02T09:00:00Z", "2026-05-02T09:00:00Z"),
        SCHED,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


def test_crew_capacity_exceeded_rejected(api):
    """PRD §3.8: "The crew's `daily_capacity_sqft` must be at least the project's
    `billable_area_sqft`; insufficient capacity is rejected with
    `ERR_CREW_CAPACITY_EXCEEDED`."

    Design: Corner/validations/crew_capacity_exceeded
    """
    # STANDARD billable_area 648; crew capacity 500 < 648.
    ctx = fx.setup_deposit_paid_project(variant="STANDARD")
    pid = ctx["project"]["id"]
    crew = fx.create_crew(name="Small Crew", daily_capacity_sqft=500)
    resp = api_client.create_install_job(
        pid,
        f.create_install_job_payload(crew["id"], "2026-05-03T09:00:00Z", "2026-05-03T17:00:00Z"),
        SCHED,
    )
    validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED.value)

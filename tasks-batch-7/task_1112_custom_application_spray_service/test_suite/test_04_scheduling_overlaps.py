"""Interval-conflict rules (field half-open, applicator 30-min padding) and
reschedule optimistic concurrency."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_field, create_prescription, approve_prescription,
    create_applicator, create_equipment, post_calibration, create_work_order,
    schedule_work_order, must_schedule, post_weather, set_clock, must_start,
    base_environment, scheduled_environment, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _second_field_with_rx(env, label="South 20"):
    f2 = create_field(env["customer"]["id"], label=label, crop="SOY")
    lines = [{"product_id": env["p1"]["id"], "rate_per_acre": 1.5}]
    if env.get("p2") is not None:
        lines.append({"product_id": env["p2"]["id"], "rate_per_acre": 0.4})
    rx2 = approve_prescription(create_prescription(f2["id"], lines))
    return f2, rx2


def test_field_overlap_half_open_adjacency(api):
    """PRD §3.4: "The field must be free: no other `SCHEDULED` or `IN_PROGRESS`
    work order on the same field may overlap the new window under a half-open
    interval test — an existing job's start strictly before the new job's end,
    and the new job's start strictly before the existing job's end. Adjacency
    is explicitly allowed on the field: one job ending exactly when another
    begins does not conflict. A violation is `ERR_FIELD_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/field_overlap_half_open_adjacency
    """
    env = base_environment(customer_overrides={"credit_limit_cents": 5000000},
                           field_overrides={"acres": 300}, acres_to_treat=90)
    ap2 = create_applicator(display_name="Bob", license_no="L-200")
    eq2 = create_equipment(unit_label="Sprayer-2")
    post_calibration(eq2["id"], ap2["id"])

    wo1 = env["work_order"]
    must_schedule(wo1["id"], env["applicator"]["id"], env["equipment"]["id"],
                  scheduled_start="2026-05-10T08:00:00Z",
                  scheduled_end="2026-05-10T11:00:00Z")

    # Adjacent: starts exactly when the first job ends — allowed on the field.
    wo2 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=90)
    scheduled2 = must_schedule(wo2["id"], ap2["id"], eq2["id"],
                               scheduled_start="2026-05-10T11:00:00Z",
                               scheduled_end="2026-05-10T14:00:00Z")
    assert scheduled2["status"] == "SCHEDULED"

    # One minute of real overlap (13:59 < 14:00) — rejected.
    wo3 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=90)
    res = schedule_work_order(wo3["id"], env["applicator"]["id"], env["equipment"]["id"],
                              scheduled_start="2026-05-10T13:59:00Z",
                              scheduled_end="2026-05-10T16:00:00Z")
    validate_error(res, "ERR_FIELD_TIME_CONFLICT", expected_status=409)


def test_field_overlap_with_in_progress_job_conflicts(api):
    """PRD §3.4: "The field must be free: no other `SCHEDULED` or `IN_PROGRESS`
    work order on the same field may overlap the new window under a half-open
    interval test — an existing job's start strictly before the new job's end,
    and the new job's start strictly before the existing job's end."
    PRD §3.4: "A violation is `ERR_FIELD_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/field_overlap_half_open_adjacency
    """
    env = base_environment(customer_overrides={"credit_limit_cents": 5000000},
                           acres_to_treat=90)
    ap2 = create_applicator(display_name="Bob", license_no="L-200")
    eq2 = create_equipment(unit_label="Sprayer-2")
    post_calibration(eq2["id"], ap2["id"])

    wo1 = env["work_order"]
    must_schedule(wo1["id"], env["applicator"]["id"], env["equipment"]["id"],
                  scheduled_start="2026-05-10T08:00:00Z",
                  scheduled_end="2026-05-10T11:00:00Z")
    post_weather(env["applicator"]["id"])
    set_clock("2026-05-10T08:00:00Z")
    started = must_start(wo1["id"], env["applicator"]["id"])
    assert started["status"] == "IN_PROGRESS"

    wo2 = create_work_order(env["customer"]["id"], env["field"]["id"],
                            env["prescription"]["id"], acres_to_treat=90)
    res = schedule_work_order(wo2["id"], ap2["id"], eq2["id"],
                              scheduled_start="2026-05-10T10:00:00Z",
                              scheduled_end="2026-05-10T12:00:00Z")
    validate_error(res, "ERR_FIELD_TIME_CONFLICT", expected_status=409)


def test_applicator_overlap_travel_buffer(api):
    """PRD §3.4: "The applicator must be free with travel slack: the same
    overlap test runs against the applicator's other `SCHEDULED` or
    `IN_PROGRESS` work, except both intervals are padded by a 30-minute travel
    buffer — the existing window extends from thirty minutes before its start
    to thirty minutes after its end. With padding, back-to-back jobs for the
    same applicator do conflict. A violation is `ERR_APPLICATOR_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/applicator_overlap_travel_buffer
    """
    env = base_environment(customer_overrides={"credit_limit_cents": 5000000},
                           acres_to_treat=50)
    f2, rx2 = _second_field_with_rx(env)
    ap = env["applicator"]["id"]
    eq = env["equipment"]["id"]

    must_schedule(env["work_order"]["id"], ap, eq,
                  scheduled_start="2026-05-10T08:00:00Z",
                  scheduled_end="2026-05-10T11:00:00Z")

    # Back-to-back on another field: padded [10:30,13:30) meets padded
    # [07:30,11:30) — adjacency is NOT allowed for an applicator.
    wob = create_work_order(env["customer"]["id"], f2["id"], rx2["id"], acres_to_treat=50)
    res = schedule_work_order(wob["id"], ap, eq,
                              scheduled_start="2026-05-10T11:00:00Z",
                              scheduled_end="2026-05-10T13:00:00Z")
    validate_error(res, "ERR_APPLICATOR_TIME_CONFLICT", expected_status=409)

    # End + 30 minutes exactly: padded [11:30,14:30) touches [07:30,11:30)
    # half-open — allowed.
    woc = create_work_order(env["customer"]["id"], f2["id"], rx2["id"], acres_to_treat=50)
    scheduled = must_schedule(woc["id"], ap, eq,
                              scheduled_start="2026-05-10T12:00:00Z",
                              scheduled_end="2026-05-10T14:00:00Z")
    assert scheduled["status"] == "SCHEDULED"


def test_different_applicator_back_to_back_no_conflict(api):
    """PRD §3.4: "the same overlap test runs against the applicator's other
    `SCHEDULED` or `IN_PROGRESS` work, except both intervals are padded by a
    30-minute travel buffer" — padding binds the applicator's own jobs only.

    Design: Difficulty/resource_temporal_overlap/applicator_overlap_travel_buffer
    """
    env = base_environment(customer_overrides={"credit_limit_cents": 5000000},
                           acres_to_treat=50)
    f2, rx2 = _second_field_with_rx(env)
    ap2 = create_applicator(display_name="Bob", license_no="L-200")
    eq2 = create_equipment(unit_label="Sprayer-2")
    post_calibration(eq2["id"], ap2["id"])

    must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                  env["equipment"]["id"],
                  scheduled_start="2026-05-10T08:00:00Z",
                  scheduled_end="2026-05-10T11:00:00Z")

    # A different applicator may start back-to-back on a different field.
    wob = create_work_order(env["customer"]["id"], f2["id"], rx2["id"], acres_to_treat=50)
    scheduled = must_schedule(wob["id"], ap2["id"], eq2["id"],
                              scheduled_start="2026-05-10T11:00:00Z",
                              scheduled_end="2026-05-10T13:00:00Z")
    assert scheduled["status"] == "SCHEDULED"


def test_workorder_reschedule_stale_version(api):
    """PRD §2.7: "Rescheduling a work order requires the request to carry
    `expected_work_order_version`, a non-optional input holding the work
    order's `version` as the dispatcher last observed it. Amending a
    `SCHEDULED` work order is legitimate any number of times, so a second
    reschedule cannot be refused on state grounds; instead, if the supplied
    value does not match the work order's current `version`, the reschedule is
    rejected with `ERR_STALE_VERSION` (HTTP 412) purely because the client's
    observed version is stale."

    Design: Corner/cross_cutting_complexity_layers/workorder_reschedule_stale_version
    """
    env = base_environment(num_products=1)
    scheduled = must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"],
                              scheduled_start="2026-05-10T08:00:00Z",
                              scheduled_end="2026-05-10T11:00:00Z")
    observed_version = scheduled["version"]

    first = validate_success(api_client.reschedule_work_order(
        env["work_order"]["id"],
        {"scheduled_start": "2026-05-11T08:00:00Z",
         "scheduled_end": "2026-05-11T11:00:00Z",
         "expected_work_order_version": observed_version},
        DISPATCHER), 200)
    assert first["scheduled_start"] == "2026-05-11T08:00:00.000Z"
    assert first["version"] == observed_version + 1

    # Second reschedule with the pre-first-reschedule version: stale, not state.
    res = api_client.reschedule_work_order(
        env["work_order"]["id"],
        {"scheduled_start": "2026-05-12T08:00:00Z",
         "scheduled_end": "2026-05-12T11:00:00Z",
         "expected_work_order_version": observed_version},
        DISPATCHER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    after = validate_success(api_client.get_work_order(env["work_order"]["id"], DISPATCHER), 200)
    assert after["scheduled_start"] == "2026-05-11T08:00:00.000Z", \
        "rejected reschedule must not move the window"

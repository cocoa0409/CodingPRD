"""Test event endpoints: scheduling (with ground-before-flight and buffered
flight-window separation), result recording (flight-fail rework cascade), and
rescheduling (attempt ceiling 3)."""
from flask import Blueprint, request

import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    pagination_args,
    paginate,
    req_dt,
    req_enum,
    req_str,
    require_role,
)
from response import success
from serializers import ser_test_event
from services.core import (
    children_of,
    flight_window_conflict,
    recompute_work_order,
)

bp = Blueprint("test_events", __name__)

TEST_KINDS = {"GROUND", "FLIGHT"}


def _get_event(testEventId):
    e = db.test_events.get(testEventId)
    if e is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Test event not found")
    return e


@bp.post("/avionics/test-events")
def create_test_event():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    work_order_id = req_str(b, "work_order_id")
    test_kind = req_enum(b, "test_kind", TEST_KINDS)
    scheduled_start = req_dt(b, "scheduled_start")
    scheduled_end = req_dt(b, "scheduled_end")
    if not (scheduled_end > scheduled_start):
        errors.raise_err(errors.ERR_VALIDATION, "scheduled_end must be after scheduled_start")

    wo = db.work_orders.get(work_order_id)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")
    if wo.status != "TESTING":
        errors.raise_err(errors.ERR_INVALID_STATE, "Work order is not in TESTING")

    if test_kind == "FLIGHT":
        # safety gate (priority 6b): a PASSED ground run must exist first
        if not any(
            e.test_kind == "GROUND" and e.status == "PASSED"
            for e in children_of(db.test_events, wo.id)
        ):
            errors.raise_err(
                errors.ERR_GROUND_TEST_REQUIRED,
                "A passed ground test is required before scheduling a flight test",
            )
        # temporal (priority 7): buffered-window separation on the same aircraft
        if flight_window_conflict(wo.aircraft_id, scheduled_start, scheduled_end):
            errors.raise_err(
                errors.ERR_FLIGHT_WINDOW_CONFLICT,
                "Flight window conflicts with another flight's buffered window",
            )

    e = db.new_entity(
        work_order_id=wo.id,
        test_kind=test_kind,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        attempt=1,
        result="NONE",
        status="SCHEDULED",
    )
    db.test_events[e.id] = e
    return success(ser_test_event(e), 201)


@bp.get("/avionics/test-events/<testEventId>")
def get_test_event(testEventId):
    authenticate()
    return success(ser_test_event(_get_event(testEventId)), 200)


@bp.get("/avionics/test-events")
def list_test_events():
    authenticate()
    limit, offset = pagination_args()
    work_order_id = request.args.get("work_order_id")
    test_kind = request.args.get("test_kind")
    items = sorted(db.test_events.values(), key=lambda e: e._seq)
    if work_order_id is not None:
        items = [e for e in items if e.work_order_id == work_order_id]
    if test_kind is not None:
        items = [e for e in items if e.test_kind == test_kind]
    page, meta = paginate([ser_test_event(e) for e in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/test-events/<testEventId>/record-result")
def record_result(testEventId):
    _, role = authenticate()
    require_role(role, {"Inspector"})
    b = body()
    result = req_enum(b, "result", {"PASS", "FAIL"})
    e = _get_event(testEventId)
    wo = db.work_orders[e.work_order_id]
    if e.status != "SCHEDULED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a SCHEDULED test can be recorded")
    if wo.status != "TESTING":
        errors.raise_err(errors.ERR_INVALID_STATE, "Parent work order is not in TESTING")

    e.result = result
    if result == "PASS":
        e.status = "PASSED"
        touch(e)
        return success(ser_test_event(e), 200)

    e.status = "FAILED"
    touch(e)
    if e.test_kind == "FLIGHT":
        # rework cascade: verified tasks revert to IN_PROGRESS, billing voided
        for t in children_of(db.install_tasks, wo.id):
            if t.status == "VERIFIED":
                t.status = "IN_PROGRESS"
                t.billed_labor_cents = None
                t.verified_by_user_id = None
                touch(t)
        recompute_work_order(wo)
        # work order regresses while unverified tasks remain after the revert
        if wo.tasks_unverified_count > 0:
            wo.status = "INSTALLATION"
            touch(wo)
    # GROUND failures carry no cascade (bench retest only)
    return success(ser_test_event(e), 200)


@bp.post("/avionics/test-events/<testEventId>/reschedule")
def reschedule(testEventId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    scheduled_start = req_dt(b, "scheduled_start")
    scheduled_end = req_dt(b, "scheduled_end")
    if not (scheduled_end > scheduled_start):
        errors.raise_err(errors.ERR_VALIDATION, "scheduled_end must be after scheduled_start")
    e = _get_event(testEventId)
    wo = db.work_orders[e.work_order_id]
    if e.status != "FAILED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a FAILED test can be rescheduled")
    # temporal (priority 7) before the attempt ceiling (priority 9)
    if e.test_kind == "FLIGHT" and flight_window_conflict(
        wo.aircraft_id, scheduled_start, scheduled_end, exclude_id=e.id
    ):
        errors.raise_err(
            errors.ERR_FLIGHT_WINDOW_CONFLICT,
            "Flight window conflicts with another flight's buffered window",
        )
    if e.attempt >= 3:
        errors.raise_err(errors.ERR_TEST_ATTEMPT_LIMIT, "Test attempt limit (3) reached")
    e.scheduled_start = scheduled_start
    e.scheduled_end = scheduled_end
    e.attempt += 1
    e.result = "NONE"
    e.status = "SCHEDULED"
    touch(e)
    return success(ser_test_event(e), 200)

"""Assignment endpoints: fetch/list, respond, release."""

from flask import request

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_str, field_enum, touch, sort_created, now, ApiError, err_not_found,
    err_forbidden,
)
from domain import (
    ser_assignment, append_event, posture_complete, driver_current_load,
    driver_has_overlap,
)

DECISIONS = {"ACCEPT", "DECLINE"}


def _assignment_or_404(aid):
    asg = db.assignments.get(aid)
    if asg is None:
        raise err_not_found("Assignment not found")
    return asg


def register(app):

    @app.route("/assignments/<aid>", methods=["GET"])
    def get_assignment(aid):
        caller = get_caller()
        require_role(caller, {"Coordinator", "BillingAdmin", "Driver"})
        asg = _assignment_or_404(aid)
        if caller.role == "Driver" and asg["driver_id"] != caller.user_id:
            raise err_forbidden("Driver may only access their own assignments")
        return ok(ser_assignment(asg))

    @app.route("/assignments", methods=["GET"])
    def list_assignments():
        caller = get_caller()
        require_role(caller, {"Coordinator", "BillingAdmin", "Driver"})
        limit, offset = parse_pagination()
        items = sort_created(db.assignments.values())
        if caller.role == "Driver":
            items = [a for a in items if a["driver_id"] == caller.user_id]
        for param in ("ride_id", "driver_id", "status"):
            val = request.args.get(param)
            if val is not None:
                items = [a for a in items if a.get(param) == val]
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_assignment(a) for a in page], response_type="array", pagination=meta
        )

    @app.route("/assignments/<aid>/respond", methods=["POST"])
    def respond_assignment(aid):
        body = get_body()
        decision = field_enum(body, "decision", DECISIONS, required=True)
        decline_reason = field_str(body, "decline_reason")
        caller = get_caller()
        require_role(caller, {"Driver"})
        asg = _assignment_or_404(aid)
        if asg["driver_id"] != caller.user_id:
            raise err_forbidden("Only the offered driver may respond")
        if asg["status"] != "OFFERED":
            raise ApiError(
                "ERR_ASSIGNMENT_NOT_ACTIONABLE", 409,
                "Assignment is no longer OFFERED",
            )
        ride = db.rides.get(asg["ride_id"])
        driver = db.drivers.get(asg["driver_id"])
        if decision == "ACCEPT":
            # 9. driver eligibility recheck
            pickup_date = ride["scheduled_pickup_at"].date() if ride else None
            if (
                driver is None
                or driver["status"] != "ACTIVE"
                or not posture_complete(driver["id"], pickup_date)
            ):
                raise ApiError(
                    "ERR_DRIVER_NOT_ELIGIBLE", 409,
                    "Driver is not eligible for this ride",
                )
            if (
                driver_current_load(driver["id"]) + ride["estimated_duration_minutes"]
                > driver["max_daily_service_minutes"]
            ):
                raise ApiError(
                    "ERR_DRIVER_DAILY_CAP_EXCEEDED", 409,
                    "Daily service-minute cap would be exceeded",
                )
            # 11. buffered-window overlap
            if driver_has_overlap(driver["id"], ride, exclude_assignment_id=asg["id"]):
                raise ApiError(
                    "ERR_RIDE_OVERLAP_DRIVER", 409,
                    "Buffered-window overlap with another accepted assignment",
                )
            asg["status"] = "ACCEPTED"
            asg["responded_at"] = now()
            touch(asg)
            ride["status"] = "ASSIGNED"
            ride["assigned_driver_id"] = driver["id"]
            touch(ride)
            append_event(ride, "ACCEPTED", "Driver", caller.user_id)
        else:
            asg["status"] = "DECLINED"
            asg["responded_at"] = now()
            asg["decline_reason"] = decline_reason
            touch(asg)
            if ride is not None and driver["id"] not in ride["excluded_driver_ids"]:
                ride["excluded_driver_ids"].append(driver["id"])
                touch(ride)
            append_event(ride, "DECLINED", "Driver", caller.user_id, note=decline_reason)
        return ok(ser_assignment(asg))

    @app.route("/assignments/<aid>/release", methods=["POST"])
    def release_assignment(aid):
        body = get_body()
        reason = field_str(body, "reason")
        caller = get_caller()
        require_role(caller, {"Driver"})
        asg = _assignment_or_404(aid)
        if asg["driver_id"] != caller.user_id:
            raise err_forbidden("Only the assigned driver may release")
        if asg["status"] != "ACCEPTED":
            raise ApiError(
                "ERR_ASSIGNMENT_RELEASE_INVALID", 409,
                "Only an ACCEPTED assignment can be released",
            )
        ride = db.rides.get(asg["ride_id"])
        asg["status"] = "RELEASED"
        asg["release_reason"] = "DRIVER_RELEASE"
        asg["responded_at"] = now()
        touch(asg)
        if ride is not None and ride["status"] in (
            "ASSIGNED", "EN_ROUTE", "ARRIVED", "IN_SERVICE"
        ):
            ride["status"] = "DISPATCHING"
            ride["assigned_driver_id"] = None
            ride["dispatch_round"] += 1
            if asg["driver_id"] not in ride["excluded_driver_ids"]:
                ride["excluded_driver_ids"].append(asg["driver_id"])
            touch(ride)
            append_event(ride, "RELEASED", "Driver", caller.user_id, note=reason)
        return ok(ser_assignment(asg))

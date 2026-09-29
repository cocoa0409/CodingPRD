"""Safety plans: provisioning, submission, certification and return (PRD 3.5)."""
from db import db, new_row, touch
from errors import fail
from middleware import (
    ROLE_FINANCE_CONTROLLER,
    ROLE_SAFETY_OFFICIAL,
    ROLE_SERIES_PROMOTER,
    ROLE_VENUE_MANAGER,
    auth,
    pagination,
)
from response import list_response, object_response
from services import derive, flow, serialize
import validate

PROVISIONING_FIELDS = (
    "barrier_linear_feet",
    "catch_fence_height_ft",
    "medical_als_staff_count",
    "medical_bls_staff_count",
    "ambulance_count",
    "emergency_access_lanes",
)
READ_ROLES = (
    ROLE_SERIES_PROMOTER,
    ROLE_SAFETY_OFFICIAL,
    ROLE_FINANCE_CONTROLLER,
    ROLE_VENUE_MANAGER,
)


def register(app):
    @app.route("/tour-stops/<stop_id>/safety-plan", methods=["POST"])
    def create_plan(stop_id):
        user_id, _role = auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        values = {}
        for name in PROVISIONING_FIELDS:
            values[name] = validate.field_int(payload, name, minimum=0)

        stop = derive.get_stop(stop_id)
        flow.ensure_stop_writable(stop)
        if derive.plan_of_stop(stop["id"]) is not None:
            fail("ERR_DUPLICATE_CHILD")

        row = new_row(
            tour_stop_id=stop["id"],
            state="DRAFT",
            required_als_staff_count=0,
            required_bls_staff_count=0,
            required_ambulance_count=0,
            required_catch_fence_height_ft=0,
            required_emergency_access_lanes=0,
            required_barrier_linear_feet=0,
            safety_cost_cents=0,
            authored_by_user_id=user_id,
            certified_by_user_id=None,
            return_count=0,
            return_reason=None,
            **values
        )
        db.plans[row["id"]] = row
        flow.refresh_plan_requirements(stop, row, bump=False)
        return object_response(serialize.plan(row), 201)

    @app.route("/tour-stops/<stop_id>/safety-plan", methods=["GET"])
    def read_stop_plan(stop_id):
        auth(*READ_ROLES)
        limit, offset = pagination()
        stop = derive.get_stop(stop_id)
        plan = derive.plan_of_stop(stop["id"])
        rows = [] if plan is None else [serialize.plan(plan)]
        return list_response(rows, limit, offset)

    @app.route("/safety-plans/<plan_id>", methods=["GET"])
    def read_plan(plan_id):
        auth(*READ_ROLES)
        return object_response(serialize.plan(derive.get_plan(plan_id)))

    @app.route("/safety-plans/<plan_id>", methods=["PATCH"])
    def patch_plan(plan_id):
        user_id, _role = auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        values = {}
        for name in PROVISIONING_FIELDS:
            supplied = validate.field_int(payload, name, required=False, minimum=0)
            if supplied is not None:
                values[name] = supplied

        plan = derive.get_plan(plan_id)
        stop = db.stops[plan["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if plan["state"] not in ("DRAFT", "RETURNED"):
            fail("ERR_INVALID_STATE_TRANSITION")

        plan.update(values)
        plan["state"] = "DRAFT"
        plan["authored_by_user_id"] = user_id
        flow.refresh_plan_requirements(stop, plan, bump=False)
        touch(plan)
        return object_response(serialize.plan(plan))

    @app.route("/safety-plans/<plan_id>/submit", methods=["POST"])
    def submit_plan(plan_id):
        auth(ROLE_SAFETY_OFFICIAL)
        validate.body()
        plan = derive.get_plan(plan_id)
        stop = db.stops[plan["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if plan["state"] not in ("DRAFT", "RETURNED"):
            fail("ERR_INVALID_STATE_TRANSITION")

        flow.refresh_plan_requirements(stop, plan, bump=False)
        flow.check_provisioning(plan, derive.venue_of_stop(stop))

        plan["state"] = "SUBMITTED"
        touch(plan)
        stop["safety_state"] = "SAFETY_REVIEW"
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.plan(plan))

    @app.route("/safety-plans/<plan_id>/certify", methods=["POST"])
    def certify_plan(plan_id):
        user_id, _role = auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        validate.field_string(payload, "note", required=False)
        plan = derive.get_plan(plan_id)
        if user_id == plan["authored_by_user_id"]:
            fail("ERR_SAFETY_SELF_CERTIFICATION")
        stop = db.stops[plan["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if plan["state"] != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION")

        flow.refresh_plan_requirements(stop, plan, bump=False)
        flow.check_provisioning(plan, derive.venue_of_stop(stop))

        plan["state"] = "CERTIFIED"
        plan["certified_by_user_id"] = user_id
        touch(plan)
        stop["safety_state"] = "SAFETY_CERTIFIED"
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.plan(plan))

    @app.route("/safety-plans/<plan_id>/return", methods=["POST"])
    def return_plan(plan_id):
        auth(ROLE_SAFETY_OFFICIAL)
        payload = validate.body()
        reason = validate.field_string(payload, "reason")
        plan = derive.get_plan(plan_id)
        stop = db.stops[plan["tour_stop_id"]]
        flow.ensure_stop_writable(stop)
        if plan["state"] != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION")

        plan["state"] = "RETURNED"
        plan["return_count"] = plan["return_count"] + 1
        plan["return_reason"] = reason
        plan["certified_by_user_id"] = None
        touch(plan)
        stop["safety_state"] = "SAFETY_DRAFT"
        touch(stop)
        flow.apply_posture(stop)
        return object_response(serialize.plan(plan))

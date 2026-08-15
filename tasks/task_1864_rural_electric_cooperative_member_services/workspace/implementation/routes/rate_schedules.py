"""RateSchedule endpoints."""
from flask import Blueprint

from middleware import get_context, require_roles, get_json_body
from response import ok, created
from services import rate_schedule as rs_svc

bp = Blueprint("rate_schedules", __name__)


@bp.route("/coop/rate-schedules", methods=["POST"])
def create_rate_schedule():
    uid, role = get_context()
    require_roles(["RateAnalyst"])
    body = get_json_body()
    result = rs_svc.create_rate_schedule(body)
    return created(result)


@bp.route("/coop/rate-schedules/<schedule_id>", methods=["GET"])
def get_rate_schedule(schedule_id):
    uid, role = get_context()
    require_roles(["RateAnalyst", "MemberServicesRep", "BillingClerk"])
    result = rs_svc.get_rate_schedule(schedule_id)
    return ok(result)


@bp.route("/coop/rate-schedules/<schedule_id>/publish", methods=["POST"])
def publish_schedule(schedule_id):
    uid, role = get_context()
    require_roles(["RateAnalyst"])
    result = rs_svc.publish_schedule(schedule_id)
    return ok(result)


@bp.route("/coop/rate-schedules/<schedule_id>/supersede", methods=["POST"])
def supersede_schedule(schedule_id):
    uid, role = get_context()
    require_roles(["RateAnalyst"])
    body = get_json_body()
    result = rs_svc.supersede_schedule(schedule_id, body)
    return ok(result)

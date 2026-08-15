"""WasteLog verify/post/reject endpoints."""
from flask import Blueprint

from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import c6_recompute, get_period, get_waste_log, ser, touch
from routes.common import list_endpoint

bp = Blueprint("waste", __name__)


@bp.get("/waste-logs")
def list_waste_logs():
    return list_endpoint(
        "waste_logs",
        [
            ("meal_period_id", "meal_period_id"),
            ("status", "status"),
            ("category", "category"),
            ("disposition", "disposition"),
        ],
    )


@bp.get("/waste-logs/<wid>")
def get_one_waste_log(wid):
    auth(ALL_ROLES)
    return ok(ser(get_waste_log(wid)))


@bp.post("/waste-logs/<wid>/verify")
def verify_waste_log(wid):
    user_id, _ = auth(["HallManager"])
    log = get_waste_log(wid)
    if log["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Waste log is not RECORDED")
    period = get_period(log["meal_period_id"])
    if period["status"] not in ("IN_SERVICE", "RECONCILED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Period is not IN_SERVICE or RECONCILED"
        )
    # Tier 5: segregation of duties — verifier must differ from recorder.
    if user_id == log["recorded_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The verifier must differ from the recorder",
        )
    log["verified_by_user_id"] = user_id
    log["status"] = "VERIFIED"
    touch(log)
    return ok(ser(log))


@bp.post("/waste-logs/<wid>/post")
def post_waste_log(wid):
    auth(["HallManager"])
    log = get_waste_log(wid)
    if log["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Waste log is not VERIFIED")
    period = get_period(log["meal_period_id"])
    if period["status"] != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Period is not RECONCILED")
    log["status"] = "POSTED"
    touch(log)
    c6_recompute(period)
    touch(period)
    return ok(ser(log))


@bp.post("/waste-logs/<wid>/reject")
def reject_waste_log(wid):
    auth(["HallManager"])
    log = get_waste_log(wid)
    if log["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Waste log is not VERIFIED")
    log["verified_by_user_id"] = None
    log["status"] = "RECORDED"
    touch(log)
    return ok(ser(log))

from flask import Blueprint

from db import db, new_row, now_iso, touch
from errors import ApiError
from middleware import (
    auth,
    body,
    must_exist,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_enrollment_active,
    require_subscriber_owner,
)
from response import ok, ok_list, paginate, read_pagination
from serializers import ser, ser_thaw_window, ser_thaw_windows
from services import calc

bp = Blueprint("bureau", __name__)

FREEZE_ACTIONS = ("FREEZE", "THAW")


@bp.get("/idp/bureau-profiles/<profile_id>")
def read_profile(profile_id):
    role, user_id = auth("Subscriber", "PlatformAdmin", "ClaimsAdjuster")
    profile = must_exist("bureau_profiles", profile_id)
    require_subscriber_owner(role, user_id, profile["subscriber_id"])
    return ok(ser(profile))


@bp.post("/idp/bureau-profiles/<profile_id>/score-refresh")
def score_refresh(profile_id):
    auth("PlatformAdmin")
    profile = must_exist("bureau_profiles", profile_id)
    subscriber = db.subscribers[profile["subscriber_id"]]

    data = body()
    credit_score = req_int(data, "credit_score", minimum=300, maximum=850)

    require_enrollment_active(subscriber)

    profile["credit_score"] = credit_score
    profile["score_pulled_at"] = now_iso()
    touch(profile)

    composite = calc.composite_credit_score(subscriber["id"])
    subscriber["composite_credit_score"] = composite
    if composite is not None:
        if subscriber["baseline_composite_credit_score"] is None:
            subscriber["baseline_composite_credit_score"] = composite
        if subscriber["monitoring_status"] == "PENDING_DATA":
            subscriber["monitoring_status"] = "MONITORED"

    calc.recompute_risk(subscriber)
    touch(subscriber)
    return ok(ser(profile))


@bp.post("/idp/bureau-profiles/<profile_id>/freeze-request")
def freeze_request(profile_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    profile = must_exist("bureau_profiles", profile_id)
    require_subscriber_owner(role, user_id, profile["subscriber_id"])
    subscriber = db.subscribers[profile["subscriber_id"]]

    data = body()
    action = req_enum(data, "action", FREEZE_ACTIONS)

    if action == "FREEZE":
        if profile["freeze_status"] != "UNFROZEN":
            raise ApiError("ERR_INVALID_STATE", "Bureau file is not UNFROZEN.")
        require_enrollment_active(subscriber)
        profile["freeze_status"] = "FREEZE_PENDING"
    else:
        if profile["freeze_status"] != "FROZEN":
            raise ApiError("ERR_INVALID_STATE", "Bureau file is not FROZEN.")
        require_enrollment_active(subscriber)
        profile["freeze_status"] = "THAW_PENDING"

    touch(profile)
    return ok(ser(profile))


@bp.post("/idp/bureau-profiles/<profile_id>/confirm")
def confirm(profile_id):
    auth("PlatformAdmin")
    profile = must_exist("bureau_profiles", profile_id)
    body()

    if profile["freeze_status"] == "FREEZE_PENDING":
        profile["freeze_status"] = "FROZEN"
    elif profile["freeze_status"] == "THAW_PENDING":
        profile["freeze_status"] = "UNFROZEN"
    else:
        raise ApiError("ERR_INVALID_STATE", "Bureau file has nothing pending.")

    touch(profile)
    return ok(ser(profile))


@bp.post("/idp/bureau-profiles/<profile_id>/thaw-windows")
def create_thaw_window(profile_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    profile = must_exist("bureau_profiles", profile_id)
    require_subscriber_owner(role, user_id, profile["subscriber_id"])
    subscriber = db.subscribers[profile["subscriber_id"]]

    data = body()
    start = req_datetime(data, "window_start")
    end = req_datetime(data, "window_end")
    purpose = req_str(data, "purpose")

    require_enrollment_active(subscriber)

    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW", "window_end must be strictly after window_start.")
    if start < calc.now():
        raise ApiError("ERR_WINDOW_IN_PAST", "window_start may not precede the logical clock.")
    if calc.thaw_window_overlaps(profile["id"], start, end):
        raise ApiError(
            "ERR_THAW_WINDOW_OVERLAP",
            "The window collides with an existing thaw window on this bureau profile.",
        )

    window = new_row(
        bureau_profile_id=profile["id"],
        window_start=data["window_start"],
        window_end=data["window_end"],
        purpose=purpose,
    )
    window["_ws"] = start
    window["_we"] = end
    db.thaw_windows[window["id"]] = window
    return ok(ser_thaw_window(window), 201)


@bp.get("/idp/bureau-profiles/<profile_id>/thaw-windows")
def list_thaw_windows(profile_id):
    role, user_id = auth("Subscriber", "PlatformAdmin")
    profile = must_exist("bureau_profiles", profile_id)
    require_subscriber_owner(role, user_id, profile["subscriber_id"])
    limit, offset = read_pagination()

    rows = [w for w in db.thaw_windows.values() if w["bureau_profile_id"] == profile["id"]]
    rows.sort(key=lambda w: (w["_ws"], w["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list(ser_thaw_windows(page), limit, offset, total)

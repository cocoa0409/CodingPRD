"""BlackoutPeriod endpoints (PRD section 3.5)."""

import db
import services
from errors import (
    ApiError,
    ERR_BLACKOUT_NOT_ENDED,
    ERR_BLACKOUT_NOT_IN_WINDOW,
    ERR_BLACKOUT_NOTICE_MISSING,
    ERR_BLACKOUT_NOT_SCHEDULED,
    ERR_BLACKOUT_WINDOW_OVERLAP,
    ERR_CASE_INVALID_STATE,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_blackout
from util import (
    body_fk,
    body_json,
    check_no_fields,
    check_shape,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = make_blueprint("blackouts")


@bp.post("/blackout-periods")
def create_blackout():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "termination_case_id": {"type": "string", "required": True},
        "start_at": {"type": "datetime", "required": True},
        "end_at": {"type": "datetime", "required": True},
        "outgoing_recordkeeper": {"type": "string", "required": True},
        "incoming_recordkeeper": {"type": "string", "required": True},
    })
    start_at = parse_dt(body["start_at"], "start_at")
    end_at = parse_dt(body["end_at"], "end_at")
    # Half-open window: end_at must be strictly after start_at.
    if end_at <= start_at:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "end_at must be strictly after start_at"
        )
    case = body_fk(body, "termination_case_id", "cases", "termination case")
    if case["status"] == "CLOSED":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "blackouts may not be scheduled on a CLOSED case",
        )
    # Priority 9: half-open overlap; pure adjacency is allowed.
    for other in services.case_blackouts(case["id"]):
        if start_at < other["end_at"] and other["start_at"] < end_at:
            raise ApiError(
                ERR_BLACKOUT_WINDOW_OVERLAP, 409,
                "blackout windows on the same case may not intersect",
            )
    blackout = db.new_entity("blackouts", {
        "termination_case_id": case["id"],
        "start_at": start_at,
        "end_at": end_at,
        "outgoing_recordkeeper": body["outgoing_recordkeeper"],
        "incoming_recordkeeper": body["incoming_recordkeeper"],
        "status": "SCHEDULED",
        "activated_at": None,
        "completed_at": None,
    })
    return success_obj(public_blackout(blackout), 201)


@bp.get("/termination-cases/<case_id>/blackout-periods")
def list_blackouts(case_id):
    authenticate(ALL_ROLES)
    case = path_entity("cases", case_id, "termination case")
    limit, offset = pagination_params()
    items = services.case_blackouts(case["id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_blackout(b) for b in page], limit, offset, total, has_more
    )


@bp.post("/blackout-periods/<blackout_id>/activate")
def activate_blackout(blackout_id):
    authenticate(["Recordkeeper"])
    body = body_json()
    check_no_fields(body)
    blackout = path_entity("blackouts", blackout_id, "blackout period")
    # Priority 6 (state) beats priority 10 (temporal).
    if blackout["status"] != "SCHEDULED":
        raise ApiError(
            ERR_BLACKOUT_NOT_SCHEDULED, 409,
            "activation requires a SCHEDULED blackout",
        )
    now = db.now()
    if not (blackout["start_at"] <= now < blackout["end_at"]):
        raise ApiError(
            ERR_BLACKOUT_NOT_IN_WINDOW, 409,
            "activation requires the clock inside [start_at, end_at)",
        )
    advisory = services.live_notice(
        blackout["termination_case_id"], "BLACKOUT_ADVISORY"
    )
    if advisory is None or advisory["action_effective_date"] != blackout["start_at"]:
        raise ApiError(
            ERR_BLACKOUT_NOTICE_MISSING, 422,
            "a non-superseded BLACKOUT_ADVISORY notice covering start_at is "
            "required",
        )
    blackout["status"] = "ACTIVE"
    blackout["activated_at"] = now
    db.touch(blackout)
    return success_obj(public_blackout(blackout), 200)


@bp.post("/blackout-periods/<blackout_id>/complete")
def complete_blackout(blackout_id):
    authenticate(["Recordkeeper"])
    body = body_json()
    check_no_fields(body)
    blackout = path_entity("blackouts", blackout_id, "blackout period")
    if blackout["status"] != "ACTIVE":
        raise ApiError(
            ERR_BLACKOUT_NOT_SCHEDULED, 409,
            "completion requires an ACTIVE blackout",
        )
    now = db.now()
    if now < blackout["end_at"]:
        raise ApiError(
            ERR_BLACKOUT_NOT_ENDED, 409,
            "completion requires the clock at or after end_at",
        )
    blackout["status"] = "COMPLETED"
    blackout["completed_at"] = now
    db.touch(blackout)
    # Cascade hop 2: release the case's queued PREPARED payouts.
    for pay in db.all_of("payouts"):
        participant = db.get("participants", pay["participant_id"])
        if (
            participant is not None
            and participant["termination_case_id"] == blackout["termination_case_id"]
            and pay["status"] == "PREPARED"
        ):
            pay["status"] = "ISSUED"
            pay["issued_at"] = now
            db.touch(pay)
    return success_obj(public_blackout(blackout), 200)

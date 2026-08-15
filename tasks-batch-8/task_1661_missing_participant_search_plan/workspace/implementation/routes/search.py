"""MissingSearchCase and SearchAttempt endpoints (PRD section 3.4)."""

from datetime import timedelta

import db
import services
from errors import (
    ApiError,
    ERR_ATTEMPT_TIMESTAMP_INVALID,
    ERR_CERTIFIED_MAIL_RESPONSE_WINDOW_OPEN,
    ERR_CERTIFIED_MAIL_WINDOW_ACTIVE,
    ERR_NO_ATTEMPT_ON_CURRENT_STEP,
    ERR_SEARCH_CASE_NOT_ESCAPABLE,
    ERR_SEARCH_CASE_NOT_OPEN,
    ERR_SEARCH_METHOD_MISMATCH,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_attempt, public_search_case
from util import (
    apply_filters,
    body_json,
    check_no_fields,
    check_shape,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = make_blueprint("search")


def _get_search_case(search_case_id):
    return path_entity("search_cases", search_case_id, "search case")


@bp.get("/search-cases/<search_case_id>")
def get_search_case(search_case_id):
    authenticate(ALL_ROLES)
    return success_obj(public_search_case(_get_search_case(search_case_id)), 200)


@bp.get("/search-cases")
def list_search_cases():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("search_cases"), [
        "participant_id",
        "termination_case_id",
        "status",
    ])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_search_case(sc) for sc in page], limit, offset, total, has_more
    )


@bp.post("/search-cases/<search_case_id>/attempts")
def record_attempt(search_case_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "method": {
            "type": "enum",
            "values": {
                "COMMERCIAL_LOCATOR",
                "PUBLIC_RECORDS",
                "CREDIT_BUREAU",
                "CERTIFIED_MAIL",
            },
            "required": True,
        },
        "vendor_name": {"type": "string", "required": True},
        "attempted_at": {"type": "datetime", "required": True},
        "outcome": {
            "type": "enum", "values": {"NO_RESULT", "LOCATED"}, "required": True,
        },
        "notes": {"type": "string"},
    })
    search_case = _get_search_case(search_case_id)
    # Priority 6: the case must be in a step state.
    if search_case["status"] not in services.SEARCH_STEP_STATES:
        raise ApiError(
            ERR_SEARCH_CASE_NOT_OPEN, 409,
            "attempts may only be recorded on an open search case",
        )
    # Priority 9: structural constraints.
    if body["method"] != services.STEP_METHOD[search_case["status"]]:
        raise ApiError(
            ERR_SEARCH_METHOD_MISMATCH, 422,
            "method must equal the search case's current step",
        )
    attempted_at = parse_dt(body["attempted_at"], "attempted_at")
    prior_attempts = services.search_case_attempts(search_case["id"])
    if (
        attempted_at > db.now()
        or attempted_at < search_case["opened_at"]
        or any(attempted_at < a["attempted_at"] for a in prior_attempts)
    ):
        raise ApiError(
            ERR_ATTEMPT_TIMESTAMP_INVALID, 422,
            "attempted_at must be >= opened_at, <= now, and >= every prior "
            "attempt's attempted_at on this case",
        )
    # Priority 10: certified-mail 15-day trailing buffer.
    if body["method"] == "CERTIFIED_MAIL":
        for prior in prior_attempts:
            if (
                prior["method"] == "CERTIFIED_MAIL"
                and attempted_at
                < prior["attempted_at"] + timedelta(
                    days=services.CERTIFIED_MAIL_BUFFER_DAYS
                )
            ):
                raise ApiError(
                    ERR_CERTIFIED_MAIL_WINDOW_ACTIVE, 409,
                    "a certified-mail attempt falls inside the 15-day "
                    "trailing buffer of a previous certified-mail attempt",
                )
    attempt = db.new_entity("attempts", {
        "search_case_id": search_case["id"],
        "method": body["method"],
        "vendor_name": body["vendor_name"],
        "attempted_at": attempted_at,
        "outcome": body["outcome"],
        "notes": body.get("notes"),
    }, common=False)
    if body["outcome"] == "LOCATED":
        # Resolve the case and run the participant locate cascade.
        participant = db.get("participants", search_case["participant_id"])
        if participant is not None and participant["locate_status"] == "MISSING":
            services.locate_participant(participant)
        else:
            search_case["status"] = "RESOLVED"
            search_case["resolved_at"] = db.now()
            db.touch(search_case)
    return success_obj(public_attempt(attempt), 201)


@bp.get("/search-cases/<search_case_id>/attempts")
def list_attempts(search_case_id):
    authenticate(ALL_ROLES)
    search_case = _get_search_case(search_case_id)
    limit, offset = pagination_params()
    items = services.search_case_attempts(search_case["id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_attempt(a) for a in page], limit, offset, total, has_more
    )


@bp.post("/search-cases/<search_case_id>/escalate")
def escalate(search_case_id):
    user_id, _role = authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    search_case = _get_search_case(search_case_id)
    if search_case["status"] not in services.SEARCH_STEP_STATES:
        raise ApiError(
            ERR_SEARCH_CASE_NOT_ESCAPABLE, 409,
            "only a search case in a step state can be escalated",
        )
    current_method = services.STEP_METHOD[search_case["status"]]
    attempts = services.search_case_attempts(search_case["id"])
    if not any(
        a["method"] == current_method and a["outcome"] == "NO_RESULT"
        for a in attempts
    ):
        raise ApiError(
            ERR_NO_ATTEMPT_ON_CURRENT_STEP, 409,
            "an attempt with outcome NO_RESULT on the current step is required",
        )
    now = db.now()
    if search_case["status"] == "STEP4_CERTIFIED_MAIL":
        certified = [a for a in attempts if a["method"] == "CERTIFIED_MAIL"]
        latest = max(certified, key=lambda a: (a["attempted_at"], a["_seq"]))
        if now < latest["attempted_at"] + timedelta(
            days=services.CERTIFIED_MAIL_BUFFER_DAYS
        ):
            raise ApiError(
                ERR_CERTIFIED_MAIL_RESPONSE_WINDOW_OPEN, 409,
                "the 15-day certified-mail response window is still open",
            )
    idx = services.SEARCH_STEP_STATES.index(search_case["status"])
    if idx < 3:
        search_case["status"] = services.SEARCH_STEP_STATES[idx + 1]
    else:
        # STEP4 -> EXHAUSTED: stamp exhaustion and freeze the snapshot.
        search_case["status"] = "EXHAUSTED"
        search_case["exhausted_at"] = now
        search_case["exhausted_by_user_id"] = user_id
        participant = db.get("participants", search_case["participant_id"])
        search_case["exhaustion_snapshot_cents"] = (
            services.net_distributable(participant) if participant else None
        )
    db.touch(search_case)
    return success_obj(public_search_case(search_case), 200)

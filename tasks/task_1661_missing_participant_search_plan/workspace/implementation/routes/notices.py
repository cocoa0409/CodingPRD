"""ParticipantNotice endpoints (PRD section 3.1). OCC-guarded on the case
version; issuance supersedes the live notice of the same type."""

import db
import services
from errors import (
    ApiError,
    ERR_BLACKOUT_NOTICE_WINDOW,
    ERR_BLACKOUT_NOT_SCHEDULED,
    ERR_CASE_INVALID_STATE,
    ERR_INTERESTED_PARTY_WINDOW,
    ERR_NOIT_DATE_MISMATCH,
    ERR_NOIT_TIMING_WINDOW,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_notice
from util import (
    apply_filters,
    body_fk,
    body_json,
    check_shape,
    days_between,
    occ_check,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = make_blueprint("notices")

NOTICE_TYPES = {"NOIT", "INTERESTED_PARTY", "BLACKOUT_ADVISORY", "DISTRIBUTION"}


@bp.post("/notices")
def create_notice():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "termination_case_id": {"type": "string", "required": True},
        "notice_type": {"type": "enum", "values": NOTICE_TYPES, "required": True},
        "action_effective_date": {"type": "datetime", "required": True},
        "expected_termination_case_version": {
            "type": "integer", "required": True,
        },
    })
    case = body_fk(body, "termination_case_id", "cases", "termination case")
    # Priority 5: OCC (after existence, before business rules).
    occ_check(body, "expected_termination_case_version", case["version"])

    notice_type = body["notice_type"]
    action_effective_date = parse_dt(
        body["action_effective_date"], "action_effective_date"
    )
    now = db.now()

    # Priority 6: from-state gates.
    if notice_type == "NOIT":
        if case["status"] not in ("DRAFT", "NOTICE_OF_INTENT_ISSUED"):
            raise ApiError(
                ERR_CASE_INVALID_STATE, 409,
                "NOIT requires case status DRAFT or NOTICE_OF_INTENT_ISSUED",
            )
    elif notice_type == "DISTRIBUTION":
        if case["status"] != "TERMINATION_EFFECTIVE":
            raise ApiError(
                ERR_CASE_INVALID_STATE, 409,
                "DISTRIBUTION notice requires TERMINATION_EFFECTIVE",
            )
    else:  # INTERESTED_PARTY, BLACKOUT_ADVISORY: any status except CLOSED
        if case["status"] == "CLOSED":
            raise ApiError(
                ERR_CASE_INVALID_STATE, 409,
                "notices may not be issued on a CLOSED case",
            )
    if notice_type == "BLACKOUT_ADVISORY":
        covering = [
            b for b in services.case_blackouts(case["id"])
            if b["status"] == "SCHEDULED" and b["start_at"] == action_effective_date
        ]
        if not covering:
            raise ApiError(
                ERR_BLACKOUT_NOT_SCHEDULED, 409,
                "no SCHEDULED blackout with start_at == action_effective_date",
            )

    # Priority 10: statutory issuance windows (whole calendar days).
    if notice_type == "NOIT":
        if action_effective_date != case["proposed_termination_date"]:
            raise ApiError(
                ERR_NOIT_DATE_MISMATCH, 422,
                "NOIT action_effective_date must equal proposed_termination_date",
            )
        days = days_between(now, action_effective_date)
        if not (services.NOIT_MIN_DAYS <= days <= services.NOIT_MAX_DAYS):
            raise ApiError(
                ERR_NOIT_TIMING_WINDOW, 422,
                "NOIT must be issued 60 to 90 days before the termination date",
            )
    elif notice_type == "INTERESTED_PARTY":
        days = days_between(now, action_effective_date)
        if not (
            services.INTERESTED_PARTY_MIN_DAYS
            <= days
            <= services.INTERESTED_PARTY_MAX_DAYS
        ):
            raise ApiError(
                ERR_INTERESTED_PARTY_WINDOW, 422,
                "INTERESTED_PARTY notice must be issued 10 to 24 days before "
                "the intended filing date",
            )
    elif notice_type == "BLACKOUT_ADVISORY":
        days = days_between(now, action_effective_date)
        if not (
            services.BLACKOUT_ADVISORY_MIN_DAYS
            <= days
            <= services.BLACKOUT_ADVISORY_MAX_DAYS
        ):
            raise ApiError(
                ERR_BLACKOUT_NOTICE_WINDOW, 422,
                "BLACKOUT_ADVISORY must be issued 30 to 60 days before the "
                "blackout start",
            )

    # Side effects: supersede the live notice of the same type on the case.
    prior = services.live_notice(case["id"], notice_type)
    notice = db.new_entity("notices", {
        "termination_case_id": case["id"],
        "notice_type": notice_type,
        "issued_at": now,
        "action_effective_date": action_effective_date,
        "superseded_by_id": None,
    })
    if prior is not None:
        prior["superseded_by_id"] = notice["id"]
        db.touch(prior)
    if notice_type == "NOIT" and case["status"] == "DRAFT":
        case["status"] = "NOTICE_OF_INTENT_ISSUED"
    # Every successful issuance increments the case version by one.
    db.touch(case)
    return success_obj(public_notice(notice), 201)


@bp.get("/notices/<notice_id>")
def get_notice(notice_id):
    authenticate(ALL_ROLES)
    return success_obj(
        public_notice(path_entity("notices", notice_id, "notice")), 200
    )


@bp.get("/notices")
def list_notices():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("notices"), [
        "termination_case_id",
        "notice_type",
        "superseded_by_id",
    ])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_notice(n) for n in page], limit, offset, total, has_more
    )

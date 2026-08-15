"""DeterminationLetterRequest endpoints (PRD section 3.7)."""

import db
import services
from errors import (
    ApiError,
    ERR_CASE_INVALID_STATE,
    ERR_DLR_ALREADY_OPEN,
    ERR_DLR_INVALID_STATE,
    ERR_INTERESTED_PARTY_WINDOW,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_dlr
from util import (
    body_fk,
    body_json,
    check_no_fields,
    check_shape,
    days_between,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = make_blueprint("dlrs")

OPEN_DLR_STATUSES = {"DRAFT", "FILED", "ADVERSE"}


def _covering_interested_party_notice(case_id, intended_filing_date):
    """The live INTERESTED_PARTY notice whose action_effective_date equals the
    intended filing date, if one exists."""
    notices = [
        n for n in services.case_notices(case_id)
        if n["notice_type"] == "INTERESTED_PARTY"
        and n["superseded_by_id"] is None
        and n["action_effective_date"] == intended_filing_date
    ]
    return notices[-1] if notices else None


@bp.post("/determination-letter-requests")
def create_dlr():
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "termination_case_id": {"type": "string", "required": True},
        "intended_filing_date": {"type": "datetime", "required": True},
    })
    case = body_fk(body, "termination_case_id", "cases", "termination case")
    intended_filing_date = parse_dt(
        body["intended_filing_date"], "intended_filing_date"
    )
    if case["status"] == "CLOSED":
        raise ApiError(
            ERR_CASE_INVALID_STATE, 409,
            "determination letter requests may not be created on a CLOSED case",
        )
    # Priority 9: only one open request at a time.
    if any(
        d["status"] in OPEN_DLR_STATUSES
        for d in db.all_of("dlrs")
        if d["termination_case_id"] == case["id"]
    ):
        raise ApiError(
            ERR_DLR_ALREADY_OPEN, 409,
            "an open determination letter request already exists for the case",
        )
    # Priority 11: a live covering INTERESTED_PARTY notice is required (its
    # 10-to-24-day issuance window was enforced at issuance time).
    if _covering_interested_party_notice(case["id"], intended_filing_date) is None:
        raise ApiError(
            ERR_INTERESTED_PARTY_WINDOW, 422,
            "a non-superseded INTERESTED_PARTY notice covering the intended "
            "filing date is required",
        )
    dlr = db.new_entity("dlrs", {
        "termination_case_id": case["id"],
        "intended_filing_date": intended_filing_date,
        "filed_at": None,
        "status": "DRAFT",
    })
    return success_obj(public_dlr(dlr), 201)


@bp.get("/termination-cases/<case_id>/determination-letter-requests")
def list_dlrs(case_id):
    authenticate(ALL_ROLES)
    case = path_entity("cases", case_id, "termination case")
    limit, offset = pagination_params()
    items = [
        d for d in db.all_of("dlrs") if d["termination_case_id"] == case["id"]
    ]
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_dlr(d) for d in page], limit, offset, total, has_more
    )


@bp.post("/determination-letter-requests/<dlr_id>/file")
def file_dlr(dlr_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    dlr = path_entity("dlrs", dlr_id, "determination letter request")
    if dlr["status"] != "DRAFT":
        raise ApiError(
            ERR_DLR_INVALID_STATE, 409, "file requires a DRAFT request"
        )
    # Re-verify the interested-party window against the clock: the whole
    # calendar days between the covering notice's issued_at and now must be
    # in [10, 24] inclusive.
    notice = _covering_interested_party_notice(
        dlr["termination_case_id"], dlr["intended_filing_date"]
    )
    now = db.now()
    if notice is None:
        raise ApiError(
            ERR_INTERESTED_PARTY_WINDOW, 422,
            "no live covering INTERESTED_PARTY notice exists",
        )
    days = days_between(notice["issued_at"], now)
    if not (
        services.INTERESTED_PARTY_MIN_DAYS
        <= days
        <= services.INTERESTED_PARTY_MAX_DAYS
    ):
        raise ApiError(
            ERR_INTERESTED_PARTY_WINDOW, 422,
            "the covering INTERESTED_PARTY notice must be 10 to 24 days old "
            "at filing",
        )
    dlr["status"] = "FILED"
    dlr["filed_at"] = now
    db.touch(dlr)
    return success_obj(public_dlr(dlr), 200)


@bp.post("/determination-letter-requests/<dlr_id>/record-determination")
def record_determination(dlr_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_shape(body, {
        "outcome": {
            "type": "enum",
            "values": {"FAVORABLE", "ADVERSE"},
            "required": True,
        },
    })
    dlr = path_entity("dlrs", dlr_id, "determination letter request")
    if dlr["status"] != "FILED":
        raise ApiError(
            ERR_DLR_INVALID_STATE, 409,
            "record-determination requires a FILED request",
        )
    dlr["status"] = body["outcome"]
    db.touch(dlr)
    return success_obj(public_dlr(dlr), 200)


@bp.post("/determination-letter-requests/<dlr_id>/withdraw")
def withdraw_dlr(dlr_id):
    authenticate(["PlanAdministrator"])
    body = body_json()
    check_no_fields(body)
    dlr = path_entity("dlrs", dlr_id, "determination letter request")
    if dlr["status"] not in OPEN_DLR_STATUSES:
        raise ApiError(
            ERR_DLR_INVALID_STATE, 409,
            "withdraw requires a DRAFT, FILED, or ADVERSE request",
        )
    dlr["status"] = "WITHDRAWN"
    db.touch(dlr)
    return success_obj(public_dlr(dlr), 200)

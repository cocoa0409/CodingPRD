from flask import Blueprint, request

import response
from db import store, new_rec, touch, serialize, parse_dt
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_ENGAGEMENT_CLIENT,
    ERR_NOT_ASSIGNED_APPRAISER,
    ERR_INVALID_STATE,
    ERR_PERIOD_OVERLAP,
)
from middleware import auth, require_role, get_body, req_enum, req_int, req_str
from response import sort_by_creation
from services import calc, domain

bp = Blueprint("submissions", __name__)

SUBMISSION_TYPES = ("RENT_ROLL", "OPERATING_STATEMENT", "TAX_BILL")


@bp.post("/engagements/<engagementId>/data-submissions")
def create_submission(engagementId):
    uid, role = auth()
    require_role(role, {"Client"})
    eng = domain.get_engagement(engagementId)
    body = get_body()
    submission_type = req_enum(body, "submission_type", SUBMISSION_TYPES)
    period_start_raw = body.get("period_start")
    period_end_raw = body.get("period_end")
    if not isinstance(period_start_raw, str) or not period_start_raw.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "period_start is required")
    if not isinstance(period_end_raw, str) or not period_end_raw.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "period_end is required")
    try:
        period_start = parse_dt(period_start_raw)
        period_end = parse_dt(period_end_raw)
    except Exception:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "period_start/period_end must be ISO 8601"
        )
    if period_end < period_start:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "period_end must not be earlier than period_start"
        )
    scheduled_gross_rent_cents = req_int(body, "scheduled_gross_rent_cents", minimum=0)
    vacancy_loss_cents = req_int(body, "vacancy_loss_cents", minimum=0)
    expense_reimbursements_cents = req_int(
        body, "expense_reimbursements_cents", minimum=0
    )
    operating_expenses_cents = req_int(body, "operating_expenses_cents", minimum=0)
    # Priority 5: client ownership.
    if eng["client_id"] != uid:
        raise ApiError(
            ERR_NOT_ENGAGEMENT_CLIENT, 403, "Caller is not the engagement's client"
        )
    # Priority 8: engagement must be underway.
    if eng["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS"
        )
    # Priority 12: operating-statement inclusive period overlap.
    if submission_type == "OPERATING_STATEMENT":
        for other in store.submissions.values():
            if (
                other["engagement_id"] == eng["id"]
                and other["submission_type"] == "OPERATING_STATEMENT"
                and other["status"] != "REJECTED"
                and period_start <= other["_period_end_dt"]
                and other["_period_start_dt"] <= period_end
            ):
                raise ApiError(
                    ERR_PERIOD_OVERLAP,
                    409,
                    "OPERATING_STATEMENT period overlaps another non-REJECTED statement",
                )
    rec = new_rec(
        {
            "engagement_id": eng["id"],
            "submission_type": submission_type,
            "period_start": period_start_raw,
            "period_end": period_end_raw,
            "scheduled_gross_rent_cents": scheduled_gross_rent_cents,
            "vacancy_loss_cents": vacancy_loss_cents,
            "expense_reimbursements_cents": expense_reimbursements_cents,
            "operating_expenses_cents": operating_expenses_cents,
            "noi_trailing_cents": None,
            "noi_stabilized_cents": None,
            "review_note": None,
            "status": "SUBMITTED",
            "_period_start_dt": period_start,
            "_period_end_dt": period_end,
        }
    )
    store.submissions[rec["id"]] = rec
    return response.success(serialize(rec), status=201)


@bp.get("/data-submissions/<submissionId>")
def get_submission(submissionId):
    auth()
    rec = domain.get_submission(submissionId)
    return response.success(serialize(rec))


@bp.get("/data-submissions")
def list_submissions():
    auth()
    items = list(store.submissions.values())
    for field in ("engagement_id", "submission_type", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    items = sort_by_creation(items)
    return response.list_response([serialize(r) for r in items])


def _review_context(submissionId, uid):
    sub = domain.get_submission(submissionId)
    eng = domain.engagement_of(sub)
    if eng["author_appraiser_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_APPRAISER,
            403,
            "Caller is not the engagement's author appraiser",
        )
    if eng["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is not IN_PROGRESS")
    if sub["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Data submission is not in SUBMITTED"
        )
    return sub, eng


@bp.post("/data-submissions/<submissionId>/accept")
def accept_submission(submissionId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    sub = domain.get_submission(submissionId)
    _review_context(submissionId, uid)
    if sub["submission_type"] == "OPERATING_STATEMENT":
        trailing, stabilized = calc.noi_variants(sub)
        sub["noi_trailing_cents"] = trailing
        sub["noi_stabilized_cents"] = stabilized
    sub["status"] = "ACCEPTED"
    touch(sub)
    return response.success(serialize(sub))


@bp.post("/data-submissions/<submissionId>/reject")
def reject_submission(submissionId):
    uid, role = auth()
    require_role(role, {"StaffAppraiser"})
    sub = domain.get_submission(submissionId)
    body = get_body()
    review_note = req_str(body, "review_note")
    _review_context(submissionId, uid)
    sub["review_note"] = review_note
    sub["status"] = "REJECTED"
    touch(sub)
    return response.success(serialize(sub))

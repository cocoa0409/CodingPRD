"""HearingRequest endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_HEARING_LEAD_TIME,
    ERR_INVALID_HEARING_STATE,
    invalid_request,
    not_found,
)
from middleware import require_roles
from response import ok, paginated
from services import state as svc_state
from services.utils import (
    paginate,
    parse_iso8601,
    parse_pagination,
    require_body,
    require_str,
)

bp = Blueprint("hearings", __name__)


@bp.route("/ssdi/hearings/<hid>", methods=["GET"])
@require_roles("Claimant", "ALJ", "SSAAdmin")
def get_hearing(hid, user_id, role):
    rec = db.hearings.get(hid)
    if rec is None:
        raise not_found(f"hearing {hid} not found")
    return ok(rec)


@bp.route("/ssdi/hearings", methods=["GET"])
@require_roles("ALJ", "SSAAdmin")
def list_hearings(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.hearings.values())
    app_filter = request.args.get("application_id")
    alj_filter = request.args.get("alj_user_id")
    status_filter = request.args.get("status")
    if app_filter:
        items = [r for r in items if r.get("application_id") == app_filter]
    if alj_filter:
        items = [r for r in items if r.get("alj_user_id") == alj_filter]
    if status_filter:
        items = [r for r in items if r.get("status") == status_filter]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)


@bp.route("/ssdi/hearings/<hid>/schedule", methods=["POST"])
@require_roles("ALJ")
def schedule_hearing(hid, user_id, role):
    hr = db.hearings.get(hid)
    if hr is None:
        raise not_found(f"hearing {hid} not found")
    if hr.get("status") != "REQUESTED":
        raise APIError(
            ERR_INVALID_HEARING_STATE,
            409,
            f"hearing not in REQUESTED (current: {hr.get('status')})",
        )
    body = require_body()
    sched = require_str(body, "scheduled_date")
    sched_dt = parse_iso8601(sched, "scheduled_date")
    requested_dt = parse_iso8601(hr["requested_date"], "requested_date")
    if sched_dt < requested_dt + timedelta(days=75):
        raise APIError(
            ERR_HEARING_LEAD_TIME,
            422,
            "scheduled_date must be at least 75 days after requested_date",
        )
    hr["status"] = "SCHEDULED"
    hr["alj_user_id"] = user_id
    hr["scheduled_date"] = sched
    db.stamp_update(hr)
    return ok(hr)


@bp.route("/ssdi/hearings/<hid>/record-held", methods=["POST"])
@require_roles("ALJ")
def record_held(hid, user_id, role):
    hr = db.hearings.get(hid)
    if hr is None:
        raise not_found(f"hearing {hid} not found")
    if hr.get("status") != "SCHEDULED":
        raise APIError(
            ERR_INVALID_HEARING_STATE,
            409,
            f"hearing not in SCHEDULED (current: {hr.get('status')})",
        )
    sched_dt = parse_iso8601(hr["scheduled_date"], "scheduled_date")
    if db.now_utc() < sched_dt:
        raise APIError(
            ERR_INVALID_HEARING_STATE,
            409,
            "cannot record-held before scheduled_date",
        )
    hr["status"] = "HELD"
    db.stamp_update(hr)
    return ok(hr)


@bp.route("/ssdi/hearings/<hid>/decision", methods=["POST"])
@require_roles("ALJ")
def hearing_decision(hid, user_id, role):
    hr = db.hearings.get(hid)
    if hr is None:
        raise not_found(f"hearing {hid} not found")
    # Allow decision from SCHEDULED (or HELD — but scaffold says SCHEDULED). PRD
    # transitions are from SCHEDULED -> APPROVED/DENIED. Accept SCHEDULED only.
    if hr.get("status") != "SCHEDULED":
        raise APIError(
            ERR_INVALID_HEARING_STATE,
            409,
            f"hearing not in SCHEDULED (current: {hr.get('status')})",
        )
    body = require_body()
    outcome = require_str(body, "outcome")
    if outcome not in {"APPROVED", "DENIED"}:
        raise invalid_request(f"invalid outcome: {outcome}")
    app = db.applications.get(hr["application_id"])
    if app is None:
        raise not_found("parent application not found")
    if outcome == "APPROVED":
        hr["status"] = "APPROVED"
        db.stamp_update(hr)
        svc_state.apply_alj_approved(hr, app)
    else:
        hr["status"] = "DENIED"
        db.stamp_update(hr)
        app["status"] = "ALJ_DENIED"
        db.stamp_update(app)
    return ok(hr)


@bp.route("/ssdi/hearings/<hid>/cancel", methods=["POST"])
@require_roles("Claimant")
def cancel_hearing(hid, user_id, role):
    hr = db.hearings.get(hid)
    if hr is None:
        raise not_found(f"hearing {hid} not found")
    if hr.get("status") != "REQUESTED":
        raise APIError(
            ERR_INVALID_HEARING_STATE,
            409,
            f"hearing not in REQUESTED (current: {hr.get('status')})",
        )
    hr["status"] = "CANCELLED"
    db.stamp_update(hr)
    app = db.applications.get(hr["application_id"])
    if app is not None and app.get("status") == "ALJ_PENDING":
        app["status"] = "RECONSIDERATION"
        db.stamp_update(app)
    return ok(hr)

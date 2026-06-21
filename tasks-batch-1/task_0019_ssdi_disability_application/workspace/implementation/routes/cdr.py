"""CDRReview endpoints + clock."""
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_CDR_NOT_DUE,
    ERR_INVALID_APPLICATION_STATE,
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
    years_between,
)

bp = Blueprint("cdr", __name__)


@bp.route("/ssdi/cdr-reviews/<cid>", methods=["GET"])
@require_roles("Claimant", "SSAAdmin", "BenefitsAdmin")
def get_cdr(cid, user_id, role):
    rec = db.cdr_reviews.get(cid)
    if rec is None:
        raise not_found(f"cdr review {cid} not found")
    return ok(rec)


@bp.route("/ssdi/cdr-reviews", methods=["GET"])
@require_roles("SSAAdmin", "BenefitsAdmin")
def list_cdr(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.cdr_reviews.values())
    award_filter = request.args.get("benefit_award_id")
    outcome_filter = request.args.get("outcome")
    if award_filter:
        items = [r for r in items if r.get("benefit_award_id") == award_filter]
    if outcome_filter:
        items = [r for r in items if r.get("outcome") == outcome_filter]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)


def _app_for_cdr(cdr: dict):
    award = db.awards.get(cdr.get("benefit_award_id", ""))
    if award is None:
        return None
    return db.applications.get(award.get("application_id", ""))


@bp.route("/ssdi/cdr-reviews/<cid>/start", methods=["POST"])
@require_roles("SSAAdmin")
def start_cdr(cid, user_id, role):
    cdr = db.cdr_reviews.get(cid)
    if cdr is None:
        raise not_found(f"cdr review {cid} not found")
    app = _app_for_cdr(cdr)
    if app is None:
        raise not_found("parent application not found for this CDR")
    # State must be AWARDED
    if app.get("status") != "AWARDED":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"application not in AWARDED (current: {app.get('status')})",
        )
    # CDR must be due
    sched_dt = parse_iso8601(cdr["scheduled_review_date"], "scheduled_review_date")
    if db.now_utc() < sched_dt:
        raise APIError(ERR_CDR_NOT_DUE, 409, "CDR is not due yet")
    app["status"] = "CDR_FROZEN"
    db.stamp_update(app)
    return ok(cdr)


@bp.route("/ssdi/cdr-reviews/<cid>/complete", methods=["POST"])
@require_roles("SSAAdmin")
def complete_cdr(cid, user_id, role):
    cdr = db.cdr_reviews.get(cid)
    if cdr is None:
        raise not_found(f"cdr review {cid} not found")
    app = _app_for_cdr(cdr)
    if app is None:
        raise not_found("parent application not found for this CDR")
    body = require_body()
    outcome = require_str(body, "outcome")
    if outcome not in {"CONTINUED", "CESSATION"}:
        raise invalid_request(f"invalid outcome: {outcome}")
    if app.get("status") != "CDR_FROZEN":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"application not in CDR_FROZEN (current: {app.get('status')})",
        )
    if cdr.get("outcome") != "PENDING":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"cdr review not in PENDING (current: {cdr.get('outcome')})",
        )
    if outcome == "CONTINUED":
        svc_state.cdr_complete_continued(cdr, app)
    else:
        svc_state.cdr_complete_cessation(cdr, app)
    return ok(cdr)


# ---------- Clock endpoints ----------
clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/ssdi/_clock/set_current_utc", methods=["POST"])
@require_roles("SSAAdmin")
def set_clock(user_id, role):
    body = require_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso, "to_iso8601")
    db.set_clock(dt)
    return ok({})


@clock_bp.route("/ssdi/_clock/advance", methods=["POST"])
@require_roles("SSAAdmin")
def advance_clock(user_id, role):
    body = require_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso, "to_iso8601")
    db.set_clock(dt)
    # Re-evaluate child auxiliaries: any ACTIVE whose child is now >=18 years -> TERMINATED_AGE
    now = db.now_utc()
    for aux in db.child_aux.values():
        if aux.get("status") != "ACTIVE":
            continue
        cdob = parse_iso8601(aux["child_date_of_birth"], "child_date_of_birth")
        if years_between(cdob, now) >= 18:
            aux["status"] = "TERMINATED_AGE"
            db.stamp_update(aux)
    return ok({})

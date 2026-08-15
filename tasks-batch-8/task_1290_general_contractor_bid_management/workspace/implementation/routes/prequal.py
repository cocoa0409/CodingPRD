from flask import Blueprint, request

import errors
from db import DB, CLOCK, new_id, stamp_new, touch, format_ts
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_int, require_number, require_enum, parse_limit_offset,
)
from response import success_object, success_list
from services import prequal as prequal_svc

bp = Blueprint("prequal", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}


def serialize_app(app):
    return {
        "id": app["id"],
        "subcontractor_id": app["subcontractor_id"],
        "declared_annual_revenue_cents": app["declared_annual_revenue_cents"],
        "declared_emr": app["declared_emr"],
        "declared_bonding_capacity_cents": app["declared_bonding_capacity_cents"],
        "self_reported_score": app["self_reported_score"],
        "verified_annual_revenue_cents": app["verified_annual_revenue_cents"],
        "verified_emr": app["verified_emr"],
        "verified_bonding_capacity_cents": app["verified_bonding_capacity_cents"],
        "verified_score": app["verified_score"],
        "review_notes": app["review_notes"],
        "approved_at": app["approved_at"],
        "expires_at": app["expires_at"],
        "status": app["status"],
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "version": app["version"],
    }


def get_app_or_404(app_id):
    app = DB.prequal_applications.get(app_id)
    if app is None:
        raise errors.err_prequal_not_found()
    prequal_svc.apply_lazy_expiry(app)
    prequal_svc.recompute_subcontractor_status(app["subcontractor_id"])
    return app


@bp.post("/prequal-applications")
def create_application():
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    body = get_json_body()
    reject_unexpected(body, {
        "subcontractor_id", "declared_annual_revenue_cents",
        "declared_emr", "declared_bonding_capacity_cents",
    })
    require_fields(body, [
        "subcontractor_id", "declared_annual_revenue_cents",
        "declared_emr", "declared_bonding_capacity_cents",
    ])
    sub_id = body["subcontractor_id"]
    if not isinstance(sub_id, str):
        raise errors.err_invalid_request("subcontractor_id must be a string")
    # Existence (priority 3) before ownership (priority 4)
    sub = DB.subcontractors.get(sub_id)
    if sub is None:
        raise errors.err_subcontractor_not_found()
    if sub_id != user_id:
        raise errors.err_forbidden_ownership()
    rev = require_int(body, "declared_annual_revenue_cents", minimum=0)
    emr = require_number(body, "declared_emr", strict_minimum=0)
    bonding = require_int(body, "declared_bonding_capacity_cents", minimum=0)
    # Window overlap gate (lazy expiry applied inside)
    if prequal_svc.live_application_exists(sub_id):
        raise errors.err_prequal_window_overlap()

    app = {
        "id": new_id(),
        "subcontractor_id": sub_id,
        "declared_annual_revenue_cents": rev,
        "declared_emr": emr,
        "declared_bonding_capacity_cents": bonding,
        "self_reported_score": prequal_svc.prequal_score(rev, emr, bonding, "self_reported"),
        "verified_annual_revenue_cents": None,
        "verified_emr": None,
        "verified_bonding_capacity_cents": None,
        "verified_score": None,
        "review_notes": None,
        "approved_at": None,
        "expires_at": None,
        "_expires_at_dt": None,
        "status": "SUBMITTED",
    }
    stamp_new(app)
    app["_created_at_dt"] = CLOCK.now()
    DB.prequal_applications[app["id"]] = app
    prequal_svc.recompute_subcontractor_status(sub_id)
    return success_object(serialize_app(app), 201)


@bp.get("/prequal-applications")
def list_applications():
    user_id, role = get_context()
    require_role(role, ESTIMATORS | {"Subcontractor"})
    limit, offset = parse_limit_offset(request.args)
    sub_f = request.args.get("subcontractor_id")
    status_f = request.args.get("status")
    # lazy expiry on read
    for app in DB.prequal_applications.values():
        prequal_svc.apply_lazy_expiry(app)
    items = sorted(DB.prequal_applications.values(), key=lambda a: (a["_created_at_dt"], a["id"]))
    if role == "Subcontractor":
        items = [a for a in items if a["subcontractor_id"] == user_id]
    if sub_f is not None:
        items = [a for a in items if a["subcontractor_id"] == sub_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_app(a) for a in page], limit, offset, total)


@bp.get("/prequal-applications/<app_id>")
def read_application(app_id):
    user_id, role = get_context()
    require_role(role, ESTIMATORS | {"Subcontractor"})
    app = get_app_or_404(app_id)
    if role == "Subcontractor" and app["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    return success_object(serialize_app(app))


@bp.post("/prequal-applications/<app_id>/decision")
def decide_application(app_id):
    _, role = get_context()
    require_role(role, {"PrequalReviewer"})
    app = get_app_or_404(app_id)
    body = get_json_body()
    reject_unexpected(body, {
        "decision", "verified_annual_revenue_cents", "verified_emr",
        "verified_bonding_capacity_cents", "review_notes",
    })
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVED", "REJECTED"})
    if app["status"] != "SUBMITTED":
        raise errors.err_application_invalid_state("Decision requires SUBMITTED")

    verified_rev = body.get("verified_annual_revenue_cents")
    verified_emr = body.get("verified_emr")
    verified_bond = body.get("verified_bonding_capacity_cents")
    review_notes = body.get("review_notes")
    if review_notes is not None and not isinstance(review_notes, str):
        raise errors.err_invalid_request("review_notes must be a string")

    if decision == "APPROVED":
        # All three verified inputs required
        for f, v in (("verified_annual_revenue_cents", verified_rev),
                     ("verified_emr", verified_emr),
                     ("verified_bonding_capacity_cents", verified_bond)):
            if v is None:
                raise errors.err_invalid_request(f"Missing required field: {f}")
        if not isinstance(verified_rev, int) or isinstance(verified_rev, bool) or verified_rev < 0:
            raise errors.err_invalid_request("verified_annual_revenue_cents must be an integer >= 0")
        if not isinstance(verified_emr, (int, float)) or isinstance(verified_emr, bool) or verified_emr <= 0:
            raise errors.err_invalid_request("verified_emr must be a number > 0")
        if not isinstance(verified_bond, int) or isinstance(verified_bond, bool) or verified_bond < 0:
            raise errors.err_invalid_request("verified_bonding_capacity_cents must be an integer >= 0")
        score = prequal_svc.prequal_score(verified_rev, verified_emr, verified_bond, "verified")
        app["verified_annual_revenue_cents"] = verified_rev
        app["verified_emr"] = verified_emr
        app["verified_bonding_capacity_cents"] = verified_bond
        app["verified_score"] = score
        if score < 70:
            raise errors.err_score_below_threshold()
        app["status"] = "APPROVED"
        now = CLOCK.now()
        app["approved_at"] = format_ts(now)
        expires = prequal_svc.expires_at_from(now)
        app["expires_at"] = format_ts(expires)
        app["_expires_at_dt"] = expires
        app["review_notes"] = review_notes
    else:  # REJECTED
        # verified_score computed only when all verified_* present
        if verified_rev is not None and verified_emr is not None and verified_bond is not None:
            if not isinstance(verified_rev, int) or isinstance(verified_rev, bool) or verified_rev < 0:
                raise errors.err_invalid_request("verified_annual_revenue_cents must be an integer >= 0")
            if not isinstance(verified_emr, (int, float)) or isinstance(verified_emr, bool) or verified_emr <= 0:
                raise errors.err_invalid_request("verified_emr must be a number > 0")
            if not isinstance(verified_bond, int) or isinstance(verified_bond, bool) or verified_bond < 0:
                raise errors.err_invalid_request("verified_bonding_capacity_cents must be an integer >= 0")
            app["verified_annual_revenue_cents"] = verified_rev
            app["verified_emr"] = verified_emr
            app["verified_bonding_capacity_cents"] = verified_bond
            app["verified_score"] = prequal_svc.prequal_score(
                verified_rev, verified_emr, verified_bond, "verified")
        app["status"] = "REJECTED"
        app["review_notes"] = review_notes

    touch(app)
    prequal_svc.recompute_subcontractor_status(app["subcontractor_id"])
    return success_object(serialize_app(app))


@bp.post("/prequal-applications/<app_id>/resubmit")
def resubmit_application(app_id):
    user_id, role = get_context()
    require_role(role, {"Subcontractor"})
    app = get_app_or_404(app_id)
    if app["subcontractor_id"] != user_id:
        raise errors.err_forbidden_ownership()
    if app["status"] != "REJECTED":
        raise errors.err_application_invalid_state("Resubmit requires REJECTED")
    body = get_json_body()
    reject_unexpected(body, {
        "declared_annual_revenue_cents", "declared_emr", "declared_bonding_capacity_cents",
    })
    require_fields(body, [
        "declared_annual_revenue_cents", "declared_emr", "declared_bonding_capacity_cents",
    ])
    rev = require_int(body, "declared_annual_revenue_cents", minimum=0)
    emr = require_number(body, "declared_emr", strict_minimum=0)
    bonding = require_int(body, "declared_bonding_capacity_cents", minimum=0)
    if prequal_svc.live_application_exists(app["subcontractor_id"], exclude_id=app["id"]):
        raise errors.err_prequal_window_overlap()
    app["declared_annual_revenue_cents"] = rev
    app["declared_emr"] = emr
    app["declared_bonding_capacity_cents"] = bonding
    app["self_reported_score"] = prequal_svc.prequal_score(rev, emr, bonding, "self_reported")
    app["verified_annual_revenue_cents"] = None
    app["verified_emr"] = None
    app["verified_bonding_capacity_cents"] = None
    app["verified_score"] = None
    app["status"] = "SUBMITTED"
    touch(app)
    prequal_svc.recompute_subcontractor_status(app["subcontractor_id"])
    return success_object(serialize_app(app))

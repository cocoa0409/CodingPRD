"""Background vetting: open check, adjudicate, manual clear/deny (PRD §3.3, §3.4)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_BACKGROUND_CHECK_EXISTS,
    ERR_FEE_UNPAID,
    ERR_INVALID_STATE,
)
from middleware import current_user_id, require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_int,
    order_by_created,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services.audit import write_audit
from services.calculations import (
    compute_risk_score,
    dominant_hit_category,
    effective_score,
)
from services.lookups import get_or_404, program_by_code

bp = Blueprint("vetting", __name__)

BC_LIST_ROLES = ["VettingOfficer", "AppealsOfficer", "SchedulingAdmin"]


# --- open vetting: create the BackgroundCheck ---------------------------------
@bp.route("/applications/<app_id>/background-checks", methods=["POST"])
def open_vetting(app_id):
    require_auth(["VettingOfficer"])
    app = get_or_404(db.applications, app_id, "Application")
    body = get_body()
    criminal = optional_int(body, "criminal_hits", default=0, minimum=0)
    watchlist = optional_int(body, "watchlist_hits", default=0, minimum=0)
    revocations = optional_int(body, "prior_revocations", default=0, minimum=0)

    # State precondition (priority 7): SUBMITTED.
    if app["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Application must be SUBMITTED to open vetting")

    # Fee settled (priority 19, business_fiscal — after state per §2.9 ordering).
    if app["fee_paid_cents"] < app["fee_due_cents"]:
        raise APIError(ERR_FEE_UNPAID, 402, "Fee must be paid before vetting may begin")

    # Exactly one BackgroundCheck per application.
    for bc in db.background_checks.values():
        if bc.get("application_id") == app_id:
            raise APIError(ERR_BACKGROUND_CHECK_EXISTS, 409,
                           "A BackgroundCheck already exists for this application")

    risk = compute_risk_score(criminal, watchlist, revocations)
    bc = {
        "application_id": app_id,
        "criminal_hits": criminal,
        "watchlist_hits": watchlist,
        "prior_revocations": revocations,
        "risk_score": risk,
        "redress_offset_applied": 0,
        "status": "PENDING",
        "adjudicated_by_user_id": None,
    }
    stamp_create(bc)
    db.background_checks[bc["id"]] = bc

    app["status"] = "VETTING"
    touch(app)
    write_audit(app_id, "VETTING_STARTED", "Background check opened")
    return ok_object(_public_bc(bc), 201)


@bp.route("/applications/<app_id>/background-checks", methods=["GET"])
def list_background_checks(app_id):
    require_auth(BC_LIST_ROLES)
    get_or_404(db.applications, app_id, "Application")
    limit, offset = parse_pagination()
    items = [b for b in db.background_checks.values() if b.get("application_id") == app_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array([_public_bc(b) for b in page], limit, offset, total)


@bp.route("/background-checks/<bid>", methods=["GET"])
def get_background_check(bid):
    require_auth(BC_LIST_ROLES)
    bc = get_or_404(db.background_checks, bid, "BackgroundCheck")
    return ok_object(_public_bc(bc), 200)


# --- adjudicate ---------------------------------------------------------------
@bp.route("/applications/<app_id>/adjudicate", methods=["POST"])
def adjudicate(app_id):
    require_auth(["VettingOfficer"])
    app = get_or_404(db.applications, app_id, "Application")
    bc = _the_check(app_id)
    if bc is None or bc["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "BackgroundCheck must be PENDING to adjudicate")

    program = program_by_code(app["program_code"])
    risk_threshold = program["vetting_risk_threshold"]
    deny_threshold = program["vetting_deny_threshold"]
    eff = effective_score(bc["risk_score"], bc["redress_offset_applied"])

    bc["adjudicated_by_user_id"] = current_user_id()

    if eff <= risk_threshold:
        bc["status"] = "CLEARED"
        touch(bc)
        # Application stays VETTING (advances only when an appointment is booked).
        return ok_object(_public_bc(bc), 200)
    elif eff < deny_threshold:
        bc["status"] = "REVIEW"
        touch(bc)
        return ok_object(_public_bc(bc), 200)
    else:
        bc["status"] = "ADVERSE"
        touch(bc)
        _deny_application(app, bc)
        write_audit(app_id, "VETTING_ADVERSE", "Adjudication adverse; application denied")
        return ok_object(_public_bc(bc), 200)


# --- manual clear / deny (from REVIEW) ---------------------------------------
@bp.route("/background-checks/<bid>/manual-clear", methods=["POST"])
def manual_clear(bid):
    require_auth(["VettingOfficer"])
    bc = get_or_404(db.background_checks, bid, "BackgroundCheck")
    if bc["status"] != "REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "BackgroundCheck must be in REVIEW")
    bc["status"] = "CLEARED"
    bc["adjudicated_by_user_id"] = current_user_id()
    touch(bc)
    return ok_object(_public_bc(bc), 200)


@bp.route("/background-checks/<bid>/manual-deny", methods=["POST"])
def manual_deny(bid):
    require_auth(["VettingOfficer"])
    bc = get_or_404(db.background_checks, bid, "BackgroundCheck")
    if bc["status"] != "REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "BackgroundCheck must be in REVIEW")
    bc["status"] = "ADVERSE"
    bc["adjudicated_by_user_id"] = current_user_id()
    touch(bc)
    app = db.applications.get(bc["application_id"])
    if app is not None:
        _deny_application(app, bc)
        write_audit(app["id"], "VETTING_ADVERSE", "Manual deny; application denied")
    return ok_object(_public_bc(bc), 200)


# --- helpers ------------------------------------------------------------------
def _the_check(app_id: str):
    for bc in db.background_checks.values():
        if bc.get("application_id") == app_id:
            return bc
    return None


def _deny_application(app: dict, bc: dict) -> None:
    app["status"] = "DENIED"
    app["adverse_reason"] = dominant_hit_category(
        bc["criminal_hits"], bc["watchlist_hits"], bc["prior_revocations"])
    touch(app)


def _public_bc(bc: dict) -> dict:
    """Serialized view; expose the adjudicating officer id and effective score."""
    out = {k: v for k, v in bc.items() if k != "_seq"}
    out["effective_score"] = effective_score(bc["risk_score"], bc["redress_offset_applied"])
    return out

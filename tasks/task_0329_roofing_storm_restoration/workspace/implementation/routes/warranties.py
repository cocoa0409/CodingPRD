"""Warranty resource: create, read, list, activate, cancel, expire."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from timeutil import parse_iso8601, now_iso
from clock import clock
from services import calculations as calc
import validators as V

bp = Blueprint("warranties", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}
CANCEL_BASES = {"PRORATED", "SHORT_RATE"}


@bp.route("/warranties", methods=["POST"])
def create_warranty():
    require_role({"ProductionManager"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    premium_cents = V.require_field(body, "premium_cents")
    if not isinstance(job_id, str):
        V.missing_field("job_id")
    # FK (priority 4)
    V.resolve_fk(db.jobs, job_id)
    # range / type (priority 6)
    V.validate_int(premium_cents, "premium_cents", ge=0)
    term_months = body.get("term_months", 120)
    if term_months is None:
        term_months = 120
    V.validate_int(term_months, "term_months", gt=0)

    ent = common_create_fields(versioned=True)
    ent.update({
        "job_id": job_id,
        "term_months": term_months,
        "premium_cents": premium_cents,
        "start_at": None,
        "status": "PENDING",
        "cancel_basis": None,
        "refund_cents": None,
    })
    with db.lock:
        db.warranties[ent["id"]] = ent
    return success(ent, status=201)


@bp.route("/warranties/<entity_id>", methods=["GET"])
def get_warranty(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.warranties, entity_id)
    return success(ent, status=200)


@bp.route("/warranties", methods=["GET"])
def list_warranties():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.warranties.values())
    for key in ("job_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/warranties/<entity_id>/activate", methods=["POST"])
def activate_warranty(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        w = V.find_or_404(db.warranties, entity_id)
        # state (priority 7)
        if w["status"] != "PENDING":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Warranty not PENDING")
        # cross-entity: parent job must be COMPLETED
        job = db.jobs.get(w["job_id"])
        if job is None or job["status"] != "COMPLETED":
            raise ApiError(errors.ERR_JOB_NOT_COMPLETED, 409, "Job not COMPLETED")
        w["status"] = "ACTIVE"
        w["start_at"] = now_iso(clock.now())
        touch(w)
        # retainage release cascade
        released = job["retainage_held_cents"]
        if released:
            job["retainage_held_cents"] = 0
            job["disbursed_net_cents"] += released
            touch(job)
        return success(w, status=200)


@bp.route("/warranties/<entity_id>/cancel", methods=["POST"])
def cancel_warranty(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        w = V.find_or_404(db.warranties, entity_id)
        body = get_json_body()
        cancel_basis = body.get("cancel_basis")
        # required & valid: absent or unrecognized -> ERR_MISSING_FIELD (PRD §3.10)
        if cancel_basis is None or cancel_basis not in CANCEL_BASES:
            raise ApiError(errors.ERR_MISSING_FIELD, 400,
                           "cancel_basis required (PRORATED or SHORT_RATE)")
        # state (priority 7)
        if w["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Warranty not ACTIVE")
        start_at = parse_iso8601(w["start_at"])
        current = clock.now()
        refund = calc.warranty_refund_cents(
            w["premium_cents"], w["term_months"], start_at, current, cancel_basis,
        )
        w["status"] = "CANCELLED"
        w["cancel_basis"] = cancel_basis
        w["refund_cents"] = refund
        touch(w)
        return success(w, status=200)


@bp.route("/warranties/<entity_id>/expire", methods=["POST"])
def expire_warranty(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        w = V.find_or_404(db.warranties, entity_id)
        # state (priority 7)
        if w["status"] != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "Warranty not ACTIVE")
        start_at = parse_iso8601(w["start_at"])
        expiry = calc.add_months(start_at, w["term_months"])
        if clock.now() < expiry:
            raise ApiError(errors.ERR_WARRANTY_NOT_EXPIRED, 409,
                           "Warranty term not yet elapsed")
        w["status"] = "EXPIRED"
        touch(w)
        return success(w, status=200)

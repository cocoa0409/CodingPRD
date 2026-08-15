"""Candidate registration, views, and departure recording."""

from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_role
import services as svc
from services import new_entity, touch
from util import (req_str, opt_str, opt_dt, req_dt, respond_object, respond_list,
                  parse_pagination, paginate)
from views import candidate_view, referral_view

bp = Blueprint("candidates", __name__)

READ_ROLES = ("PlatformAdmin", "TalentAdmin", "Recruiter", "HiringManager",
              "PayrollProcessor", "ComplianceOfficer")
SUBVIEW_ROLES = ("PlatformAdmin", "TalentAdmin", "Recruiter", "HiringManager",
                 "ComplianceOfficer")


def normalize_email(email):
    return email.strip().lower()


def _get_candidate(cand_id):
    c = store.candidates.get(cand_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Candidate not found")
    return c


@bp.post("/erp/candidates")
def create_candidate():
    body = request.get_json(silent=True) or {}
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    phone = opt_str(body, "phone", None)
    prior_application_at = opt_dt(body, "prior_application_at", None)
    require_role("Recruiter", "TalentAdmin")
    cand = new_entity(store.candidates, {
        "full_name": full_name,
        "email": email,
        "normalized_email": normalize_email(email),
        "phone": phone,
        "prior_application_at": prior_application_at,
        "global_status": "AVAILABLE",
        # A prior direct application seeds the terminal-outcome clock.
        "last_terminal_outcome_at": prior_application_at,
        "hired_via_referral_id": None,
        "departed_at": None,
    })
    return respond_object(candidate_view(cand), status=201)


@bp.get("/erp/candidates")
def list_candidates():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.candidates.values())
    global_status = request.args.get("global_status")
    hired_via = request.args.get("hired_via_referral_id")
    if global_status is not None:
        items = [c for c in items if c["global_status"] == global_status]
    if hired_via is not None:
        items = [c for c in items if c["hired_via_referral_id"] == hired_via]
    page, total = paginate(items, limit, offset)
    return respond_list([candidate_view(c) for c in page], total, limit, offset)


@bp.get("/erp/candidates/<cand_id>")
def get_candidate(cand_id):
    require_role(*READ_ROLES)
    return respond_object(candidate_view(_get_candidate(cand_id)))


@bp.get("/erp/candidates/<cand_id>/referrals")
def candidate_referrals(cand_id):
    require_role(*SUBVIEW_ROLES)
    _get_candidate(cand_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [r for r in svc.sort_by_created(store.referrals.values())
             if r["candidate_id"] == cand_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([referral_view(r) for r in page], total, limit, offset)


@bp.post("/erp/candidates/<cand_id>/record-departure")
def record_departure(cand_id):
    body = request.get_json(silent=True) or {}
    terminated_at = req_dt(body, "terminated_at")
    require_role("Recruiter", "TalentAdmin")
    cand = _get_candidate(cand_id)
    if cand["global_status"] != "HIRED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Candidate must be HIRED to record a departure (currently %s)"
                       % cand["global_status"])
    cand["global_status"] = "DEPARTED"
    cand["departed_at"] = terminated_at
    touch(cand)
    # Retention-failure and clawback consequences are applied by the next
    # POST /erp/_ops/evaluate sweep.
    return respond_object(candidate_view(cand))

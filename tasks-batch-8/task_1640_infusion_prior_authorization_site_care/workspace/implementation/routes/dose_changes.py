"""Dose change requests and decisions with the supersede cascade (PRD 3.8)."""
from flask import Blueprint

from db import db, next_seq, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_AUTH_NOT_APPROVED,
    ERR_DOSE_EXCEEDS_MAX,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_request, get_dose_change, policy_for_request, list_response
from serializers import serialize
from services.calculations import compute_delta_pct
from services.transitions import supersede_request
from util import new_id, CLOCK
from validate import get_body, req_int, req_enum

bp = Blueprint("dose_changes", __name__)


@bp.post("/infusion/authorization-requests/<rid>/dose-change-requests")
def create_dose_change(rid):
    authorized(["AuthCoordinator"])
    body = get_body()
    new_dose_mg = req_int(body, "new_dose_mg")

    req = get_request(rid)
    if req["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED,
                    f"dose changes require an APPROVED request, found {req['status']}")
    policy = policy_for_request(req)
    if new_dose_mg > int(policy["max_dose_mg"]):
        raise_error(ERR_DOSE_EXCEEDS_MAX,
                    f"new_dose_mg {new_dose_mg} exceeds policy max_dose_mg {policy['max_dose_mg']}")

    delta_pct, reauth_required = compute_delta_pct(new_dose_mg, req["approved_dose_mg"])

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "new_dose_mg": new_dose_mg,
        "delta_pct": delta_pct,
        "reauth_required": reauth_required,
        "status": "PENDING",
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["dose_change_requests"][rec["id"]] = rec

    # immediate cascade: a re-auth-required creation places the request's
    # ESTIMATED clearance (at most one) ON_HOLD
    if reauth_required:
        for clearance in db["financial_clearances"].values():
            if (clearance["authorization_request_id"] == req["id"]
                    and clearance["status"] == "ESTIMATED"):
                clearance["status"] = "ON_HOLD"
                touch(clearance, now)
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/dose-change-requests")
def list_dose_changes(rid):
    authorized(["AuthCoordinator", "MedicalDirector"])
    get_request(rid)
    items = [d for d in db["dose_change_requests"].values()
             if d["authorization_request_id"] == rid]
    return list_response(items)


@bp.post("/infusion/dose-change-requests/<did>/decisions")
def decide_dose_change(did):
    caller = authorized(["MedicalDirector"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["APPROVED", "REJECTED"])

    dcr = get_dose_change(did)
    if dcr["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE,
                    f"dose-change request is {dcr['status']}; only PENDING may be decided")

    now = CLOCK.now()
    dcr["status"] = outcome
    dcr["decided_by_user_id"] = caller.user_id
    touch(dcr, now)

    req = db["authorization_requests"].get(dcr["authorization_request_id"])
    if outcome == "APPROVED" and req is not None and req["status"] == "APPROVED":
        if dcr["reauth_required"]:
            # depth-3 cascade: supersede the request, cancelling its future
            # SCHEDULED/CONFIRMED appointments; the clearance remains ON_HOLD
            supersede_request(req, now)
        else:
            # sub-threshold adjustment: just write the new approved dose
            req["approved_dose_mg"] = dcr["new_dose_mg"]
            touch(req, now)
    # REJECTED leaves the parent request untouched; an ON_HOLD clearance becomes
    # eligible for recompute.
    return success_object(serialize(dcr))

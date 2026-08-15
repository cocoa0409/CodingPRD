"""Shared route helpers: pagination, list responses, existence getters, selectors."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_VALIDATION_FAILED,
    ERR_PATIENT_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_AUTH_REQUEST_NOT_FOUND,
    ERR_CRITERIA_SUBMISSION_NOT_FOUND,
    ERR_APPEAL_NOT_FOUND,
    ERR_P2P_NOT_FOUND,
    ERR_BENEFIT_INVESTIGATION_NOT_FOUND,
    ERR_CLEARANCE_NOT_FOUND,
    ERR_LINE_ITEM_NOT_FOUND,
    ERR_CHAIR_NOT_FOUND,
    ERR_APPOINTMENT_NOT_FOUND,
    ERR_DOSE_CHANGE_NOT_FOUND,
    ERR_INVALID_STATE,
)
from response import success_list
from serializers import serialize

ALL_ROLES = ["PolicyAdmin", "AuthCoordinator", "MedicalDirector", "FinanceSpecialist", "Scheduler"]

REQUEST_STATUSES = {"DRAFT", "SUBMITTED", "PENDED", "APPROVED", "DENIED",
                    "SUPERSEDED", "EXPIRED", "DENIED_CLOSED"}
TERMINAL_REQUEST_STATES = {"SUPERSEDED", "EXPIRED", "DENIED_CLOSED"}
SITE_TYPES = {"HOME", "OFFICE", "HOSPITAL_OUTPATIENT"}

# Pagination defaults/bounds from scaffold response_envelope.pagination_defaults.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION_FAILED, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_error(ERR_VALIDATION_FAILED, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION_FAILED, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_VALIDATION_FAILED, "offset must be >= 0")
    return limit, offset


def list_response(items):
    """Sorted by creation timestamp ascending (insertion order breaks ties)."""
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Existence getters (validation stage 4: dedicated 404 per resource)
# ---------------------------------------------------------------------------

def _get(collection, rid, spec, label):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(spec, f"{label} {rid} does not exist")
    return rec


def get_policy(pid):
    return _get("payer_policies", pid, ERR_POLICY_NOT_FOUND, "payer policy")


def get_patient(pid):
    return _get("patients", pid, ERR_PATIENT_NOT_FOUND, "patient")


def get_request(rid):
    return _get("authorization_requests", rid, ERR_AUTH_REQUEST_NOT_FOUND, "authorization request")


def get_submission(sid):
    return _get("criteria_submissions", sid, ERR_CRITERIA_SUBMISSION_NOT_FOUND, "criteria submission")


def get_appeal(aid):
    return _get("appeals", aid, ERR_APPEAL_NOT_FOUND, "appeal")


def get_p2p(rid):
    return _get("peer_to_peer_reviews", rid, ERR_P2P_NOT_FOUND, "peer-to-peer review")


def get_investigation(bid):
    return _get("benefit_investigations", bid, ERR_BENEFIT_INVESTIGATION_NOT_FOUND, "benefit investigation")


def get_clearance(cid):
    return _get("financial_clearances", cid, ERR_CLEARANCE_NOT_FOUND, "financial clearance")


def get_line_item(lid):
    return _get("responsibility_line_items", lid, ERR_LINE_ITEM_NOT_FOUND, "responsibility line item")


def get_chair(cid):
    return _get("infusion_chairs", cid, ERR_CHAIR_NOT_FOUND, "infusion chair")


def get_appointment(aid):
    return _get("appointments", aid, ERR_APPOINTMENT_NOT_FOUND, "appointment")


def get_dose_change(did):
    return _get("dose_change_requests", did, ERR_DOSE_CHANGE_NOT_FOUND, "dose-change request")


# ---------------------------------------------------------------------------
# Selectors / shared gates
# ---------------------------------------------------------------------------

def check_request_not_terminal(req):
    """Terminal-state lockdown: writes aimed at a SUPERSEDED / EXPIRED /
    DENIED_CLOSED request are rejected (PRD 2.9 stage 6)."""
    if req["status"] in TERMINAL_REQUEST_STATES:
        raise_error(ERR_INVALID_STATE,
                    f"authorization request is {req['status']} (terminal)")


def policy_for_request(req):
    return db["payer_policies"].get(req["policy_id"])


def patient_for_request(req):
    return db["patients"].get(req["patient_id"])


def has_verified_benefit(request_id) -> bool:
    return any(b["authorization_request_id"] == request_id and b["status"] == "VERIFIED"
               for b in db["benefit_investigations"].values())


def latest_site_determination(request_id):
    dets = [d for d in db["site_of_care_determinations"].values()
            if d["authorization_request_id"] == request_id]
    if not dets:
        return None
    return max(dets, key=lambda d: (d["created_at"], d["_seq"]))


def clearance_in_statuses(request_id, statuses):
    for c in db["financial_clearances"].values():
        if c["authorization_request_id"] == request_id and c["status"] in statuses:
            return c
    return None

"""Attestation campaigns, attestations, and attestation exceptions."""
from flask import Blueprint, request, g

from db import new_entity, now, store, touch
from errors import ApiError, bad_request, not_found
from middleware import require_any_authenticated, require_roles
from response import get_body, list_response, pub, req_dt, req_enum, req_int, req_str, success
from services import close_campaign, finalize_metrics, open_campaign

bp = Blueprint("attestations", __name__)

REASON_CODES = ("MEDICAL_LEAVE", "MILITARY_DUTY", "ROLE_TRANSITION", "OTHER")
CAMPAIGN_STATUSES = ("DRAFT", "OPEN", "CLOSED", "FINALIZED")


def get_campaign(cid):
    c = store.campaigns.get(cid)
    if c is None:
        raise not_found("campaign not found")
    return c


def get_attestation(aid):
    a = store.attestations.get(aid)
    if a is None:
        raise not_found("attestation not found")
    return a


def get_exception(xid):
    x = store.exceptions.get(xid)
    if x is None:
        raise not_found("exception not found")
    return x


# ------------------------------------------------------------------ campaigns

@bp.post("/campaigns")
def create_campaign():
    require_roles("ComplianceAdmin")
    body = get_body()
    year = req_int(body, "year", 2000, 2100)
    regulator_id = req_str(body, "regulator_id")
    open_at = req_dt(body, "window_open_at")
    close_at = req_dt(body, "window_close_at")
    statement = req_str(body, "statement_version")
    if regulator_id not in store.regulators:
        raise not_found("regulator not found")
    # P8 temporal: close must be strictly later than open.
    if close_at <= open_at:
        raise ApiError("ERR_CAMPAIGN_WINDOW_INVALID",
                       "window_close_at must be strictly later than window_open_at")
    c = new_entity()
    c.update({
        "year": year, "regulator_id": regulator_id,
        "window_open_at": open_at, "window_close_at": close_at,
        "statement_version": statement, "status": "DRAFT", "metrics": None,
    })
    store.campaigns[c["id"]] = c
    return success(pub(c), "object", 201)


@bp.get("/campaigns")
def list_campaigns():
    require_any_authenticated()
    reg_f = request.args.get("regulator_id")
    status_f = request.args.get("status")
    items = list(store.campaigns.values())
    if reg_f is not None:
        items = [c for c in items if c["regulator_id"] == reg_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda c: c["created_at"])
    return list_response(items)


@bp.get("/campaigns/<cid>")
def read_campaign(cid):
    require_any_authenticated()
    return success(pub(get_campaign(cid)))


@bp.post("/campaigns/<cid>/open")
def open_campaign_endpoint(cid):
    require_roles("ComplianceAdmin")
    c = get_campaign(cid)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_CAMPAIGN_NOT_DRAFT", "campaign is not in DRAFT")
    t = now()
    if not (c["window_open_at"] <= t <= c["window_close_at"]):
        raise ApiError("ERR_CAMPAIGN_WINDOW_INVALID",
                       "current instant is outside the campaign window")
    open_campaign(c)
    return success(pub(c))


@bp.post("/campaigns/<cid>/close")
def close_campaign_endpoint(cid):
    require_roles("ComplianceAdmin")
    c = get_campaign(cid)
    if c["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN", "campaign is not OPEN")
    close_campaign(c)
    return success(pub(c))


@bp.post("/campaigns/<cid>/finalize")
def finalize_campaign(cid):
    require_roles("Auditor")
    c = get_campaign(cid)
    if c["status"] != "CLOSED":
        raise ApiError("ERR_CAMPAIGN_NOT_FINALIZABLE", "campaign is not CLOSED")
    c["metrics"] = finalize_metrics(c)
    c["status"] = "FINALIZED"
    touch(c)
    return success(pub(c))


@bp.get("/campaigns/<cid>/attestations")
def list_campaign_attestations(cid):
    require_any_authenticated()
    get_campaign(cid)
    items = [a for a in store.attestations.values() if a["campaign_id"] == cid]
    items.sort(key=lambda a: a["created_at"])
    return list_response(items)


# ---------------------------------------------------------------- attestations

@bp.get("/employees/<eid>/attestations")
def list_employee_attestations(eid):
    require_any_authenticated()
    if eid not in store.employees:
        raise not_found("employee not found")
    items = [a for a in store.attestations.values() if a["employee_id"] == eid]
    items.sort(key=lambda a: a["created_at"])
    return list_response(items)


@bp.get("/attestations/<aid>")
def read_attestation(aid):
    require_any_authenticated()
    return success(pub(get_attestation(aid)))


@bp.post("/attestations/<aid>/attest")
def attest(aid):
    uid, _ = require_roles("Employee")
    att = get_attestation(aid)
    if att["employee_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "caller does not own this attestation")
    if att["status"] != "PENDING":
        raise ApiError("ERR_ATTESTATION_NOT_ACTIONABLE", "attestation is not PENDING")
    camp = store.campaigns.get(att["campaign_id"])
    if camp is None or camp["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN", "campaign is not OPEN")
    emp = store.employees.get(att["employee_id"])
    if emp is not None and emp["status"] == "TERMINATED":
        raise ApiError("ERR_EMPLOYEE_TERMINATED", "employee is TERMINATED")
    att["status"] = "ATTESTED"
    att["attested_at"] = now()
    att["statement_version_snapshot"] = camp["statement_version"]
    touch(att)
    return success(pub(att))


@bp.post("/attestations/<aid>/exceptions")
def request_exception(aid):
    uid, _ = require_roles("Manager")
    att = get_attestation(aid)
    emp = store.employees.get(att["employee_id"])
    # P3: self-service forbidden; otherwise caller must be the employee's current manager.
    if uid == att["employee_id"]:
        raise ApiError("ERR_SELF_ACTION_FORBIDDEN",
                       "a manager may not request an exception on their own attestation")
    if emp is None or emp["manager_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "caller is not the current manager of this employee")
    body = get_body()
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    detail = req_str(body, "detail", min_len=10)
    if att["status"] != "PENDING":
        raise ApiError("ERR_ATTESTATION_NOT_ACTIONABLE", "attestation is not PENDING")
    camp = store.campaigns.get(att["campaign_id"])
    if camp is None or camp["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN", "campaign is not OPEN")
    x = new_entity()
    x.update({
        "attestation_id": aid,
        "reason_code": reason_code,
        "detail": detail,
        "requested_by_manager_id": uid,
        "status": "REQUESTED",
        "decided_by": None,
        "decision_note": None,
    })
    store.exceptions[x["id"]] = x
    att["status"] = "EXCEPTION_PENDING"
    touch(att)
    return success(pub(x), "object", 201)


@bp.get("/attestations/<aid>/exceptions")
def list_attestation_exceptions(aid):
    require_any_authenticated()
    get_attestation(aid)
    items = [x for x in store.exceptions.values() if x["attestation_id"] == aid]
    items.sort(key=lambda x: x["created_at"])
    return list_response(items)


@bp.get("/employees/<eid>/requested-exceptions")
def list_requested_exceptions(eid):
    require_any_authenticated()
    if eid not in store.employees:
        raise not_found("employee not found")
    items = [x for x in store.exceptions.values() if x["requested_by_manager_id"] == eid]
    items.sort(key=lambda x: x["created_at"])
    return list_response(items)


@bp.post("/exceptions/<xid>/approve")
def approve_exception(xid):
    uid, _ = require_roles("ComplianceAdmin")
    x = get_exception(xid)
    if x["status"] != "REQUESTED":
        raise ApiError("ERR_EXCEPTION_NOT_PENDING", "exception is not REQUESTED")
    x["status"] = "APPROVED"
    x["decided_by"] = uid
    touch(x)
    att = store.attestations.get(x["attestation_id"])
    if att is not None and att["status"] == "EXCEPTION_PENDING":
        att["status"] = "EXEMPTED"
        touch(att)
    return success(pub(x))


@bp.post("/exceptions/<xid>/deny")
def deny_exception(xid):
    uid, _ = require_roles("ComplianceAdmin")
    body = get_body()
    note = req_str(body, "decision_note")
    x = get_exception(xid)
    if x["status"] != "REQUESTED":
        raise ApiError("ERR_EXCEPTION_NOT_PENDING", "exception is not REQUESTED")
    x["status"] = "DENIED"
    x["decided_by"] = uid
    x["decision_note"] = note
    touch(x)
    att = store.attestations.get(x["attestation_id"])
    if att is not None and att["status"] == "EXCEPTION_PENDING":
        att["status"] = "PENDING"  # cycle back; the employee can still attest
        touch(att)
    return success(pub(x))

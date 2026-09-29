"""Platform request packages, the provider review cycle and authority grants
(PRD sections 3.5, 3.6).
"""
from flask import Blueprint, request

from authz import (ALL_ROLES, COURT_REGISTRAR, FIDUCIARY, PLATFORM_COMPLIANCE,
                   authenticate, require_action_role,
                   require_fiduciary_estate, require_platform_scope,
                   require_role)
from clock import CLOCK, add_days_dt, format_dt, parse_datetime
from db import DB, bump, sorted_records, stamp_new
from errors import ApiError
from response import public, single
from routes.common import paged
from services import authority, lookup
from services import estate as estate_svc
from validation import bad, parse_body, v_enum, v_id, v_str, v_text, validate

bp = Blueprint("requests", __name__)

REQUEST_TYPES = ("CATALOG_ACCESS", "CONTENT_ACCESS", "DISPOSITION", "CANCELLATION")
REQUESTED_SCOPES = ("CATALOG_ONLY", "CATALOG_AND_CONTENT")
LIVE_WINDOW_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
MAX_INFO_CYCLES = 3

REQUEST_ACTIONS = ("SUBMIT", "START_REVIEW", "REQUEST_INFO", "RESUBMIT",
                   "DECIDE", "WITHDRAW")
REQUEST_ACTION_OWNERS = {
    "SUBMIT": FIDUCIARY,
    "RESUBMIT": FIDUCIARY,
    "WITHDRAW": FIDUCIARY,
    "START_REVIEW": PLATFORM_COMPLIANCE,
    "REQUEST_INFO": PLATFORM_COMPLIANCE,
    "DECIDE": PLATFORM_COMPLIANCE,
}

GRANT_ACTION_OWNERS = {"REVOKE": COURT_REGISTRAR}


@bp.route("/estates/<estate_id>/platform-requests", methods=["POST"])
def create_request(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "platform_id": v_id(),
        "request_type": v_enum(REQUEST_TYPES),
        "requested_scope": v_enum(REQUESTED_SCOPES),
        "death_certificate_document_id": v_id(),
        "letters_document_id": v_id(),
        "platform_form_code": v_str(40),
    })
    estate = lookup.get_estate(estate_id)
    platform = lookup.get_platform(body["platform_id"])
    death_cert = lookup.get_document(body["death_certificate_document_id"])
    letters = lookup.get_document(body["letters_document_id"])
    require_fiduciary_estate(user_id, role, estate_id)
    estate_svc.require_open(estate)

    if death_cert["estate_id"] != estate_id or letters["estate_id"] != estate_id:
        raise ApiError("ERR_DOCUMENT_ESTATE_MISMATCH")
    if death_cert["doc_type"] != "DEATH_CERTIFICATE":
        raise ApiError("ERR_DOCUMENT_TYPE_MISMATCH")
    if letters["doc_type"] != "LETTERS_OF_AUTHORITY":
        raise ApiError("ERR_DOCUMENT_TYPE_MISMATCH")
    if body["platform_form_code"] != platform["form_code"]:
        raise ApiError("ERR_PLATFORM_FORM_MISMATCH")

    record = {
        "estate_id": estate_id,
        "platform_id": platform["id"],
        "death_certificate_document_id": death_cert["id"],
        "letters_document_id": letters["id"],
        "request_type": body["request_type"],
        "requested_scope": body["requested_scope"],
        "platform_form_code": body["platform_form_code"],
        "status": "DRAFT",
        "review_window_start": None,
        "review_window_end": None,
        "info_cycle_count": 0,
        "decision": None,
        "decision_note": None,
        "missing_items": None,
        "remediation_note": None,
        "withdrawal_reason": None,
        "resolved_scope": None,
        "resolved_basis": None,
        "clamp_reason": "NONE",
    }
    stamp_new(record)
    DB.requests[record["id"]] = record
    return single(public(record), 201)


@bp.route("/platform-requests/<request_id>", methods=["GET"])
def read_request(request_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_request(request_id)), 200)


@bp.route("/platform-requests", methods=["GET"])
def list_requests():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.requests.values(), request.args, {
        "estate_id": "estate_id",
        "platform_id": "platform_id",
        "status": "status",
        "request_type": "request_type",
        "death_certificate_document_id": "death_certificate_document_id",
        "letters_document_id": "letters_document_id",
    })


def _window_conflict(req, new_start, new_end):
    """Half-open [start, end) overlap against the live packages on the same
    (estate_id, platform_id, request_type) desk. Adjacency is allowed."""
    for other in sorted_records(lookup.estate_requests(req["estate_id"])):
        if other["id"] == req["id"]:
            continue
        if other["platform_id"] != req["platform_id"]:
            continue
        if other["request_type"] != req["request_type"]:
            continue
        if other["status"] not in LIVE_WINDOW_STATUSES:
            continue
        if not other["review_window_start"] or not other["review_window_end"]:
            continue
        start = parse_datetime(other["review_window_start"])
        end = parse_datetime(other["review_window_end"])
        if new_start < end and start < new_end:
            return True
    return False


def _paperwork_gate(req, platform, estate):
    death_cert = DB.documents.get(req["death_certificate_document_id"])
    letters = DB.documents.get(req["letters_document_id"])
    # priority 39 -- the provider may have changed its form code since drafting
    if req["platform_form_code"] != platform["form_code"]:
        raise ApiError("ERR_PLATFORM_FORM_MISMATCH")
    if death_cert is None or death_cert["verification_status"] != "VERIFIED":
        raise ApiError("ERR_DEATH_CERTIFICATE_NOT_VERIFIED")
    if letters is None or letters["verification_status"] != "VERIFIED":
        raise ApiError("ERR_LETTERS_NOT_ISSUED")
    named = DB.fiduciaries.get(letters.get("fiduciary_id"))
    if named is None or named["letters_status"] != "ISSUED":
        raise ApiError("ERR_LETTERS_NOT_ISSUED")
    if platform["status"] == "SUSPENDED":
        raise ApiError("ERR_PLATFORM_SUSPENDED")


def _content_gate(req, platform, estate):
    if req["request_type"] != "CONTENT_ACCESS":
        return
    result = authority.resolve_authority(estate, platform, None)
    if result["pre_clamp_scope"] != "CATALOG_AND_CONTENT":
        raise ApiError("ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED")
    if result["clamp_reason"] == "COURT_ORDER_REQUIRED":
        raise ApiError("ERR_COURT_ORDER_REQUIRED")


def _open_window(req, platform):
    start = CLOCK.instant()
    end = add_days_dt(start, platform["review_window_days"])
    if _window_conflict(req, start, end):
        raise ApiError("ERR_REQUEST_WINDOW_OVERLAP")
    return format_dt(start), format_dt(end)


@bp.route("/platform-requests/<request_id>/transitions", methods=["POST"])
def request_transition(request_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY, PLATFORM_COMPLIANCE))
    payload = parse_body(request)
    body = validate(payload, required={"action": v_enum(REQUEST_ACTIONS)},
                    optional={
                        "decision": v_enum(("APPROVED", "DENIED")),
                        "decision_note": v_text(),
                        "missing_items": v_text(),
                        "remediation_note": v_text(),
                        "withdrawal_reason": v_text(),
                    })
    action = body["action"]
    if action == "DECIDE" and "decision" not in body:
        raise bad("decision is required with the DECIDE action.")
    require_action_role(role, action, REQUEST_ACTION_OWNERS)

    req = lookup.get_request(request_id)
    estate = DB.estates.get(req["estate_id"])
    platform = DB.platforms.get(req["platform_id"])
    require_fiduciary_estate(user_id, role, req["estate_id"])
    require_platform_scope(user_id, role, req["platform_id"])
    estate_svc.require_open(estate)

    status = req["status"]

    if action == "SUBMIT":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_REQUEST_STATE")
        _paperwork_gate(req, platform, estate)
        _content_gate(req, platform, estate)
        start, end = _open_window(req, platform)
        req["status"] = "SUBMITTED"
        req["review_window_start"] = start
        req["review_window_end"] = end
        bump(req)
        return single(public(req), 200)

    if action == "START_REVIEW":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_REQUEST_STATE")
        req["status"] = "UNDER_REVIEW"
        bump(req)
        return single(public(req), 200)

    if action == "REQUEST_INFO":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_REQUEST_STATE")
        req["status"] = "INFO_REQUESTED"
        req["missing_items"] = body.get("missing_items")
        req["review_window_start"] = None
        req["review_window_end"] = None
        bump(req)
        return single(public(req), 200)

    if action == "RESUBMIT":
        if status != "INFO_REQUESTED":
            raise ApiError("ERR_INVALID_REQUEST_STATE")
        _paperwork_gate(req, platform, estate)
        start, end = _open_window(req, platform)
        if req["info_cycle_count"] >= MAX_INFO_CYCLES:
            raise ApiError("ERR_INFO_CYCLE_LIMIT")
        req["status"] = "SUBMITTED"
        req["info_cycle_count"] += 1
        req["remediation_note"] = body.get("remediation_note")
        req["review_window_start"] = start
        req["review_window_end"] = end
        bump(req)
        return single(public(req), 200)

    if action == "WITHDRAW":
        if status not in ("DRAFT", "SUBMITTED", "INFO_REQUESTED"):
            raise ApiError("ERR_INVALID_REQUEST_STATE")
        req["status"] = "WITHDRAWN"
        req["withdrawal_reason"] = body.get("withdrawal_reason")
        req["review_window_start"] = None
        req["review_window_end"] = None
        bump(req)
        return single(public(req), 200)

    # DECIDE
    if status != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REQUEST_STATE")
    decision = body["decision"]
    if decision == "DENIED":
        req["status"] = "DENIED"
        req["decision"] = "DENIED"
        req["decision_note"] = body.get("decision_note")
        bump(req)
        return single(public(req), 200)

    if platform["status"] == "SUSPENDED":
        raise ApiError("ERR_PLATFORM_SUSPENDED")
    result = authority.resolve_authority(estate, platform, None)
    req["status"] = "APPROVED"
    req["decision"] = "APPROVED"
    req["decision_note"] = body.get("decision_note")
    req["resolved_scope"] = result["resolved_scope"]
    req["resolved_basis"] = result["resolved_basis"]
    req["clamp_reason"] = result["clamp_reason"]
    bump(req)

    grant = authority.create_grant(req)
    touched = authority.disclose_assets(grant)
    authority.open_cancellation_orders(touched)
    estate_svc.recompute(estate)
    return single(public(req), 200)


# --------------------------------------------------------- AuthorityGrant

@bp.route("/authority-grants/<grant_id>", methods=["GET"])
def read_grant(grant_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_grant(grant_id)), 200)


@bp.route("/authority-grants", methods=["GET"])
def list_grants():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.grants.values(), request.args, {
        "estate_id": "estate_id",
        "platform_id": "platform_id",
        "platform_request_id": "platform_request_id",
        "status": "status",
        "granted_scope": "granted_scope",
        "basis": "basis",
    })


@bp.route("/authority-grants/<grant_id>/transitions", methods=["POST"])
def grant_transition(grant_id):
    _, role = authenticate(request)
    require_role(role, (COURT_REGISTRAR,))
    body = validate(parse_body(request),
                    required={"action": v_enum(("REVOKE",))},
                    optional={"reason": v_text()})
    require_action_role(role, body["action"], GRANT_ACTION_OWNERS)

    grant = lookup.get_grant(grant_id)
    estate = DB.estates.get(grant["estate_id"])
    estate_svc.require_open(estate)
    if grant["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_GRANT_STATE")

    authority.revoke_grant(grant, "REGISTRAR_ORDER", reset_clamp=False)
    estate_svc.recompute(estate)
    return single(public(grant), 200)

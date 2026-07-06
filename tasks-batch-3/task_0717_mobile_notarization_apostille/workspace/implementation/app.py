"""Mobile Notarization & Apostille Service API — Flask entry point.

In-memory storage only; the store starts empty on every boot. No seeding.
"""
import os

from flask import Flask, request

import db
import errors
import helpers as h
import models
import calculations as calc
from errors import ApiError, fail
from middleware import require_auth, ALL_ROLES, COORD, NOTARY, CLERK
from response import ok_object, ok_array, error_response

app = Flask(__name__)

# Enum vocabularies
DOC_CATEGORIES = {"GENERAL", "REAL_ESTATE", "LOAN_SIGNING", "APOSTILLE_BOUND"}
DELIVERY_MODES = {"RON", "MOBILE"}
ID_DOC_TYPES = {"DRIVERS_LICENSE", "PASSPORT", "STATE_ID"}
DOC_TYPES = {"DEED", "MORTGAGE", "POA", "AFFIDAVIT", "BIRTH_CERT", "DIPLOMA", "OTHER"}
ACT_TYPES = {"ACKNOWLEDGMENT", "JURAT", "OATH", "COPY_CERTIFICATION"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_INVALID_REQUEST", str(e)), 400


# ---------------------------------------------------------------------------
# Existence helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def must(store, _id):
    rec = store.get(_id)
    if rec is None:
        fail(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@app.route("/notary/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(COORD)
    body = h.get_body()
    iso = h.req_str(body, "to_iso8601")
    try:
        db.parse_iso(iso)
    except (ValueError, TypeError):
        fail(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    db.set_clock(iso)
    return ok_object({}, 200)


# ---------------------------------------------------------------------------
# FeeSchedule
# ---------------------------------------------------------------------------
@app.route("/notary/fee-schedules", methods=["POST"])
def create_fee_schedule():
    require_auth(COORD)
    body = h.get_body()
    rec = models.new_record("FeeSchedule", {
        "state_code": h.req_str(body, "state_code"),
        "per_stamp_cents": h.req_int(body, "per_stamp_cents"),
        "travel_base_cents": h.req_int(body, "travel_base_cents"),
        "travel_per_mile_cents": h.req_int(body, "travel_per_mile_cents"),
        "ron_surcharge_cents": h.req_int(body, "ron_surcharge_cents"),
        "state_cap_cents": h.req_int(body, "state_cap_cents"),
        "enhanced_trust_required": h.opt_bool(body, "enhanced_trust_required", False),
    })
    db.fee_schedules[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/fee-schedules/<fid>", methods=["GET"])
def get_fee_schedule(fid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.fee_schedules, fid)), 200)


@app.route("/notary/fee-schedules", methods=["GET"])
def list_fee_schedules():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    state_code = request.args.get("state_code")
    items = [r for r in db.fee_schedules.values()
             if state_code is None or r["state_code"] == state_code]
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
@app.route("/notary/accounts", methods=["POST"])
def create_account():
    require_auth(COORD)
    body = h.get_body()
    rec = models.new_record("Account", {
        "org_name": h.req_str(body, "org_name"),
        "default_state_code": h.req_str(body, "default_state_code"),
        "retention_years": h.opt_int(body, "retention_years", 10),
    })
    db.accounts[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/accounts/<aid>", methods=["GET"])
def get_account(aid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.accounts, aid)), 200)


# ---------------------------------------------------------------------------
# Notary
# ---------------------------------------------------------------------------
@app.route("/notary/notaries", methods=["POST"])
def create_notary():
    require_auth(COORD)
    body = h.get_body()
    account_id = h.req_str(body, "account_id")
    full_name = h.req_str(body, "full_name")
    commission_state = h.req_str(body, "commission_state")
    commission_expires_at = h.req_str(body, "commission_expires_at")
    try:
        db.parse_iso(commission_expires_at)
    except (ValueError, TypeError):
        fail(errors.ERR_INVALID_REQUEST, "commission_expires_at must be a valid ISO 8601 instant")
    ron_authorized = h.opt_bool(body, "ron_authorized", False)
    nsa_certified = h.opt_bool(body, "nsa_certified", False)
    must(db.accounts, account_id)
    rec = models.new_record("Notary", {
        "account_id": account_id,
        "full_name": full_name,
        "commission_state": commission_state,
        "commission_expires_at": commission_expires_at,
        "ron_authorized": ron_authorized,
        "nsa_certified": nsa_certified,
        "status": "ACTIVE",
        "active_session_count": 0,
    })
    db.notaries[rec["id"]] = rec
    return ok_object(_notary_view(rec), 201)


def _notary_view(rec):
    # active_session_count is derived; reconcile on read.
    rec["active_session_count"] = calc.notary_active_session_count(rec["id"])
    return models.serialize(rec)


@app.route("/notary/notaries/<nid>", methods=["GET"])
def get_notary(nid):
    require_auth(ALL_ROLES)
    return ok_object(_notary_view(must(db.notaries, nid)), 200)


@app.route("/notary/notaries", methods=["GET"])
def list_notaries():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    account_id = request.args.get("account_id")
    items = [r for r in db.notaries.values()
             if account_id is None or r["account_id"] == account_id]
    page, total = h.paginate(items, limit, offset)
    return ok_array([_notary_view(r) for r in page], limit, offset, total)


def _notary_has_live_session(notary_id):
    return any(s["notary_id"] == notary_id and s["session_status"] == "LIVE"
               for s in db.ron_sessions.values())


@app.route("/notary/notaries/<nid>/suspend", methods=["POST"])
def suspend_notary(nid):
    require_auth(COORD)
    h.get_body()
    rec = must(db.notaries, nid)
    if rec["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_STATE, "Notary must be ACTIVE to suspend")
    if _notary_has_live_session(nid):
        fail(errors.ERR_NOTARY_HAS_LIVE_SESSION, "Notary has a LIVE session")
    rec["status"] = "SUSPENDED"
    models.touch(rec)
    return ok_object(_notary_view(rec), 200)


@app.route("/notary/notaries/<nid>/reinstate", methods=["POST"])
def reinstate_notary(nid):
    require_auth(COORD)
    h.get_body()
    rec = must(db.notaries, nid)
    if rec["status"] != "SUSPENDED":
        fail(errors.ERR_INVALID_STATE, "Notary must be SUSPENDED to reinstate")
    if db.parse_iso(rec["commission_expires_at"]) <= db.clock_dt():
        fail(errors.ERR_COMMISSION_EXPIRED, "Commission has expired")
    rec["status"] = "ACTIVE"
    models.touch(rec)
    return ok_object(_notary_view(rec), 200)


@app.route("/notary/notaries/<nid>/expire", methods=["POST"])
def expire_notary(nid):
    require_auth(COORD)
    h.get_body()
    rec = must(db.notaries, nid)
    origin = rec["status"]
    if origin not in ("ACTIVE", "SUSPENDED"):
        fail(errors.ERR_INVALID_STATE, "Notary must be ACTIVE or SUSPENDED to expire")
    if origin == "ACTIVE" and _notary_has_live_session(nid):
        fail(errors.ERR_NOTARY_HAS_LIVE_SESSION, "Notary has a LIVE session")
    rec["status"] = "EXPIRED"
    # Release every ACTIVE assignment for this notary.
    for asg in db.assignments.values():
        if asg["notary_id"] == nid and asg["status"] == "ACTIVE":
            asg["status"] = "RELEASED"
            models.touch(asg)
            # Expiry from ACTIVE cascades one level deeper.
            if origin == "ACTIVE":
                req = db.requests.get(asg["request_id"])
                if req is not None and req["status"] == "ASSIGNED":
                    req["status"] = "DRAFT"
                    req["assigned_notary_id"] = None
                    models.touch(req)
    models.touch(rec)
    return ok_object(_notary_view(rec), 200)


# ---------------------------------------------------------------------------
# Signer
# ---------------------------------------------------------------------------
@app.route("/notary/signers", methods=["POST"])
def create_signer():
    require_auth(COORD)
    body = h.get_body()
    account_id = h.req_str(body, "account_id")
    full_name = h.req_str(body, "full_name")
    email = h.req_str(body, "email")
    id_doc_type = h.req_enum(body, "id_doc_type", ID_DOC_TYPES)
    must(db.accounts, account_id)
    rec = models.new_record("Signer", {
        "account_id": account_id,
        "full_name": full_name,
        "email": email,
        "id_doc_type": id_doc_type,
    })
    db.signers[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/signers/<sid>", methods=["GET"])
def get_signer(sid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.signers, sid)), 200)


@app.route("/notary/signers", methods=["GET"])
def list_signers():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    account_id = request.args.get("account_id")
    items = [r for r in db.signers.values()
             if account_id is None or r["account_id"] == account_id]
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# SigningRequest
# ---------------------------------------------------------------------------
@app.route("/notary/requests", methods=["POST"])
def create_request():
    require_auth(COORD)
    body = h.get_body()
    account_id = h.req_str(body, "account_id")
    signer_id = h.req_str(body, "signer_id")
    state_code = h.req_str(body, "state_code")
    doc_category = h.req_enum(body, "doc_category", DOC_CATEGORIES)
    delivery_mode = h.req_enum(body, "delivery_mode", DELIVERY_MODES)
    expected_stamp_count = h.req_int(body, "expected_stamp_count")
    estimated_travel_miles = h.opt_int(body, "estimated_travel_miles", 0)
    must(db.accounts, account_id)
    must(db.signers, signer_id)
    rec = models.new_record("SigningRequest", {
        "account_id": account_id,
        "signer_id": signer_id,
        "state_code": state_code,
        "doc_category": doc_category,
        "delivery_mode": delivery_mode,
        "expected_stamp_count": expected_stamp_count,
        "estimated_travel_miles": estimated_travel_miles,
        "assigned_notary_id": None,
        "status": "DRAFT",
        "estimate_fee_cents": 0,
        "final_fee_cents": 0,
        "actual_travel_miles": 0,
    })
    db.requests[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/requests/<rid>", methods=["GET"])
def get_request(rid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.requests, rid)), 200)


@app.route("/notary/requests", methods=["GET"])
def list_requests():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    account_id = request.args.get("account_id")
    signer_id = request.args.get("signer_id")
    assigned_notary_id = request.args.get("assigned_notary_id")
    status = request.args.get("status")
    items = []
    for r in db.requests.values():
        if account_id is not None and r["account_id"] != account_id:
            continue
        if signer_id is not None and r["signer_id"] != signer_id:
            continue
        if assigned_notary_id is not None and r["assigned_notary_id"] != assigned_notary_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


def _fee_schedule_for_state(state_code):
    for fs in db.fee_schedules.values():
        if fs["state_code"] == state_code:
            return fs
    return None


@app.route("/notary/requests/<rid>/quote", methods=["POST"])
def quote_request(rid):
    require_auth(COORD)
    h.get_body()
    req = must(db.requests, rid)
    if req["status"] != "DRAFT":
        fail(errors.ERR_INVALID_STATE, "Request must be DRAFT to quote")
    docs = [d for d in db.documents.values() if d["request_id"] == rid]
    if not docs:
        fail(errors.ERR_NO_DOCUMENTS, "Request has no documents")
    fs = _fee_schedule_for_state(req["state_code"])
    if fs is None:
        fail(errors.ERR_FEE_SCHEDULE_MISSING, "No fee schedule for request state")
    ron = req["delivery_mode"] == "RON"
    miles = 0 if ron else req["estimated_travel_miles"]
    req["estimate_fee_cents"] = calc.request_fee(fs, ron, req["expected_stamp_count"], miles)
    req["status"] = "QUOTED"
    models.touch(req)
    return ok_object(models.serialize(req), 200)


@app.route("/notary/requests/<rid>/assign", methods=["POST"])
def assign_request(rid):
    require_auth(COORD)
    body = h.get_body()
    # priority 3: existence, path first (left-to-right)
    req = must(db.requests, rid)
    # priority 4: body well-formedness
    notary_id = h.req_str(body, "notary_id")
    expected_version = h.req_int(body, "expected_request_version")
    # priority 3 (body-referenced): notary existence
    notary = must(db.notaries, notary_id)
    # priority 5: OCC
    if expected_version != req["version"]:
        fail(errors.ERR_STALE_VERSION, "Request version is stale")
    # priority 6: state
    if req["status"] != "QUOTED":
        fail(errors.ERR_INVALID_STATE, "Request must be QUOTED to assign")
    # priority 7: RON/NSA authorization
    if req["delivery_mode"] == "RON" and not notary["ron_authorized"]:
        fail(errors.ERR_RON_NOT_AUTHORIZED, "Notary is not RON authorized")
    if req["doc_category"] == "LOAN_SIGNING" and not notary["nsa_certified"]:
        fail(errors.ERR_NSA_NOT_CERTIFIED, "Notary is not NSA certified")
    # priority 8: commission validity (status ACTIVE + unexpired)
    if notary["status"] != "ACTIVE":
        fail(errors.ERR_NOTARY_NOT_ACTIVE, "Notary is not ACTIVE")
    if db.parse_iso(notary["commission_expires_at"]) <= db.clock_dt():
        fail(errors.ERR_COMMISSION_EXPIRED, "Notary commission expired")
    req["assigned_notary_id"] = notary_id
    req["status"] = "ASSIGNED"
    asg = models.new_record("Assignment", {
        "request_id": rid,
        "notary_id": notary_id,
        "status": "ACTIVE",
    })
    db.assignments[asg["id"]] = asg
    models.touch(req)
    return ok_object(models.serialize(req), 200)


def _cancel_scheduled_sessions(rid):
    for s in db.ron_sessions.values():
        if s["request_id"] == rid and s["session_status"] == "SCHEDULED":
            s["session_status"] = "ENDED"
            if s["recording_status"] != "ARCHIVED":
                s["recording_status"] = "ARCHIVED"
            models.touch(s)


def _release_active_assignment(rid):
    for asg in db.assignments.values():
        if asg["request_id"] == rid and asg["status"] == "ACTIVE":
            asg["status"] = "RELEASED"
            models.touch(asg)


def _request_has_live_session(rid):
    return any(s["request_id"] == rid and s["session_status"] == "LIVE"
               for s in db.ron_sessions.values())


@app.route("/notary/requests/<rid>/revise", methods=["POST"])
def revise_request(rid):
    require_auth(COORD)
    h.get_body()
    req = must(db.requests, rid)
    if req["status"] != "ASSIGNED":
        fail(errors.ERR_INVALID_STATE, "Request must be ASSIGNED to revise")
    if _request_has_live_session(rid):
        fail(errors.ERR_SESSION_LIVE, "A RON session is LIVE")
    req["assigned_notary_id"] = None
    _release_active_assignment(rid)
    _cancel_scheduled_sessions(rid)
    req["estimate_fee_cents"] = 0
    req["status"] = "DRAFT"
    models.touch(req)
    return ok_object(models.serialize(req), 200)


@app.route("/notary/requests/<rid>/start-session", methods=["POST"])
def start_session(rid):
    require_auth(NOTARY)
    h.get_body()
    req = must(db.requests, rid)
    if req["status"] != "ASSIGNED":
        fail(errors.ERR_INVALID_STATE, "Request must be ASSIGNED to start session")
    scheduled = [s for s in db.ron_sessions.values()
                 if s["request_id"] == rid and s["session_status"] == "SCHEDULED"]
    if len(scheduled) != 1:
        fail(errors.ERR_NO_SCHEDULED_SESSION, "Exactly one SCHEDULED session required")
    # PASS IdVerification for (request, request.signer)
    verified = any(
        v["request_id"] == rid and v["signer_id"] == req["signer_id"] and v["outcome"] == "PASS"
        for v in db.id_verifications.values())
    if not verified:
        fail(errors.ERR_ID_NOT_VERIFIED, "No PASS IdVerification for the request signer")
    session = scheduled[0]
    session["session_status"] = "LIVE"
    session["recording_status"] = "RECORDING"
    models.touch(session)
    req["status"] = "IN_SESSION"
    models.touch(req)
    return ok_object(models.serialize(req), 200)


@app.route("/notary/requests/<rid>/complete", methods=["POST"])
def complete_request(rid):
    require_auth(NOTARY)
    body = h.get_body()
    actual_travel_miles = h.opt_int(body, "actual_travel_miles", 0)
    req = must(db.requests, rid)
    if req["status"] != "IN_SESSION":
        fail(errors.ERR_INVALID_STATE, "Request must be IN_SESSION to complete")
    live = [s for s in db.ron_sessions.values()
            if s["request_id"] == rid and s["session_status"] == "LIVE"]
    if not live:
        fail(errors.ERR_NO_LIVE_SESSION, "No LIVE session")
    completed_entries = [e for e in db.journal_entries.values()
                         if e["request_id"] == rid and e["entry_status"] == "COMPLETED"]
    if not completed_entries:
        fail(errors.ERR_NO_JOURNAL_ENTRIES, "No COMPLETED journal entries")
    fs = _fee_schedule_for_state(req["state_code"])
    ron = req["delivery_mode"] == "RON"
    miles = 0 if ron else actual_travel_miles
    req["actual_travel_miles"] = actual_travel_miles
    req["final_fee_cents"] = calc.request_fee(fs, ron, len(completed_entries), miles)
    # End the live session.
    for s in live:
        s["session_status"] = "ENDED"
        s["recording_status"] = "ARCHIVED"
        models.touch(s)
    req["status"] = "COMPLETED"
    models.touch(req)
    # RetentionRecord
    account = db.accounts.get(req["account_id"])
    retention_years = account["retention_years"] if account else 10
    completion_dt = db.clock_dt()
    retain_until = completion_dt.replace(year=completion_dt.year + retention_years)
    retain_iso = retain_until.strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{retain_until.microsecond // 1000:03d}Z"
    rr = models.new_record("RetentionRecord", {
        "request_id": rid,
        "journal_entry_count": len(completed_entries),
        "retain_until": retain_iso,
        "hold_status": "ACTIVE",
    })
    db.retention_records[rr["id"]] = rr
    return ok_object(models.serialize(req), 200)


@app.route("/notary/requests/<rid>/cancel", methods=["POST"])
def cancel_request(rid):
    require_auth(COORD)
    h.get_body()
    req = must(db.requests, rid)
    status = req["status"]
    if status not in ("DRAFT", "QUOTED", "ASSIGNED"):
        fail(errors.ERR_INVALID_STATE, "Request cannot be cancelled from this state")
    if status == "ASSIGNED":
        if _request_has_live_session(rid):
            fail(errors.ERR_SESSION_LIVE, "A RON session is LIVE")
        _release_active_assignment(rid)
        _cancel_scheduled_sessions(rid)
    req["status"] = "CANCELLED"
    models.touch(req)
    return ok_object(models.serialize(req), 200)


# ---------------------------------------------------------------------------
# RequestDocument
# ---------------------------------------------------------------------------
@app.route("/notary/documents", methods=["POST"])
def create_document():
    require_auth(COORD)
    body = h.get_body()
    request_id = h.req_str(body, "request_id")
    title = h.req_str(body, "title")
    doc_type = h.req_enum(body, "doc_type", DOC_TYPES)
    requires_apostille = h.opt_bool(body, "requires_apostille", False)
    signing_fee_cents = h.req_int(body, "signing_fee_cents")
    req = must(db.requests, request_id)
    if req["status"] != "DRAFT":
        fail(errors.ERR_INVALID_STATE, "Documents may only be added while request is DRAFT")
    rec = models.new_record("RequestDocument", {
        "request_id": request_id,
        "title": title,
        "doc_type": doc_type,
        "requires_apostille": requires_apostille,
        "signing_fee_cents": signing_fee_cents,
    })
    db.documents[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/documents/<did>", methods=["GET"])
def get_document(did):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.documents, did)), 200)


@app.route("/notary/documents", methods=["GET"])
def list_documents():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    items = [r for r in db.documents.values()
             if request_id is None or r["request_id"] == request_id]
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Assignment (read-only)
# ---------------------------------------------------------------------------
@app.route("/notary/assignments", methods=["GET"])
def list_assignments():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    notary_id = request.args.get("notary_id")
    items = []
    for r in db.assignments.values():
        if request_id is not None and r["request_id"] != request_id:
            continue
        if notary_id is not None and r["notary_id"] != notary_id:
            continue
        items.append(r)
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


@app.route("/notary/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.assignments, aid)), 200)


# ---------------------------------------------------------------------------
# RonSession
# ---------------------------------------------------------------------------
@app.route("/notary/ron-sessions", methods=["POST"])
def create_ron_session():
    require_auth(NOTARY)
    body = h.get_body()
    request_id = h.req_str(body, "request_id")
    scheduled_start = h.req_str(body, "scheduled_start")
    scheduled_end = h.req_str(body, "scheduled_end")
    try:
        start_dt = db.parse_iso(scheduled_start)
        end_dt = db.parse_iso(scheduled_end)
    except (ValueError, TypeError):
        fail(errors.ERR_INVALID_REQUEST, "scheduled_start/end must be valid ISO 8601")
    req = must(db.requests, request_id)
    # state: request must be ASSIGNED
    if req["status"] != "ASSIGNED":
        fail(errors.ERR_INVALID_STATE, "Request must be ASSIGNED to schedule a session")
    notary_id = req["assigned_notary_id"]
    # priority 10: temporal/overlap; end strictly after start
    if end_dt <= start_dt:
        fail(errors.ERR_SESSION_OVERLAP, "scheduled_end must be strictly after scheduled_start")
    for s in db.ron_sessions.values():
        if s["notary_id"] != notary_id or s["session_status"] == "ENDED":
            continue
        s_start = db.parse_iso(s["scheduled_start"])
        s_end = db.parse_iso(s["scheduled_end"])
        # half-open [start, end) overlap
        if start_dt < s_end and s_start < end_dt:
            fail(errors.ERR_SESSION_OVERLAP, "Session overlaps another non-ENDED session")
    # priority 12: concurrent-session cap
    if calc.notary_active_session_count(notary_id) >= calc.MAX_CONCURRENT_SESSIONS:
        fail(errors.ERR_SESSION_CAP_EXCEEDED, "Notary at concurrent-session cap")
    rec = models.new_record("RonSession", {
        "request_id": request_id,
        "notary_id": notary_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "session_status": "SCHEDULED",
        "recording_status": "NOT_STARTED",
    })
    db.ron_sessions[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/ron-sessions/<sid>", methods=["GET"])
def get_ron_session(sid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.ron_sessions, sid)), 200)


@app.route("/notary/ron-sessions", methods=["GET"])
def list_ron_sessions():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    notary_id = request.args.get("notary_id")
    items = []
    for r in db.ron_sessions.values():
        if request_id is not None and r["request_id"] != request_id:
            continue
        if notary_id is not None and r["notary_id"] != notary_id:
            continue
        items.append(r)
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# IdVerification
# ---------------------------------------------------------------------------
@app.route("/notary/id-verifications", methods=["POST"])
def create_id_verification():
    require_auth(NOTARY)
    body = h.get_body()
    request_id = h.req_str(body, "request_id")
    signer_id = h.req_str(body, "signer_id")
    kba_score = h.req_score(body, "kba_score")
    credential_score = h.req_score(body, "credential_score")
    biometric_score = h.req_score(body, "biometric_score")
    req = must(db.requests, request_id)
    must(db.signers, signer_id)
    fs = _fee_schedule_for_state(req["state_code"])
    enhanced = req["doc_category"] == "LOAN_SIGNING" or \
        (fs is not None and fs.get("enhanced_trust_required", False))
    variant, trust_score, outcome = calc.credential_trust(
        enhanced, kba_score, credential_score, biometric_score)
    rec = models.new_record("IdVerification", {
        "request_id": request_id,
        "signer_id": signer_id,
        "kba_score": kba_score,
        "credential_score": credential_score,
        "biometric_score": biometric_score,
        "trust_variant": variant,
        "trust_score": trust_score,
        "outcome": outcome,
    })
    db.id_verifications[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/id-verifications/<vid>", methods=["GET"])
def get_id_verification(vid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.id_verifications, vid)), 200)


@app.route("/notary/id-verifications", methods=["GET"])
def list_id_verifications():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    signer_id = request.args.get("signer_id")
    items = []
    for r in db.id_verifications.values():
        if request_id is not None and r["request_id"] != request_id:
            continue
        if signer_id is not None and r["signer_id"] != signer_id:
            continue
        items.append(r)
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# JournalEntry
# ---------------------------------------------------------------------------
@app.route("/notary/journal-entries", methods=["POST"])
def create_journal_entry():
    require_auth(NOTARY)
    body = h.get_body()
    request_id = h.req_str(body, "request_id")
    document_id = h.req_str(body, "document_id")
    act_type = h.req_enum(body, "act_type", ACT_TYPES)
    req = must(db.requests, request_id)
    doc = must(db.documents, document_id)
    if req["status"] != "IN_SESSION":
        fail(errors.ERR_INVALID_STATE, "Request must be IN_SESSION to append a journal entry")
    rec = models.new_record("JournalEntry", {
        "request_id": request_id,
        "document_id": document_id,
        "notary_id": req["assigned_notary_id"],
        "act_type": act_type,
        "entry_status": "COMPLETED",
    })
    db.journal_entries[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/journal-entries/<jid>/void", methods=["POST"])
def void_journal_entry(jid):
    require_auth(COORD)
    h.get_body()
    rec = must(db.journal_entries, jid)
    if rec["entry_status"] != "COMPLETED":
        fail(errors.ERR_INVALID_STATE, "Only a COMPLETED entry may be voided")
    rec["entry_status"] = "VOIDED"
    return ok_object(models.serialize(rec), 200)


@app.route("/notary/journal-entries/<jid>", methods=["GET"])
def get_journal_entry(jid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.journal_entries, jid)), 200)


@app.route("/notary/journal-entries", methods=["GET"])
def list_journal_entries():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    document_id = request.args.get("document_id")
    notary_id = request.args.get("notary_id")
    items = []
    for r in db.journal_entries.values():
        if request_id is not None and r["request_id"] != request_id:
            continue
        if document_id is not None and r["document_id"] != document_id:
            continue
        if notary_id is not None and r["notary_id"] != notary_id:
            continue
        items.append(r)
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# ApostilleOrder
# ---------------------------------------------------------------------------
@app.route("/notary/apostille-orders", methods=["POST"])
def create_apostille_order():
    require_auth(CLERK)
    body = h.get_body()
    document_id = h.req_str(body, "document_id")
    destination_country = h.req_str(body, "destination_country")
    sos_office_state = h.req_str(body, "sos_office_state")
    doc = must(db.documents, document_id)
    if not doc.get("requires_apostille", False):
        fail(errors.ERR_INVALID_REQUEST, "Document does not require apostille")
    # duplicate in-flight check (SUBMITTED/ROUTED for same document)
    for o in db.apostille_orders.values():
        if o["document_id"] == document_id and o["status"] in ("SUBMITTED", "ROUTED"):
            fail(errors.ERR_DUPLICATE_APOSTILLE, "An in-flight apostille order exists for this document")
    auth_type, fee_cents = calc.apostille_fee(destination_country)
    rec = models.new_record("ApostilleOrder", {
        "document_id": document_id,
        "destination_country": destination_country,
        "authentication_type": auth_type,
        "sos_office_state": sos_office_state,
        "fee_cents": fee_cents,
        "status": "SUBMITTED",
        "resubmit_count": 0,
    })
    db.apostille_orders[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/apostille-orders/<oid>", methods=["GET"])
def get_apostille_order(oid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.apostille_orders, oid)), 200)


@app.route("/notary/apostille-orders", methods=["GET"])
def list_apostille_orders():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    document_id = request.args.get("document_id")
    status = request.args.get("status")
    items = []
    for r in db.apostille_orders.values():
        if document_id is not None and r["document_id"] != document_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


@app.route("/notary/apostille-orders/<oid>/route", methods=["POST"])
def route_apostille_order(oid):
    require_auth(CLERK)
    h.get_body()
    order = must(db.apostille_orders, oid)
    if order["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Order must be SUBMITTED to route")
    doc = db.documents.get(order["document_id"])
    req = db.requests.get(doc["request_id"]) if doc else None
    if req is None or req["status"] != "COMPLETED":
        fail(errors.ERR_DOCUMENT_NOT_NOTARIZED, "Document's request is not COMPLETED")
    order["status"] = "ROUTED"
    models.touch(order)
    return ok_object(models.serialize(order), 200)


@app.route("/notary/apostille-orders/<oid>/reject", methods=["POST"])
def reject_apostille_order(oid):
    require_auth(CLERK)
    h.get_body()
    order = must(db.apostille_orders, oid)
    if order["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Order must be SUBMITTED to reject")
    order["status"] = "REJECTED"
    models.touch(order)
    return ok_object(models.serialize(order), 200)


@app.route("/notary/apostille-orders/<oid>/authenticate", methods=["POST"])
def authenticate_apostille_order(oid):
    require_auth(CLERK)
    h.get_body()
    order = must(db.apostille_orders, oid)
    if order["status"] != "ROUTED":
        fail(errors.ERR_INVALID_STATE, "Order must be ROUTED to authenticate")
    order["status"] = "AUTHENTICATED"
    models.touch(order)
    return ok_object(models.serialize(order), 200)


@app.route("/notary/apostille-orders/<oid>/return", methods=["POST"])
def return_apostille_order(oid):
    require_auth(CLERK)
    h.get_body()
    order = must(db.apostille_orders, oid)
    if order["status"] != "ROUTED":
        fail(errors.ERR_INVALID_STATE, "Order must be ROUTED to return")
    order["status"] = "RETURNED"
    models.touch(order)
    return ok_object(models.serialize(order), 200)


@app.route("/notary/apostille-orders/<oid>/resubmit", methods=["POST"])
def resubmit_apostille_order(oid):
    require_auth(CLERK)
    h.get_body()
    order = must(db.apostille_orders, oid)
    if order["status"] != "RETURNED":
        fail(errors.ERR_INVALID_STATE, "Order must be RETURNED to resubmit")
    if order["resubmit_count"] >= 3:
        fail(errors.ERR_RESUBMIT_LIMIT, "Resubmit limit reached")
    order["resubmit_count"] += 1
    order["status"] = "SUBMITTED"
    models.touch(order)
    return ok_object(models.serialize(order), 200)


# ---------------------------------------------------------------------------
# LoanPackage
# ---------------------------------------------------------------------------
@app.route("/notary/loan-packages", methods=["POST"])
def create_loan_package():
    require_auth(NOTARY)
    body = h.get_body()
    request_id = h.req_str(body, "request_id")
    lender_ref = h.req_str(body, "lender_ref")
    package_discount_pct = h.opt_number(body, "package_discount_pct", 0)
    req = must(db.requests, request_id)
    if req["doc_category"] != "LOAN_SIGNING":
        fail(errors.ERR_NOT_LOAN_SIGNING, "Request is not a LOAN_SIGNING")
    rec = models.new_record("LoanPackage", {
        "request_id": request_id,
        "lender_ref": lender_ref,
        "package_discount_pct": package_discount_pct,
        "scrub_passed": False,
        "package_fee_cents": 0,
        "status": "DRAFT",
    })
    db.loan_packages[rec["id"]] = rec
    return ok_object(models.serialize(rec), 201)


@app.route("/notary/loan-packages/<pid>", methods=["GET"])
def get_loan_package(pid):
    require_auth(ALL_ROLES)
    return ok_object(models.serialize(must(db.loan_packages, pid)), 200)


@app.route("/notary/loan-packages", methods=["GET"])
def list_loan_packages():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    items = [r for r in db.loan_packages.values()
             if request_id is None or r["request_id"] == request_id]
    page, total = h.paginate(items, limit, offset)
    return ok_array([models.serialize(r) for r in page], limit, offset, total)


@app.route("/notary/loan-packages/<pid>/scrub", methods=["POST"])
def scrub_loan_package(pid):
    require_auth(NOTARY)
    h.get_body()
    pkg = must(db.loan_packages, pid)
    if pkg["status"] != "DRAFT":
        fail(errors.ERR_INVALID_STATE, "Package must be DRAFT to scrub")
    docs = [d for d in db.documents.values() if d["request_id"] == pkg["request_id"]]
    if not any(d["doc_type"] in ("DEED", "MORTGAGE") for d in docs):
        fail(errors.ERR_PACKAGE_MISSING_DOC, "No DEED/MORTGAGE document found")
    ordered = sorted(docs, key=lambda d: (d["created_at"], d.get("_seq", 0)))
    pkg["scrub_passed"] = True
    pkg["package_fee_cents"] = calc.loan_package_fee(ordered, pkg["package_discount_pct"])
    pkg["status"] = "SCRUBBED"
    models.touch(pkg)
    return ok_object(models.serialize(pkg), 200)


@app.route("/notary/loan-packages/<pid>/unscrub", methods=["POST"])
def unscrub_loan_package(pid):
    require_auth(NOTARY)
    h.get_body()
    pkg = must(db.loan_packages, pid)
    if pkg["status"] != "SCRUBBED":
        fail(errors.ERR_INVALID_STATE, "Package must be SCRUBBED to unscrub")
    pkg["scrub_passed"] = False
    pkg["package_fee_cents"] = 0
    pkg["status"] = "DRAFT"
    models.touch(pkg)
    return ok_object(models.serialize(pkg), 200)


@app.route("/notary/loan-packages/<pid>/fund", methods=["POST"])
def fund_loan_package(pid):
    require_auth(COORD)
    body = h.get_body()
    # priority 3: path existence first
    pkg = must(db.loan_packages, pid)
    # priority 4: body well-formedness
    expected_version = h.req_int(body, "expected_package_version")
    # priority 5: OCC
    if expected_version != pkg["version"]:
        fail(errors.ERR_STALE_VERSION, "Package version is stale")
    # priority 6: state
    if pkg["status"] != "SCRUBBED":
        fail(errors.ERR_INVALID_STATE, "Package must be SCRUBBED to fund")
    req = db.requests.get(pkg["request_id"])
    if req is None or req["status"] != "COMPLETED":
        fail(errors.ERR_REQUEST_NOT_COMPLETED, "Wrapped request is not COMPLETED")
    pkg["status"] = "FUNDED"
    models.touch(pkg)
    return ok_object(models.serialize(pkg), 200)


@app.route("/notary/loan-packages/<pid>/cancel", methods=["POST"])
def cancel_loan_package(pid):
    require_auth(COORD)
    h.get_body()
    pkg = must(db.loan_packages, pid)
    if pkg["status"] != "DRAFT":
        fail(errors.ERR_INVALID_STATE, "Package must be DRAFT to cancel")
    pkg["status"] = "CANCELLED"
    models.touch(pkg)
    return ok_object(models.serialize(pkg), 200)


# ---------------------------------------------------------------------------
# RetentionRecord (read-only)
# ---------------------------------------------------------------------------
def _retention_view(rec):
    # hold_status becomes PURGEABLE once the logical clock passes retain_until.
    if rec["hold_status"] != "PURGEABLE":
        if db.clock_dt() >= db.parse_iso(rec["retain_until"]):
            rec["hold_status"] = "PURGEABLE"
    return models.serialize(rec)


@app.route("/notary/retention-records/<rid>", methods=["GET"])
def get_retention_record(rid):
    require_auth(ALL_ROLES)
    return ok_object(_retention_view(must(db.retention_records, rid)), 200)


@app.route("/notary/retention-records", methods=["GET"])
def list_retention_records():
    require_auth(ALL_ROLES)
    limit, offset = h.pagination()
    request_id = request.args.get("request_id")
    items = [r for r in db.retention_records.values()
             if request_id is None or r["request_id"] == request_id]
    page, total = h.paginate(items, limit, offset)
    return ok_array([_retention_view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Direct RonSession drive endpoints (go-live / end)
# ---------------------------------------------------------------------------
@app.route("/notary/ron-sessions/<sid>/go-live", methods=["POST"])
def go_live_session(sid):
    require_auth(NOTARY)
    h.get_body()
    session = must(db.ron_sessions, sid)
    if session["session_status"] != "SCHEDULED":
        fail(errors.ERR_INVALID_STATE, "Session must be SCHEDULED to go live")
    if session["recording_status"] != "NOT_STARTED":
        fail(errors.ERR_RECORDING_ALREADY_STARTED, "Recording already started")
    req = db.requests.get(session["request_id"])
    if req is None or req["status"] != "ASSIGNED":
        fail(errors.ERR_INVALID_STATE, "Owning request must be ASSIGNED")
    session["session_status"] = "LIVE"
    session["recording_status"] = "RECORDING"
    models.touch(session)
    return ok_object(models.serialize(session), 200)


@app.route("/notary/ron-sessions/<sid>/end", methods=["POST"])
def end_session(sid):
    require_auth(NOTARY)
    h.get_body()
    session = must(db.ron_sessions, sid)
    if session["session_status"] != "LIVE":
        fail(errors.ERR_INVALID_STATE, "Session must be LIVE to end")
    if session["recording_status"] != "RECORDING":
        fail(errors.ERR_RECORDING_NOT_ACTIVE, "Recording is not active")
    session["session_status"] = "ENDED"
    session["recording_status"] = "ARCHIVED"
    models.touch(session)
    return ok_object(models.serialize(session), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

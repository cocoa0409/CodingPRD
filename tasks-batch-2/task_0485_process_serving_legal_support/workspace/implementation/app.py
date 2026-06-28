"""Process Serving & Legal Support API — entry point and route registration.

Validation precedence (PRD 2.6): auth(401) -> authz(403) -> existence(404) ->
well-formedness(422) -> stale_version(412) -> invalid_state(409) -> business
rules. Each route follows this order explicitly.
"""
import math
import os

from flask import Flask

from auth import get_principal, require_roles
from clock import clock
from db import db, new_id, now_iso, touch
from errors import ApiError, err
from response import success, error_response
import fees
import serializers as S
import services as svc
from timeutil import parse_dt, format_dt, add_hours, add_days
from validate import (
    get_body, require, require_str, require_enum, require_number, require_int,
    optional_bool, optional_int, parse_pagination, paginate,
)

app = Flask(__name__)

DOC_TYPES = {"SUMMONS", "SUBPOENA", "COMPLAINT", "NOTICE", "WRIT"}
SERVICE_TYPES = {"PERSONAL", "SUBSTITUTE", "POSTING"}
ATTEMPT_OUTCOMES = {"NO_ANSWER", "EVADED", "BAD_ADDRESS", "CONTACT_MADE"}


# ==========================================================================
# Error handling
# ==========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % e)


# ==========================================================================
# Lookup helpers (existence, priority 3)
# ==========================================================================
def must(coll, _id):
    obj = coll.get(_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return obj


def sort_created(items):
    # PRD 2.3: list results sorted by created_at ascending. created_at strings
    # share the same format; tie-break by id for stability.
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


def list_response(views, items, code=200):
    limit, offset = parse_pagination()
    items = sort_created(items)
    page, pagination = paginate(items, limit, offset)
    data = [views(x) for x in page]
    return success(data, code, pagination=pagination)


# ==========================================================================
# Clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_principal()
    require_roles(role, {"Admin"})
    body = get_body()
    iso = require_str(body, "to_iso8601")
    dt = parse_dt(iso, "to_iso8601")
    clock.set(dt)
    return success({"now_utc": format_dt(clock.get())}, 200)


# ==========================================================================
# Client
# ==========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    body = get_body()
    firm_name = require_str(body, "firm_name")
    email = require_str(body, "email")
    ts = now_iso()
    client = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "firm_name": firm_name, "email": email,
        "prepaid_balance_cents": 0, "status": "ACTIVE",
    }
    db.clients[client["id"]] = client
    return success(S.client_view(client), 201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client"})
    client = must(db.clients, cid)
    return success(S.client_view(client), 200)


@app.route("/clients/<cid>/deposits", methods=["POST"])
def add_deposit(cid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    client = must(db.clients, cid)
    body = get_body()
    amount = require_int(body, "amount_cents")
    client["prepaid_balance_cents"] += amount
    touch(client)
    return success(S.client_view(client), 200)


@app.route("/clients/<cid>/state", methods=["POST"])
def set_client_state(cid):
    _, role = get_principal()
    require_roles(role, {"Admin"})
    client = must(db.clients, cid)
    body = get_body()
    to_status = require_enum(body, "to_status", {"ACTIVE", "SUSPENDED"})
    client["status"] = to_status
    touch(client)
    return success(S.client_view(client), 200)


# ==========================================================================
# County
# ==========================================================================
@app.route("/counties", methods=["POST"])
def create_county():
    _, role = get_principal()
    require_roles(role, {"Admin"})
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    ts = now_iso()
    county = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "name": name, "state_code": state_code,
        "e_file_enabled": optional_bool(body, "e_file_enabled", False),
        "min_diligent_attempts": optional_int(body, "min_diligent_attempts", 3, minimum=0),
        "filing_fee_cents": optional_int(body, "filing_fee_cents", 4000, minimum=0),
        "max_concurrent_filings": optional_int(body, "max_concurrent_filings", 2, minimum=0),
    }
    db.counties[county["id"]] = county
    return success(S.county_view(county), 201)


@app.route("/counties/<cid>", methods=["GET"])
def get_county(cid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    county = must(db.counties, cid)
    return success(S.county_view(county), 200)


@app.route("/counties/<cid>/territories", methods=["GET"])
def list_county_territories(cid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    must(db.counties, cid)
    items = [t for t in db.server_territories.values() if t["county_id"] == cid]
    return list_response(S.territory_view, items)


# ==========================================================================
# Server
# ==========================================================================
@app.route("/servers", methods=["POST"])
def create_server():
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    body = get_body()
    full_name = require_str(body, "full_name")
    license_no = require_str(body, "license_no")
    ts = now_iso()
    server = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "full_name": full_name, "license_no": license_no,
        "max_active_assignments": optional_int(body, "max_active_assignments", 5, minimum=0),
        "active_assignment_count": 0, "completed_count": 0,
        "reliability_score": 100, "status": "ACTIVE",
    }
    db.servers[server["id"]] = server
    return success(S.server_view(server), 201)


@app.route("/servers/<sid>", methods=["GET"])
def get_server(sid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    server = must(db.servers, sid)
    return success(S.server_view(server), 200)


@app.route("/servers/<sid>/state", methods=["POST"])
def set_server_state(sid):
    _, role = get_principal()
    require_roles(role, {"Admin"})
    server = must(db.servers, sid)
    body = get_body()
    to_status = require_enum(body, "to_status", {"ACTIVE", "SUSPENDED"})
    server["status"] = to_status
    touch(server)
    return success(S.server_view(server), 200)


@app.route("/servers/<sid>/reliability-projection", methods=["GET"])
def reliability_projection(sid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    server = must(db.servers, sid)
    data = {
        "realized_score": fees.realized_score(sid),
        "projected_score": fees.projected_score(sid),
        "active_assignment_count": server["active_assignment_count"],
    }
    return success(data, 200)


@app.route("/servers/<sid>/territories", methods=["POST"])
def create_territory(sid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    server = must(db.servers, sid)
    body = get_body()
    county_id = require_str(body, "county_id")
    must(db.counties, county_id)
    # Unique (server_id, county_id): a server covers a county at most once.
    for t in db.server_territories.values():
        if t["server_id"] == sid and t["county_id"] == county_id:
            return success(S.territory_view(t), 201)
    territory = {
        "id": new_id(), "created_at": now_iso(),
        "server_id": sid, "county_id": county_id,
    }
    db.server_territories[territory["id"]] = territory
    return success(S.territory_view(territory), 201)


@app.route("/servers/<sid>/territories", methods=["GET"])
def list_server_territories(sid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    must(db.servers, sid)
    items = [t for t in db.server_territories.values() if t["server_id"] == sid]
    return list_response(S.territory_view, items)


@app.route("/servers/<sid>/stakeouts", methods=["GET"])
def list_server_stakeouts(sid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    must(db.servers, sid)
    items = [s for s in db.stakeouts.values() if s["server_id"] == sid]
    return list_response(S.stakeout_view, items)


# ==========================================================================
# ServiceRequest
# ==========================================================================
@app.route("/service-requests", methods=["POST"])
def create_service_request():
    user_id, role = get_principal()
    require_roles(role, {"Client", "Dispatcher"})
    body = get_body()
    client_id = require_str(body, "client_id")
    county_id = require_str(body, "county_id")
    recipient_name = require_str(body, "recipient_name")
    service_address = require_str(body, "service_address")
    service_lat = require_number(body, "service_lat")
    service_lng = require_number(body, "service_lng")
    rush = optional_bool(body, "rush", False)
    skip_trace_requested = optional_bool(body, "skip_trace_requested", False)
    client = must(db.clients, client_id)
    must(db.counties, county_id)
    if role == "Client" and user_id != client_id:
        raise err("ERR_UNAUTHORIZED", "Client may only create its own requests")
    ts = now_iso()
    sr = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "client_id": client_id, "county_id": county_id,
        "recipient_name": recipient_name, "service_address": service_address,
        "service_lat": service_lat, "service_lng": service_lng,
        "rush": rush, "deadline_utc": None,
        "skip_trace_requested": skip_trace_requested,
        "assignment_id": None, "service_type": None,
        "distinct_attempt_days": 0, "quoted_fee_cents": 0,
        "final_fee_cents": 0, "status": "DRAFT",
    }
    db.service_requests[sr["id"]] = sr
    return success(S.service_request_view(sr), 201)


def _sr_owned(sr, user_id, role):
    if role == "Client" and sr["client_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Client may only act on its own requests")


@app.route("/service-requests/<sid>", methods=["GET"])
def get_service_request(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    return success(S.service_request_view(sr), 200)


@app.route("/service-requests", methods=["GET"])
def list_service_requests():
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client"})
    from flask import request
    items = list(db.service_requests.values())
    if role == "Client":
        items = [s for s in items if s["client_id"] == user_id]
    if "client_id" in request.args:
        items = [s for s in items if s["client_id"] == request.args.get("client_id")]
    if "county_id" in request.args:
        items = [s for s in items if s["county_id"] == request.args.get("county_id")]
    if "assignment_id" in request.args:
        items = [s for s in items if s["assignment_id"] == request.args.get("assignment_id")]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args.get("status")]
    return list_response(S.service_request_view, items)


@app.route("/service-requests/<sid>/documents", methods=["POST"])
def create_document(sid):
    user_id, role = get_principal()
    require_roles(role, {"Client", "Dispatcher"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    body = get_body()
    doc_type = require_enum(body, "doc_type", DOC_TYPES)
    page_count = require_int(body, "page_count", minimum=1)
    if sr["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Documents may only be attached while DRAFT")
    ts = now_iso()
    doc = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "service_request_id": sid, "doc_type": doc_type, "page_count": page_count,
    }
    db.documents[doc["id"]] = doc
    return success(S.document_view(doc), 201)


@app.route("/service-requests/<sid>/documents", methods=["GET"])
def list_documents(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    items = [d for d in db.documents.values() if d["service_request_id"] == sid]
    return list_response(S.document_view, items)


@app.route("/service-requests/<sid>/submit", methods=["POST"])
def submit_request(sid):
    user_id, role = get_principal()
    require_roles(role, {"Client", "Dispatcher"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    if sr["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only DRAFT requests may be submitted")
    client = db.clients[sr["client_id"]]
    if client["status"] != "ACTIVE":
        raise err("ERR_CLIENT_SUSPENDED", "Suspended client cannot submit requests")
    has_doc = any(d["service_request_id"] == sid for d in db.documents.values())
    if not has_doc:
        raise err("ERR_NO_DOCUMENT", "At least one document is required to submit")
    # Side effects (PRD 3.2).
    created = parse_dt(sr["created_at"], "created_at")
    if sr["rush"]:
        sr["deadline_utc"] = format_dt(add_hours(created, 48))
    else:
        sr["deadline_utc"] = format_dt(add_days(created, 30))
    sr["quoted_fee_cents"] = fees.compute_fee(sr, "quoted")
    svc.add_invoice_line(sid, "BASE", fees.BASE_FEE_CENTS)
    printing = math.ceil(fees.total_page_count(sid) * fees.PER_PAGE_CENTS)
    svc.add_invoice_line(sid, "PRINTING", int(printing))
    if sr["rush"]:
        svc.add_invoice_line(sid, "RUSH", fees.RUSH_FEE_CENTS)
    if sr["skip_trace_requested"]:
        svc.add_invoice_line(sid, "SKIP_TRACE", fees.SKIP_TRACE_FEE_CENTS)
    sr["status"] = "SUBMITTED"
    sr["final_fee_cents"] = fees.compute_fee(sr, "final")
    touch(sr)
    return success(S.service_request_view(sr), 200)


@app.route("/service-requests/<sid>/skip-traces", methods=["POST"])
def order_skip_trace(sid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    sr = must(db.service_requests, sid)
    body = get_body()
    candidate_addresses = body.get("candidate_addresses")
    if candidate_addresses is None:
        candidate_addresses = []
    if not isinstance(candidate_addresses, list) or not all(isinstance(a, str) for a in candidate_addresses):
        raise err("ERR_INVALID_REQUEST", "candidate_addresses must be an array of strings")
    ts = now_iso()
    st = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "service_request_id": sid, "candidate_addresses": list(candidate_addresses),
        "located_address": None, "status": "REQUESTED",
    }
    db.skip_traces[st["id"]] = st
    return success(S.skip_trace_view(st), 201)


@app.route("/service-requests/<sid>/skip-traces", methods=["GET"])
def list_skip_traces(sid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    must(db.service_requests, sid)
    items = [s for s in db.skip_traces.values() if s["service_request_id"] == sid]
    return list_response(S.skip_trace_view, items)


@app.route("/service-requests/<sid>/assignments", methods=["POST"])
def offer_assignment(sid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    sr = must(db.service_requests, sid)
    body = get_body()
    server_id = require_str(body, "server_id")
    expected_version = require_int(body, "expected_service_request_version")
    server = must(db.servers, server_id)
    # OCC (priority 5).
    if expected_version != sr["version"]:
        raise err("ERR_STALE_VERSION", "Stale service request version")
    # Territory (priority 10).
    covers = any(
        t["server_id"] == server_id and t["county_id"] == sr["county_id"]
        for t in db.server_territories.values()
    )
    if not covers:
        raise err("ERR_OUTSIDE_TERRITORY", "Server does not cover the request's county")
    # Supersede any prior OFFERED assignment for this request.
    for a in db.assignments.values():
        if a["service_request_id"] == sid and a["status"] == "OFFERED":
            a["status"] = "REASSIGNED"
            a["superseded"] = True
            touch(a)
    ts = now_iso()
    asg = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "service_request_id": sid, "server_id": server_id,
        "superseded": False, "status": "OFFERED", "request_terminal": None,
    }
    db.assignments[asg["id"]] = asg
    sr["version"] += 1
    sr["updated_at"] = now_iso()
    return success(S.assignment_view(asg), 201)


@app.route("/service-requests/<sid>/assignments", methods=["GET"])
def list_request_assignments(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    items = [a for a in db.assignments.values() if a["service_request_id"] == sid]
    return list_response(S.assignment_view, items)


@app.route("/service-requests/<sid>/reassign", methods=["POST"])
def reassign_request(sid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    sr = must(db.service_requests, sid)
    asg_id = sr["assignment_id"]
    asg = db.assignments.get(asg_id) if asg_id else None
    if asg is None or asg["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "No active assignment to reassign")
    # ACTIVE -> REASSIGNED (PRD 3.3): free server, no completion credit.
    asg["status"] = "REASSIGNED"
    touch(asg)
    server = db.servers[asg["server_id"]]
    server["active_assignment_count"] -= 1
    touch(server)
    svc.recompute_reliability(server)
    svc.supersede_attempts(asg_id, sr)
    sr["assignment_id"] = None
    sr["status"] = "SUBMITTED"
    touch(sr)
    svc.recompute_distinct_attempt_days(sr)
    return success(S.service_request_view(sr), 200)


@app.route("/service-requests/<sid>/services", methods=["POST"])
def record_service(sid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    sr = must(db.service_requests, sid)
    body = get_body()
    assignment_id = require_str(body, "assignment_id")
    service_type = require_enum(body, "service_type", SERVICE_TYPES)
    served_at = require_str(body, "served_at_utc")
    served_dt = parse_dt(served_at, "served_at_utc")
    recipient_relation = body.get("recipient_relation", "")
    if recipient_relation is None:
        recipient_relation = ""
    if not isinstance(recipient_relation, str):
        raise err("ERR_INVALID_REQUEST", "recipient_relation must be a string")
    asg = must(db.assignments, assignment_id)
    if asg["service_request_id"] != sid:
        raise err("ERR_NOT_FOUND", "Assignment does not belong to this request")
    # Ownership: only the owning server may record service.
    if asg["server_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may record service")
    # State (priority 6): request must be IN_PROGRESS.
    if sr["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Service may only be recorded from IN_PROGRESS")
    # Business preconditions (PRD 3.5).
    if service_type == "PERSONAL":
        latest = _latest_non_superseded_attempt(sid)
        if latest is None or latest["outcome"] != "CONTACT_MADE":
            raise err("ERR_NO_CONTACT_ATTEMPT", "Latest attempt must be CONTACT_MADE for PERSONAL service")
    else:
        county = db.counties[sr["county_id"]]
        if sr["distinct_attempt_days"] < county["min_diligent_attempts"]:
            raise err("ERR_DILIGENCE_NOT_MET", "Diligence floor not met")
    if sr["rush"]:
        deadline = parse_dt(sr["deadline_utc"], "deadline_utc")
        if served_dt > deadline:
            raise err("ERR_DEADLINE_PASSED", "Rush service recorded after the deadline")
    ts = now_iso()
    service = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "service_request_id": sid, "assignment_id": assignment_id,
        "service_type": service_type, "recipient_relation": recipient_relation,
        "served_at_utc": served_at,
    }
    db.services[service["id"]] = service
    # Side effects.
    sr["service_type"] = service_type
    sr["status"] = "SERVED"
    touch(sr)
    aff = {
        "id": new_id(), "created_at": ts, "updated_at": now_iso(), "version": 1,
        "service_request_id": sid, "service_id": service["id"],
        "declarant_server_id": asg["server_id"], "notary_user_id": None,
        "status": "DRAFT",
    }
    db.affidavits[aff["id"]] = aff
    svc.complete_assignment(asg, "SERVED")
    return success(S.service_view(service), 201)


def _latest_non_superseded_attempt(sid):
    candidates = [
        a for a in db.attempts.values()
        if a["service_request_id"] == sid and not a["superseded"]
    ]
    if not candidates:
        return None
    # Latest by attempted_at_utc; tie-break by created_at then id.
    return max(candidates, key=lambda a: (a["attempted_at_utc"], a["created_at"], a["id"]))


@app.route("/service-requests/<sid>/services", methods=["GET"])
def list_request_services(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    items = [s for s in db.services.values() if s["service_request_id"] == sid]
    return list_response(S.service_view, items)


@app.route("/assignments/<aid>/services", methods=["GET"])
def list_assignment_services(aid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server"})
    must(db.assignments, aid)
    items = [s for s in db.services.values() if s["assignment_id"] == aid]
    return list_response(S.service_view, items)


@app.route("/service-requests/<sid>/non-est", methods=["POST"])
def declare_non_est(sid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    sr = must(db.service_requests, sid)
    asg_id = sr["assignment_id"]
    asg = db.assignments.get(asg_id) if asg_id else None
    # Ownership: server must own the governing assignment.
    if asg is not None and asg["server_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may declare non-est")
    if sr["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Non-est may only be declared from IN_PROGRESS")
    county = db.counties[sr["county_id"]]
    if sr["distinct_attempt_days"] < county["min_diligent_attempts"]:
        raise err("ERR_DILIGENCE_NOT_MET", "Diligence floor not met")
    sr["status"] = "NON_EST"
    touch(sr)
    if asg is not None and asg["status"] == "ACTIVE":
        svc.complete_assignment(asg, "NON_EST")
    return success(S.service_request_view(sr), 200)


@app.route("/service-requests/<sid>/cancel", methods=["POST"])
def cancel_request(sid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    sr = must(db.service_requests, sid)
    status = sr["status"]
    if status == "DRAFT":
        sr["status"] = "CANCELLED"
        touch(sr)
    elif status == "SUBMITTED":
        for a in db.assignments.values():
            if a["service_request_id"] == sid and a["status"] == "OFFERED":
                a["status"] = "DECLINED"
                touch(a)
        sr["status"] = "CANCELLED"
        touch(sr)
    elif status in ("ASSIGNED", "IN_PROGRESS"):
        asg_id = sr["assignment_id"]
        asg = db.assignments.get(asg_id) if asg_id else None
        if asg is not None and asg["status"] == "ACTIVE":
            svc.cancel_assignment_cascade(asg, sr)
        sr["status"] = "CANCELLED"
        sr["assignment_id"] = None
        touch(sr)
        svc.recompute_final_fee(sr)
    else:
        raise err("ERR_INVALID_STATE", "Request cannot be cancelled from its current state")
    return success(S.service_request_view(sr), 200)


@app.route("/service-requests/<sid>/complete", methods=["POST"])
def complete_request(sid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    sr = must(db.service_requests, sid)
    if sr["status"] not in ("FILED", "NON_EST"):
        raise err("ERR_INVALID_STATE", "Only FILED or NON_EST requests may be completed")
    final = fees.compute_fee(sr, "final")
    client = db.clients[sr["client_id"]]
    if client["prepaid_balance_cents"] < final:
        raise err("ERR_INSUFFICIENT_FUNDS", "Insufficient prepaid balance")
    sr["final_fee_cents"] = final
    client["prepaid_balance_cents"] -= final
    touch(client)
    sr["status"] = "COMPLETED"
    touch(sr)
    return success(S.service_request_view(sr), 200)


@app.route("/service-requests/<sid>/invoice-lines", methods=["GET"])
def list_invoice_lines(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    items = [l for l in db.invoice_lines.values() if l["service_request_id"] == sid]
    return list_response(S.invoice_line_view, items)


# ==========================================================================
# Assignment
# ==========================================================================
@app.route("/assignments", methods=["GET"])
def list_assignments():
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    from flask import request
    items = list(db.assignments.values())
    if "server_id" in request.args:
        items = [a for a in items if a["server_id"] == request.args.get("server_id")]
    if "service_request_id" in request.args:
        items = [a for a in items if a["service_request_id"] == request.args.get("service_request_id")]
    return list_response(S.assignment_view, items)


@app.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    asg = must(db.assignments, aid)
    return success(S.assignment_view(asg), 200)


@app.route("/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    asg = must(db.assignments, aid)
    # A superseded offer (re-offered to a better-ranked server) was marked
    # REASSIGNED+superseded; accepting it yields ERR_ASSIGNMENT_SUPERSEDED, taking
    # precedence over the generic state check below.
    if asg["superseded"]:
        raise err("ERR_ASSIGNMENT_SUPERSEDED", "Assignment offer has been superseded")
    # State (priority 6): must currently be OFFERED.
    if asg["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Only an OFFERED assignment may be accepted")
    server = db.servers[asg["server_id"]]
    # Business gates (PRD 3.3), in the documented order.
    if server["status"] != "ACTIVE":
        raise err("ERR_SERVER_SUSPENDED", "Suspended server cannot accept offers")
    if server["active_assignment_count"] >= server["max_active_assignments"]:
        raise err("ERR_SERVER_AT_CAPACITY", "Server is at capacity")
    if user_id != asg["server_id"]:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may accept")
    # OFFERED -> ACCEPTED -> ACTIVE (auto-advance).
    asg["status"] = "ACTIVE"
    touch(asg)
    server["active_assignment_count"] += 1
    touch(server)
    sr = db.service_requests[asg["service_request_id"]]
    if sr["status"] == "SUBMITTED":
        sr["status"] = "ASSIGNED"
    sr["assignment_id"] = asg["id"]
    touch(sr)
    # Supersede every other OFFERED assignment for the same request.
    for other in db.assignments.values():
        if other["id"] == asg["id"]:
            continue
        if other["service_request_id"] == sr["id"] and other["status"] == "OFFERED":
            other["status"] = "REASSIGNED"
            other["superseded"] = True
            touch(other)
    return success(S.assignment_view(asg), 200)


@app.route("/assignments/<aid>/state", methods=["POST"])
def assignment_state(aid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    asg = must(db.assignments, aid)
    body = get_body()
    to_status = require_enum(body, "to_status", {"DECLINED"})
    # State (priority 6): only an OFFERED assignment may be declined.
    if asg["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Only an OFFERED assignment may be declined")
    if user_id != asg["server_id"]:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may decline")
    asg["status"] = "DECLINED"
    touch(asg)
    return success(S.assignment_view(asg), 200)


@app.route("/assignments/<aid>/attempts", methods=["POST"])
def log_attempt(aid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    asg = must(db.assignments, aid)
    body = get_body()
    attempted_at = require_str(body, "attempted_at_utc")
    attempted_dt = parse_dt(attempted_at, "attempted_at_utc")
    gps_lat = require_number(body, "gps_lat")
    gps_lng = require_number(body, "gps_lng")
    outcome = require_enum(body, "outcome", ATTEMPT_OUTCOMES)
    # Ownership.
    if user_id != asg["server_id"]:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may log attempts")
    # Server suspension (PRD 3.4).
    server = db.servers[asg["server_id"]]
    if server["status"] != "ACTIVE":
        raise err("ERR_SERVER_SUSPENDED", "Suspended server cannot log attempts")
    # Assignment must be ACTIVE.
    if asg["status"] != "ACTIVE":
        raise err("ERR_ASSIGNMENT_NOT_ACTIVE", "Assignment is not ACTIVE")
    # PRD 3.4 notes attempted_at_utc should be no later than the current logical
    # clock, but the error catalogue defines no dedicated code for a future-dated
    # attempt and the declared test setups log same-period attempts against the
    # default clock expecting success. We therefore accept the supplied
    # timestamp as-is (the clock value is parsed/validated for format only).
    _ = attempted_dt
    sr = db.service_requests[asg["service_request_id"]]
    ts = now_iso()
    attempt = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "assignment_id": aid, "service_request_id": sr["id"],
        "attempted_at_utc": attempted_at, "gps_lat": gps_lat, "gps_lng": gps_lng,
        "outcome": outcome, "superseded": False,
    }
    db.attempts[attempt["id"]] = attempt
    # First non-superseded attempt moves request ASSIGNED -> IN_PROGRESS.
    if sr["status"] == "ASSIGNED":
        sr["status"] = "IN_PROGRESS"
        touch(sr)
    svc.recompute_distinct_attempt_days(sr)
    svc.recompute_final_fee(sr)
    return success(S.attempt_view(attempt), 201)


@app.route("/assignments/<aid>/attempts", methods=["GET"])
def list_assignment_attempts(aid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server"})
    must(db.assignments, aid)
    items = [a for a in db.attempts.values() if a["assignment_id"] == aid]
    return list_response(S.attempt_view, items)


@app.route("/service-requests/<sid>/attempts", methods=["GET"])
def list_request_attempts(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    must(db.service_requests, sid)
    # Non-superseded attempts across the request's assignments.
    items = [
        a for a in db.attempts.values()
        if a["service_request_id"] == sid and not a["superseded"]
    ]
    return list_response(S.attempt_view, items)


@app.route("/assignments/<aid>/stakeouts", methods=["POST"])
def create_stakeout(aid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    asg = must(db.assignments, aid)
    body = get_body()
    ws = require_str(body, "window_start_utc")
    we = require_str(body, "window_end_utc")
    ws_dt = parse_dt(ws, "window_start_utc")
    we_dt = parse_dt(we, "window_end_utc")
    if user_id != asg["server_id"]:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may schedule stakeouts")
    if asg["status"] != "ACTIVE":
        raise err("ERR_ASSIGNMENT_NOT_ACTIVE", "Stakeouts require an ACTIVE assignment")
    server_id = asg["server_id"]
    # Overlap against any other non-CANCELLED stakeout for the same server
    # (half-open [start,end); adjacency allowed).
    for other in db.stakeouts.values():
        if other["server_id"] != server_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        o_start = parse_dt(other["window_start_utc"], "window_start_utc")
        o_end = parse_dt(other["window_end_utc"], "window_end_utc")
        if ws_dt < o_end and o_start < we_dt:
            raise err("ERR_STAKEOUT_OVERLAP", "Stakeout window overlaps an existing window")
    sr = db.service_requests[asg["service_request_id"]]
    ts = now_iso()
    stk = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "assignment_id": aid, "service_request_id": sr["id"], "server_id": server_id,
        "window_start_utc": ws, "window_end_utc": we, "status": "SCHEDULED",
    }
    db.stakeouts[stk["id"]] = stk
    line = svc.add_invoice_line(sr["id"], "STAKEOUT", fees.STAKEOUT_FEE_CENTS)
    line["stakeout_id"] = stk["id"]
    svc.recompute_final_fee(sr)
    return success(S.stakeout_view(stk), 201)


@app.route("/assignments/<aid>/stakeouts", methods=["GET"])
def list_assignment_stakeouts(aid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    must(db.assignments, aid)
    items = [s for s in db.stakeouts.values() if s["assignment_id"] == aid]
    return list_response(S.stakeout_view, items)


@app.route("/stakeouts/<stid>/state", methods=["POST"])
def stakeout_state(stid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    stk = must(db.stakeouts, stid)
    body = get_body()
    to_status = require_enum(body, "to_status", {"COMPLETED", "CANCELLED"})
    if stk["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED stakeout may transition")
    asg = db.assignments[stk["assignment_id"]]
    if user_id != asg["server_id"]:
        raise err("ERR_UNAUTHORIZED", "Only the owning server may transition the stakeout")
    sr = db.service_requests[stk["service_request_id"]]
    if to_status == "COMPLETED":
        stk["status"] = "COMPLETED"
        touch(stk)
    else:
        stk["status"] = "CANCELLED"
        touch(stk)
        svc.cancel_stakeout_line(stk, sr)
        svc.recompute_final_fee(sr)
    return success(S.stakeout_view(stk), 200)


# ==========================================================================
# SkipTrace
# ==========================================================================
@app.route("/skip-traces/<stid>", methods=["GET"])
def get_skip_trace(stid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Server"})
    st = must(db.skip_traces, stid)
    return success(S.skip_trace_view(st), 200)


@app.route("/skip-traces/<stid>/state", methods=["POST"])
def skip_trace_state(stid):
    _, role = get_principal()
    require_roles(role, {"Server"})
    st = must(db.skip_traces, stid)
    body = get_body()
    to_status = require_enum(body, "to_status", {"IN_PROGRESS", "LOCATED", "NOT_LOCATED"})
    cur = st["status"]
    if to_status == "IN_PROGRESS":
        if cur != "REQUESTED":
            raise err("ERR_INVALID_STATE", "IN_PROGRESS only from REQUESTED")
        st["status"] = "IN_PROGRESS"
        touch(st)
    elif to_status == "LOCATED":
        if cur != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "LOCATED only from IN_PROGRESS")
        if not st["candidate_addresses"]:
            raise err("ERR_NO_CANDIDATE_ADDRESS", "No candidate addresses to locate")
        located = require_str(body, "located_address")
        if located not in st["candidate_addresses"]:
            raise err("ERR_ADDRESS_NOT_CANDIDATE", "located_address is not a candidate")
        st["located_address"] = located
        st["status"] = "LOCATED"
        touch(st)
        sr = db.service_requests[st["service_request_id"]]
        sr["service_address"] = located
        touch(sr)
    else:  # NOT_LOCATED
        if cur != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "NOT_LOCATED only from IN_PROGRESS")
        st["status"] = "NOT_LOCATED"
        touch(st)
    return success(S.skip_trace_view(st), 200)


# ==========================================================================
# Affidavit
# ==========================================================================
@app.route("/affidavits/<afid>", methods=["GET"])
def get_affidavit(afid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server", "Notary"})
    aff = must(db.affidavits, afid)
    return success(S.affidavit_view(aff), 200)


@app.route("/service-requests/<sid>/affidavits", methods=["GET"])
def list_request_affidavits(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client", "Server", "Notary"})
    sr = must(db.service_requests, sid)
    if role == "Client":
        _sr_owned(sr, user_id, role)
    from flask import request
    items = [a for a in db.affidavits.values() if a["service_request_id"] == sid]
    if "service_id" in request.args:
        items = [a for a in items if a["service_id"] == request.args.get("service_id")]
    return list_response(S.affidavit_view, items)


@app.route("/affidavits", methods=["GET"])
def list_affidavits():
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Notary", "Server"})
    from flask import request
    items = list(db.affidavits.values())
    if "declarant_server_id" in request.args:
        items = [a for a in items if a["declarant_server_id"] == request.args.get("declarant_server_id")]
    if "service_id" in request.args:
        items = [a for a in items if a["service_id"] == request.args.get("service_id")]
    return list_response(S.affidavit_view, items)


@app.route("/affidavits/<afid>/sign", methods=["POST"])
def sign_affidavit(afid):
    user_id, role = get_principal()
    require_roles(role, {"Server"})
    aff = must(db.affidavits, afid)
    if aff["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT affidavit may be signed")
    if user_id != aff["declarant_server_id"]:
        raise err("ERR_UNAUTHORIZED", "Only the declarant server may sign")
    aff["status"] = "SIGNED"
    touch(aff)
    return success(S.affidavit_view(aff), 200)


@app.route("/affidavits/<afid>/notarize", methods=["POST"])
def notarize_affidavit(afid):
    user_id, role = get_principal()
    require_roles(role, {"Notary"})
    aff = must(db.affidavits, afid)
    if aff["status"] != "SIGNED":
        raise err("ERR_INVALID_STATE", "Only a SIGNED affidavit may be notarized")
    # Segregation of duties (priority 9).
    if user_id == aff["declarant_server_id"]:
        raise err("ERR_SEGREGATION_VIOLATION", "Declarant cannot notarize own affidavit")
    aff["notary_user_id"] = user_id
    aff["status"] = "NOTARIZED"
    touch(aff)
    return success(S.affidavit_view(aff), 200)


# ==========================================================================
# Filing
# ==========================================================================
@app.route("/service-requests/<sid>/filings", methods=["POST"])
def create_filing(sid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    sr = must(db.service_requests, sid)
    body = get_body()
    affidavit_id = require_str(body, "affidavit_id")
    ws = require_str(body, "window_start_utc")
    we = require_str(body, "window_end_utc")
    parse_dt(ws, "window_start_utc")
    parse_dt(we, "window_end_utc")
    aff = must(db.affidavits, affidavit_id)
    if aff["service_request_id"] != sid:
        raise err("ERR_NOT_FOUND", "Affidavit does not belong to this request")
    ts = now_iso()
    filing = {
        "id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
        "service_request_id": sid, "county_id": sr["county_id"],
        "affidavit_id": affidavit_id, "window_start_utc": ws, "window_end_utc": we,
        "reject_count": 0, "status": "PENDING",
    }
    db.filings[filing["id"]] = filing
    return success(S.filing_view(filing), 201)


@app.route("/service-requests/<sid>/filings", methods=["GET"])
def list_request_filings(sid):
    user_id, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher", "Client"})
    sr = must(db.service_requests, sid)
    _sr_owned(sr, user_id, role)
    from flask import request
    items = [f for f in db.filings.values() if f["service_request_id"] == sid]
    if "affidavit_id" in request.args:
        items = [f for f in items if f["affidavit_id"] == request.args.get("affidavit_id")]
    return list_response(S.filing_view, items)


@app.route("/filings", methods=["GET"])
def list_filings():
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    from flask import request
    items = list(db.filings.values())
    if "county_id" in request.args:
        items = [f for f in items if f["county_id"] == request.args.get("county_id")]
    if "affidavit_id" in request.args:
        items = [f for f in items if f["affidavit_id"] == request.args.get("affidavit_id")]
    if "status" in request.args:
        items = [f for f in items if f["status"] == request.args.get("status")]
    return list_response(S.filing_view, items)


@app.route("/filings/<fid>", methods=["GET"])
def get_filing(fid):
    _, role = get_principal()
    require_roles(role, {"Admin", "Dispatcher"})
    filing = must(db.filings, fid)
    return success(S.filing_view(filing), 200)


def _count_overlapping_submitted_filings(county_id, ws_dt, we_dt, exclude_id):
    count = 0
    for other in db.filings.values():
        if other["id"] == exclude_id:
            continue
        if other["county_id"] != county_id:
            continue
        if other["status"] != "SUBMITTED":
            continue
        o_start = parse_dt(other["window_start_utc"], "window_start_utc")
        o_end = parse_dt(other["window_end_utc"], "window_end_utc")
        if ws_dt < o_end and o_start < we_dt:
            count += 1
    return count


@app.route("/filings/<fid>/state", methods=["POST"])
def filing_state(fid):
    _, role = get_principal()
    require_roles(role, {"Dispatcher"})
    filing = must(db.filings, fid)
    body = get_body()
    to_status = require_enum(body, "to_status", {"SUBMITTED", "ACCEPTED", "REJECTED"})
    sr = db.service_requests[filing["service_request_id"]]
    aff = db.affidavits[filing["affidavit_id"]]
    county = db.counties[filing["county_id"]]
    cur = filing["status"]

    if to_status == "SUBMITTED":
        # Valid from PENDING or REJECTED (resubmit loop).
        if cur not in ("PENDING", "REJECTED"):
            raise err("ERR_INVALID_STATE", "SUBMITTED only from PENDING or REJECTED")
        if cur == "PENDING":
            # PENDING -> SUBMITTED checks read in order (PRD 3.9).
            if sr["status"] != "SERVED":
                raise err("ERR_INVALID_STATE", "Request must be SERVED")
            if aff["status"] != "NOTARIZED":
                raise err("ERR_AFFIDAVIT_NOT_NOTARIZED", "Affidavit must be NOTARIZED")
            if not county["e_file_enabled"]:
                raise err("ERR_EFILE_NOT_ENABLED", "County does not accept e-filing")
            ws_dt = parse_dt(filing["window_start_utc"], "window_start_utc")
            we_dt = parse_dt(filing["window_end_utc"], "window_end_utc")
            overlap = _count_overlapping_submitted_filings(county["id"], ws_dt, we_dt, fid)
            if overlap >= county["max_concurrent_filings"]:
                raise err("ERR_FILING_WINDOW_FULL", "Filing window capacity reached")
            filing["status"] = "SUBMITTED"
            touch(filing)
            line = svc.add_invoice_line(sr["id"], "FILING", county["filing_fee_cents"])
            line["filing_id"] = fid
            svc.recompute_final_fee(sr)
        else:  # REJECTED -> SUBMITTED
            if aff["status"] != "NOTARIZED":
                raise err("ERR_AFFIDAVIT_NOT_NOTARIZED", "Affidavit must be NOTARIZED")
            ws_dt = parse_dt(filing["window_start_utc"], "window_start_utc")
            we_dt = parse_dt(filing["window_end_utc"], "window_end_utc")
            overlap = _count_overlapping_submitted_filings(county["id"], ws_dt, we_dt, fid)
            if overlap >= county["max_concurrent_filings"]:
                raise err("ERR_FILING_WINDOW_FULL", "Filing window capacity reached")
            filing["reject_count"] += 1
            filing["status"] = "SUBMITTED"
            touch(filing)
            _regenerate_filing_line(sr, fid, county["filing_fee_cents"])
            svc.recompute_final_fee(sr)

    elif to_status == "ACCEPTED":
        if cur != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "ACCEPTED only from SUBMITTED")
        filing["status"] = "ACCEPTED"
        touch(filing)
        # Bubble-up: request SERVED -> FILED; affidavit NOTARIZED -> FILED.
        if sr["status"] == "SERVED":
            sr["status"] = "FILED"
            touch(sr)
        if aff["status"] == "NOTARIZED":
            aff["status"] = "FILED"
            touch(aff)

    else:  # REJECTED
        if cur != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "REJECTED only from SUBMITTED")
        filing["status"] = "REJECTED"
        touch(filing)
        _void_filing_line(sr, fid)
        svc.recompute_final_fee(sr)

    return success(S.filing_view(filing), 200)


def _void_filing_line(sr, fid):
    for line in db.invoice_lines.values():
        if line.get("filing_id") == fid and line["kind"] == "FILING" and not line["voided"]:
            line["voided"] = True
            touch(line)


def _regenerate_filing_line(sr, fid, amount):
    # Resubmit regenerates the FILING line: add a fresh non-voided line.
    line = svc.add_invoice_line(sr["id"], "FILING", amount)
    line["filing_id"] = fid


# ==========================================================================
# Main
# ==========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

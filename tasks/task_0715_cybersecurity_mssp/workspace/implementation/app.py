"""Cybersecurity MSSP API — Flask entry point and all routes."""
import os
from flask import Flask, request

from errors import ApiError
from store import db, new_id, now_clock, parse_iso, add_hours
from response import ok_object, ok_array, err_response, round2
from auth import authenticate, require_roles
from helpers import (get_json_body, require_fields, require_str, require_enum,
                     require_number, require_int, require_bool, require_datetime,
                     parse_pagination, paginate)
import domain as D

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = err_response(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = err_response("ERR_NOT_FOUND", "Resource not found.")
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = err_response("ERR_NOT_FOUND", "Method not allowed.")
    return body, 404


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = err_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
    return body, 400


# ---------------------------------------------------------------------------
# Lookup helpers (path existence -> ERR_NOT_FOUND; FK -> ERR_FK_NOT_FOUND)
# ---------------------------------------------------------------------------

def get_path(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found.")
    return obj


def get_fk(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise ApiError("ERR_FK_NOT_FOUND", "Referenced resource not found.")
    return obj


def assert_state(obj, allowed):
    if obj["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", "Resource is not in a valid state for this transition.")


# ===========================================================================
# CLIENTS
# ===========================================================================

@app.route("/clients", methods=["POST"])
def create_client():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["name", "tier", "retainer_hours_per_period"])
    name = require_str(body, "name")
    tier = require_enum(body, "tier", {"ESSENTIAL", "ADVANCED", "ELITE"})
    rh = require_number(body, "retainer_hours_per_period", minimum=0)

    cid = new_id()
    client = {"id": cid, "name": name, "tier": tier,
              "retainer_hours_per_period": round2(rh), "current_period_index": 0,
              "posture": "OPEN", "open_critical_findings": 0, "status": "ACTIVE"}
    D.init_common(client)
    db.clients[cid] = client

    # Open first ledger for period 0.
    lid = new_id()
    led = {"id": lid, "client_id": cid, "period_index": 0,
           "hours_granted": round2(rh), "hours_reserved": 0.0,
           "hours_consumed": 0.0, "hours_available": round2(rh), "status": "OPEN"}
    D.init_common(led)
    db.retainer_ledgers[lid] = led

    return ok_object(D.ser_client(client), 201)


@app.route("/clients", methods=["GET"])
def list_clients():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst", "Auditor"})
    limit, offset = parse_pagination()
    rows = list(db.clients.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_client(r) for r in page], limit, offset, total)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst", "Auditor", "ClientContact"})
    c = get_path(db.clients, cid)
    return ok_object(D.ser_client(c))


@app.route("/clients/<cid>/advance-period", methods=["POST"])
def advance_period(cid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin"})
    c = get_path(db.clients, cid)

    old_idx = c["current_period_index"]
    old_led = D.find_ledger(cid, old_idx)
    if old_led is not None:
        old_led["status"] = "CLOSED"
        D.touch(old_led)

    c["current_period_index"] = old_idx + 1
    new_idx = c["current_period_index"]

    # Open fresh ledger for the new period.
    lid = new_id()
    led = {"id": lid, "client_id": cid, "period_index": new_idx,
           "hours_granted": round2(c["retainer_hours_per_period"]),
           "hours_reserved": 0.0, "hours_consumed": 0.0,
           "hours_available": round2(c["retainer_hours_per_period"]), "status": "OPEN"}
    D.init_common(led)
    db.retainer_ledgers[lid] = led

    # Expiry sweep: AUTHORIZED engagements past their window that never started.
    clock = now_clock()
    for eng in db.engagements.values():
        if eng["client_id"] != cid:
            continue
        if eng["status"] == "AUTHORIZED" and eng.get("authorized_window_end") is not None \
                and clock > eng["authorized_window_end"]:
            eng["status"] = "EXPIRED"
            D.touch(eng)
            # Release reservation: recompute on the engagement's period ledger.
            old_period_led = D.find_ledger(cid, eng.get("period_index"))
            if old_period_led is not None:
                D.recompute_ledger(old_period_led)
            D.append_audit(cid, role, uid, "ENGAGEMENT_EXPIRED", "Engagement", eng["id"])

    D.touch(c)
    return ok_object(D.ser_client(c))


@app.route("/clients/<cid>/suspend", methods=["POST"])
def suspend_client(cid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin"})
    c = get_path(db.clients, cid)
    c["status"] = "SUSPENDED"
    D.touch(c)
    return ok_object(D.ser_client(c))


# ===========================================================================
# RETAINER LEDGERS
# ===========================================================================

@app.route("/retainer-ledgers", methods=["GET"])
def list_ledgers():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead"})
    limit, offset = parse_pagination()
    rows = list(db.retainer_ledgers.values())
    cid = request.args.get("client_id")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    pidx = request.args.get("period_index")
    if pidx is not None:
        try:
            pi = int(pidx)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "period_index must be an integer.")
        rows = [r for r in rows if r["period_index"] == pi]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_ledger(r) for r in page], limit, offset, total)


@app.route("/retainer-ledgers/<lid>", methods=["GET"])
def get_ledger(lid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead"})
    led = get_path(db.retainer_ledgers, lid)
    return ok_object(D.ser_ledger(led))


# ===========================================================================
# ASSETS
# ===========================================================================

@app.route("/assets", methods=["POST"])
def create_asset():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead"})
    body = get_json_body()
    require_fields(body, ["client_id", "hostname", "ip_address", "criticality"])
    client_id = require_str(body, "client_id")
    get_fk(db.clients, client_id)
    hostname = require_str(body, "hostname")
    ip = require_str(body, "ip_address")
    crit = require_enum(body, "criticality", {"LOW", "MEDIUM", "HIGH", "CROWN_JEWEL"})
    exposure = "INTERNAL"
    if "exposure" in body and body["exposure"] is not None:
        exposure = require_enum(body, "exposure", {"INTERNAL", "EXTERNAL"})

    # Hostname uniqueness among non-DECOMMISSIONED assets of this client.
    for a in db.assets.values():
        if a["client_id"] == client_id and a["status"] != "DECOMMISSIONED" and a["hostname"] == hostname:
            raise ApiError("ERR_DUPLICATE_HOSTNAME", "Hostname already in use for this client.")

    aid = new_id()
    asset = {"id": aid, "client_id": client_id, "hostname": hostname, "ip_address": ip,
             "criticality": crit, "exposure": exposure, "status": "ACTIVE"}
    D.init_common(asset)
    db.assets[aid] = asset
    return ok_object(D.ser_asset(asset), 201)


@app.route("/assets", methods=["GET"])
def list_assets():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst", "ClientContact"})
    limit, offset = parse_pagination()
    rows = list(db.assets.values())
    cid = request.args.get("client_id")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_asset(r) for r in page], limit, offset, total)


@app.route("/assets/<aid>", methods=["GET"])
def get_asset(aid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst", "ClientContact"})
    a = get_path(db.assets, aid)
    return ok_object(D.ser_asset(a))


@app.route("/assets/<aid>/decommission", methods=["POST"])
def decommission_asset(aid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead"})
    a = get_path(db.assets, aid)
    a["status"] = "DECOMMISSIONED"
    D.touch(a)
    return ok_object(D.ser_asset(a))


# ===========================================================================
# ENGAGEMENTS
# ===========================================================================

@app.route("/engagements", methods=["POST"])
def create_engagement():
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    body = get_json_body()
    require_fields(body, ["client_id", "kind", "authorized_window_start",
                          "authorized_window_end", "estimated_hours", "scope_asset_ids"])
    client_id = require_str(body, "client_id")
    get_fk(db.clients, client_id)
    kind = require_enum(body, "kind", {"VULN_SCAN", "PENTEST"})
    ws = require_datetime(body, "authorized_window_start")
    we = require_datetime(body, "authorized_window_end")
    est = require_number(body, "estimated_hours", exclusive_min=0)
    scope = body.get("scope_asset_ids")
    if not isinstance(scope, list) or not all(isinstance(x, str) for x in scope):
        raise ApiError("ERR_INVALID_REQUEST", "scope_asset_ids must be an array of strings.")

    eid = new_id()
    eng = {"id": eid, "client_id": client_id, "kind": kind,
           "authorized_window_start": ws, "authorized_window_end": we,
           "estimated_hours": round2(est), "scope_asset_ids": list(scope),
           "authorization_signed_by": None, "period_index": None, "status": "DRAFT"}
    D.init_common(eng)
    db.engagements[eid] = eng
    return ok_object(D.ser_engagement(eng), 201)


@app.route("/engagements", methods=["GET"])
def list_engagements():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "ClientContact"})
    limit, offset = parse_pagination()
    rows = list(db.engagements.values())
    cid = request.args.get("client_id")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_engagement(r) for r in page], limit, offset, total)


@app.route("/engagements/<eid>", methods=["GET"])
def get_engagement(eid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "ClientContact"})
    e = get_path(db.engagements, eid)
    return ok_object(D.ser_engagement(e))


@app.route("/engagements/<eid>/authorize", methods=["POST"])
def authorize_engagement(eid):
    uid, role = authenticate()
    require_roles(role, {"ClientContact"})
    eng = get_path(db.engagements, eid)
    assert_state(eng, {"DRAFT"})
    client = db.clients[eng["client_id"]]

    # Posture lockdown (priority 8 — business_safety, before referential/fiscal).
    if client["posture"] == "LOCKDOWN":
        raise ApiError("ERR_POSTURE_LOCKDOWN", "Client in LOCKDOWN; authorizations frozen.")
    # Client must be ACTIVE.
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", "Client is not ACTIVE.")

    # Every scope asset is an ACTIVE asset owned by this client.
    for asset_id in eng["scope_asset_ids"]:
        a = db.assets.get(asset_id)
        if a is None or a["client_id"] != eng["client_id"] or a["status"] != "ACTIVE":
            raise ApiError("ERR_SCOPE_ASSET_INVALID", "A scope asset is not an ACTIVE asset of this client.")

    # PENTEST window overlap on shared scope assets.
    if eng["kind"] == "PENTEST":
        for other in db.engagements.values():
            if other["id"] == eng["id"]:
                continue
            if other["kind"] != "PENTEST":
                continue
            if other["status"] not in ("AUTHORIZED", "ACTIVE"):
                continue
            if not set(other["scope_asset_ids"]) & set(eng["scope_asset_ids"]):
                continue
            # Half-open interval overlap: [s1,e1) overlaps [s2,e2) iff s1 < e2 and s2 < e1.
            s1, e1 = eng["authorized_window_start"], eng["authorized_window_end"]
            s2, e2 = other["authorized_window_start"], other["authorized_window_end"]
            if s1 < e2 and s2 < e1:
                raise ApiError("ERR_WINDOW_OVERLAP", "Overlapping pentest window on shared scope asset.")

    # Retainer ledger must be OPEN and have enough available hours.
    led = D.find_open_ledger(eng["client_id"])
    if led is None or led["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED", "Current retainer ledger is not OPEN.")
    if led["hours_available"] < eng["estimated_hours"]:
        raise ApiError("ERR_RETAINER_EXHAUSTED", "Insufficient retainer hours available.")

    eng["status"] = "AUTHORIZED"
    eng["authorization_signed_by"] = uid
    eng["period_index"] = client["current_period_index"]
    D.touch(eng)
    D.recompute_ledger(led)
    D.append_audit(eng["client_id"], role, uid, "ENGAGEMENT_AUTHORIZED", "Engagement", eng["id"])
    return ok_object(D.ser_engagement(eng))


@app.route("/engagements/<eid>/start", methods=["POST"])
def start_engagement(eid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    eng = get_path(db.engagements, eid)
    assert_state(eng, {"AUTHORIZED"})
    client = db.clients[eng["client_id"]]
    clock = now_clock()
    if not (eng["authorized_window_start"] <= clock <= eng["authorized_window_end"]):
        raise ApiError("ERR_OUTSIDE_WINDOW", "Clock outside authorized window.")
    if client["posture"] == "LOCKDOWN":
        raise ApiError("ERR_POSTURE_LOCKDOWN", "Client in LOCKDOWN; starts frozen.")
    eng["status"] = "ACTIVE"
    D.touch(eng)
    D.append_audit(eng["client_id"], role, uid, "ENGAGEMENT_STARTED", "Engagement", eng["id"])
    return ok_object(D.ser_engagement(eng))


@app.route("/engagements/<eid>/complete", methods=["POST"])
def complete_engagement(eid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    eng = get_path(db.engagements, eid)
    assert_state(eng, {"ACTIVE"})
    for sc in db.scans.values():
        if sc["engagement_id"] == eng["id"] and sc["status"] in ("QUEUED", "RUNNING"):
            raise ApiError("ERR_SCANS_IN_FLIGHT", "Scans still in flight.")
    eng["status"] = "COMPLETED"
    D.touch(eng)
    led = D.find_ledger(eng["client_id"], eng.get("period_index"))
    if led is not None:
        D.recompute_ledger(led)
    D.append_audit(eng["client_id"], role, uid, "ENGAGEMENT_COMPLETED", "Engagement", eng["id"])
    return ok_object(D.ser_engagement(eng))


@app.route("/engagements/<eid>/cancel", methods=["POST"])
def cancel_engagement(eid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    eng = get_path(db.engagements, eid)
    assert_state(eng, {"DRAFT", "AUTHORIZED"})
    was_authorized = eng["status"] == "AUTHORIZED"
    eng["status"] = "CANCELLED"
    D.touch(eng)
    if was_authorized:
        led = D.find_ledger(eng["client_id"], eng.get("period_index"))
        if led is not None:
            D.recompute_ledger(led)
    D.append_audit(eng["client_id"], role, uid, "ENGAGEMENT_CANCELLED", "Engagement", eng["id"])
    return ok_object(D.ser_engagement(eng))


# ===========================================================================
# SCANS
# ===========================================================================

@app.route("/scans", methods=["POST"])
def create_scan():
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    body = get_json_body()
    require_fields(body, ["engagement_id", "expected_engagement_version"])
    engagement_id = require_str(body, "engagement_id")
    eng = get_fk(db.engagements, engagement_id)
    expected = require_int(body, "expected_engagement_version")
    if expected != eng["version"]:
        raise ApiError("ERR_STALE_VERSION", "Engagement version is stale.")

    sid = new_id()
    scan = {"id": sid, "engagement_id": engagement_id, "client_id": eng["client_id"],
            "started_at": None, "completed_at": None, "actual_hours": None,
            "raw_finding_count": 0, "status": "QUEUED", "_completed_period_index": None}
    D.init_common(scan)
    db.scans[sid] = scan
    # Creating a sibling scan bumps the parent engagement version.
    D.touch(eng)
    return ok_object(D.ser_scan(scan), 201)


@app.route("/scans", methods=["GET"])
def list_scans():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead"})
    limit, offset = parse_pagination()
    rows = list(db.scans.values())
    eng_id = request.args.get("engagement_id")
    if eng_id is not None:
        rows = [r for r in rows if r["engagement_id"] == eng_id]
    cid = request.args.get("client_id")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_scan(r) for r in page], limit, offset, total)


@app.route("/scans/<sid>", methods=["GET"])
def get_scan(sid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead"})
    s = get_path(db.scans, sid)
    return ok_object(D.ser_scan(s))


SCAN_COOLDOWN_HOURS = 24


@app.route("/scans/<sid>/start", methods=["POST"])
def start_scan(sid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    scan = get_path(db.scans, sid)
    assert_state(scan, {"QUEUED"})
    eng = db.engagements[scan["engagement_id"]]
    if eng["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "Parent engagement is not ACTIVE.")
    clock = now_clock()
    if not (eng["authorized_window_start"] <= clock <= eng["authorized_window_end"]):
        raise ApiError("ERR_OUTSIDE_WINDOW", "Clock outside engagement window.")
    # No RUNNING scan on same engagement whose [started_at, started_at+24h] closed
    # buffered interval contains the clock.
    for other in db.scans.values():
        if other["id"] == scan["id"]:
            continue
        if other["engagement_id"] != scan["engagement_id"]:
            continue
        if other["status"] != "RUNNING" or other.get("started_at") is None:
            continue
        lo = other["started_at"]
        hi = add_hours(other["started_at"], SCAN_COOLDOWN_HOURS)
        if lo <= clock <= hi:
            raise ApiError("ERR_SCAN_WINDOW_OVERLAP", "Scan collides with a running scan's cooldown.")
    scan["status"] = "RUNNING"
    scan["started_at"] = clock
    D.touch(scan)
    D.append_audit(scan["client_id"], role, uid, "SCAN_STARTED", "Scan", scan["id"])
    return ok_object(D.ser_scan(scan))


@app.route("/scans/<sid>/complete", methods=["POST"])
def complete_scan(sid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    scan = get_path(db.scans, sid)
    body = get_json_body()
    # actual_hours required and >= 0 (ERR_INVALID_REQUEST) — validated before state? No:
    # state precedence (priority 7) before business_constraint of complete. But the
    # actual_hours validity for complete is the transition body shape (priority 5),
    # which precedes state (priority 6/7). We check body shape (5) then state (7).
    require_fields(body, ["actual_hours"])
    actual = require_number(body, "actual_hours", minimum=0)
    raw_count = 0
    if "raw_finding_count" in body and body["raw_finding_count"] is not None:
        raw_count = require_int(body, "raw_finding_count", minimum=0)
    assert_state(scan, {"RUNNING"})

    client = db.clients[scan["client_id"]]
    scan["status"] = "COMPLETED"
    scan["completed_at"] = now_clock()
    scan["actual_hours"] = round2(actual)
    scan["raw_finding_count"] = raw_count
    scan["_completed_period_index"] = client["current_period_index"]
    D.touch(scan)
    led = D.find_ledger(scan["client_id"], client["current_period_index"])
    if led is not None:
        D.recompute_ledger(led)
    D.append_audit(scan["client_id"], role, uid, "SCAN_COMPLETED", "Scan", scan["id"])
    return ok_object(D.ser_scan(scan))


@app.route("/scans/<sid>/abort", methods=["POST"])
def abort_scan(sid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    scan = get_path(db.scans, sid)
    assert_state(scan, {"QUEUED", "RUNNING"})
    scan["status"] = "ABORTED"
    D.touch(scan)
    D.append_audit(scan["client_id"], role, uid, "SCAN_ABORTED", "Scan", scan["id"])
    return ok_object(D.ser_scan(scan))


# ===========================================================================
# FINDINGS
# ===========================================================================

@app.route("/findings", methods=["POST"])
def create_finding():
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst", "EngagementLead"})
    body = get_json_body()
    require_fields(body, ["scan_id", "asset_id", "title", "cvss_base"])
    scan_id = require_str(body, "scan_id")
    scan = get_fk(db.scans, scan_id)
    asset_id = require_str(body, "asset_id")
    asset = get_fk(db.assets, asset_id)
    if asset["client_id"] != scan["client_id"]:
        raise ApiError("ERR_FK_NOT_FOUND", "Asset does not belong to the scan's client.")
    title = require_str(body, "title")
    cvss = require_number(body, "cvss_base", minimum=0, maximum=10)

    client = db.clients[scan["client_id"]]
    severity = D.compute_severity(cvss, asset["criticality"])

    fid = new_id()
    finding = {"id": fid, "scan_id": scan_id, "asset_id": asset_id,
               "client_id": scan["client_id"], "title": title, "cvss_base": cvss,
               "severity": severity, "submitted_by": uid, "accepted_by": None,
               "linked_incident_id": None, "status": "OPEN"}
    D.init_common(finding)
    finding["sla_due_at"] = D.compute_sla_due_at(finding["created_at"], severity, client["tier"])
    db.findings[fid] = finding
    D.recompute_open_critical(scan["client_id"])
    return ok_object(D.ser_finding(finding), 201)


@app.route("/findings", methods=["GET"])
def list_findings():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst", "ClientContact", "Auditor"})
    limit, offset = parse_pagination()
    rows = list(db.findings.values())
    for key in ("scan_id", "client_id", "asset_id", "severity", "status", "linked_incident_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_finding(r) for r in page], limit, offset, total)


@app.route("/findings/<fid>", methods=["GET"])
def get_finding(fid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst", "ClientContact", "Auditor"})
    f = get_path(db.findings, fid)
    return ok_object(D.ser_finding(f))


@app.route("/findings/<fid>/start-remediation", methods=["POST"])
def start_remediation(fid):
    uid, role = authenticate()
    require_roles(role, {"ClientContact"})
    f = get_path(db.findings, fid)
    assert_state(f, {"OPEN", "RETEST_FAILED"})
    scan = db.scans[f["scan_id"]]
    if scan["status"] != "COMPLETED":
        raise ApiError("ERR_SCAN_NOT_COMPLETED", "Parent scan is not COMPLETED.")
    was_failed = f["status"] == "RETEST_FAILED"
    f["status"] = "REMEDIATION_IN_PROGRESS"
    D.touch(f)
    action = "REMEDIATION_RESTARTED" if was_failed else "REMEDIATION_STARTED"
    D.append_audit(f["client_id"], role, uid, action, "Finding", f["id"])
    return ok_object(D.ser_finding(f))


@app.route("/findings/<fid>/submit-remediation", methods=["POST"])
def submit_remediation(fid):
    uid, role = authenticate()
    require_roles(role, {"ClientContact"})
    f = get_path(db.findings, fid)
    assert_state(f, {"REMEDIATION_IN_PROGRESS"})
    f["status"] = "REMEDIATION_SUBMITTED"
    D.touch(f)
    D.append_audit(f["client_id"], role, uid, "REMEDIATION_SUBMITTED", "Finding", f["id"])
    return ok_object(D.ser_finding(f))


@app.route("/findings/<fid>/retest", methods=["POST"])
def retest_finding(fid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    f = get_path(db.findings, fid)
    body = get_json_body()
    require_fields(body, ["retest_passed"])
    passed = require_bool(body, "retest_passed")
    assert_state(f, {"REMEDIATION_SUBMITTED"})
    if uid == f["submitted_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Retester must differ from finding submitter.")
    if passed:
        f["status"] = "REMEDIATED"
        f["accepted_by"] = uid
        D.touch(f)
        D.recompute_open_critical(f["client_id"])
        D.append_audit(f["client_id"], role, uid, "FINDING_REMEDIATED", "Finding", f["id"])
    else:
        f["status"] = "RETEST_FAILED"
        D.touch(f)
        D.append_audit(f["client_id"], role, uid, "RETEST_FAILED", "Finding", f["id"])
    return ok_object(D.ser_finding(f))


@app.route("/findings/<fid>/accept-risk", methods=["POST"])
def accept_risk(fid):
    uid, role = authenticate()
    require_roles(role, {"ClientContact"})
    f = get_path(db.findings, fid)
    assert_state(f, {"OPEN"})
    if f["severity"] == "CRITICAL":
        raise ApiError("ERR_CANNOT_ACCEPT_CRITICAL", "CRITICAL findings may not be risk-accepted.")
    f["status"] = "RISK_ACCEPTED"
    D.touch(f)
    D.recompute_open_critical(f["client_id"])
    D.append_audit(f["client_id"], role, uid, "RISK_ACCEPTED", "Finding", f["id"])
    return ok_object(D.ser_finding(f))


@app.route("/findings/<fid>/mark-false-positive", methods=["POST"])
def mark_false_positive(fid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    f = get_path(db.findings, fid)
    assert_state(f, {"OPEN"})
    if uid == f["submitted_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Marker must differ from finding submitter.")
    f["status"] = "FALSE_POSITIVE"
    D.touch(f)
    D.recompute_open_critical(f["client_id"])
    D.append_audit(f["client_id"], role, uid, "FALSE_POSITIVE", "Finding", f["id"])
    return ok_object(D.ser_finding(f))


# ===========================================================================
# ALERTS
# ===========================================================================

@app.route("/alerts", methods=["POST"])
def create_alert():
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst", "PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["client_id", "asset_id", "source", "raw_score"])
    client_id = require_str(body, "client_id")
    get_fk(db.clients, client_id)
    asset_id = require_str(body, "asset_id")
    asset = get_fk(db.assets, asset_id)
    if asset["client_id"] != client_id:
        raise ApiError("ERR_FK_NOT_FOUND", "Asset does not belong to this client.")
    source = require_enum(body, "source", {"SIEM", "EDR"})
    raw = require_number(body, "raw_score", minimum=0, maximum=100)

    priority = D.compute_triage_priority(raw, asset["criticality"], asset["exposure"])
    aid = new_id()
    alert = {"id": aid, "client_id": client_id, "asset_id": asset_id, "source": source,
             "raw_score": raw, "triage_priority": priority, "triaged_by": None,
             "promoted_incident_id": None, "status": "NEW"}
    D.init_common(alert)
    db.alerts[aid] = alert
    return ok_object(D.ser_alert(alert), 201)


@app.route("/alerts", methods=["GET"])
def list_alerts():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst"})
    limit, offset = parse_pagination()
    rows = list(db.alerts.values())
    for key in ("client_id", "asset_id", "status", "triage_priority", "promoted_incident_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_alert(r) for r in page], limit, offset, total)


@app.route("/alerts/<aid>", methods=["GET"])
def get_alert(aid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst"})
    a = get_path(db.alerts, aid)
    return ok_object(D.ser_alert(a))


@app.route("/alerts/<aid>/triage", methods=["POST"])
def triage_alert(aid):
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst"})
    alert = get_path(db.alerts, aid)
    assert_state(alert, {"NEW"})
    asset = db.assets.get(alert["asset_id"])
    if asset is None or asset["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ASSET_DECOMMISSIONED", "Alert asset is decommissioned.")
    # Recompute triage_priority on triage (per calc trigger).
    alert["triage_priority"] = D.compute_triage_priority(alert["raw_score"], asset["criticality"], asset["exposure"])
    alert["status"] = "TRIAGED"
    alert["triaged_by"] = uid
    D.touch(alert)
    D.append_audit(alert["client_id"], role, uid, "ALERT_TRIAGED", "Alert", alert["id"])
    return ok_object(D.ser_alert(alert))


@app.route("/alerts/<aid>/dismiss", methods=["POST"])
def dismiss_alert(aid):
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst"})
    alert = get_path(db.alerts, aid)
    assert_state(alert, {"TRIAGED"})
    if alert["triage_priority"] not in ("P3", "P4"):
        raise ApiError("ERR_CANNOT_DISMISS_HIGH_PRIORITY", "P1/P2 alerts must be promoted, not dismissed.")
    alert["status"] = "DISMISSED"
    D.touch(alert)
    D.append_audit(alert["client_id"], role, uid, "ALERT_DISMISSED", "Alert", alert["id"])
    return ok_object(D.ser_alert(alert))


@app.route("/alerts/<aid>/promote", methods=["POST"])
def promote_alert(aid):
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst"})
    alert = get_path(db.alerts, aid)
    assert_state(alert, {"TRIAGED"})
    client = db.clients[alert["client_id"]]
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", "Client is not ACTIVE.")
    severity = D.PRIORITY_TO_SEVERITY[alert["triage_priority"]]
    iid = new_id()
    incident = {"id": iid, "client_id": alert["client_id"], "triggering_alert_id": alert["id"],
                "severity": severity, "response_hours": 0, "contained_count": 0,
                "resolved_period_index": None, "quarantined_asset_id": None, "status": "DETECTED"}
    D.init_common(incident)
    incident["escalation_deadline_at"] = D.compute_escalation_deadline(
        incident["created_at"], severity, client["tier"])
    db.incidents[iid] = incident
    alert["status"] = "PROMOTED"
    alert["promoted_incident_id"] = iid
    D.touch(alert)
    D.recompute_posture(alert["client_id"])
    D.append_audit(alert["client_id"], role, uid, "ALERT_PROMOTED", "Alert", alert["id"])
    return ok_object(D.ser_alert(alert))


# ===========================================================================
# INCIDENTS
# ===========================================================================

@app.route("/incidents", methods=["GET"])
def list_incidents():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst"})
    limit, offset = parse_pagination()
    rows = list(db.incidents.values())
    for key in ("client_id", "status", "severity", "triggering_alert_id", "quarantined_asset_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_incident(r) for r in page], limit, offset, total)


@app.route("/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "SocAnalyst"})
    i = get_path(db.incidents, iid)
    return ok_object(D.ser_incident(i))


@app.route("/incidents/<iid>/acknowledge", methods=["POST"])
def acknowledge_incident(iid):
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst"})
    inc = get_path(db.incidents, iid)
    assert_state(inc, {"DETECTED"})
    inc["status"] = "ACKNOWLEDGED"
    D.touch(inc)
    D.append_audit(inc["client_id"], role, uid, "INCIDENT_ACKNOWLEDGED", "Incident", inc["id"])
    return ok_object(D.ser_incident(inc))


@app.route("/incidents/<iid>/contain", methods=["POST"])
def contain_incident(iid):
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst"})
    inc = get_path(db.incidents, iid)
    body = get_json_body()
    quarantine = False
    if "quarantine_asset" in body and body["quarantine_asset"] is not None:
        quarantine = require_bool(body, "quarantine_asset")
    assert_state(inc, {"ACKNOWLEDGED", "REOPENED"})

    if quarantine:
        # The triggering alert's asset must be ACTIVE.
        asset = None
        if inc.get("triggering_alert_id"):
            alert = db.alerts.get(inc["triggering_alert_id"])
            if alert is not None:
                asset = db.assets.get(alert["asset_id"])
        if asset is None or asset["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Asset is not ACTIVE for quarantine.")

    inc["contained_count"] = inc["contained_count"] + 1
    if quarantine:
        asset["status"] = "QUARANTINED"
        D.touch(asset)
        inc["quarantined_asset_id"] = asset["id"]
    inc["status"] = "CONTAINED"
    D.touch(inc)
    D.append_audit(inc["client_id"], role, uid, "INCIDENT_CONTAINED", "Incident", inc["id"])
    return ok_object(D.ser_incident(inc))


@app.route("/incidents/<iid>/escalate", methods=["POST"])
def escalate_incident(iid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    inc = get_path(db.incidents, iid)
    assert_state(inc, {"DETECTED", "ACKNOWLEDGED"})
    if inc["severity"] not in ("HIGH", "CRITICAL"):
        raise ApiError("ERR_CANNOT_ESCALATE_LOW", "Only HIGH/CRITICAL incidents may be escalated.")
    inc["status"] = "ESCALATED"
    D.touch(inc)
    D.recompute_posture(inc["client_id"])
    D.append_audit(inc["client_id"], role, uid, "INCIDENT_ESCALATED", "Incident", inc["id"])
    return ok_object(D.ser_incident(inc))


@app.route("/incidents/<iid>/resolve", methods=["POST"])
def resolve_incident(iid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    inc = get_path(db.incidents, iid)
    body = get_json_body()
    require_fields(body, ["response_hours"])
    rh = require_number(body, "response_hours", minimum=0)
    assert_state(inc, {"CONTAINED", "ESCALATED"})
    client = db.clients[inc["client_id"]]
    led = D.find_open_ledger(inc["client_id"])
    if led is None or led["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED", "Current retainer ledger is not OPEN.")

    inc["status"] = "RESOLVED"
    inc["response_hours"] = round2(rh)
    inc["resolved_period_index"] = client["current_period_index"]
    # Reverse quarantine.
    if inc.get("quarantined_asset_id"):
        asset = db.assets.get(inc["quarantined_asset_id"])
        if asset is not None:
            asset["status"] = "ACTIVE"
            D.touch(asset)
        inc["quarantined_asset_id"] = None
    D.touch(inc)
    D.recompute_ledger(led)
    D.recompute_posture(inc["client_id"])
    D.append_audit(inc["client_id"], role, uid, "INCIDENT_RESOLVED", "Incident", inc["id"])
    return ok_object(D.ser_incident(inc))


@app.route("/incidents/<iid>/reopen", methods=["POST"])
def reopen_incident(iid):
    uid, role = authenticate()
    require_roles(role, {"SocAnalyst"})
    inc = get_path(db.incidents, iid)
    assert_state(inc, {"RESOLVED"})
    client = db.clients[inc["client_id"]]
    if client["current_period_index"] != inc.get("resolved_period_index"):
        raise ApiError("ERR_REOPEN_WINDOW_CLOSED", "Reopen allowed only in the same period.")
    inc["status"] = "REOPENED"
    D.touch(inc)
    D.recompute_posture(inc["client_id"])
    D.append_audit(inc["client_id"], role, uid, "INCIDENT_REOPENED", "Incident", inc["id"])
    return ok_object(D.ser_incident(inc))


# ===========================================================================
# COMPLIANCE AUDITS
# ===========================================================================

@app.route("/audits", methods=["POST"])
def create_audit():
    uid, role = authenticate()
    require_roles(role, {"Auditor", "EngagementLead"})
    body = get_json_body()
    require_fields(body, ["client_id", "framework", "required_control_count"])
    client_id = require_str(body, "client_id")
    get_fk(db.clients, client_id)
    framework = require_enum(body, "framework", {"SOC2", "HIPAA", "PCI"})
    rcc = require_int(body, "required_control_count", exclusive_min=0)

    aid = new_id()
    audit = {"id": aid, "client_id": client_id, "framework": framework,
             "required_control_count": rcc, "readiness_pct": 0.0, "status": "PLANNING"}
    D.init_common(audit)
    db.audits[aid] = audit
    return ok_object(D.ser_audit(audit), 201)


@app.route("/audits", methods=["GET"])
def list_audits():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "Auditor", "ClientContact"})
    limit, offset = parse_pagination()
    rows = list(db.audits.values())
    for key in ("client_id", "framework", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_audit(r) for r in page], limit, offset, total)


@app.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "Auditor", "ClientContact"})
    a = get_path(db.audits, aid)
    return ok_object(D.ser_audit(a))


@app.route("/audits/<aid>/begin-fieldwork", methods=["POST"])
def begin_fieldwork(aid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    audit = get_path(db.audits, aid)
    assert_state(audit, {"PLANNING"})
    audit["status"] = "FIELDWORK"
    D.touch(audit)
    D.append_audit(audit["client_id"], role, uid, "AUDIT_FIELDWORK", "ComplianceAudit", audit["id"])
    return ok_object(D.ser_audit(audit))


@app.route("/audits/<aid>/mark-ready", methods=["POST"])
def mark_ready(aid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    audit = get_path(db.audits, aid)
    assert_state(audit, {"FIELDWORK"})
    D.recompute_readiness(audit)
    if audit["readiness_pct"] != 100.00:
        raise ApiError("ERR_AUDIT_NOT_READY", "All required controls must be covered.")
    client = db.clients[audit["client_id"]]
    if client["open_critical_findings"] > 0:
        raise ApiError("ERR_OPEN_CRITICAL_FINDINGS", "Client has open CRITICAL findings.")
    audit["status"] = "READY"
    D.touch(audit)
    D.append_audit(audit["client_id"], role, uid, "AUDIT_READY", "ComplianceAudit", audit["id"])
    return ok_object(D.ser_audit(audit))


@app.route("/audits/<aid>/attest", methods=["POST"])
def attest_audit(aid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    audit = get_path(db.audits, aid)
    assert_state(audit, {"READY"})
    for ev in db.evidence.values():
        if ev["audit_id"] == audit["id"] and ev["submitted_by"] == uid:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Attester must not have submitted evidence.")
    audit["status"] = "ATTESTED"
    D.touch(audit)
    D.append_audit(audit["client_id"], role, uid, "AUDIT_ATTESTED", "ComplianceAudit", audit["id"])
    return ok_object(D.ser_audit(audit))


@app.route("/audits/<aid>/fail", methods=["POST"])
def fail_audit(aid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    audit = get_path(db.audits, aid)
    assert_state(audit, {"FIELDWORK"})
    audit["status"] = "FAILED"
    D.touch(audit)
    D.append_audit(audit["client_id"], role, uid, "AUDIT_FAILED", "ComplianceAudit", audit["id"])
    return ok_object(D.ser_audit(audit))


@app.route("/audits/<aid>/reopen-fieldwork", methods=["POST"])
def reopen_fieldwork(aid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    audit = get_path(db.audits, aid)
    assert_state(audit, {"READY"})
    audit["status"] = "FIELDWORK"
    D.touch(audit)
    D.append_audit(audit["client_id"], role, uid, "AUDIT_REOPENED", "ComplianceAudit", audit["id"])
    return ok_object(D.ser_audit(audit))


# ===========================================================================
# AUDIT EVIDENCE
# ===========================================================================

@app.route("/evidence", methods=["POST"])
def create_evidence():
    uid, role = authenticate()
    require_roles(role, {"Auditor", "EngagementLead"})
    body = get_json_body()
    require_fields(body, ["audit_id", "control_ref", "expected_audit_version"])
    audit_id = require_str(body, "audit_id")
    audit = get_fk(db.audits, audit_id)
    control_ref = require_str(body, "control_ref")
    finding_id = None
    if "finding_id" in body and body["finding_id"] is not None:
        finding_id = require_str(body, "finding_id")
        f = get_fk(db.findings, finding_id)
        if f["client_id"] != audit["client_id"]:
            raise ApiError("ERR_FK_NOT_FOUND", "Finding does not belong to the audit's client.")
    expected = require_int(body, "expected_audit_version")
    if expected != audit["version"]:
        raise ApiError("ERR_STALE_VERSION", "Audit version is stale.")

    eid = new_id()
    ev = {"id": eid, "audit_id": audit_id, "control_ref": control_ref,
          "finding_id": finding_id, "submitted_by": uid, "status": "SUBMITTED"}
    D.init_common(ev)
    db.evidence[eid] = ev
    D.touch(audit)
    return ok_object(D.ser_evidence(ev), 201)


@app.route("/evidence", methods=["GET"])
def list_evidence():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "Auditor"})
    limit, offset = parse_pagination()
    rows = list(db.evidence.values())
    for key in ("audit_id", "control_ref", "status", "finding_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_evidence(r) for r in page], limit, offset, total)


@app.route("/evidence/<eid>", methods=["GET"])
def get_evidence(eid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "Auditor"})
    e = get_path(db.evidence, eid)
    return ok_object(D.ser_evidence(e))


@app.route("/evidence/<eid>/approve", methods=["POST"])
def approve_evidence(eid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    ev = get_path(db.evidence, eid)
    assert_state(ev, {"SUBMITTED"})
    audit = db.audits[ev["audit_id"]]
    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_AUDIT_NOT_IN_FIELDWORK", "Parent audit not in FIELDWORK.")
    if uid == ev["submitted_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from submitter.")
    ev["status"] = "APPROVED"
    D.touch(ev)
    D.recompute_readiness(audit)
    D.touch(audit)
    D.append_audit(audit["client_id"], role, uid, "EVIDENCE_APPROVED", "AuditEvidence", ev["id"])
    return ok_object(D.ser_evidence(ev))


@app.route("/evidence/<eid>/reject", methods=["POST"])
def reject_evidence(eid):
    uid, role = authenticate()
    require_roles(role, {"Auditor"})
    ev = get_path(db.evidence, eid)
    assert_state(ev, {"SUBMITTED"})
    audit = db.audits[ev["audit_id"]]
    if uid == ev["submitted_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Rejecter must differ from submitter.")
    ev["status"] = "REJECTED"
    D.touch(ev)
    D.recompute_readiness(audit)
    D.append_audit(audit["client_id"], role, uid, "EVIDENCE_REJECTED", "AuditEvidence", ev["id"])
    return ok_object(D.ser_evidence(ev))


# ===========================================================================
# REPORTS
# ===========================================================================

@app.route("/reports", methods=["POST"])
def create_report():
    uid, role = authenticate()
    require_roles(role, {"EngagementLead", "Auditor"})
    body = get_json_body()
    require_fields(body, ["client_id", "kind"])
    client_id = require_str(body, "client_id")
    client = get_fk(db.clients, client_id)
    kind = require_enum(body, "kind", {"ASSESSMENT", "INCIDENT", "COMPLIANCE", "RETAINER"})
    subject_id = None
    if "subject_id" in body and body["subject_id"] is not None:
        subject_id = require_str(body, "subject_id")

    # Frozen denormalized snapshot of current metrics.
    led = D.find_open_ledger(client_id)
    snapshot = {
        "posture": client["posture"],
        "open_critical_findings": client["open_critical_findings"],
        "current_period_index": client["current_period_index"],
        "finding_count": sum(1 for f in db.findings.values() if f["client_id"] == client_id),
        "incident_count": sum(1 for i in db.incidents.values() if i["client_id"] == client_id),
        "hours_reserved": led["hours_reserved"] if led else 0.0,
        "hours_consumed": led["hours_consumed"] if led else 0.0,
        "hours_available": led["hours_available"] if led else 0.0,
    }
    rid = new_id()
    report = {"id": rid, "client_id": client_id, "kind": kind, "subject_id": subject_id,
              "snapshot": snapshot, "status": "GENERATED"}
    D.init_common(report)
    db.reports[rid] = report
    return ok_object(D.ser_report(report), 201)


@app.route("/reports", methods=["GET"])
def list_reports():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "Auditor", "ClientContact"})
    limit, offset = parse_pagination()
    rows = list(db.reports.values())
    for key in ("client_id", "kind", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_report(r) for r in page], limit, offset, total)


@app.route("/reports/<rid>", methods=["GET"])
def get_report(rid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "EngagementLead", "Auditor", "ClientContact"})
    r = get_path(db.reports, rid)
    return ok_object(D.ser_report(r))


@app.route("/reports/<rid>/publish", methods=["POST"])
def publish_report(rid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    report = get_path(db.reports, rid)
    assert_state(report, {"GENERATED"})
    client = db.clients[report["client_id"]]
    if client["posture"] == "LOCKDOWN":
        raise ApiError("ERR_POSTURE_LOCKDOWN", "Report publication frozen in LOCKDOWN.")
    report["status"] = "PUBLISHED"
    D.touch(report)
    D.append_audit(report["client_id"], role, uid, "REPORT_PUBLISHED", "Report", report["id"])
    return ok_object(D.ser_report(report))


@app.route("/reports/<rid>/retract", methods=["POST"])
def retract_report(rid):
    uid, role = authenticate()
    require_roles(role, {"EngagementLead"})
    report = get_path(db.reports, rid)
    assert_state(report, {"PUBLISHED"})
    report["status"] = "RETRACTED"
    D.touch(report)
    D.append_audit(report["client_id"], role, uid, "REPORT_RETRACTED", "Report", report["id"])
    return ok_object(D.ser_report(report))


# ===========================================================================
# AUDIT LOG (read-only)
# ===========================================================================

@app.route("/audit-log", methods=["GET"])
def list_audit_log():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Auditor"})
    limit, offset = parse_pagination()
    rows = list(db.audit_log.values())
    for key in ("client_id", "action", "target_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    page, total = paginate(rows, limit, offset)
    return ok_array([D.ser_audit_log(r) for r in page], limit, offset, total)


@app.route("/audit-log/<lid>", methods=["GET"])
def get_audit_log(lid):
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Auditor"})
    e = get_path(db.audit_log, lid)
    return ok_object(D.ser_audit_log(e))


# ===========================================================================
# CLOCK
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    require_roles(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = require_datetime(body, "to_iso8601")
    db.clock = dt
    return ok_object({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

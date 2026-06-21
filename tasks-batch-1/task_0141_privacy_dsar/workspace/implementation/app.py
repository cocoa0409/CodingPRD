"""Privacy DSAR API — Flask entry point, error handlers, and all routes.

Storage is in-memory only (see db.py); no seeding at startup. The server reads
$PORT, binds 0.0.0.0, and runs in the foreground (see start.sh).
"""

import os
import socket
import time

from flask import Flask

from db import store
from errors import ApiError, err
from middleware import require_roles
import response as resp
import serializers as ser
import services as svc
import validators as val

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return resp.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return resp.error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return resp.error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return resp.error_response(e.error_id, e.message, e.http_status)
    # Fall back to a generic 400 invalid-request rather than leaking a 500.
    return resp.error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ---------------------------------------------------------------------------
# Row creation helper: attaches common system fields
# ---------------------------------------------------------------------------
def _new_common(extra):
    now = store.now()
    rid = store.new_id()
    row = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(extra)
    return row


def _request_out(r):
    return ser.dsar_request_out(r, svc.request_computed_fields(r))


# ===========================================================================
# Controller
# ===========================================================================
@app.route("/controllers", methods=["POST"])
def create_controller():
    require_roles(["PrivacyOfficer"])
    body = val.get_body()
    name = val.require_str(body, "name")
    jurisdiction = val.require_enum(body, "jurisdiction", val.JURISDICTIONS)
    dpo_email = val.require_str(body, "dpo_email")
    row = _new_common({"name": name, "jurisdiction": jurisdiction, "dpo_email": dpo_email})
    store.controllers[row["id"]] = row
    return resp.object_response(
        ser.controller_out(row, svc.controller_open_request_count(row["id"])), 201
    )


@app.route("/controllers/<cid>", methods=["GET"])
def get_controller(cid):
    require_roles(["PrivacyOfficer", "IntakeAgent"])
    c = val.get_controller(cid)
    return resp.object_response(
        ser.controller_out(c, svc.controller_open_request_count(c["id"])), 200
    )


# ===========================================================================
# DataSubject
# ===========================================================================
@app.route("/data-subjects", methods=["POST"])
def create_data_subject():
    require_roles(["IntakeAgent", "PrivacyOfficer"])
    body = val.get_body()
    controller_id = val.require_str(body, "controller_id")
    email = val.require_str(body, "email")
    full_name = val.require_str(body, "full_name")
    residency = val.require_enum(body, "jurisdiction_residency", val.RESIDENCIES)
    known = val.optional_int(body, "known_record_count", 0, minimum=0)
    val.get_controller(controller_id)  # existence
    row = _new_common({
        "controller_id": controller_id,
        "email": email,
        "full_name": full_name,
        "jurisdiction_residency": residency,
        "known_record_count": known,
    })
    store.data_subjects[row["id"]] = row
    return resp.object_response(ser.data_subject_out(row), 201)


@app.route("/data-subjects/<sid>", methods=["GET"])
def get_data_subject(sid):
    require_roles(["IntakeAgent", "PrivacyOfficer"])
    return resp.object_response(ser.data_subject_out(val.get_data_subject(sid)), 200)


@app.route("/data-subjects", methods=["GET"])
def list_data_subjects():
    require_roles(["IntakeAgent", "PrivacyOfficer"])
    limit, offset = val.parse_pagination()
    controller_id = val.request_arg("controller_id")
    rows = list(store.data_subjects.values())
    if controller_id is not None:
        rows = [s for s in rows if s["controller_id"] == controller_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.data_subject_out(s) for s in window], limit, offset, total
    )


# ===========================================================================
# Processor
# ===========================================================================
@app.route("/processors", methods=["POST"])
def create_processor():
    require_roles(["PrivacyOfficer"])
    body = val.get_body()
    controller_id = val.require_str(body, "controller_id")
    name = val.require_str(body, "name")
    notify_email = val.require_str(body, "notify_email")
    sla = val.optional_int(body, "sla_ack_hours", 72, minimum=1)
    val.get_controller(controller_id)
    row = _new_common({
        "controller_id": controller_id,
        "name": name,
        "notify_email": notify_email,
        "sla_ack_hours": sla,
        "status": "ACTIVE",
    })
    store.processors[row["id"]] = row
    return resp.object_response(ser.processor_out(row), 201)


@app.route("/processors/<pid>", methods=["GET"])
def get_processor(pid):
    require_roles(["PrivacyOfficer", "FulfillmentWorker"])
    return resp.object_response(ser.processor_out(val.get_processor(pid)), 200)


@app.route("/processors", methods=["GET"])
def list_processors():
    require_roles(["PrivacyOfficer", "FulfillmentWorker"])
    limit, offset = val.parse_pagination()
    controller_id = val.request_arg("controller_id")
    rows = list(store.processors.values())
    if controller_id is not None:
        rows = [p for p in rows if p["controller_id"] == controller_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response([ser.processor_out(p) for p in window], limit, offset, total)


@app.route("/processors/<pid>/suspend", methods=["POST"])
def suspend_processor(pid):
    require_roles(["PrivacyOfficer"])
    p = val.get_processor(pid)
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Processor is not ACTIVE")
    p["status"] = "SUSPENDED"
    svc.touch(p)
    return resp.object_response(ser.processor_out(p), 200)


# ===========================================================================
# ConsentRecord
# ===========================================================================
@app.route("/consent-records", methods=["POST"])
def create_consent_record():
    require_roles(["IntakeAgent", "PrivacyOfficer"])
    body = val.get_body()
    data_subject_id = val.require_str(body, "data_subject_id")
    purpose = val.require_enum(body, "purpose", val.PURPOSES)
    val.get_data_subject(data_subject_id)
    row = _new_common({
        "data_subject_id": data_subject_id,
        "purpose": purpose,
        "state": "GRANTED",
        "withdrawn_at": None,
    })
    store.consent_records[row["id"]] = row
    return resp.object_response(ser.consent_record_out(row), 201)


@app.route("/consent-records/<cid>", methods=["GET"])
def get_consent_record(cid):
    require_roles(["IntakeAgent", "PrivacyOfficer", "DataSubjectAgent"])
    return resp.object_response(ser.consent_record_out(val.get_consent_record(cid)), 200)


@app.route("/consent-records", methods=["GET"])
def list_consent_records():
    require_roles(["IntakeAgent", "PrivacyOfficer", "DataSubjectAgent"])
    limit, offset = val.parse_pagination()
    data_subject_id = val.request_arg("data_subject_id")
    rows = list(store.consent_records.values())
    if data_subject_id is not None:
        rows = [c for c in rows if c["data_subject_id"] == data_subject_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.consent_record_out(c) for c in window], limit, offset, total
    )


@app.route("/consent-records/<cid>/withdraw", methods=["POST"])
def withdraw_consent(cid):
    require_roles(["DataSubjectAgent", "PrivacyOfficer"])
    c = val.get_consent_record(cid)
    if c["state"] != "GRANTED":
        raise err("ERR_INVALID_STATE", "ConsentRecord is not GRANTED")
    c["state"] = "WITHDRAWN"
    c["withdrawn_at"] = store.now()
    svc.touch(c)
    return resp.object_response(ser.consent_record_out(c), 200)


# ===========================================================================
# LegalHold
# ===========================================================================
@app.route("/legal-holds", methods=["POST"])
def create_legal_hold():
    require_roles(["PrivacyOfficer"])
    body = val.get_body()
    controller_id = val.require_str(body, "controller_id")
    data_subject_id = val.require_str(body, "data_subject_id")
    matter_reference = val.require_str(body, "matter_reference")
    categories = val.require_category_array(body, "data_categories")
    val.get_controller(controller_id)
    val.get_data_subject(data_subject_id)
    row = _new_common({
        "controller_id": controller_id,
        "data_subject_id": data_subject_id,
        "matter_reference": matter_reference,
        "data_categories": categories,
        "state": "ACTIVE",
    })
    store.legal_holds[row["id"]] = row
    return resp.object_response(ser.legal_hold_out(row), 201)


@app.route("/legal-holds/<hid>", methods=["GET"])
def get_legal_hold(hid):
    require_roles(["PrivacyOfficer"])
    return resp.object_response(ser.legal_hold_out(val.get_legal_hold(hid)), 200)


@app.route("/legal-holds", methods=["GET"])
def list_legal_holds():
    require_roles(["PrivacyOfficer"])
    limit, offset = val.parse_pagination()
    controller_id = val.request_arg("controller_id")
    data_subject_id = val.request_arg("data_subject_id")
    rows = list(store.legal_holds.values())
    if controller_id is not None:
        rows = [h for h in rows if h["controller_id"] == controller_id]
    if data_subject_id is not None:
        rows = [h for h in rows if h["data_subject_id"] == data_subject_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response([ser.legal_hold_out(h) for h in window], limit, offset, total)


@app.route("/legal-holds/<hid>/lift", methods=["POST"])
def lift_legal_hold(hid):
    require_roles(["PrivacyOfficer"])
    h = val.get_legal_hold(hid)
    if h["state"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "LegalHold is not ACTIVE")
    h["state"] = "LIFTED"
    svc.touch(h)
    return resp.object_response(ser.legal_hold_out(h), 200)


# ===========================================================================
# DsarRequest — core
# ===========================================================================
@app.route("/dsar-requests", methods=["POST"])
def create_dsar_request():
    require_roles(["IntakeAgent", "PrivacyOfficer"])
    body = val.get_body()
    controller_id = val.require_str(body, "controller_id")
    data_subject_id = val.require_str(body, "data_subject_id")
    request_type = val.require_enum(body, "request_type", val.REQUEST_TYPES)
    received_at = val.require_iso(body, "received_at")
    controller = val.get_controller(controller_id)
    val.get_data_subject(data_subject_id)
    deadline = svc.compute_deadline(received_at, controller["jurisdiction"], 0)
    row = _new_common({
        "controller_id": controller_id,
        "data_subject_id": data_subject_id,
        "request_type": request_type,
        "received_at": received_at,
        "status": "PENDING_VERIFICATION",
        "identity_attempts": 0,
        "extension_count": 0,
        "deadline_at": deadline,
        "verified_by_user_id": None,
    })
    store.dsar_requests[row["id"]] = row
    return resp.object_response(_request_out(row), 201)


@app.route("/dsar-requests/<rid>", methods=["GET"])
def get_dsar_request(rid):
    require_roles(["IntakeAgent", "PrivacyOfficer", "FulfillmentWorker"])
    return resp.object_response(_request_out(val.get_dsar_request(rid)), 200)


@app.route("/dsar-requests", methods=["GET"])
def list_dsar_requests():
    require_roles(["IntakeAgent", "PrivacyOfficer", "FulfillmentWorker"])
    limit, offset = val.parse_pagination()
    controller_id = val.request_arg("controller_id")
    data_subject_id = val.request_arg("data_subject_id")
    status = val.request_arg("status")
    rows = list(store.dsar_requests.values())
    if controller_id is not None:
        rows = [r for r in rows if r["controller_id"] == controller_id]
    if data_subject_id is not None:
        rows = [r for r in rows if r["data_subject_id"] == data_subject_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response([_request_out(r) for r in window], limit, offset, total)


@app.route("/dsar-requests/<rid>/risk", methods=["GET"])
def get_request_risk(rid):
    require_roles(["PrivacyOfficer"])
    r = val.get_dsar_request(rid)
    score, residual, total = svc.compute_erasure_risk(r["id"])
    return resp.object_response(
        {"erasure_exposure_score": score, "residual_weighted": residual,
         "total_weighted": total}, 200
    )


# --- Identity-verification loop -------------------------------------------
@app.route("/dsar-requests/<rid>/verify-identity", methods=["POST"])
def verify_identity(rid):
    user_id, role = require_roles(["IntakeAgent"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    if r["status"] != "PENDING_VERIFICATION":
        raise err("ERR_INVALID_STATE", "Request is not PENDING_VERIFICATION")
    if store.now() > r["deadline_at"]:
        raise err("ERR_DEADLINE_PASSED", "Request is past its statutory deadline")
    evidence_reference = val.require_str(body, "evidence_reference")
    r["status"] = "DISCOVERY"
    r["identity_attempts"] += 1
    r["verified_by_user_id"] = user_id
    svc.append_audit(r["id"], role, user_id, "IDENTITY_VERIFIED",
                     "Identity verified: %s" % evidence_reference)
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


@app.route("/dsar-requests/<rid>/reject-identity", methods=["POST"])
def reject_identity(rid):
    user_id, role = require_roles(["IntakeAgent"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    if r["status"] != "PENDING_VERIFICATION":
        raise err("ERR_INVALID_STATE", "Request is not PENDING_VERIFICATION")
    reason = val.require_str(body, "reason")
    r["status"] = "VERIFICATION_REJECTED"
    r["identity_attempts"] += 1
    svc.append_audit(r["id"], role, user_id, "IDENTITY_REJECTED",
                     "Identity rejected: %s" % reason)
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


@app.route("/dsar-requests/<rid>/resubmit-identity", methods=["POST"])
def resubmit_identity(rid):
    require_roles(["IntakeAgent"])
    r = val.get_dsar_request(rid)
    if r["status"] != "VERIFICATION_REJECTED":
        raise err("ERR_INVALID_STATE", "Request is not VERIFICATION_REJECTED")
    if r["identity_attempts"] >= 3:
        raise err("ERR_VERIFICATION_ATTEMPTS_EXHAUSTED",
                  "Identity-verification attempts exhausted")
    r["status"] = "PENDING_VERIFICATION"
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


@app.route("/dsar-requests/<rid>/complete-discovery", methods=["POST"])
def complete_discovery(rid):
    require_roles(["PrivacyOfficer"])
    r = val.get_dsar_request(rid)
    if r["status"] != "DISCOVERY":
        raise err("ERR_INVALID_STATE", "Request is not in DISCOVERY")
    if store.now() > r["deadline_at"]:
        raise err("ERR_DEADLINE_PASSED", "Request is past its statutory deadline")
    findings = [f for f in store.discovery_findings.values()
                if f["dsar_request_id"] == r["id"]]
    if len(findings) == 0:
        raise err("ERR_NO_FINDINGS", "complete-discovery requires at least one finding")
    if any(f["state"] == "PENDING" for f in findings):
        raise err("ERR_UNRESOLVED_FINDINGS", "A DiscoveryFinding is still PENDING")
    r["status"] = "UNDER_REVIEW"
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


@app.route("/dsar-requests/<rid>/extend-deadline", methods=["POST"])
def extend_deadline(rid):
    user_id, role = require_roles(["PrivacyOfficer"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    if r["status"] not in ("DISCOVERY", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "Extension only permitted in DISCOVERY or UNDER_REVIEW")
    if r["extension_count"] != 0:
        raise err("ERR_EXTENSION_LIMIT_REACHED", "Only one extension permitted")
    reason = val.require_str(body, "reason")
    r["extension_count"] = 1
    controller = store.controllers[r["controller_id"]]
    r["deadline_at"] = svc.compute_deadline(
        r["received_at"], controller["jurisdiction"], r["extension_count"]
    )
    svc.append_audit(r["id"], role, user_id, "DEADLINE_EXTENDED",
                     "Deadline extended: %s" % reason)
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


@app.route("/dsar-requests/<rid>/dispatch-fulfillment", methods=["POST"])
def dispatch_fulfillment(rid):
    user_id, role = require_roles(["PrivacyOfficer"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    # State
    if r["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Request is not UNDER_REVIEW")
    # Deadline
    if store.now() > r["deadline_at"]:
        raise err("ERR_DEADLINE_PASSED", "Request is past its statutory deadline")
    # Segregation of duties
    if user_id == r["verified_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Dispatching officer must differ from the verifying agent")
    # Undecided exemptions
    exemptions = [e for e in store.exemption_claims.values()
                  if e["dsar_request_id"] == r["id"]]
    if any(e["state"] == "ASSERTED" for e in exemptions):
        raise err("ERR_UNDECIDED_EXEMPTION", "An ExemptionClaim is still ASSERTED")
    # OCC
    expected = val.require_int(body, "expected_request_version")
    if expected != r["version"]:
        raise err("ERR_STALE_VERSION", "expected_request_version does not match current version")

    # Fan-out one item per CONFIRMED finding.
    shielded = svc.upheld_exemption_categories(r["id"])
    action = svc.ACTION_FOR_REQUEST_TYPE[r["request_type"]]
    confirmed = [f for f in store.discovery_findings.values()
                 if f["dsar_request_id"] == r["id"] and f["state"] == "CONFIRMED"]
    confirmed.sort(key=lambda f: (f["created_at"], f.get("_seq", 0)))
    for f in confirmed:
        category = f["data_category"]
        if category in shielded:
            state = "SKIPPED_EXEMPT"
        elif action == "ERASE" and svc.active_hold_covers(r["data_subject_id"], category):
            state = "BLOCKED"
        else:
            state = "QUEUED"
        item = _new_common({
            "dsar_request_id": r["id"],
            "discovery_finding_id": f["id"],
            "processor_id": f["processor_id"],
            "data_category": category,
            "action": action,
            "record_count": f["record_count"],
            "state": state,
        })
        store.fulfillment_items[item["id"]] = item

    r["status"] = "FULFILLING"
    svc.append_audit(r["id"], role, user_id, "FULFILLMENT_DISPATCHED",
                     "Fulfillment dispatched")
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


@app.route("/dsar-requests/<rid>/close", methods=["POST"])
def close_request(rid):
    user_id, role = require_roles(["PrivacyOfficer"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    disposition = val.require_str(body, "disposition")
    if r["status"] == "FULFILLING":
        items = svc.items_for_request(r["id"])
        if any(i["state"] in ("QUEUED", "DISPATCHED", "BLOCKED") for i in items):
            raise err("ERR_FULFILLMENT_INCOMPLETE",
                      "All fulfillment items must be terminal before closing")
        r["status"] = "CLOSED_FULFILLED"
    elif r["status"] == "VERIFICATION_REJECTED":
        r["status"] = "CLOSED_REJECTED"
    else:
        raise err("ERR_INVALID_STATE", "Request cannot be closed from its current state")
    svc.append_audit(r["id"], role, user_id, "REQUEST_CLOSED",
                     "Request closed: %s" % disposition)
    svc.touch(r)
    return resp.object_response(_request_out(r), 200)


# ===========================================================================
# DiscoveryFinding
# ===========================================================================
@app.route("/dsar-requests/<rid>/findings", methods=["POST"])
def create_finding(rid):
    require_roles(["PrivacyOfficer", "IntakeAgent"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    if r["status"] != "DISCOVERY":
        raise err("ERR_INVALID_STATE", "Findings can only be recorded in DISCOVERY")
    processor_id = val.require_str(body, "processor_id")
    data_category = val.require_enum(body, "data_category", val.DATA_CATEGORIES)
    record_count = val.require_int(body, "record_count", minimum=1)
    confidence = val.require_enum(body, "confidence", val.CONFIDENCES)
    val.get_processor(processor_id)
    row = _new_common({
        "dsar_request_id": r["id"],
        "processor_id": processor_id,
        "data_category": data_category,
        "record_count": record_count,
        "confidence": confidence,
        "state": "PENDING",
    })
    store.discovery_findings[row["id"]] = row
    svc.touch(r)  # finding creation bumps the parent request version
    return resp.object_response(ser.discovery_finding_out(row), 201)


@app.route("/dsar-requests/<rid>/findings", methods=["GET"])
def list_request_findings(rid):
    require_roles(["PrivacyOfficer", "IntakeAgent", "FulfillmentWorker"])
    val.get_dsar_request(rid)
    limit, offset = val.parse_pagination()
    state = val.request_arg("state")
    rows = [f for f in store.discovery_findings.values() if f["dsar_request_id"] == rid]
    if state is not None:
        rows = [f for f in rows if f["state"] == state]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.discovery_finding_out(f) for f in window], limit, offset, total
    )


@app.route("/findings/<fid>", methods=["GET"])
def get_finding(fid):
    require_roles(["PrivacyOfficer", "IntakeAgent", "FulfillmentWorker"])
    return resp.object_response(ser.discovery_finding_out(val.get_finding(fid)), 200)


@app.route("/findings", methods=["GET"])
def list_findings():
    require_roles(["PrivacyOfficer", "IntakeAgent", "FulfillmentWorker"])
    limit, offset = val.parse_pagination()
    processor_id = val.request_arg("processor_id")
    dsar_request_id = val.request_arg("dsar_request_id")
    rows = list(store.discovery_findings.values())
    if processor_id is not None:
        rows = [f for f in rows if f["processor_id"] == processor_id]
    if dsar_request_id is not None:
        rows = [f for f in rows if f["dsar_request_id"] == dsar_request_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.discovery_finding_out(f) for f in window], limit, offset, total
    )


@app.route("/findings/<fid>/confirm", methods=["POST"])
def confirm_finding(fid):
    require_roles(["PrivacyOfficer"])
    f = val.get_finding(fid)
    r = store.dsar_requests[f["dsar_request_id"]]
    if f["state"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Finding is not PENDING")
    if r["status"] != "DISCOVERY":
        raise err("ERR_INVALID_STATE", "Parent request is not in DISCOVERY")
    f["state"] = "CONFIRMED"
    svc.touch(f)
    svc.touch(r)  # finding decision bumps the parent request version
    return resp.object_response(ser.discovery_finding_out(f), 200)


@app.route("/findings/<fid>/dismiss", methods=["POST"])
def dismiss_finding(fid):
    require_roles(["PrivacyOfficer"])
    f = val.get_finding(fid)
    r = store.dsar_requests[f["dsar_request_id"]]
    if f["state"] not in ("PENDING", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Finding cannot be dismissed from its current state")
    if r["status"] != "DISCOVERY":
        raise err("ERR_INVALID_STATE", "Parent request is not in DISCOVERY")
    f["state"] = "DISMISSED"
    svc.touch(f)
    svc.touch(r)
    return resp.object_response(ser.discovery_finding_out(f), 200)


# ===========================================================================
# ExemptionClaim
# ===========================================================================
@app.route("/dsar-requests/<rid>/exemptions", methods=["POST"])
def create_exemption(rid):
    require_roles(["PrivacyOfficer"])
    r = val.get_dsar_request(rid)
    body = val.get_body()
    if r["status"] not in ("DISCOVERY", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "Exemptions can only be asserted in DISCOVERY or UNDER_REVIEW")
    data_category = val.require_enum(body, "data_category", val.DATA_CATEGORIES)
    basis = val.require_enum(body, "basis", val.EXEMPTION_BASES)
    row = _new_common({
        "dsar_request_id": r["id"],
        "data_category": data_category,
        "basis": basis,
        "state": "ASSERTED",
    })
    store.exemption_claims[row["id"]] = row
    svc.touch(r)
    return resp.object_response(ser.exemption_claim_out(row), 201)


@app.route("/dsar-requests/<rid>/exemptions", methods=["GET"])
def list_request_exemptions(rid):
    require_roles(["PrivacyOfficer"])
    val.get_dsar_request(rid)
    limit, offset = val.parse_pagination()
    state = val.request_arg("state")
    rows = [e for e in store.exemption_claims.values() if e["dsar_request_id"] == rid]
    if state is not None:
        rows = [e for e in rows if e["state"] == state]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.exemption_claim_out(e) for e in window], limit, offset, total
    )


@app.route("/exemptions/<eid>", methods=["GET"])
def get_exemption(eid):
    require_roles(["PrivacyOfficer"])
    return resp.object_response(ser.exemption_claim_out(val.get_exemption(eid)), 200)


@app.route("/exemptions/<eid>/decide", methods=["POST"])
def decide_exemption(eid):
    user_id, role = require_roles(["PrivacyOfficer"])
    e = val.get_exemption(eid)
    r = store.dsar_requests[e["dsar_request_id"]]
    body = val.get_body()
    if e["state"] != "ASSERTED":
        raise err("ERR_INVALID_STATE", "Exemption is not ASSERTED")
    if r["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Parent request is not UNDER_REVIEW")
    decision = val.require_enum(body, "decision", val.EXEMPTION_DECISIONS)
    if decision == "UPHELD" and e["basis"] == "LEGAL_HOLD":
        if not svc.active_hold_covers(r["data_subject_id"], e["data_category"]):
            raise err("ERR_EXEMPTION_BASIS_UNSUPPORTED",
                      "LEGAL_HOLD exemption requires a matching ACTIVE LegalHold")
    e["state"] = decision
    svc.append_audit(r["id"], role, user_id, "EXEMPTION_DECIDED",
                     "Exemption %s" % decision)
    svc.touch(e)
    svc.touch(r)
    return resp.object_response(ser.exemption_claim_out(e), 200)


# ===========================================================================
# FulfillmentItem
# ===========================================================================
@app.route("/dsar-requests/<rid>/fulfillment-items", methods=["GET"])
def list_request_items(rid):
    require_roles(["PrivacyOfficer", "FulfillmentWorker"])
    val.get_dsar_request(rid)
    limit, offset = val.parse_pagination()
    state = val.request_arg("state")
    rows = [i for i in store.fulfillment_items.values() if i["dsar_request_id"] == rid]
    if state is not None:
        rows = [i for i in rows if i["state"] == state]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.fulfillment_item_out(i) for i in window], limit, offset, total
    )


@app.route("/fulfillment-items/<iid>", methods=["GET"])
def get_fulfillment_item(iid):
    require_roles(["PrivacyOfficer", "FulfillmentWorker"])
    return resp.object_response(ser.fulfillment_item_out(val.get_fulfillment_item(iid)), 200)


@app.route("/fulfillment-items", methods=["GET"])
def list_fulfillment_items():
    require_roles(["PrivacyOfficer", "FulfillmentWorker"])
    limit, offset = val.parse_pagination()
    discovery_finding_id = val.request_arg("discovery_finding_id")
    processor_id = val.request_arg("processor_id")
    dsar_request_id = val.request_arg("dsar_request_id")
    rows = list(store.fulfillment_items.values())
    if discovery_finding_id is not None:
        rows = [i for i in rows if i["discovery_finding_id"] == discovery_finding_id]
    if processor_id is not None:
        rows = [i for i in rows if i["processor_id"] == processor_id]
    if dsar_request_id is not None:
        rows = [i for i in rows if i["dsar_request_id"] == dsar_request_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.fulfillment_item_out(i) for i in window], limit, offset, total
    )


@app.route("/fulfillment-items/<iid>/dispatch", methods=["POST"])
def dispatch_item(iid):
    user_id, role = require_roles(["FulfillmentWorker"])
    i = val.get_fulfillment_item(iid)
    r = store.dsar_requests[i["dsar_request_id"]]
    body = val.get_body()
    if i["state"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "Item is not QUEUED")
    if r["status"] != "FULFILLING":
        raise err("ERR_INVALID_STATE", "Parent request is not FULFILLING")
    processor = store.processors[i["processor_id"]]
    if processor["status"] != "ACTIVE":
        raise err("ERR_PROCESSOR_SUSPENDED", "Referenced processor is SUSPENDED")
    expected = val.require_int(body, "expected_item_version")
    if expected != i["version"]:
        raise err("ERR_STALE_VERSION", "expected_item_version does not match current version")
    # Create the processor notification (SENT).
    now = store.now()
    notif = _new_common({
        "fulfillment_item_id": i["id"],
        "processor_id": i["processor_id"],
        "dispatched_at": now,
        "ack_deadline_at": svc.compute_ack_deadline(now, processor["sla_ack_hours"]),
        "state": "SENT",
    })
    store.processor_notifications[notif["id"]] = notif
    i["state"] = "DISPATCHED"
    svc.append_audit(r["id"], role, user_id, "FULFILLMENT_DISPATCHED",
                     "Item dispatched to processor")
    svc.touch(i)
    return resp.object_response(ser.fulfillment_item_out(i), 200)


@app.route("/fulfillment-items/<iid>/complete", methods=["POST"])
def complete_item(iid):
    require_roles(["FulfillmentWorker"])
    i = val.get_fulfillment_item(iid)
    r = store.dsar_requests[i["dsar_request_id"]]
    if i["state"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Item is not DISPATCHED")
    notifs = [n for n in store.processor_notifications.values()
              if n["fulfillment_item_id"] == i["id"]]
    if not any(n["state"] == "ACKNOWLEDGED" for n in notifs):
        raise err("ERR_NOTIFICATION_NOT_ACKED", "Item's notification is not ACKNOWLEDGED")
    i["state"] = "COMPLETED"
    # SUPPRESS cascade: withdraw the subject's still-GRANTED non-essential consents.
    if i["action"] == "SUPPRESS":
        subject_id = r["data_subject_id"]
        now = store.now()
        for c in store.consent_records.values():
            if (
                c["data_subject_id"] == subject_id
                and c["state"] == "GRANTED"
                and c["purpose"] in ("MARKETING", "ANALYTICS", "SALE_OF_DATA")
            ):
                c["state"] = "WITHDRAWN"
                c["withdrawn_at"] = now
                svc.touch(c)
    svc.touch(i)
    return resp.object_response(ser.fulfillment_item_out(i), 200)


@app.route("/fulfillment-items/<iid>/unblock", methods=["POST"])
def unblock_item(iid):
    require_roles(["PrivacyOfficer"])
    i = val.get_fulfillment_item(iid)
    r = store.dsar_requests[i["dsar_request_id"]]
    if i["state"] != "BLOCKED":
        raise err("ERR_INVALID_STATE", "Item is not BLOCKED")
    if svc.active_hold_covers(r["data_subject_id"], i["data_category"]):
        raise err("ERR_LEGAL_HOLD_ACTIVE",
                  "An ACTIVE LegalHold still covers this category")
    i["state"] = "QUEUED"
    svc.touch(i)
    return resp.object_response(ser.fulfillment_item_out(i), 200)


# ===========================================================================
# ProcessorNotification
# ===========================================================================
@app.route("/fulfillment-items/<iid>/notifications", methods=["GET"])
def list_item_notifications(iid):
    require_roles(["PrivacyOfficer", "FulfillmentWorker", "ProcessorAgent"])
    val.get_fulfillment_item(iid)
    limit, offset = val.parse_pagination()
    state = val.request_arg("state")
    rows = [n for n in store.processor_notifications.values()
            if n["fulfillment_item_id"] == iid]
    if state is not None:
        rows = [n for n in rows if n["state"] == state]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.processor_notification_out(n) for n in window], limit, offset, total
    )


@app.route("/processor-notifications/<nid>", methods=["GET"])
def get_notification(nid):
    require_roles(["PrivacyOfficer", "FulfillmentWorker", "ProcessorAgent"])
    return resp.object_response(
        ser.processor_notification_out(val.get_notification(nid)), 200
    )


@app.route("/processor-notifications", methods=["GET"])
def list_notifications():
    require_roles(["PrivacyOfficer", "FulfillmentWorker", "ProcessorAgent"])
    limit, offset = val.parse_pagination()
    processor_id = val.request_arg("processor_id")
    fulfillment_item_id = val.request_arg("fulfillment_item_id")
    rows = list(store.processor_notifications.values())
    if processor_id is not None:
        rows = [n for n in rows if n["processor_id"] == processor_id]
    if fulfillment_item_id is not None:
        rows = [n for n in rows if n["fulfillment_item_id"] == fulfillment_item_id]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.processor_notification_out(n) for n in window], limit, offset, total
    )


@app.route("/processor-notifications/<nid>/acknowledge", methods=["POST"])
def acknowledge_notification(nid):
    require_roles(["ProcessorAgent"])
    n = val.get_notification(nid)
    if n["state"] not in ("SENT", "OVERDUE"):
        raise err("ERR_INVALID_STATE", "Notification cannot be acknowledged from its current state")
    n["state"] = "ACKNOWLEDGED"
    svc.touch(n)
    return resp.object_response(ser.processor_notification_out(n), 200)


# ===========================================================================
# AuditEvent
# ===========================================================================
@app.route("/dsar-requests/<rid>/audit-events", methods=["GET"])
def list_audit_events(rid):
    require_roles(["PrivacyOfficer", "IntakeAgent"])
    val.get_dsar_request(rid)
    limit, offset = val.parse_pagination()
    event_type = val.request_arg("event_type")
    rows = [a for a in store.audit_events.values() if a["dsar_request_id"] == rid]
    if event_type is not None:
        rows = [a for a in rows if a["event_type"] == event_type]
    window, total = val.paginate(rows, limit, offset)
    return resp.array_response(
        [ser.audit_event_out(a) for a in window], limit, offset, total
    )


# ===========================================================================
# SystemClock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(["PrivacyOfficer"])
    body = val.get_body()
    instant = val.require_iso(body, "to_iso8601")
    store.clock_current_utc = instant
    store.clock_explicitly_set = True
    svc.run_clock_sweeps()
    return resp.object_response(ser.system_clock_out(store), 200)


# ---------------------------------------------------------------------------
# Launcher: bind 0.0.0.0:$PORT with a small retry loop (avoid bind-race under
# the parallel per-test reboot sweep), run in the foreground.
# ---------------------------------------------------------------------------
def _bind_socket(host, port):
    last_err = None
    for _ in range(40):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.set_inheritable(True)
            return sock
        except OSError as e:
            last_err = e
            sock.close()
            time.sleep(0.25)
    raise last_err


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    listen_sock = _bind_socket(host, port)
    try:
        from werkzeug.serving import make_server
        srv = make_server(host, port, app, threaded=True, fd=listen_sock.fileno())
        srv.serve_forever()
    except TypeError:
        # Older werkzeug without fd= support: close our probe socket and let
        # werkzeug bind itself (SO_REUSEADDR makes the re-bind succeed).
        listen_sock.close()
        app.run(host=host, port=port, threaded=True)

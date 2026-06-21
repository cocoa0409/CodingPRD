"""eDiscovery & Litigation Hold API — Flask entry point.

In-memory only. No seeded data. Boots clean from a fresh process every time.
"""
import os
import re

from flask import Flask, request

import clock
import db
import errors
import helpers
import middleware
import response
import serializers as ser
import services as svc

app = Flask(__name__)

BATES_PREFIX_RE = re.compile(r"^[A-Z]{1,8}$")
DECISION_VALUES = {
    "RESPONSIVE_NOT_PRIV",
    "RESPONSIVE_PRIV",
    "RESPONSIVE_REDACTED",
    "NON_RESPONSIVE",
}
DECISION_TAG_MAP = {
    "RESPONSIVE_NOT_PRIV": ("RESPONSIVE", "NOT_PRIVILEGED"),
    "RESPONSIVE_PRIV": ("RESPONSIVE", "PRIVILEGED"),
    "RESPONSIVE_REDACTED": ("RESPONSIVE", "REDACTED"),
    "NON_RESPONSIVE": ("NON_RESPONSIVE", "NOT_PRIVILEGED"),
}


# ==========================================================================
# Error handling
# ==========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error_response(e.error_id, e.message, e.http_status)
    return response.error_response("ERR_INVALID_REQUEST", "Internal error: %s" % str(e), 422)


@app.after_request
def _close_connection(resp):
    # Transport hygiene only: the per-test-server harness reuses a pooled
    # keep-alive client socket across the threaded Werkzeug dev server's
    # connection teardown, which can intermittently surface as a
    # BadStatusLine / ConnectionError race under concurrent sweep load.
    # Forcing Connection: close prevents socket reuse. No endpoint, field,
    # status code, error_id, state transition, or calculation is affected.
    resp.headers["Connection"] = "close"
    return resp


# ==========================================================================
# Helpers shared by routes
# ==========================================================================
def auth():
    return middleware.authenticate()


def find_or_404(store, key):
    entity = store.get(key)
    if entity is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return entity


def list_response(items, out_fn):
    limit, offset = helpers.parse_pagination()
    ordered = helpers.sort_by_created(items)
    window, total = helpers.paginate(ordered, limit, offset)
    return response.array_response([out_fn(x) for x in window], limit, offset, total)


def matter_out(m):
    svc.recompute_custodian_count(m)
    return ser.matter_out(m)


# ==========================================================================
# Matter
# ==========================================================================
@app.route("/matters", methods=["POST"])
def create_matter():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["caption", "bates_prefix"])

    caption = body["caption"]
    if not isinstance(caption, str) or not (1 <= len(caption) <= 200):
        raise errors.err(errors.ERR_INVALID_REQUEST, "caption must be 1..200 chars")
    bates_prefix = body["bates_prefix"]
    if not isinstance(bates_prefix, str) or not BATES_PREFIX_RE.match(bates_prefix):
        raise errors.err(errors.ERR_INVALID_REQUEST, "bates_prefix must be uppercase letters, length 1..8")

    m = db.base_fields()
    m.update({
        "caption": caption,
        "bates_prefix": bates_prefix,
        "lifecycle_status": "OPEN",
        "hold_status": "NO_HOLD",
        "custodian_count": 0,
        "acknowledged_count": 0,
        "ack_rate": 0.0,
        "responsive_doc_count": 0,
        "next_bates_seq": 1,
        "produced_document_count": 0,
        "clawed_back_document_count": 0,
        "spoliation_risk_score": 0,
    })
    db.matters[m["id"]] = m
    return response.object_response(ser.matter_out(m), 201)


@app.route("/matters/<mid>", methods=["GET"])
def get_matter(mid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead", "Reviewer", "Producer"})
    m = find_or_404(db.matters, mid)
    return response.object_response(matter_out(m))


@app.route("/matters", methods=["GET"])
def list_matters():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead", "Reviewer", "Producer"})
    items = list(db.matters.values())
    for m in items:
        svc.recompute_custodian_count(m)
    return list_response(items, ser.matter_out)


@app.route("/matters/<mid>/risk", methods=["GET"])
def matter_risk(mid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    m = find_or_404(db.matters, mid)
    return response.object_response({
        "provisional_risk": svc.provisional_risk(m),
        "final_risk": svc.final_risk(m),
    })


@app.route("/matters/<mid>/collection-summary", methods=["GET"])
def matter_collection_summary(mid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    m = find_or_404(db.matters, mid)
    estimate, actual = svc.collection_summary(mid)
    return response.object_response({
        "estimate_total": estimate,
        "actual_total": actual,
    })


@app.route("/matters/<mid>/begin-close", methods=["POST"])
def begin_close(mid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    m = find_or_404(db.matters, mid)
    if m["lifecycle_status"] != "IN_DISCOVERY":
        raise errors.err(errors.ERR_INVALID_STATE, "Matter is not IN_DISCOVERY")
    # no production set on this matter in DRAFT or VALIDATING
    for s in db.production_sets.values():
        if s["matter_id"] == mid and s["status"] in ("DRAFT", "VALIDATING"):
            raise errors.err(errors.ERR_INVALID_STATE, "Production work still mid-flight")
    m["lifecycle_status"] = "CLOSING"
    db.touch(m)
    return response.object_response(matter_out(m))


@app.route("/matters/<mid>/release-hold", methods=["POST"])
def release_hold(mid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    m = find_or_404(db.matters, mid)
    if m["hold_status"] != "HOLD_ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Hold is not HOLD_ACTIVE")
    if m["lifecycle_status"] != "CLOSING":
        raise errors.err(errors.ERR_INVALID_STATE, "Matter lifecycle must be CLOSING")
    m["hold_status"] = "HOLD_RELEASED"
    svc.cascade_release_hold(m)
    db.touch(m)
    return response.object_response(matter_out(m))


@app.route("/matters/<mid>/close", methods=["POST"])
def close_matter(mid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    m = find_or_404(db.matters, mid)
    if m["lifecycle_status"] != "CLOSING":
        raise errors.err(errors.ERR_INVALID_STATE, "Matter lifecycle is not CLOSING")
    if m["hold_status"] != "HOLD_RELEASED":
        raise errors.err(errors.ERR_INVALID_STATE, "Hold must be HOLD_RELEASED before close")
    m["lifecycle_status"] = "CLOSED"
    db.touch(m)
    return response.object_response(matter_out(m))


# ==========================================================================
# Custodian
# ==========================================================================
@app.route("/custodians", methods=["POST"])
def create_custodian():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["matter_id", "full_name", "email"])

    matter = find_or_404(db.matters, body["matter_id"])

    full_name = body["full_name"]
    if not isinstance(full_name, str) or not full_name:
        raise errors.err(errors.ERR_INVALID_REQUEST, "full_name must be non-empty")
    email = body["email"]
    if not isinstance(email, str) or not email:
        raise errors.err(errors.ERR_INVALID_REQUEST, "email must be non-empty")

    # unique email per matter, case-insensitive
    for c in svc.custodians_of_matter(matter["id"]):
        if c["email"].lower() == email.lower():
            raise errors.err(errors.ERR_DUPLICATE_CUSTODIAN_EMAIL, "Email already used on this matter")

    c = db.base_fields()
    c.update({
        "matter_id": matter["id"],
        "full_name": full_name,
        "email": email,
        "ack_state": "NONE",
        "retention_released": False,
    })
    db.custodians[c["id"]] = c
    svc.recompute_custodian_count(matter)
    db.touch(matter)
    return response.object_response(ser.custodian_out(c), 201)


@app.route("/custodians/<cid>", methods=["GET"])
def get_custodian(cid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead", "Producer"})
    c = find_or_404(db.custodians, cid)
    return response.object_response(ser.custodian_out(c))


@app.route("/custodians", methods=["GET"])
def list_custodians():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead", "Producer"})
    items = list(db.custodians.values())
    matter_id = request.args.get("matter_id")
    if matter_id is not None:
        items = [c for c in items if c["matter_id"] == matter_id]
    return list_response(items, ser.custodian_out)


# ==========================================================================
# LegalHold
# ==========================================================================
@app.route("/legal-holds", methods=["POST"])
def create_legal_hold():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["matter_id", "title", "instructions", "ack_deadline"])

    matter = find_or_404(db.matters, body["matter_id"])
    title = body["title"]
    if not isinstance(title, str) or not title:
        raise errors.err(errors.ERR_INVALID_REQUEST, "title must be non-empty")
    instructions = body["instructions"]
    if not isinstance(instructions, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "instructions must be a string")
    deadline = clock.parse_iso(body["ack_deadline"])
    if deadline is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "ack_deadline must be ISO8601")

    h = db.base_fields()
    h.update({
        "matter_id": matter["id"],
        "title": title,
        "instructions": instructions,
        "status": "DRAFT",
        "issued_at": None,
        "ack_deadline": clock.to_iso(deadline),
        "pending_ack_count": 0,
    })
    db.legal_holds[h["id"]] = h
    return response.object_response(ser.legal_hold_out(h), 201)


@app.route("/legal-holds/<hid>", methods=["GET"])
def get_legal_hold(hid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead"})
    h = find_or_404(db.legal_holds, hid)
    return response.object_response(ser.legal_hold_out(h))


@app.route("/legal-holds", methods=["GET"])
def list_legal_holds():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead"})
    items = list(db.legal_holds.values())
    matter_id = request.args.get("matter_id")
    if matter_id is not None:
        items = [h for h in items if h["matter_id"] == matter_id]
    return list_response(items, ser.legal_hold_out)


@app.route("/legal-holds/<hid>/issue", methods=["POST"])
def issue_legal_hold(hid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    h = find_or_404(db.legal_holds, hid)
    if h["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Hold is not DRAFT")
    matter = db.matters.get(h["matter_id"])
    custs = svc.custodians_of_matter(h["matter_id"])
    if len(custs) < 1:
        raise errors.err(errors.ERR_HOLD_HAS_NO_CUSTODIANS, "Matter has no custodians")

    h["status"] = "ISSUED"
    h["issued_at"] = clock.iso_now()
    pending = 0
    for c in custs:
        a = db.base_fields()
        a.update({
            "hold_id": h["id"],
            "custodian_id": c["id"],
            "status": "PENDING",
            "acknowledged_at": None,
            "on_time": False,
        })
        db.hold_acknowledgements[a["id"]] = a
        c["ack_state"] = "PENDING"
        db.touch(c)
        pending += 1
    h["pending_ack_count"] = pending
    db.touch(h)

    # bubble matter hold axis NO_HOLD -> HOLD_ACTIVE
    if matter is not None and matter["hold_status"] == "NO_HOLD":
        matter["hold_status"] = "HOLD_ACTIVE"
        svc.recompute_ack_fields(matter)
        svc.recompute_spoliation(matter)
        db.touch(matter)
    return response.object_response(ser.legal_hold_out(h))


# ==========================================================================
# HoldAcknowledgement
# ==========================================================================
@app.route("/hold-acknowledgements/<aid>", methods=["GET"])
def get_hold_ack(aid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "Custodian"})
    a = find_or_404(db.hold_acknowledgements, aid)
    if role == "Custodian" and a["custodian_id"] != user_id:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return response.object_response(ser.hold_ack_out(a))


@app.route("/hold-acknowledgements", methods=["GET"])
def list_hold_acks():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "Custodian"})
    items = list(db.hold_acknowledgements.values())
    hold_id = request.args.get("hold_id")
    custodian_id = request.args.get("custodian_id")
    if hold_id is not None:
        items = [a for a in items if a["hold_id"] == hold_id]
    if custodian_id is not None:
        items = [a for a in items if a["custodian_id"] == custodian_id]
    if role == "Custodian":
        items = [a for a in items if a["custodian_id"] == user_id]
    return list_response(items, ser.hold_ack_out)


@app.route("/hold-acknowledgements/<aid>/acknowledge", methods=["POST"])
def acknowledge(aid):
    user_id, role = auth()
    middleware.require_role(role, {"Custodian"})
    a = find_or_404(db.hold_acknowledgements, aid)
    # ownership: custodian acknowledges only their own notice
    if a["custodian_id"] != user_id:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    hold = db.legal_holds.get(a["hold_id"])
    if a["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Acknowledgement is not PENDING")
    if hold is None or hold["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Parent hold is not ISSUED")

    a["status"] = "ACKNOWLEDGED"
    a["acknowledged_at"] = clock.iso_now()
    acked = clock.parse_iso(a["acknowledged_at"])
    deadline = clock.parse_iso(hold["ack_deadline"]) if hold.get("ack_deadline") else None
    a["on_time"] = bool(deadline is not None and acked is not None and acked <= deadline)
    db.touch(a)

    cust = db.custodians.get(a["custodian_id"])
    if cust is not None:
        cust["ack_state"] = "ACKNOWLEDGED"
        db.touch(cust)

    matter = db.matters.get(cust["matter_id"]) if cust else None
    if matter is not None:
        svc.recompute_ack_fields(matter)
        svc.recompute_spoliation(matter)
        db.touch(matter)

    # decrement hold pending_ack_count; auto-transition to ACKNOWLEDGED at 0
    hold["pending_ack_count"] = max(0, hold["pending_ack_count"] - 1)
    if hold["pending_ack_count"] == 0 and hold["status"] == "ISSUED":
        hold["status"] = "ACKNOWLEDGED"
    db.touch(hold)

    return response.object_response(ser.hold_ack_out(a))


# ==========================================================================
# CollectionScope
# ==========================================================================
@app.route("/collection-scopes", methods=["POST"])
def create_collection_scope():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, [
        "matter_id", "custodian_id", "source_label",
        "range_start", "range_end", "expected_doc_count",
    ])
    matter = find_or_404(db.matters, body["matter_id"])
    custodian = find_or_404(db.custodians, body["custodian_id"])

    source_label = body["source_label"]
    if not isinstance(source_label, str) or not source_label:
        raise errors.err(errors.ERR_INVALID_REQUEST, "source_label must be non-empty")
    expected = body["expected_doc_count"]
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_doc_count must be >= 0")

    rs = clock.parse_iso(body["range_start"])
    re_ = clock.parse_iso(body["range_end"])
    if rs is None or re_ is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "range_start/range_end must be ISO8601")
    if not (rs < re_):
        raise errors.err(errors.ERR_INVALID_DATE_RANGE, "range_start must be strictly before range_end")

    # overlap: same custodian + same matter, half-open [start,end) overlap
    for s in db.collection_scopes.values():
        if s["matter_id"] != matter["id"] or s["custodian_id"] != custodian["id"]:
            continue
        es = clock.parse_iso(s["range_start"])
        ee = clock.parse_iso(s["range_end"])
        if es is None or ee is None:
            continue
        # half-open overlap iff rs < ee and es < re_
        if rs < ee and es < re_:
            raise errors.err(errors.ERR_SCOPE_DATE_OVERLAP, "Scope date range overlaps an existing scope")

    s = db.base_fields()
    s.update({
        "matter_id": matter["id"],
        "custodian_id": custodian["id"],
        "source_label": source_label,
        "range_start": clock.to_iso(rs),
        "range_end": clock.to_iso(re_),
        "expected_doc_count": expected,
        "status": "DEFINED",
        "collected_actual_count": 0,
    })
    db.collection_scopes[s["id"]] = s
    return response.object_response(ser.collection_scope_out(s), 201)


@app.route("/collection-scopes/<sid>", methods=["GET"])
def get_collection_scope(sid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "Producer"})
    s = find_or_404(db.collection_scopes, sid)
    return response.object_response(ser.collection_scope_out(s))


@app.route("/collection-scopes", methods=["GET"])
def list_collection_scopes():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "Producer"})
    items = list(db.collection_scopes.values())
    matter_id = request.args.get("matter_id")
    custodian_id = request.args.get("custodian_id")
    if matter_id is not None:
        items = [s for s in items if s["matter_id"] == matter_id]
    if custodian_id is not None:
        items = [s for s in items if s["custodian_id"] == custodian_id]
    return list_response(items, ser.collection_scope_out)


@app.route("/collection-scopes/<sid>/start", methods=["POST"])
def start_collection(sid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    s = find_or_404(db.collection_scopes, sid)
    matter = db.matters.get(s["matter_id"])
    if s["status"] != "DEFINED":
        raise errors.err(errors.ERR_INVALID_STATE, "Scope is not DEFINED")
    if matter is None or matter["hold_status"] != "HOLD_ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Matter hold is not HOLD_ACTIVE")
    cust = db.custodians.get(s["custodian_id"])
    if cust is None or cust["ack_state"] != "ACKNOWLEDGED":
        raise errors.err(errors.ERR_CUSTODIAN_NOT_ACKNOWLEDGED, "Custodian has not acknowledged the hold")
    s["status"] = "COLLECTING"
    db.touch(s)
    return response.object_response(ser.collection_scope_out(s))


@app.route("/collection-scopes/<sid>/finish", methods=["POST"])
def finish_collection(sid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    s = find_or_404(db.collection_scopes, sid)
    if s["status"] != "COLLECTING":
        raise errors.err(errors.ERR_INVALID_STATE, "Scope is not COLLECTING")
    s["status"] = "COLLECTED"
    svc.recompute_scope_collected_count(s)
    db.touch(s)
    return response.object_response(ser.collection_scope_out(s))


# ==========================================================================
# Document
# ==========================================================================
@app.route("/documents", methods=["POST"])
def create_document():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["scope_id", "content_hash", "page_count"])
    scope = find_or_404(db.collection_scopes, body["scope_id"])

    content_hash = body["content_hash"]
    if not isinstance(content_hash, str) or not content_hash:
        raise errors.err(errors.ERR_INVALID_REQUEST, "content_hash must be a non-empty string")
    if not re.match(r"^[0-9a-fA-F]+$", content_hash):
        raise errors.err(errors.ERR_INVALID_REQUEST, "content_hash must be a hex string")
    page_count = body["page_count"]
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "page_count must be >= 1")

    if scope["status"] != "COLLECTING":
        raise errors.err(errors.ERR_INVALID_STATE, "Scope is not COLLECTING")

    d = db.base_fields()
    d.update({
        "scope_id": scope["id"],
        "matter_id": scope["matter_id"],
        "content_hash": content_hash,
        "page_count": page_count,
        "status": "COLLECTED",
        "privilege_tag": "UNREVIEWED",
        "responsiveness_tag": "UNREVIEWED",
        "duplicate_of_id": None,
    })
    db.documents[d["id"]] = d
    svc.recompute_scope_collected_count(scope)
    db.touch(scope)
    return response.object_response(ser.document_out(d), 201)


@app.route("/documents/<did>", methods=["GET"])
def get_document(did):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead", "Reviewer", "Producer"})
    d = find_or_404(db.documents, did)
    return response.object_response(ser.document_out(d))


@app.route("/documents", methods=["GET"])
def list_documents():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps", "ReviewLead", "Reviewer", "Producer"})
    items = list(db.documents.values())
    scope_id = request.args.get("scope_id")
    matter_id = request.args.get("matter_id")
    status = request.args.get("status")
    duplicate_of_id = request.args.get("duplicate_of_id")
    if scope_id is not None:
        items = [d for d in items if d["scope_id"] == scope_id]
    if matter_id is not None:
        items = [d for d in items if d["matter_id"] == matter_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if duplicate_of_id is not None:
        items = [d for d in items if d["duplicate_of_id"] == duplicate_of_id]
    return list_response(items, ser.document_out)


# ==========================================================================
# ProcessingJob
# ==========================================================================
@app.route("/processing-jobs", methods=["POST"])
def create_processing_job():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["matter_id", "scope_id"])
    matter = find_or_404(db.matters, body["matter_id"])
    scope = find_or_404(db.collection_scopes, body["scope_id"])

    j = db.base_fields()
    j.update({
        "matter_id": matter["id"],
        "scope_id": scope["id"],
        "status": "QUEUED",
        "total_input_count": 0,
        "unique_count": 0,
        "duplicate_count": 0,
    })
    db.processing_jobs[j["id"]] = j
    return response.object_response(ser.processing_job_out(j), 201)


@app.route("/processing-jobs/<jid>", methods=["GET"])
def get_processing_job(jid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    j = find_or_404(db.processing_jobs, jid)
    return response.object_response(ser.processing_job_out(j))


@app.route("/processing-jobs", methods=["GET"])
def list_processing_jobs():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    items = list(db.processing_jobs.values())
    matter_id = request.args.get("matter_id")
    scope_id = request.args.get("scope_id")
    if matter_id is not None:
        items = [j for j in items if j["matter_id"] == matter_id]
    if scope_id is not None:
        items = [j for j in items if j["scope_id"] == scope_id]
    return list_response(items, ser.processing_job_out)


@app.route("/processing-jobs/<jid>/run", methods=["POST"])
def run_processing_job(jid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    j = find_or_404(db.processing_jobs, jid)
    scope = db.collection_scopes.get(j["scope_id"])
    if j["status"] != "QUEUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Job is not QUEUED")
    if scope is None or scope["status"] != "COLLECTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Referenced scope is not COLLECTED")
    j["status"] = "RUNNING"
    collected = [d for d in svc.documents_of_scope(scope["id"]) if d["status"] == "COLLECTED"]
    j["total_input_count"] = len(collected)
    db.touch(j)
    return response.object_response(ser.processing_job_out(j))


@app.route("/processing-jobs/<jid>/complete", methods=["POST"])
def complete_processing_job(jid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    j = find_or_404(db.processing_jobs, jid)
    if j["status"] != "RUNNING":
        raise errors.err(errors.ERR_INVALID_STATE, "Job is not RUNNING")
    j["status"] = "COMPLETED"
    svc.run_dedup(j)
    db.touch(j)

    scope = db.collection_scopes.get(j["scope_id"])
    if scope is not None and scope["status"] == "COLLECTED":
        scope["status"] = "PROCESSED"
        db.touch(scope)

    matter = db.matters.get(j["matter_id"])
    if matter is not None and matter["lifecycle_status"] == "OPEN":
        # first COMPLETED job on matter bubbles lifecycle OPEN->IN_DISCOVERY
        matter["lifecycle_status"] = "IN_DISCOVERY"
        db.touch(matter)
    return response.object_response(ser.processing_job_out(j))


@app.route("/processing-jobs/<jid>/fail", methods=["POST"])
def fail_processing_job(jid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    j = find_or_404(db.processing_jobs, jid)
    if j["status"] != "RUNNING":
        raise errors.err(errors.ERR_INVALID_STATE, "Job is not RUNNING")
    j["status"] = "FAILED"
    db.touch(j)
    return response.object_response(ser.processing_job_out(j))


# ==========================================================================
# ReviewBatch
# ==========================================================================
@app.route("/review-batches", methods=["POST"])
def create_review_batch():
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["matter_id", "name"])
    matter = find_or_404(db.matters, body["matter_id"])
    name = body["name"]
    if not isinstance(name, str) or not name:
        raise errors.err(errors.ERR_INVALID_REQUEST, "name must be non-empty")
    b = db.base_fields()
    b.update({
        "matter_id": matter["id"],
        "name": name,
        "status": "DRAFT",
        "document_count": 0,
        "reviewed_count": 0,
    })
    db.review_batches[b["id"]] = b
    return response.object_response(ser.review_batch_out(b), 201)


@app.route("/review-batches/<bid>", methods=["GET"])
def get_review_batch(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead", "Reviewer", "Producer"})
    b = find_or_404(db.review_batches, bid)
    return response.object_response(ser.review_batch_out(b))


@app.route("/review-batches", methods=["GET"])
def list_review_batches():
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead", "Reviewer", "Producer"})
    items = list(db.review_batches.values())
    matter_id = request.args.get("matter_id")
    if matter_id is not None:
        items = [b for b in items if b["matter_id"] == matter_id]
    return list_response(items, ser.review_batch_out)


def _recompute_batch_counts(batch):
    reviews = svc.reviews_of_batch(batch["id"])
    batch["document_count"] = len(reviews)
    batch["reviewed_count"] = sum(1 for r in reviews if r["decision"] != "UNDECIDED")


@app.route("/review-batches/<bid>/reviews", methods=["POST"])
def add_review(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead"})
    b = find_or_404(db.review_batches, bid)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["document_id"])
    doc = find_or_404(db.documents, body["document_id"])
    # must be UNIQUE and same matter as the batch
    if doc["status"] != "UNIQUE" or doc["matter_id"] != b["matter_id"]:
        raise errors.err(errors.ERR_DOCUMENT_NOT_UNIQUE, "Document must be UNIQUE and of the batch's matter")

    r = db.base_fields()
    r.update({
        "batch_id": b["id"],
        "document_id": doc["id"],
        "reviewer_user_id": None,
        "decision": "UNDECIDED",
    })
    db.document_reviews[r["id"]] = r
    _recompute_batch_counts(b)
    db.touch(b)
    return response.object_response(ser.document_review_out(r), 201)


@app.route("/review-batches/<bid>/reviews", methods=["GET"])
def list_batch_reviews(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead", "Reviewer", "Producer"})
    b = find_or_404(db.review_batches, bid)
    items = [r for r in db.document_reviews.values() if r["batch_id"] == b["id"]]
    return list_response(items, ser.document_review_out)


@app.route("/review-batches/<bid>/open-review", methods=["POST"])
def open_review(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead"})
    b = find_or_404(db.review_batches, bid)
    if b["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not DRAFT")
    _recompute_batch_counts(b)
    if b["document_count"] < 1:
        raise errors.err(errors.ERR_EMPTY_BATCH, "Batch has no documents")
    b["status"] = "IN_REVIEW"
    db.touch(b)
    return response.object_response(ser.review_batch_out(b))


@app.route("/review-batches/<bid>/submit-qc", methods=["POST"])
def submit_qc(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead"})
    b = find_or_404(db.review_batches, bid)
    if b["status"] != "IN_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not IN_REVIEW")
    _recompute_batch_counts(b)
    if b["reviewed_count"] != b["document_count"]:
        raise errors.err(errors.ERR_BATCH_NOT_FULLY_REVIEWED, "Not all documents are reviewed")
    b["status"] = "QC_REVIEW"
    db.touch(b)
    return response.object_response(ser.review_batch_out(b))


@app.route("/review-batches/<bid>/reopen", methods=["POST"])
def reopen_batch(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead"})
    b = find_or_404(db.review_batches, bid)
    if b["status"] != "QC_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not QC_REVIEW")
    b["status"] = "IN_REVIEW"
    db.touch(b)
    return response.object_response(ser.review_batch_out(b))


@app.route("/review-batches/<bid>/complete", methods=["POST"])
def complete_batch(bid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead"})
    b = find_or_404(db.review_batches, bid)
    if b["status"] != "QC_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not QC_REVIEW")
    b["status"] = "COMPLETED"
    # freeze tags from each DocumentReview.decision
    for r in svc.reviews_of_batch(b["id"]):
        mapping = DECISION_TAG_MAP.get(r["decision"])
        if mapping is None:
            continue
        resp_tag, priv_tag = mapping
        doc = db.documents.get(r["document_id"])
        if doc is not None:
            doc["responsiveness_tag"] = resp_tag
            doc["privilege_tag"] = priv_tag
            db.touch(doc)
    db.touch(b)
    matter = db.matters.get(b["matter_id"])
    if matter is not None:
        svc.recompute_responsive_doc_count(matter)
        db.touch(matter)
    return response.object_response(ser.review_batch_out(b))


# ==========================================================================
# DocumentReview
# ==========================================================================
@app.route("/document-reviews/<rid>", methods=["GET"])
def get_document_review(rid):
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead", "Reviewer", "Producer"})
    r = find_or_404(db.document_reviews, rid)
    return response.object_response(ser.document_review_out(r))


@app.route("/document-reviews", methods=["GET"])
def list_document_reviews():
    user_id, role = auth()
    middleware.require_role(role, {"ReviewLead", "Reviewer", "Producer"})
    items = list(db.document_reviews.values())
    batch_id = request.args.get("batch_id")
    document_id = request.args.get("document_id")
    if batch_id is not None:
        items = [r for r in items if r["batch_id"] == batch_id]
    if document_id is not None:
        items = [r for r in items if r["document_id"] == document_id]
    return list_response(items, ser.document_review_out)


@app.route("/document-reviews/<rid>/decide", methods=["POST"])
def decide_review(rid):
    user_id, role = auth()
    middleware.require_role(role, {"Reviewer"})
    r = find_or_404(db.document_reviews, rid)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in DECISION_VALUES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid decision value")
    batch = db.review_batches.get(r["batch_id"])
    if batch is None or batch["status"] != "IN_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Batch is not IN_REVIEW")

    r["decision"] = decision
    r["reviewer_user_id"] = user_id
    db.touch(r)
    if batch is not None:
        _recompute_batch_counts(batch)
        db.touch(batch)
    return response.object_response(ser.document_review_out(r))


# ==========================================================================
# ProductionSet
# ==========================================================================
@app.route("/production-sets", methods=["POST"])
def create_production_set():
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["matter_id", "source_batch_id"])
    matter = find_or_404(db.matters, body["matter_id"])
    batch = find_or_404(db.review_batches, body["source_batch_id"])
    p = db.base_fields()
    p.update({
        "matter_id": matter["id"],
        "source_batch_id": batch["id"],
        "status": "DRAFT",
        "bates_start": None,
        "bates_end": None,
        "item_count": 0,
        "produced_page_count": None,
    })
    db.production_sets[p["id"]] = p
    return response.object_response(ser.production_set_out(p), 201)


@app.route("/production-sets/<pid>", methods=["GET"])
def get_production_set(pid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    p = find_or_404(db.production_sets, pid)
    return response.object_response(ser.production_set_out(p))


@app.route("/production-sets", methods=["GET"])
def list_production_sets():
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    items = list(db.production_sets.values())
    matter_id = request.args.get("matter_id")
    source_batch_id = request.args.get("source_batch_id")
    if matter_id is not None:
        items = [p for p in items if p["matter_id"] == matter_id]
    if source_batch_id is not None:
        items = [p for p in items if p["source_batch_id"] == source_batch_id]
    return list_response(items, ser.production_set_out)


@app.route("/production-sets/<pid>/items", methods=["POST"])
def add_production_item(pid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    p = find_or_404(db.production_sets, pid)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["document_id"])
    doc = find_or_404(db.documents, body["document_id"])
    if doc["privilege_tag"] == "PRIVILEGED":
        raise errors.err(errors.ERR_PRIVILEGED_DOCUMENT, "Privileged document may not be produced")

    item = db.base_fields(common=False)
    item.update({
        "set_id": p["id"],
        "document_id": doc["id"],
        "bates_number": None,
        "status": "STAGED",
    })
    db.production_items[item["id"]] = item
    p["item_count"] = len(svc.items_of_set(p["id"]))
    db.touch(p)
    return response.object_response(ser.production_item_out(item), 201)


@app.route("/production-sets/<pid>/items", methods=["GET"])
def list_production_items_of_set(pid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    p = find_or_404(db.production_sets, pid)
    items = [i for i in db.production_items.values() if i["set_id"] == p["id"]]
    return list_response(items, ser.production_item_out)


@app.route("/production-sets/<pid>/validate", methods=["POST"])
def validate_production_set(pid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    p = find_or_404(db.production_sets, pid)
    if p["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Set is not DRAFT")
    items = svc.items_of_set(p["id"])
    if len(items) < 1:
        raise errors.err(errors.ERR_EMPTY_PRODUCTION_SET, "Production set has no items")
    batch = db.review_batches.get(p["source_batch_id"])
    if batch is None or batch["status"] != "COMPLETED":
        raise errors.err(errors.ERR_BATCH_NOT_COMPLETED, "Source batch is not COMPLETED")

    # transition through VALIDATING then fork
    has_privileged = False
    for item in items:
        doc = db.documents.get(item["document_id"])
        if doc is not None and doc["privilege_tag"] == "PRIVILEGED":
            has_privileged = True
            break

    if has_privileged:
        p["status"] = "BLOCKED"
    else:
        p["status"] = "STAGED"
        matter = db.matters.get(p["matter_id"])
        svc.allocate_bates(matter, p, items)
        db.touch(matter)
    db.touch(p)
    return response.object_response(ser.production_set_out(p))


@app.route("/production-sets/<pid>/revise", methods=["POST"])
def revise_production_set(pid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    p = find_or_404(db.production_sets, pid)
    if p["status"] != "BLOCKED":
        raise errors.err(errors.ERR_INVALID_STATE, "Set is not BLOCKED")
    p["status"] = "DRAFT"
    db.touch(p)
    return response.object_response(ser.production_set_out(p))


@app.route("/production-sets/<pid>/produce", methods=["POST"])
def produce_production_set(pid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    p = find_or_404(db.production_sets, pid)
    # SoD check (priority 3, before existence-of-state semantics per §2.8;
    # but the set/path is already resolved here). Enforce SoD before state? Per
    # §2.8 ordering: auth(1) -> forbidden_role(2) -> SoD(3) -> not_found(4) ->
    # state(5). The path resource existence is needed to evaluate SoD, so we
    # resolve the set first (404 if missing) then SoD, then state.
    items = svc.items_of_set(p["id"])
    doc_ids = {i["document_id"] for i in items}
    for r in db.document_reviews.values():
        if r["document_id"] in doc_ids and r.get("reviewer_user_id") == user_id:
            raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Producer decided a document in this set")

    if p["status"] != "STAGED":
        raise errors.err(errors.ERR_INVALID_STATE, "Set is not STAGED")
    matter = db.matters.get(p["matter_id"])
    if matter is None or matter["lifecycle_status"] not in ("IN_DISCOVERY", "CLOSING"):
        raise errors.err(errors.ERR_INVALID_STATE, "Matter lifecycle must be IN_DISCOVERY or CLOSING")

    p["status"] = "PRODUCED"
    for item in items:
        if item["status"] == "STAGED":
            item["status"] = "PRODUCED"
    db.touch(p)
    if matter is not None:
        svc.recompute_produced_counts(matter)
        db.touch(matter)
    return response.object_response(ser.production_set_out(p))


# ==========================================================================
# ProductionItem
# ==========================================================================
@app.route("/production-items/<iid>", methods=["GET"])
def get_production_item(iid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    item = find_or_404(db.production_items, iid)
    return response.object_response(ser.production_item_out(item))


@app.route("/production-items", methods=["GET"])
def list_production_items():
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    items = list(db.production_items.values())
    set_id = request.args.get("set_id")
    document_id = request.args.get("document_id")
    if set_id is not None:
        items = [i for i in items if i["set_id"] == set_id]
    if document_id is not None:
        items = [i for i in items if i["document_id"] == document_id]
    return list_response(items, ser.production_item_out)


# ==========================================================================
# Clawback
# ==========================================================================
@app.route("/clawbacks", methods=["POST"])
def create_clawback():
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    body = helpers.get_json_body()
    helpers.require_fields(body, [
        "matter_id", "production_item_id", "reason", "expected_production_set_version",
    ])
    matter = find_or_404(db.matters, body["matter_id"])
    item = find_or_404(db.production_items, body["production_item_id"])
    reason = body["reason"]
    if not isinstance(reason, str) or not reason:
        raise errors.err(errors.ERR_INVALID_REQUEST, "reason must be non-empty")
    expected_version = body["expected_production_set_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_production_set_version must be an integer")

    pset = db.production_sets.get(item["set_id"])
    if pset is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Parent production set not found")
    # OCC check
    if expected_version != pset["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale production set version")

    cb = db.base_fields()
    cb.update({
        "matter_id": matter["id"],
        "production_item_id": item["id"],
        "reason": reason,
        "status": "REQUESTED",
    })
    db.clawbacks[cb["id"]] = cb
    # increment parent set version
    db.touch(pset)
    return response.object_response(ser.clawback_out(cb), 201)


@app.route("/clawbacks/<cid>", methods=["GET"])
def get_clawback(cid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    cb = find_or_404(db.clawbacks, cid)
    return response.object_response(ser.clawback_out(cb))


@app.route("/clawbacks", methods=["GET"])
def list_clawbacks():
    user_id, role = auth()
    middleware.require_role(role, {"Producer", "LegalOps"})
    items = list(db.clawbacks.values())
    matter_id = request.args.get("matter_id")
    production_item_id = request.args.get("production_item_id")
    if matter_id is not None:
        items = [c for c in items if c["matter_id"] == matter_id]
    if production_item_id is not None:
        items = [c for c in items if c["production_item_id"] == production_item_id]
    return list_response(items, ser.clawback_out)


@app.route("/clawbacks/<cid>/sequester", methods=["POST"])
def sequester_clawback(cid):
    user_id, role = auth()
    middleware.require_role(role, {"Producer"})
    cb = find_or_404(db.clawbacks, cid)
    if cb["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Clawback is not REQUESTED")
    item = db.production_items.get(cb["production_item_id"])
    if item is None or item["status"] != "PRODUCED":
        raise errors.err(errors.ERR_INVALID_STATE, "Production item is not PRODUCED")
    cb["status"] = "SEQUESTERED"
    item["status"] = "CLAWED_BACK"
    doc = db.documents.get(item["document_id"])
    if doc is not None:
        doc["privilege_tag"] = "PRIVILEGED"
        db.touch(doc)
    db.touch(cb)
    matter = db.matters.get(cb["matter_id"])
    if matter is not None:
        svc.recompute_produced_counts(matter)
        db.touch(matter)
    return response.object_response(ser.clawback_out(cb))


@app.route("/clawbacks/<cid>/dispute", methods=["POST"])
def dispute_clawback(cid):
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    cb = find_or_404(db.clawbacks, cid)
    if cb["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Clawback is not REQUESTED")
    cb["status"] = "DISPUTED"
    db.touch(cb)
    return response.object_response(ser.clawback_out(cb))


# ==========================================================================
# Test-driving clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth()
    middleware.require_role(role, {"LegalOps"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["to_iso8601"])
    dt = clock.parse_iso(body["to_iso8601"])
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be ISO8601")
    clock.set_now(dt)
    return response.object_response({"now": clock.to_iso(dt)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

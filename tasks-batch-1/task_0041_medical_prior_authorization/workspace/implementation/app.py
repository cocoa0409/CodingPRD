import os
import re
from datetime import datetime, timezone, timedelta

from flask import Flask, request as flask_request

from clock import clock
from db import db, new_common, touch
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_REVIEWER_PAYER_MISMATCH, ERR_OPEN_P2P_BLOCKS_DECISION, ERR_NO_EVIDENCE,
    ERR_P2P_SLOT_CONFLICT, ERR_PAST_DEADLINE, ERR_DUPLICATE_ACTIVE_AUTH,
    ERR_INVALID_DECISION_FIELDS, ERR_APPEAL_NOT_ELIGIBLE,
    ERR_INVALID_SUPERSEDE_TARGET, ERR_STALE_VERSION, ERR_VALIDATION,
    ERR_PAGINATION_INVALID,
)
from response import success, error_response, iso_ms, iso_sec
from calculations import (
    compute_sla_due_at, compute_member_cost_share, compute_appeal_deadline,
    round_half_up,
)

app = Flask(__name__)

SPECIALTIES = {"CARDIOLOGY", "ONCOLOGY", "ORTHOPEDICS", "NEUROLOGY", "PRIMARY_CARE", "RADIOLOGY"}
ROLES = {"Anonymous", "Provider", "Payer", "ExternalReviewer"}
REQUEST_TYPES = {"SERVICE", "DRUG"}
DOC_TYPES = {"CHART_NOTE", "LAB_RESULT", "IMAGING", "MEDICATION_HISTORY", "LETTER_OF_MEDICAL_NECESSITY"}
OUTCOMES = {"APPROVE", "PARTIAL", "DENY", "PEND"}
PEND_REASONS = {"INSUFFICIENT_EVIDENCE", "MISSING_LMN", "PEER_TO_PEER_REQUIRED"}


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_VALIDATION", str(e), 422)


# --------------------------------------------------------------------------
# Body / parsing helpers
# --------------------------------------------------------------------------
def get_body():
    try:
        body = flask_request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_VALIDATION, f"Missing required field: {field}")
    return body[field]


def parse_iso(value):
    if not isinstance(value, str):
        raise err(ERR_VALIDATION, "Invalid datetime.")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err(ERR_VALIDATION, "Invalid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------
def auth():
    """Returns (role, user_id). Raises ERR_UNAUTHENTICATED if missing/malformed."""
    role = flask_request.headers.get("X-User-Role")
    user_id = flask_request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers.")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, f"Role {role} not permitted for this operation.")


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def paginate(items):
    args = flask_request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_PAGINATION_INVALID, "limit out of bounds.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_PAGINATION_INVALID, "offset out of bounds.")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["_created_dt"], x["id"]))


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def ser_provider(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "npi": p["npi"], "name": p["name"],
        "specialty": p["specialty"],
    }


def ser_payer(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "name": p["name"],
        "standard_sla_hours": p["standard_sla_hours"],
        "expedited_sla_hours": p["expedited_sla_hours"],
    }


def active_auth_count(member_id):
    now = clock.now()
    count = 0
    for r in db.requests.values():
        if r["member_id"] != member_id:
            continue
        if r["status"] != "APPROVED":
            continue
        exp = r.get("_expires_dt")
        if exp is not None and exp > now:
            count += 1
    return count


def ser_member(m):
    return {
        "id": m["id"], "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"], "payer_id": m["payer_id"],
        "member_number": m["member_number"],
        "coinsurance_rate": m["coinsurance_rate"],
        "active_authorization_count": active_auth_count(m["id"]),
    }


def ser_reviewer(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "payer_id": r["payer_id"], "name": r["name"],
        "specialty": r["specialty"], "p2p_buffer_minutes": r["p2p_buffer_minutes"],
    }


def ser_request(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
        "member_id": r["member_id"], "provider_id": r["provider_id"],
        "payer_id": r["payer_id"], "request_type": r["request_type"],
        "procedure_code": r["procedure_code"], "requested_units": r["requested_units"],
        "unit_cost_cents": r["unit_cost_cents"], "is_expedited": r["is_expedited"],
        "status": r["status"],
        "submitted_at": iso_sec(r.get("_submitted_dt")),
        "review_started_at": iso_sec(r.get("_review_started_dt")),
        "sla_due_at": iso_sec(r.get("_sla_due_dt")),
        "clock_paused_hours": r["clock_paused_hours"],
        "approved_units": r["approved_units"],
        "member_cost_share_cents": r["member_cost_share_cents"],
        "authorization_expires_at": iso_sec(r.get("_expires_dt")),
        "supersedes_request_id": r.get("supersedes_request_id"),
    }


def ser_evidence(e):
    return {
        "id": e["id"], "created_at": e["created_at"],
        "request_id": e["request_id"], "document_type": e["document_type"],
        "line_item_cost_cents": e["line_item_cost_cents"], "uri": e["uri"],
    }


def ser_decision(d):
    return {
        "id": d["id"], "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"], "request_id": d["request_id"],
        "reviewer_id": d["reviewer_id"], "outcome": d["outcome"],
        "approved_units": d["approved_units"], "rationale": d.get("rationale"),
        "pend_reason": d.get("pend_reason"),
    }


def ser_session(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "request_id": s["request_id"],
        "reviewer_id": s["reviewer_id"],
        "slot_start": iso_sec(s["_slot_start_dt"]),
        "slot_end": iso_sec(s["_slot_end_dt"]),
        "status": s["status"],
    }


def ser_appeal(a):
    return {
        "id": a["id"], "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"], "request_id": a["request_id"],
        "tier": a["tier"], "status": a["status"],
        "filed_at": iso_sec(a.get("_filed_dt")),
        "appeal_deadline_at": iso_sec(a.get("_deadline_dt")),
        "decision_rationale": a.get("decision_rationale"),
    }


# --------------------------------------------------------------------------
# Lookup helpers (existence → ERR_NOT_FOUND)
# --------------------------------------------------------------------------
def find_or_404(store, _id):
    if _id is None or _id not in store:
        raise err(ERR_NOT_FOUND, "Referenced resource not found.")
    return store[_id]


# ==========================================================================
# Registration surface (Anonymous)
# ==========================================================================
@app.route("/providers", methods=["POST"])
def create_provider():
    body = get_body()
    npi = require(body, "npi")
    name = require(body, "name")
    specialty = require(body, "specialty")
    if not isinstance(npi, str) or not re.fullmatch(r"\d{10}", npi):
        raise err(ERR_VALIDATION, "npi must be exactly 10 numeric characters.")
    if not isinstance(name, str) or not name.strip():
        raise err(ERR_VALIDATION, "name is required and non-empty.")
    if specialty not in SPECIALTIES:
        raise err(ERR_VALIDATION, "Invalid specialty.")
    for p in db.providers.values():
        if p["npi"] == npi:
            raise err(ERR_VALIDATION, "npi must be unique.")
    p = new_common()
    p.update({"npi": npi, "name": name, "specialty": specialty})
    db.providers[p["id"]] = p
    return success(ser_provider(p), 201)


@app.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    return success(ser_provider(find_or_404(db.providers, pid)), 200)


@app.route("/payers", methods=["POST"])
def create_payer():
    body = get_body()
    name = require(body, "name")
    if not isinstance(name, str) or not name.strip():
        raise err(ERR_VALIDATION, "name is required and non-empty.")
    std = body.get("standard_sla_hours", 168)
    exp = body.get("expedited_sla_hours", 72)
    if not isinstance(std, int) or isinstance(std, bool) or std < 1:
        raise err(ERR_VALIDATION, "standard_sla_hours must be >= 1.")
    if not isinstance(exp, int) or isinstance(exp, bool) or exp < 1:
        raise err(ERR_VALIDATION, "expedited_sla_hours must be >= 1.")
    if exp >= std:
        raise err(ERR_VALIDATION, "expedited_sla_hours must be < standard_sla_hours.")
    p = new_common()
    p.update({"name": name, "standard_sla_hours": std, "expedited_sla_hours": exp})
    db.payers[p["id"]] = p
    return success(ser_payer(p), 201)


@app.route("/payers/<pid>", methods=["GET"])
def get_payer(pid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    return success(ser_payer(find_or_404(db.payers, pid)), 200)


@app.route("/members", methods=["POST"])
def create_member():
    body = get_body()
    payer_id = require(body, "payer_id")
    member_number = require(body, "member_number")
    find_or_404(db.payers, payer_id)
    if not isinstance(member_number, str) or not member_number.strip():
        raise err(ERR_VALIDATION, "member_number is required.")
    rate = body.get("coinsurance_rate", 0.2)
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise err(ERR_VALIDATION, "coinsurance_rate must be a number.")
    if rate < 0.0 or rate > 1.0:
        raise err(ERR_VALIDATION, "coinsurance_rate must be between 0.0 and 1.0.")
    for m in db.members.values():
        if m["payer_id"] == payer_id and m["member_number"] == member_number:
            raise err(ERR_VALIDATION, "member_number must be unique per payer.")
    m = new_common()
    m.update({"payer_id": payer_id, "member_number": member_number,
              "coinsurance_rate": rate})
    db.members[m["id"]] = m
    return success(ser_member(m), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer"})
    return success(ser_member(find_or_404(db.members, mid)), 200)


@app.route("/members", methods=["GET"])
def list_members():
    role, _ = auth()
    require_role(role, {"Provider", "Payer"})
    payer_id = flask_request.args.get("payer_id")
    items = [m for m in db.members.values()
             if payer_id is None or m["payer_id"] == payer_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_member(m) for m in page], 200, meta)


@app.route("/reviewers", methods=["POST"])
def create_reviewer():
    body = get_body()
    payer_id = require(body, "payer_id")
    name = require(body, "name")
    specialty = require(body, "specialty")
    find_or_404(db.payers, payer_id)
    if not isinstance(name, str) or not name.strip():
        raise err(ERR_VALIDATION, "name is required and non-empty.")
    if specialty not in SPECIALTIES:
        raise err(ERR_VALIDATION, "Invalid specialty.")
    buf = body.get("p2p_buffer_minutes", 0)
    if not isinstance(buf, int) or isinstance(buf, bool) or buf < 0:
        raise err(ERR_VALIDATION, "p2p_buffer_minutes must be >= 0.")
    r = new_common()
    r.update({"payer_id": payer_id, "name": name, "specialty": specialty,
              "p2p_buffer_minutes": buf})
    db.reviewers[r["id"]] = r
    return success(ser_reviewer(r), 201)


@app.route("/reviewers/<rid>", methods=["GET"])
def get_reviewer(rid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer"})
    return success(ser_reviewer(find_or_404(db.reviewers, rid)), 200)


@app.route("/reviewers", methods=["GET"])
def list_reviewers():
    role, _ = auth()
    require_role(role, {"Provider", "Payer"})
    payer_id = flask_request.args.get("payer_id")
    items = [r for r in db.reviewers.values()
             if payer_id is None or r["payer_id"] == payer_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_reviewer(r) for r in page], 200, meta)


# ==========================================================================
# Authorization requests
# ==========================================================================
def validate_int(body, field, minimum, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_VALIDATION, f"Missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, f"{field} must be an integer.")
    if v < minimum:
        raise err(ERR_VALIDATION, f"{field} must be >= {minimum}.")
    return v


@app.route("/authorization-requests", methods=["POST"])
def create_request():
    role, user_id = auth()
    require_role(role, {"Provider"})
    body = get_body()

    member_id = require(body, "member_id")
    provider_id = require(body, "provider_id")
    request_type = require(body, "request_type")
    procedure_code = require(body, "procedure_code")
    requested_units = validate_int(body, "requested_units", 1)
    unit_cost_cents = validate_int(body, "unit_cost_cents", 0)
    is_expedited = body.get("is_expedited", False)
    if not isinstance(is_expedited, bool):
        raise err(ERR_VALIDATION, "is_expedited must be a boolean.")
    if request_type not in REQUEST_TYPES:
        raise err(ERR_VALIDATION, "Invalid request_type.")
    if not isinstance(procedure_code, str) or not procedure_code.strip():
        raise err(ERR_VALIDATION, "procedure_code is required and non-empty.")

    supersedes_id = body.get("supersedes_request_id")

    # existence: path ids (none) then body FKs, left-to-right
    member = find_or_404(db.members, member_id)
    find_or_404(db.providers, provider_id)
    target = None
    if supersedes_id is not None:
        target = find_or_404(db.requests, supersedes_id)

    if supersedes_id is not None:
        already = any(
            r.get("supersedes_request_id") == supersedes_id
            for r in db.requests.values()
        )
        expected = body.get("expected_authorizationrequest_version")
        version_stale = (expected is None or expected != target["version"])
        # PRD §2.10 explicitly governs the case where the target's version no
        # longer matches "because another resubmission has already superseded
        # it, legitimately advancing its version and flipping it to its
        # superseded state": that yields ERR_STALE_VERSION, not invalid-target.
        if already and version_stale:
            raise err(ERR_STALE_VERSION, "Stale supersede-target version.")
        # supersede-target validity (priority 12)
        if (target["status"] != "EXPIRED" or
                target["member_id"] != member_id or
                target["provider_id"] != provider_id or
                already):
            raise err(ERR_INVALID_SUPERSEDE_TARGET, "Invalid supersede target.")
        # OCC version check (priority 13)
        if version_stale:
            raise err(ERR_STALE_VERSION, "Stale supersede-target version.")

    r = new_common()
    r.update({
        "member_id": member_id,
        "provider_id": provider_id,
        "payer_id": member["payer_id"],
        "request_type": request_type,
        "procedure_code": procedure_code,
        "requested_units": requested_units,
        "unit_cost_cents": unit_cost_cents,
        "is_expedited": is_expedited,
        "status": "DRAFT",
        "clock_paused_hours": 0,
        "approved_units": 0,
        "member_cost_share_cents": 0,
        "supersedes_request_id": supersedes_id,
        "_submitted_dt": None,
        "_review_started_dt": None,
        "_sla_due_dt": None,
        "_expires_dt": None,
        "_pend_started_dt": None,
    })
    db.requests[r["id"]] = r

    if target is not None:
        target["status"] = "SUPERSEDED"
        touch(target)

    return success(ser_request(r), 201)


@app.route("/authorization-requests/<rid>", methods=["GET"])
def get_request(rid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    return success(ser_request(find_or_404(db.requests, rid)), 200)


@app.route("/authorization-requests", methods=["GET"])
def list_requests():
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    a = flask_request.args
    items = list(db.requests.values())
    for f in ("member_id", "provider_id", "payer_id", "status", "supersedes_request_id"):
        val = a.get(f)
        if val is not None:
            items = [r for r in items if r.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_request(r) for r in page], 200, meta)


@app.route("/authorization-requests/<rid>/submit", methods=["POST"])
def submit_request(rid):
    role, user_id = auth()
    require_role(role, {"Provider"})
    r = find_or_404(db.requests, rid)
    if r["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Request is not DRAFT.")
    if r["provider_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Provider does not own this request.")
    has_evidence = any(e["request_id"] == rid for e in db.evidence.values())
    if not has_evidence:
        raise err(ERR_NO_EVIDENCE, "At least one ClinicalEvidence row is required.")
    now = clock.now()
    r["status"] = "SUBMITTED"
    r["_submitted_dt"] = now
    r["_review_started_dt"] = now
    r["clock_paused_hours"] = 0
    payer = db.payers[r["payer_id"]]
    member = db.members[r["member_id"]]
    compute_sla_due_at(r, payer)
    compute_member_cost_share(r, member)
    touch(r)
    return success(ser_request(r), 200)


@app.route("/authorization-requests/<rid>/start-review", methods=["POST"])
def start_review(rid):
    role, user_id = auth()
    require_role(role, {"Payer"})
    r = find_or_404(db.requests, rid)
    if r["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Request is not SUBMITTED.")
    if r["payer_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Payer does not own this request.")
    r["status"] = "UNDER_REVIEW"
    r["_review_started_dt"] = clock.now()
    compute_sla_due_at(r, db.payers[r["payer_id"]])
    touch(r)
    return success(ser_request(r), 200)


@app.route("/authorization-requests/<rid>/resume-review", methods=["POST"])
def resume_review(rid):
    role, user_id = auth()
    require_role(role, {"Payer"})
    r = find_or_404(db.requests, rid)
    if r["status"] != "PENDED":
        raise err(ERR_INVALID_STATE, "Request is not PENDED.")
    if r["payer_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Payer does not own this request.")
    # new evidence required after the pend decision
    pend_at = r.get("_pend_started_dt")
    pend_seq = r.get("_pend_seq")
    has_new = any(
        e["request_id"] == rid and pend_seq is not None
        and e.get("_created_seq", 0) > pend_seq
        for e in db.evidence.values()
    )
    if not has_new:
        raise err(ERR_NO_EVIDENCE, "New evidence required to resume.")
    now = clock.now()
    if pend_at is not None:
        paused = (now - pend_at).total_seconds() / 3600.0
        r["clock_paused_hours"] = r.get("clock_paused_hours", 0) + paused
    r["status"] = "UNDER_REVIEW"
    r["_review_started_dt"] = now
    r["_pend_started_dt"] = None
    compute_sla_due_at(r, db.payers[r["payer_id"]])
    touch(r)
    return success(ser_request(r), 200)


@app.route("/authorization-requests/<rid>/expire", methods=["POST"])
def expire_request(rid):
    role, user_id = auth()
    require_role(role, {"Payer"})
    r = find_or_404(db.requests, rid)
    if r["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Request is not APPROVED.")
    if r["payer_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Payer does not own this request.")
    exp = r.get("_expires_dt")
    if exp is None or clock.now() < exp:
        raise err(ERR_INVALID_STATE, "Clock has not reached authorization_expires_at.")
    r["status"] = "EXPIRED"
    member = db.members.get(r["member_id"])
    if member is not None:
        touch(member)  # member counter is computed; bump version/timestamp on cascade
    touch(r)
    return success(ser_request(r), 200)


# ==========================================================================
# Clinical evidence
# ==========================================================================
@app.route("/clinical-evidence", methods=["POST"])
def create_evidence():
    role, user_id = auth()
    require_role(role, {"Provider"})
    body = get_body()
    request_id = require(body, "request_id")
    document_type = require(body, "document_type")
    line_item_cost_cents = validate_int(body, "line_item_cost_cents", 0)
    uri = require(body, "uri")
    find_or_404(db.requests, request_id)
    if document_type not in DOC_TYPES:
        raise err(ERR_VALIDATION, "Invalid document_type.")
    if not isinstance(uri, str) or not uri.strip():
        raise err(ERR_VALIDATION, "uri is required and non-empty.")
    e = new_common(with_version=False)
    e.update({"request_id": request_id, "document_type": document_type,
              "line_item_cost_cents": line_item_cost_cents, "uri": uri})
    db.evidence[e["id"]] = e
    return success(ser_evidence(e), 201)


@app.route("/clinical-evidence/<eid>", methods=["GET"])
def get_evidence(eid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    return success(ser_evidence(find_or_404(db.evidence, eid)), 200)


@app.route("/clinical-evidence", methods=["GET"])
def list_evidence():
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    request_id = flask_request.args.get("request_id")
    items = [e for e in db.evidence.values()
             if request_id is None or e["request_id"] == request_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_evidence(e) for e in page], 200, meta)


# ==========================================================================
# Review decisions
# ==========================================================================
def coverage_overlaps(member_id, procedure_code, start_dt, end_dt, exclude_id):
    """Closed-interval overlap against existing APPROVED requests (capacity 1)."""
    for o in db.requests.values():
        if o["id"] == exclude_id:
            continue
        if o["member_id"] != member_id or o["procedure_code"] != procedure_code:
            continue
        if o["status"] != "APPROVED":
            continue
        o_start = o.get("_submitted_dt")
        o_end = o.get("_expires_dt")
        if o_start is None or o_end is None:
            continue
        # closed intervals overlap iff start <= o_end and o_start <= end
        if start_dt <= o_end and o_start <= end_dt:
            return True
    return False


def apply_approval(r, approved_units):
    now = clock.now()
    end_dt = now + timedelta(days=365)
    start_dt = r.get("_submitted_dt") or now
    if coverage_overlaps(r["member_id"], r["procedure_code"], start_dt, end_dt, r["id"]):
        raise err(ERR_DUPLICATE_ACTIVE_AUTH, "Duplicate active authorization.")
    r["status"] = "APPROVED"
    r["approved_units"] = approved_units
    r["_expires_dt"] = end_dt
    compute_member_cost_share(r, db.members[r["member_id"]])
    member = db.members.get(r["member_id"])
    if member is not None:
        touch(member)
    touch(r)


@app.route("/review-decisions", methods=["POST"])
def create_decision():
    role, user_id = auth()
    require_role(role, {"Payer"})
    body = get_body()
    request_id = require(body, "request_id")
    reviewer_id = require(body, "reviewer_id")
    outcome = require(body, "outcome")
    if outcome not in OUTCOMES:
        raise err(ERR_VALIDATION, "Invalid outcome.")

    # existence: body FKs left-to-right
    r = find_or_404(db.requests, request_id)
    reviewer = find_or_404(db.reviewers, reviewer_id)

    # state (priority 4)
    if r["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Request is not UNDER_REVIEW.")

    # reviewer-payer match (priority 5)
    if reviewer["payer_id"] != r["payer_id"]:
        raise err(ERR_REVIEWER_PAYER_MISMATCH, "Reviewer payer mismatch.")

    # open P2P blocks decision (priority 6)
    if any(s["request_id"] == request_id and s["status"] == "SCHEDULED"
           for s in db.sessions.values()):
        raise err(ERR_OPEN_P2P_BLOCKS_DECISION, "Open P2P session blocks decision.")

    # duplicate-active-auth (priority 8.5) — only applies to approving outcomes
    if outcome in ("APPROVE", "PARTIAL"):
        now = clock.now()
        end_dt = now + timedelta(days=365)
        start_dt = r.get("_submitted_dt") or now
        if coverage_overlaps(r["member_id"], r["procedure_code"], start_dt, end_dt, r["id"]):
            raise err(ERR_DUPLICATE_ACTIVE_AUTH, "Duplicate active authorization.")

    # past deadline (priority 9)
    due = r.get("_sla_due_dt")
    if due is not None and clock.now() > due:
        raise err(ERR_PAST_DEADLINE, "Review decision past sla_due_at.")

    # decision-field validity (priority 10)
    approved_units_in = body.get("approved_units", 0)
    rationale = body.get("rationale")
    pend_reason = body.get("pend_reason")
    if outcome == "APPROVE":
        resolved_units = r["requested_units"]
    elif outcome == "PARTIAL":
        if (isinstance(approved_units_in, bool)
                or not isinstance(approved_units_in, int)
                or approved_units_in < 1
                or approved_units_in >= r["requested_units"]):
            raise err(ERR_INVALID_DECISION_FIELDS, "PARTIAL approved_units out of range.")
        if not rationale:
            raise err(ERR_INVALID_DECISION_FIELDS, "rationale required for PARTIAL.")
        resolved_units = approved_units_in
    elif outcome == "DENY":
        if not rationale:
            raise err(ERR_INVALID_DECISION_FIELDS, "rationale required for DENY.")
        resolved_units = 0
    else:  # PEND
        if pend_reason not in PEND_REASONS:
            raise err(ERR_INVALID_DECISION_FIELDS, "pend_reason required for PEND.")
        resolved_units = 0

    # create decision row
    d = new_common()
    d.update({
        "request_id": request_id, "reviewer_id": reviewer_id, "outcome": outcome,
        "approved_units": resolved_units if outcome in ("APPROVE", "PARTIAL") else 0,
        "rationale": rationale if outcome in ("DENY", "PARTIAL") else None,
        "pend_reason": pend_reason if outcome == "PEND" else None,
    })
    db.decisions[d["id"]] = d

    if outcome in ("APPROVE", "PARTIAL"):
        apply_approval(r, resolved_units)
    elif outcome == "DENY":
        r["status"] = "DENIED"
        r["approved_units"] = 0
        touch(r)
    else:  # PEND
        r["status"] = "PENDED"
        r["_pend_started_dt"] = clock.now()
        r["_pend_seq"] = db._seq
        touch(r)

    return success(ser_decision(d), 201)


@app.route("/review-decisions/<did>", methods=["GET"])
def get_decision(did):
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    return success(ser_decision(find_or_404(db.decisions, did)), 200)


@app.route("/review-decisions", methods=["GET"])
def list_decisions():
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    a = flask_request.args
    items = list(db.decisions.values())
    for f in ("request_id", "reviewer_id"):
        val = a.get(f)
        if val is not None:
            items = [d for d in items if d.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_decision(d) for d in page], 200, meta)


# ==========================================================================
# Peer-to-peer sessions
# ==========================================================================
@app.route("/peer-to-peer-sessions", methods=["POST"])
def create_session():
    role, user_id = auth()
    require_role(role, {"Payer"})
    body = get_body()
    request_id = require(body, "request_id")
    reviewer_id = require(body, "reviewer_id")
    slot_start_raw = require(body, "slot_start")
    slot_end_raw = require(body, "slot_end")
    slot_start = parse_iso(slot_start_raw)
    slot_end = parse_iso(slot_end_raw)
    if slot_end <= slot_start:
        raise err(ERR_VALIDATION, "slot_end must be strictly after slot_start.")

    r = find_or_404(db.requests, request_id)
    reviewer = find_or_404(db.reviewers, reviewer_id)

    if r["status"] not in ("UNDER_REVIEW", "PENDED"):
        raise err(ERR_INVALID_STATE, "Request not in UNDER_REVIEW or PENDED.")

    if reviewer["payer_id"] != r["payer_id"]:
        raise err(ERR_REVIEWER_PAYER_MISMATCH, "Reviewer payer mismatch.")

    # slot-conflict (priority 8): overlap OR gap < buffer, against same reviewer's
    # non-CANCELLED slots.
    buffer = timedelta(minutes=reviewer["p2p_buffer_minutes"])
    for s in db.sessions.values():
        if s["reviewer_id"] != reviewer_id or s["status"] == "CANCELLED":
            continue
        o_start = s["_slot_start_dt"]
        o_end = s["_slot_end_dt"]
        # half-open overlap
        overlap = slot_start < o_end and o_start < slot_end
        if overlap:
            raise err(ERR_P2P_SLOT_CONFLICT, "P2P slot conflict.")
        # gap between disjoint intervals
        if slot_end <= o_start:
            gap = o_start - slot_end
        else:  # o_end <= slot_start
            gap = slot_start - o_end
        if gap < buffer:
            raise err(ERR_P2P_SLOT_CONFLICT, "P2P slot within buffer.")

    s = new_common()
    s.update({"request_id": request_id, "reviewer_id": reviewer_id,
              "_slot_start_dt": slot_start, "_slot_end_dt": slot_end,
              "status": "SCHEDULED"})
    db.sessions[s["id"]] = s
    return success(ser_session(s), 201)


@app.route("/peer-to-peer-sessions/<sid>", methods=["GET"])
def get_session(sid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer"})
    return success(ser_session(find_or_404(db.sessions, sid)), 200)


@app.route("/peer-to-peer-sessions", methods=["GET"])
def list_sessions():
    role, _ = auth()
    require_role(role, {"Provider", "Payer"})
    a = flask_request.args
    items = list(db.sessions.values())
    for f in ("request_id", "reviewer_id"):
        val = a.get(f)
        if val is not None:
            items = [s for s in items if s.get(f) == val]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_session(s) for s in page], 200, meta)


@app.route("/peer-to-peer-sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    role, user_id = auth()
    require_role(role, {"Payer"})
    s = find_or_404(db.sessions, sid)
    if s["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")
    r = db.requests.get(s["request_id"])
    if r is not None and r["payer_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Payer does not own linked request.")
    s["status"] = "COMPLETED"
    if r is not None:
        duration_hours = (s["_slot_end_dt"] - s["_slot_start_dt"]).total_seconds() / 3600.0
        r["clock_paused_hours"] = r.get("clock_paused_hours", 0) + duration_hours
        compute_sla_due_at(r, db.payers[r["payer_id"]])
        touch(r)
    touch(s)
    return success(ser_session(s), 200)


@app.route("/peer-to-peer-sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    role, user_id = auth()
    require_role(role, {"Payer"})
    s = find_or_404(db.sessions, sid)
    if s["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED.")
    r = db.requests.get(s["request_id"])
    if r is not None and r["payer_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Payer does not own linked request.")
    s["status"] = "CANCELLED"
    touch(s)
    return success(ser_session(s), 200)


# ==========================================================================
# Appeals
# ==========================================================================
@app.route("/appeals", methods=["POST"])
def create_appeal():
    role, user_id = auth()
    require_role(role, {"Provider"})
    body = get_body()
    request_id = require(body, "request_id")
    r = find_or_404(db.requests, request_id)

    appeals_for = [a for a in db.appeals.values() if a["request_id"] == request_id]

    if not appeals_for:
        # tier-1 filing: request must be DENIED
        if r["status"] != "DENIED":
            raise err(ERR_APPEAL_NOT_ELIGIBLE, "Request is not DENIED.")
        tier = 1
        prior = None
    else:
        # escalation: prior UPHELD with tier<3 and no OPEN appeal outstanding
        if any(a["status"] == "OPEN" for a in appeals_for):
            raise err(ERR_APPEAL_NOT_ELIGIBLE, "An OPEN appeal already exists.")
        # find the highest-tier UPHELD appeal eligible to escalate
        upheld = [a for a in appeals_for if a["status"] == "UPHELD" and a["tier"] < 3]
        if not upheld:
            raise err(ERR_APPEAL_NOT_ELIGIBLE, "No UPHELD tier<3 appeal to escalate.")
        prior = max(upheld, key=lambda a: a["tier"])
        tier = prior["tier"] + 1

    a = new_common()
    a.update({"request_id": request_id, "tier": tier, "status": "OPEN",
              "_filed_dt": clock.now(), "decision_rationale": None})
    a["filed_at_set"] = True
    compute_appeal_deadline(a, r)
    db.appeals[a["id"]] = a

    if prior is not None:
        prior["status"] = "ESCALATED"
        touch(prior)

    return success(ser_appeal(a), 201)


@app.route("/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    return success(ser_appeal(find_or_404(db.appeals, aid)), 200)


@app.route("/appeals", methods=["GET"])
def list_appeals():
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    request_id = flask_request.args.get("request_id")
    items = [a for a in db.appeals.values()
             if request_id is None or a["request_id"] == request_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([ser_appeal(a) for a in page], 200, meta)


def _decide_appeal(aid, allowed_role, valid_tiers, ownership):
    role, user_id = auth()
    require_role(role, allowed_role)
    body = get_body()
    decision = require(body, "decision")
    decision_rationale = body.get("decision_rationale")
    if decision not in ("UPHELD", "OVERTURNED"):
        raise err(ERR_VALIDATION, "Invalid decision.")

    a = find_or_404(db.appeals, aid)
    r = db.requests.get(a["request_id"])

    # ownership (payer path)
    if ownership == "payer" and r is not None and r["payer_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Payer does not own appeal's request.")

    # state
    if a["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Appeal is not OPEN.")
    if a["tier"] not in valid_tiers:
        raise err(ERR_INVALID_STATE, "Appeal tier not decidable here.")

    # duplicate-active-auth (priority 8.5) for OVERTURNED
    if decision == "OVERTURNED" and r is not None:
        now = clock.now()
        end_dt = now + timedelta(days=365)
        start_dt = r.get("_submitted_dt") or now
        if coverage_overlaps(r["member_id"], r["procedure_code"], start_dt, end_dt, r["id"]):
            raise err(ERR_DUPLICATE_ACTIVE_AUTH, "Duplicate active authorization.")

    # past deadline (priority 9)
    deadline = a.get("_deadline_dt")
    if deadline is not None and clock.now() > deadline:
        raise err(ERR_PAST_DEADLINE, "Appeal decision past deadline.")

    # rationale required at decision time
    if not decision_rationale:
        raise err(ERR_VALIDATION, "decision_rationale is required.")

    a["decision_rationale"] = decision_rationale
    if decision == "UPHELD":
        a["status"] = "UPHELD"
        touch(a)
    else:  # OVERTURNED — cascade DENIED -> APPROVED
        a["status"] = "OVERTURNED"
        if r is not None and r["status"] == "DENIED":
            apply_approval(r, r["requested_units"])
        touch(a)
    return success(ser_appeal(a), 200)


@app.route("/appeals/<aid>/decide", methods=["POST"])
def decide_appeal(aid):
    return _decide_appeal(aid, {"Payer"}, {1, 2}, "payer")


@app.route("/appeals/<aid>/external-decide", methods=["POST"])
def external_decide_appeal(aid):
    return _decide_appeal(aid, {"ExternalReviewer"}, {3}, "external")


@app.route("/appeals/<aid>/withdraw", methods=["POST"])
def withdraw_appeal(aid):
    role, user_id = auth()
    require_role(role, {"Provider"})
    a = find_or_404(db.appeals, aid)
    r = db.requests.get(a["request_id"])
    if r is not None and r["provider_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Provider does not own appeal's request.")
    if a["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Appeal is not OPEN.")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success(ser_appeal(a), 200)


# ==========================================================================
# Clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = auth()
    require_role(role, {"Provider", "Payer", "ExternalReviewer"})
    body = get_body()
    to_iso = require(body, "to_iso8601")
    dt = parse_iso(to_iso)
    clock.set(dt)
    return success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

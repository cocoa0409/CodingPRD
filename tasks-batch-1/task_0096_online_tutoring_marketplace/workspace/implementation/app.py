"""Online Tutoring Marketplace API — entry point and route registration.

All temporal logic uses the deterministic server clock (db.get_clock()).
Storage is in-memory only and starts empty on every boot (no seeding).
"""
import os

from flask import Flask, request

import db
import serializers as S
import services as svc
from common import (
    stamp_create, touch, parse_iso, require_body,
    req_str, req_int, opt_int, opt_str, opt_bool, req_enum, req_array_of_int,
    parse_pagination, paginate, sorted_by_created,
    round_half_up,
)
from errors import ApiError
import errors as E
from middleware import get_user_context, require_role, require_owner
from response import success, error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_VALIDATION", "resource path not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_VALIDATION", "method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_VALIDATION", f"unexpected error: {err}", 400)


def get_json_body():
    """Parse JSON body; tolerate empty body for no-input endpoints."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError(*E.ERR_VALIDATION, message="malformed JSON body")
    if body is None:
        raise ApiError(*E.ERR_VALIDATION, message="malformed JSON body")
    if not isinstance(body, dict):
        raise ApiError(*E.ERR_VALIDATION, message="request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Existence helpers (typed not-found errors, PRD 2.5)
# ---------------------------------------------------------------------------
def get_or_404(coll, _id, err_spec):
    obj = coll.get(_id)
    if obj is None:
        raise ApiError(*err_spec)
    return obj


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set", methods=["POST"])
def clock_set():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    to_iso = req_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    with db.lock:
        db.set_clock(dt)
    return success({"current_utc": db.now_iso()}, status=200)


# ===========================================================================
# Subjects
# ===========================================================================
SUBJECT_CATEGORIES = {"STEM", "LANGUAGE", "HUMANITIES", "TEST_PREP", "MUSIC"}


@app.route("/subjects", methods=["POST"])
def create_subject():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    code = req_str(body, "code")
    display_name = req_str(body, "display_name")
    category = req_enum(body, "category", SUBJECT_CATEGORIES)
    requires_credential = opt_bool(body, "requires_credential", default=False)
    with db.lock:
        e = {
            "id": db.new_id(),
            "code": code,
            "display_name": display_name,
            "category": category,
            "requires_credential": requires_credential,
            "status": "ACTIVE",
        }
        stamp_create(e)
        db.subjects[e["id"]] = e
        return success(S.subject(e), status=201)


@app.route("/subjects/<sid>", methods=["GET"])
def get_subject(sid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    e = get_or_404(db.subjects, sid, E.ERR_SUBJECT_NOT_FOUND)
    return success(S.subject(e), status=200)


# ===========================================================================
# Commission policies
# ===========================================================================
@app.route("/commission-policies", methods=["POST"])
def create_policy():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    name = req_str(body, "name")
    breakpoints = req_array_of_int(body, "tier_breakpoints_cents")
    rates = req_array_of_int(body, "tier_rates_bps")
    trial_commission_bps = req_int(body, "trial_commission_bps")
    trial_max = opt_int(body, "trial_max_billed_minutes", default=30)
    refund_window = opt_int(body, "refund_window_hours", default=168)
    if len(breakpoints) != len(rates):
        raise ApiError(*E.ERR_VALIDATION, message="tier arrays must be parallel")
    with db.lock:
        e = {
            "id": db.new_id(),
            "name": name,
            "tier_breakpoints_cents": breakpoints,
            "tier_rates_bps": rates,
            "trial_commission_bps": trial_commission_bps,
            "trial_max_billed_minutes": trial_max,
            "refund_window_hours": refund_window,
            "status": "DRAFT",
            "activated_at": None,
        }
        stamp_create(e)
        db.commission_policies[e["id"]] = e
        return success(S.commission_policy(e), status=201)


@app.route("/commission-policies/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin"])
    with db.lock:
        e = get_or_404(db.commission_policies, pid, ("ERR_VALIDATION", 404))
        # Supersede any currently ACTIVE policy (PRD 3.1).
        for p in db.commission_policies.values():
            if p["status"] == "ACTIVE" and p["id"] != pid:
                p["status"] = "SUPERSEDED"
                touch(p)
        e["status"] = "ACTIVE"
        e["activated_at"] = db.now_iso()
        touch(e)
        return success(S.commission_policy(e), status=200)


@app.route("/commission-policies/<pid>", methods=["GET"])
def get_policy(pid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Arbiter"])
    e = get_or_404(db.commission_policies, pid, ("ERR_VALIDATION", 404))
    return success(S.commission_policy(e), status=200)


# ===========================================================================
# Tutors
# ===========================================================================
@app.route("/tutors", methods=["POST"])
def create_tutor():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "Tutor"])
    body = get_json_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    base_rate = req_int(body, "base_hourly_rate_cents")
    if base_rate < 1000 or base_rate > 50000:
        raise ApiError(*E.ERR_VALIDATION, message="base_hourly_rate_cents out of range [1000,50000]")
    with db.lock:
        e = {
            "id": db.new_id(),
            "email": email,
            "full_name": full_name,
            "base_hourly_rate_cents": base_rate,
            "verification_status": "UNVERIFIED",
            "lifetime_net_earnings_cents": 0,
            "payout_balance_cents": 0,
            "clawback_owed_cents": 0,
            "reliability_score": 0.0,
            "active_subject_count": 0,
            "is_payable": False,
        }
        stamp_create(e)
        db.tutors[e["id"]] = e
        return success(S.tutor(e), status=201)


@app.route("/tutors/<tid>", methods=["GET"])
def get_tutor(tid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    e = get_or_404(db.tutors, tid, E.ERR_TUTOR_NOT_FOUND)
    return success(S.tutor(e), status=200)


def _revoke_approved_tags(tutor_id, credential_gated_only=False):
    """Cascade: revoke APPROVED tags of a tutor. Each touched tag bumps version."""
    for tag in db.subject_tags.values():
        if tag["tutor_id"] != tutor_id or tag["status"] != "APPROVED":
            continue
        if credential_gated_only:
            subj = db.subjects.get(tag["subject_id"])
            if not (subj and subj.get("requires_credential")):
                continue
        tag["status"] = "REVOKED"
        touch(tag)


@app.route("/tutors/<tid>/suspend", methods=["POST"])
def suspend_tutor(tid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.tutors, tid, E.ERR_TUTOR_NOT_FOUND)
        if e["verification_status"] != "VERIFIED":
            raise ApiError(*E.ERR_INVALID_STATE, message="tutor is not VERIFIED")
        e["verification_status"] = "SUSPENDED"
        _revoke_approved_tags(tid, credential_gated_only=False)
        svc.recompute_tutor_derived(e)
        touch(e)
        return success(S.tutor(e), status=200)


@app.route("/tutors/<tid>/reinstate", methods=["POST"])
def reinstate_tutor(tid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.tutors, tid, E.ERR_TUTOR_NOT_FOUND)
        has_verified_cred = any(
            c["tutor_id"] == tid and c["status"] == "VERIFIED"
            for c in db.credentials.values()
        )
        if e["verification_status"] != "SUSPENDED" or not has_verified_cred:
            raise ApiError(*E.ERR_TUTOR_NOT_REINSTATABLE,
                           message="reinstate requires a SUSPENDED tutor with >=1 VERIFIED credential")
        e["verification_status"] = "VERIFIED"
        svc.recompute_tutor_derived(e)
        touch(e)
        return success(S.tutor(e), status=200)


# ===========================================================================
# Credentials
# ===========================================================================
CREDENTIAL_KINDS = {"DEGREE", "CERTIFICATION", "TEACHING_LICENSE", "TRANSCRIPT"}


@app.route("/credentials", methods=["POST"])
def create_credential():
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    body = get_json_body()
    tutor_id = req_str(body, "tutor_id")
    subject_id = req_str(body, "subject_id")
    kind = req_enum(body, "kind", CREDENTIAL_KINDS)
    document_ref = req_str(body, "document_ref")
    with db.lock:
        # Ownership: tutor submits own credential (PRD 2.1).
        require_owner(uid, role, "Tutor", tutor_id)
        get_or_404(db.tutors, tutor_id, E.ERR_TUTOR_NOT_FOUND)
        get_or_404(db.subjects, subject_id, E.ERR_SUBJECT_NOT_FOUND)
        e = {
            "id": db.new_id(),
            "tutor_id": tutor_id,
            "subject_id": subject_id,
            "kind": kind,
            "document_ref": document_ref,
            "status": "SUBMITTED",
            "reviewed_by": None,
            "rejection_reason": None,
        }
        stamp_create(e)
        db.credentials[e["id"]] = e
        return success(S.credential(e), status=201)


@app.route("/credentials", methods=["GET"])
def list_credentials():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor"])
    limit, offset = parse_pagination(request.args)
    tutor_id = request.args.get("tutor_id")
    subject_id = request.args.get("subject_id")
    status = request.args.get("status")
    rows = [c for c in db.credentials.values()
            if (tutor_id is None or c["tutor_id"] == tutor_id)
            and (subject_id is None or c["subject_id"] == subject_id)
            and (status is None or c["status"] == status)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.credential(c) for c in page], status=200, pagination=meta)


@app.route("/credentials/<cid>", methods=["GET"])
def get_credential(cid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor"])
    e = get_or_404(db.credentials, cid, E.ERR_CREDENTIAL_NOT_FOUND)
    return success(S.credential(e), status=200)


@app.route("/credentials/<cid>/start-review", methods=["POST"])
def credential_start_review(cid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.credentials, cid, E.ERR_CREDENTIAL_NOT_FOUND)
        if e["status"] != "SUBMITTED":
            raise ApiError(*E.ERR_INVALID_STATE, message="credential is not SUBMITTED")
        e["status"] = "UNDER_REVIEW"
        e["reviewed_by"] = uid
        touch(e)
        tutor = db.tutors.get(e["tutor_id"])
        if tutor and tutor["verification_status"] == "UNVERIFIED":
            tutor["verification_status"] = "PENDING_REVIEW"
            svc.recompute_tutor_derived(tutor)
            touch(tutor)
        return success(S.credential(e), status=200)


@app.route("/credentials/<cid>/verify", methods=["POST"])
def credential_verify(cid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.credentials, cid, E.ERR_CREDENTIAL_NOT_FOUND)
        if e["status"] != "UNDER_REVIEW":
            raise ApiError(*E.ERR_INVALID_STATE, message="credential is not UNDER_REVIEW")
        e["status"] = "VERIFIED"
        touch(e)
        tutor = db.tutors.get(e["tutor_id"])
        if tutor:
            has_verified = any(
                c["tutor_id"] == tutor["id"] and c["status"] == "VERIFIED"
                for c in db.credentials.values()
            )
            if tutor["verification_status"] == "PENDING_REVIEW" and has_verified:
                tutor["verification_status"] = "VERIFIED"
                svc.recompute_tutor_derived(tutor)
                touch(tutor)
        return success(S.credential(e), status=200)


@app.route("/credentials/<cid>/reject", methods=["POST"])
def credential_reject(cid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    body = get_json_body()
    rejection_reason = req_str(body, "rejection_reason")
    with db.lock:
        e = get_or_404(db.credentials, cid, E.ERR_CREDENTIAL_NOT_FOUND)
        if e["status"] != "UNDER_REVIEW":
            raise ApiError(*E.ERR_INVALID_STATE, message="credential is not UNDER_REVIEW")
        e["status"] = "REJECTED"
        e["rejection_reason"] = rejection_reason
        touch(e)
        tutor = db.tutors.get(e["tutor_id"])
        if tutor and tutor["verification_status"] == "PENDING_REVIEW":
            has_verified = any(
                c["tutor_id"] == tutor["id"] and c["status"] == "VERIFIED"
                for c in db.credentials.values()
            )
            has_under_review = any(
                c["tutor_id"] == tutor["id"] and c["status"] == "UNDER_REVIEW"
                for c in db.credentials.values()
            )
            if not has_verified and not has_under_review:
                tutor["verification_status"] = "REJECTED"
                svc.recompute_tutor_derived(tutor)
                touch(tutor)
        return success(S.credential(e), status=200)


@app.route("/credentials/<cid>/expire", methods=["POST"])
def credential_expire(cid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.credentials, cid, E.ERR_CREDENTIAL_NOT_FOUND)
        if e["status"] != "VERIFIED":
            raise ApiError(*E.ERR_INVALID_STATE, message="credential is not VERIFIED")
        e["status"] = "EXPIRED"
        touch(e)
        tutor = db.tutors.get(e["tutor_id"])
        if tutor:
            has_verified = any(
                c["tutor_id"] == tutor["id"] and c["status"] == "VERIFIED"
                for c in db.credentials.values()
            )
            if not has_verified and tutor["verification_status"] == "VERIFIED":
                tutor["verification_status"] = "SUSPENDED"
                _revoke_approved_tags(tutor["id"], credential_gated_only=True)
                svc.recompute_tutor_derived(tutor)
                touch(tutor)
        return success(S.credential(e), status=200)


# ===========================================================================
# Tutor subject tags
# ===========================================================================
@app.route("/subject-tags", methods=["POST"])
def create_subject_tag():
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    body = get_json_body()
    tutor_id = req_str(body, "tutor_id")
    subject_id = req_str(body, "subject_id")
    subject_rate = opt_int(body, "subject_rate_cents", default=None)
    with db.lock:
        require_owner(uid, role, "Tutor", tutor_id)
        get_or_404(db.tutors, tutor_id, E.ERR_TUTOR_NOT_FOUND)
        get_or_404(db.subjects, subject_id, E.ERR_SUBJECT_NOT_FOUND)
        e = {
            "id": db.new_id(),
            "tutor_id": tutor_id,
            "subject_id": subject_id,
            "subject_rate_cents": subject_rate,
            "status": "PROPOSED",
            "effective_hourly_rate_cents": None,
        }
        stamp_create(e)
        db.subject_tags[e["id"]] = e
        return success(S.subject_tag(e), status=201)


@app.route("/subject-tags", methods=["GET"])
def list_subject_tags():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian"])
    limit, offset = parse_pagination(request.args)
    tutor_id = request.args.get("tutor_id")
    subject_id = request.args.get("subject_id")
    status = request.args.get("status")
    rows = [t for t in db.subject_tags.values()
            if (tutor_id is None or t["tutor_id"] == tutor_id)
            and (subject_id is None or t["subject_id"] == subject_id)
            and (status is None or t["status"] == status)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.subject_tag(t) for t in page], status=200, pagination=meta)


@app.route("/subject-tags/<tagid>", methods=["GET"])
def get_subject_tag(tagid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian"])
    e = get_or_404(db.subject_tags, tagid, E.ERR_SUBJECT_TAG_NOT_FOUND)
    return success(S.subject_tag(e), status=200)


@app.route("/subject-tags/<tagid>/approve", methods=["POST"])
def approve_subject_tag(tagid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.subject_tags, tagid, E.ERR_SUBJECT_TAG_NOT_FOUND)
        # State applicability first (PRD 3.3 / 4).
        if e["status"] != "PROPOSED":
            raise ApiError(*E.ERR_INVALID_STATE, message="tag is not PROPOSED")
        tutor = db.tutors.get(e["tutor_id"])
        subject = db.subjects.get(e["subject_id"])
        # Tutor must be VERIFIED (PRD 3.3) -> ERR_TUTOR_NOT_VERIFIED.
        if not tutor or tutor["verification_status"] != "VERIFIED":
            raise ApiError(*E.ERR_TUTOR_NOT_VERIFIED, message="owning tutor is not VERIFIED")
        # Credential gating (PRD 3.3 / validation priority 8).
        if subject and subject.get("requires_credential"):
            has_cred = any(
                c["tutor_id"] == e["tutor_id"] and c["subject_id"] == e["subject_id"]
                and c["status"] == "VERIFIED"
                for c in db.credentials.values()
            )
            if not has_cred:
                raise ApiError(*E.ERR_SUBJECT_REQUIRES_CREDENTIAL,
                               message="subject requires a VERIFIED credential")
        e["status"] = "APPROVED"
        if e["subject_rate_cents"] is not None:
            e["effective_hourly_rate_cents"] = e["subject_rate_cents"]
        else:
            e["effective_hourly_rate_cents"] = tutor["base_hourly_rate_cents"]
        touch(e)
        svc.recompute_tutor_derived(tutor)
        touch(tutor)
        return success(S.subject_tag(e), status=200)


@app.route("/subject-tags/<tagid>/revoke", methods=["POST"])
def revoke_subject_tag(tagid):
    uid, role = get_user_context()
    require_role(role, ["TrustOfficer"])
    with db.lock:
        e = get_or_404(db.subject_tags, tagid, E.ERR_SUBJECT_TAG_NOT_FOUND)
        if e["status"] not in ("PROPOSED", "APPROVED"):
            raise ApiError(*E.ERR_INVALID_STATE, message="tag is not in a revocable state")
        was_approved = e["status"] == "APPROVED"
        e["status"] = "REVOKED"
        touch(e)
        if was_approved:
            tutor = db.tutors.get(e["tutor_id"])
            if tutor:
                svc.recompute_tutor_derived(tutor)
                touch(tutor)
        return success(S.subject_tag(e), status=200)


# ===========================================================================
# Parent accounts
# ===========================================================================
@app.route("/parent-accounts", methods=["POST"])
def create_parent_account():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "ParentGuardian"])
    body = get_json_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    with db.lock:
        e = {
            "id": db.new_id(),
            "email": email,
            "full_name": full_name,
            "wallet_balance_cents": 0,
            "held_balance_cents": 0,
            "available_balance_cents": 0,
            "child_count": 0,
            "status": "ACTIVE",
        }
        stamp_create(e)
        db.parent_accounts[e["id"]] = e
        return success(S.parent_account(e), status=201)


@app.route("/parent-accounts/<pid>", methods=["GET"])
def get_parent_account(pid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "ParentGuardian", "Arbiter"])
    e = get_or_404(db.parent_accounts, pid, E.ERR_PARENT_NOT_FOUND)
    return success(S.parent_account(e), status=200)


@app.route("/parent-accounts/<pid>/deposit", methods=["POST"])
def deposit(pid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "ParentGuardian"])
    body = get_json_body()
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise ApiError(*E.ERR_VALIDATION, message="amount_cents must be positive")
    with db.lock:
        require_owner(uid, role, "ParentGuardian", pid)
        e = get_or_404(db.parent_accounts, pid, E.ERR_PARENT_NOT_FOUND)
        e["wallet_balance_cents"] += amount
        svc.recompute_parent_balances(e)
        touch(e)
        return success(S.parent_account(e), status=200)


@app.route("/parent-accounts/<pid>/students", methods=["POST"])
def add_student(pid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    body = get_json_body()
    display_name = req_str(body, "display_name")
    grade_level = req_int(body, "grade_level")
    if grade_level < 1 or grade_level > 13:
        raise ApiError(*E.ERR_VALIDATION, message="grade_level out of range [1,13]")
    with db.lock:
        require_owner(uid, role, "ParentGuardian", pid)
        parent = get_or_404(db.parent_accounts, pid, E.ERR_PARENT_NOT_FOUND)
        e = {
            "id": db.new_id(),
            "parent_account_id": pid,
            "display_name": display_name,
            "grade_level": grade_level,
            "status": "ACTIVE",
        }
        stamp_create(e)
        db.students[e["id"]] = e
        svc.recompute_parent_balances(parent)
        touch(parent)
        return success(S.student(e), status=201)


@app.route("/parent-accounts/<pid>/students", methods=["GET"])
def list_students(pid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "ParentGuardian"])
    get_or_404(db.parent_accounts, pid, E.ERR_PARENT_NOT_FOUND)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [s for s in db.students.values()
            if s["parent_account_id"] == pid
            and (status is None or s["status"] == status)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.student(s) for s in page], status=200, pagination=meta)


@app.route("/students/<sid>/archive", methods=["POST"])
def archive_student(sid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    with db.lock:
        e = get_or_404(db.students, sid, E.ERR_STUDENT_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] != "ACTIVE":
            raise ApiError(*E.ERR_INVALID_STATE, message="student is not ACTIVE")
        e["status"] = "ARCHIVED"
        touch(e)
        parent = db.parent_accounts.get(e["parent_account_id"])
        if parent:
            svc.recompute_parent_balances(parent)
            touch(parent)
        return success(S.student(e), status=200)


# ===========================================================================
# Bookings
# ===========================================================================
def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    # Half-open [start, end): overlap when a_start < b_end and b_start < a_end.
    return a_start < b_end and b_start < a_end


def _student_conflict(existing_start, existing_end, new_start, new_end, gap_minutes):
    # closed-with-buffer: reject when new_start < existing_end + gap AND
    # existing_start < new_end + gap.
    from datetime import timedelta
    gap = timedelta(minutes=gap_minutes)
    return new_start < existing_end + gap and existing_start < new_end + gap


def _check_tutor_conflict(tutor_id, new_start, new_minutes, exclude_booking_id):
    from datetime import timedelta
    new_end = new_start + timedelta(minutes=new_minutes)
    for b in db.bookings.values():
        if b["id"] == exclude_booking_id:
            continue
        if b["tutor_id"] != tutor_id:
            continue
        if b["status"] == "CANCELLED":
            continue
        b_start = parse_iso(b["scheduled_start"])
        b_end = b_start + timedelta(minutes=b["planned_minutes"])
        if _intervals_overlap_halfopen(new_start, new_end, b_start, b_end):
            raise ApiError(*E.ERR_TUTOR_TIME_CONFLICT, message="tutor calendar conflict")


def _check_student_conflict(student_id, new_start, new_minutes, exclude_booking_id):
    from datetime import timedelta
    new_end = new_start + timedelta(minutes=new_minutes)
    for b in db.bookings.values():
        if b["id"] == exclude_booking_id:
            continue
        if b["student_id"] != student_id:
            continue
        if b["status"] == "CANCELLED":
            continue
        b_start = parse_iso(b["scheduled_start"])
        b_end = b_start + timedelta(minutes=b["planned_minutes"])
        if _student_conflict(b_start, b_end, new_start, new_end, svc.STUDENT_GAP_MINUTES):
            raise ApiError(*E.ERR_STUDENT_TIME_CONFLICT, message="student calendar conflict")


@app.route("/bookings", methods=["POST"])
def create_booking():
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    body = get_json_body()
    parent_account_id = req_str(body, "parent_account_id")
    student_id = req_str(body, "student_id")
    tutor_id = req_str(body, "tutor_id")
    subject_id = req_str(body, "subject_id")
    scheduled_start_raw = req_str(body, "scheduled_start")
    planned_minutes = req_int(body, "planned_minutes")
    scheduled_start = parse_iso(scheduled_start_raw)
    with db.lock:
        # Ownership (priority 3): parent books on own account.
        require_owner(uid, role, "ParentGuardian", parent_account_id)
        # Body FK existence (priority 5).
        parent = get_or_404(db.parent_accounts, parent_account_id, E.ERR_PARENT_NOT_FOUND)
        student = get_or_404(db.students, student_id, E.ERR_STUDENT_NOT_FOUND)
        tutor = get_or_404(db.tutors, tutor_id, E.ERR_TUTOR_NOT_FOUND)
        subject = get_or_404(db.subjects, subject_id, E.ERR_SUBJECT_NOT_FOUND)

        # Business rule 9: tutor must teach this subject (APPROVED tag) and be VERIFIED.
        approved_tag = None
        for t in db.subject_tags.values():
            if (t["tutor_id"] == tutor_id and t["subject_id"] == subject_id
                    and t["status"] == "APPROVED"):
                approved_tag = t
                break
        if approved_tag is None or tutor["verification_status"] != "VERIFIED":
            raise ApiError(*E.ERR_TUTOR_SUBJECT_NOT_APPROVED,
                           message="tutor does not teach this subject or is not VERIFIED")

        # Business rule 10: scheduled_start strictly future; planned_minutes in [15,240].
        if scheduled_start <= db.get_clock() or planned_minutes < 15 or planned_minutes > 240:
            raise ApiError(*E.ERR_BOOKING_TIME_INVALID,
                           message="scheduled_start must be in the future and planned_minutes in [15,240]")

        # Business rule 11: tutor calendar overlap (half-open, zero buffer).
        _check_tutor_conflict(tutor_id, scheduled_start, planned_minutes, None)
        # Business rule 12: student calendar (closed, 15-min buffer).
        _check_student_conflict(student_id, scheduled_start, planned_minutes, None)

        # Computed fields.
        # is_trial: first non-cancelled booking for (student_id, tutor_id).
        is_trial = not any(
            b["student_id"] == student_id and b["tutor_id"] == tutor_id
            and b["status"] != "CANCELLED"
            for b in db.bookings.values()
        )
        quoted_rate = approved_tag["effective_hourly_rate_cents"]
        policy = svc.active_policy()
        trial_max = policy["trial_max_billed_minutes"] if policy else 30
        hold = svc.compute_hold_amount(quoted_rate, planned_minutes, is_trial, trial_max)

        # Business rule 17: available balance must cover the hold.
        if parent["available_balance_cents"] < hold:
            raise ApiError(*E.ERR_INSUFFICIENT_WALLET_BALANCE,
                           message="insufficient available wallet balance for hold")

        e = {
            "id": db.new_id(),
            "parent_account_id": parent_account_id,
            "student_id": student_id,
            "tutor_id": tutor_id,
            "subject_id": subject_id,
            "scheduled_start": db.iso_millis(scheduled_start),
            "planned_minutes": planned_minutes,
            "is_trial": is_trial,
            "quoted_rate_cents": quoted_rate,
            "hold_amount_cents": hold,
            "status": "SCHEDULED",
            "reschedule_count": 0,
        }
        stamp_create(e)
        db.bookings[e["id"]] = e
        svc.recompute_parent_balances(parent)
        touch(parent)
        return success(S.booking(e), status=201)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    limit, offset = parse_pagination(request.args)
    f_parent = request.args.get("parent_account_id")
    f_student = request.args.get("student_id")
    f_tutor = request.args.get("tutor_id")
    f_subject = request.args.get("subject_id")
    f_status = request.args.get("status")
    rows = [b for b in db.bookings.values()
            if (f_parent is None or b["parent_account_id"] == f_parent)
            and (f_student is None or b["student_id"] == f_student)
            and (f_tutor is None or b["tutor_id"] == f_tutor)
            and (f_subject is None or b["subject_id"] == f_subject)
            and (f_status is None or b["status"] == f_status)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.booking(b) for b in page], status=200, pagination=meta)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    e = get_or_404(db.bookings, bid, E.ERR_BOOKING_NOT_FOUND)
    return success(S.booking(e), status=200)


@app.route("/bookings/<bid>/request-reschedule", methods=["POST"])
def request_reschedule(bid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    body = get_json_body()
    req_str(body, "proposed_start")  # required field
    with db.lock:
        e = get_or_404(db.bookings, bid, E.ERR_BOOKING_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] != "SCHEDULED":
            raise ApiError(*E.ERR_INVALID_STATE, message="booking is not SCHEDULED")
        # reschedule_count cap (priority 16.5).
        if e["reschedule_count"] >= 3:
            raise ApiError(*E.ERR_RESCHEDULE_LIMIT_REACHED, message="reschedule limit reached")
        # current clock < scheduled_start.
        if db.get_clock() >= parse_iso(e["scheduled_start"]):
            raise ApiError(*E.ERR_INVALID_STATE, message="lesson start has passed")
        e["status"] = "RESCHEDULE_REQUESTED"
        e["reschedule_count"] += 1
        touch(e)
        return success(S.booking(e), status=200)


@app.route("/bookings/<bid>/confirm-reschedule", methods=["POST"])
def confirm_reschedule(bid):
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    body = get_json_body()
    proposed_start_raw = req_str(body, "proposed_start")
    proposed_start = parse_iso(proposed_start_raw)
    with db.lock:
        e = get_or_404(db.bookings, bid, E.ERR_BOOKING_NOT_FOUND)
        require_owner(uid, role, "Tutor", e["tutor_id"])
        if e["status"] != "RESCHEDULE_REQUESTED":
            raise ApiError(*E.ERR_INVALID_STATE, message="booking is not RESCHEDULE_REQUESTED")
        # Re-apply calendar conflict checks at new time (PRD 3.6), excluding self.
        _check_tutor_conflict(e["tutor_id"], proposed_start, e["planned_minutes"], e["id"])
        _check_student_conflict(e["student_id"], proposed_start, e["planned_minutes"], e["id"])
        e["status"] = "SCHEDULED"
        e["scheduled_start"] = db.iso_millis(proposed_start)
        policy = svc.active_policy()
        trial_max = policy["trial_max_billed_minutes"] if policy else 30
        e["hold_amount_cents"] = svc.compute_hold_amount(
            e["quoted_rate_cents"], e["planned_minutes"], e["is_trial"], trial_max)
        touch(e)
        parent = db.parent_accounts.get(e["parent_account_id"])
        if parent:
            svc.recompute_parent_balances(parent)
            touch(parent)
        return success(S.booking(e), status=200)


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    with db.lock:
        e = get_or_404(db.bookings, bid, E.ERR_BOOKING_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] not in ("SCHEDULED", "RESCHEDULE_REQUESTED"):
            raise ApiError(*E.ERR_INVALID_STATE, message="booking is not cancellable")
        if db.get_clock() >= parse_iso(e["scheduled_start"]):
            raise ApiError(*E.ERR_INVALID_STATE, message="lesson start has passed")
        e["status"] = "CANCELLED"
        touch(e)
        parent = db.parent_accounts.get(e["parent_account_id"])
        if parent:
            # held_balance drops because cancelled bookings are excluded; no wallet debit.
            svc.recompute_parent_balances(parent)
            touch(parent)
        return success(S.booking(e), status=200)


@app.route("/bookings/<bid>/mark-no-show", methods=["POST"])
def mark_no_show(bid):
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    with db.lock:
        e = get_or_404(db.bookings, bid, E.ERR_BOOKING_NOT_FOUND)
        require_owner(uid, role, "Tutor", e["tutor_id"])
        if e["status"] != "SCHEDULED":
            raise ApiError(*E.ERR_INVALID_STATE, message="booking is not SCHEDULED")
        if db.get_clock() < parse_iso(e["scheduled_start"]):
            raise ApiError(*E.ERR_INVALID_STATE, message="lesson time has not arrived")
        e["status"] = "NO_SHOW"
        touch(e)
        parent = db.parent_accounts.get(e["parent_account_id"])
        if parent:
            svc.recompute_parent_balances(parent)
            touch(parent)
        tutor = db.tutors.get(e["tutor_id"])
        if tutor:
            svc.recompute_tutor_lifetime_and_reliability(tutor)
            svc.recompute_tutor_derived(tutor)
            touch(tutor)
        return success(S.booking(e), status=200)


@app.route("/bookings/<bid>/deliver", methods=["POST"])
def deliver_booking(bid):
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    body = get_json_body()
    actual_minutes = req_int(body, "actual_minutes")
    with db.lock:
        e = get_or_404(db.bookings, bid, E.ERR_BOOKING_NOT_FOUND)
        require_owner(uid, role, "Tutor", e["tutor_id"])
        if e["status"] != "SCHEDULED":
            raise ApiError(*E.ERR_INVALID_STATE, message="booking is not SCHEDULED")
        if db.get_clock() < parse_iso(e["scheduled_start"]):
            raise ApiError(*E.ERR_INVALID_STATE, message="lesson time has not arrived")
        tutor = db.tutors.get(e["tutor_id"])
        if not tutor or tutor["verification_status"] != "VERIFIED":
            raise ApiError(*E.ERR_TUTOR_NOT_VERIFIED, message="tutor is not VERIFIED")
        if actual_minutes < 1 or actual_minutes > 480:
            raise ApiError(*E.ERR_VALIDATION, message="actual_minutes out of range [1,480]")
        policy = svc.active_policy()
        trial_max = policy["trial_max_billed_minutes"] if policy else 30
        billed = svc.compute_billed_minutes(actual_minutes, e["planned_minutes"],
                                            e["is_trial"], trial_max)
        e["status"] = "DELIVERED"
        touch(e)
        sess = {
            "id": db.new_id(),
            "booking_id": e["id"],
            "tutor_id": e["tutor_id"],
            "actual_minutes": actual_minutes,
            "billed_minutes": billed,
            "settlement_status": "DELIVERED",
            "delivery_status": "REPORTED",
        }
        stamp_create(sess)
        db.sessions[sess["id"]] = sess
        # held_balance: booking still DELIVERED -> still held (no change), but
        # recompute to keep available_balance consistent.
        parent = db.parent_accounts.get(e["parent_account_id"])
        if parent:
            svc.recompute_parent_balances(parent)
            touch(parent)
        return success(S.session(sess), status=201)


# ===========================================================================
# Sessions
# ===========================================================================
@app.route("/sessions", methods=["GET"])
def list_sessions():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    limit, offset = parse_pagination(request.args)
    f_booking = request.args.get("booking_id")
    f_tutor = request.args.get("tutor_id")
    f_settlement = request.args.get("settlement_status")
    f_delivery = request.args.get("delivery_status")
    rows = [s for s in db.sessions.values()
            if (f_booking is None or s["booking_id"] == f_booking)
            and (f_tutor is None or s["tutor_id"] == f_tutor)
            and (f_settlement is None or s["settlement_status"] == f_settlement)
            and (f_delivery is None or s["delivery_status"] == f_delivery)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.session(s) for s in page], status=200, pagination=meta)


@app.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    e = get_or_404(db.sessions, sid, E.ERR_SESSION_NOT_FOUND)
    return success(S.session(e), status=200)


@app.route("/sessions/<sid>/confirm", methods=["POST"])
def confirm_session(sid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    with db.lock:
        e = get_or_404(db.sessions, sid, E.ERR_SESSION_NOT_FOUND)
        booking = db.bookings.get(e["booking_id"])
        # Ownership: parent owns the booking (PRD 2.1).
        if booking:
            require_owner(uid, role, "ParentGuardian", booking["parent_account_id"])
        if e["delivery_status"] != "REPORTED":
            raise ApiError(*E.ERR_INVALID_STATE, message="session is not REPORTED")

        tutor = db.tutors.get(e["tutor_id"])
        parent = db.parent_accounts.get(booking["parent_account_id"]) if booking else None
        policy = svc.active_policy()

        # --- Settlement calculation (PRD 3.8) in fixed order ---
        quoted_rate = booking["quoted_rate_cents"]
        billed = e["billed_minutes"]
        gross = round_half_up(quoted_rate * billed, 60)

        if booking["is_trial"]:
            commission_bps = policy["trial_commission_bps"] if policy else 0
        else:
            lifetime_before = tutor["lifetime_net_earnings_cents"] if tutor else 0
            if policy:
                commission_bps = svc.select_commission_bps_standard(policy, lifetime_before)
            else:
                commission_bps = 0
        commission = round_half_up(gross * commission_bps, 10000)
        tutor_net = gross - commission

        # Transition session and booking.
        e["delivery_status"] = "CONFIRMED"
        e["settlement_status"] = "SETTLED"
        touch(e)
        if booking:
            booking["status"] = "SETTLED"
            touch(booking)

        settlement = {
            "id": db.new_id(),
            "session_id": e["id"],
            "tutor_id": e["tutor_id"],
            "gross_amount_cents": gross,
            "commission_bps": commission_bps,
            "commission_cents": commission,
            "tutor_net_cents": tutor_net,
            "refunded_cents": 0,
            "status": "SETTLED",
        }
        stamp_create(settlement)
        db.settlements[settlement["id"]] = settlement

        # --- Ledger movement (PRD 3.7): release hold, debit wallet by gross,
        # credit tutor payout by net. ---
        if parent:
            parent["wallet_balance_cents"] -= gross
            svc.recompute_parent_balances(parent)
            touch(parent)
        if tutor:
            tutor["payout_balance_cents"] += tutor_net
            svc.recompute_tutor_lifetime_and_reliability(tutor)
            svc.recompute_tutor_derived(tutor)
            touch(tutor)
        return success(S.session(e), status=200)


@app.route("/sessions/<sid>/dispute", methods=["POST"])
def dispute_session(sid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    with db.lock:
        e = get_or_404(db.sessions, sid, E.ERR_SESSION_NOT_FOUND)
        booking = db.bookings.get(e["booking_id"])
        if booking:
            require_owner(uid, role, "ParentGuardian", booking["parent_account_id"])
        if e["delivery_status"] != "REPORTED":
            raise ApiError(*E.ERR_INVALID_STATE, message="session is not REPORTED")
        e["delivery_status"] = "DISPUTED"
        # settlement_status stays DELIVERED.
        touch(e)
        return success(S.session(e), status=200)


# ===========================================================================
# Settlements
# ===========================================================================
@app.route("/settlements", methods=["GET"])
def list_settlements():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "Arbiter"])
    limit, offset = parse_pagination(request.args)
    f_session = request.args.get("session_id")
    f_tutor = request.args.get("tutor_id")
    f_status = request.args.get("status")
    rows = [s for s in db.settlements.values()
            if (f_session is None or s["session_id"] == f_session)
            and (f_tutor is None or s["tutor_id"] == f_tutor)
            and (f_status is None or s["status"] == f_status)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.settlement(s) for s in page], status=200, pagination=meta)


@app.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "Arbiter"])
    e = get_or_404(db.settlements, sid, E.ERR_SETTLEMENT_NOT_FOUND)
    return success(S.settlement(e), status=200)


# ===========================================================================
# Refund cases
# ===========================================================================
def _settlement_for_session(session_id):
    for s in db.settlements.values():
        if s["session_id"] == session_id:
            return s
    return None


def _apply_settlement_reversal(refund_case):
    """Settlement reversal waterfall (PRD 3.9.1), strictly pinned order."""
    g = refund_case["granted_amount_cents"]
    session = db.sessions.get(refund_case["session_id"])
    settlement = _settlement_for_session(refund_case["session_id"])
    parent = db.parent_accounts.get(refund_case["parent_account_id"])
    tutor = db.tutors.get(refund_case["tutor_id"])

    # 1. parent credit = g
    parent_credit = g
    # 2. tutor debit = min(g, payout_balance) — read BEFORE mutation
    payout_before = tutor["payout_balance_cents"] if tutor else 0
    tutor_debit = min(g, payout_before)
    # 3. clawback = g - tutor_debit
    clawback = g - tutor_debit
    # 4. apply
    if parent:
        parent["wallet_balance_cents"] += parent_credit
    if tutor:
        tutor["payout_balance_cents"] -= tutor_debit
        tutor["clawback_owed_cents"] += clawback
    # 5. settlement refunded_cents and status
    if settlement:
        settlement["refunded_cents"] += g
        if settlement["refunded_cents"] >= settlement["gross_amount_cents"]:
            settlement["status"] = "REVERSED"
        else:
            settlement["status"] = "PARTIALLY_REVERSED"
        touch(settlement)
    # session settlement_status
    if session and settlement:
        if settlement["refunded_cents"] >= settlement["gross_amount_cents"]:
            session["settlement_status"] = "REFUNDED"
        else:
            session["settlement_status"] = "PARTIALLY_REFUNDED"
        touch(session)
    # Recompute derived balances/derived flags.
    if parent:
        svc.recompute_parent_balances(parent)
        touch(parent)
    if tutor:
        svc.recompute_tutor_lifetime_and_reliability(tutor)
        svc.recompute_tutor_derived(tutor)
        touch(tutor)


@app.route("/refund-cases", methods=["POST"])
def create_refund_case():
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    body = get_json_body()
    session_id = req_str(body, "session_id")
    claimed_amount = req_int(body, "claimed_amount_cents")
    supersedes = opt_str(body, "supersedes_case_id", default=None)
    with db.lock:
        session = get_or_404(db.sessions, session_id, E.ERR_SESSION_NOT_FOUND)
        if supersedes is not None:
            get_or_404(db.refund_cases, supersedes, E.ERR_REFUND_CASE_NOT_FOUND)
        booking = db.bookings.get(session["booking_id"])
        parent_account_id = booking["parent_account_id"] if booking else None
        # Ownership: claimant parent owns the session's booking.
        if parent_account_id is not None:
            require_owner(uid, role, "ParentGuardian", parent_account_id)

        settlement = _settlement_for_session(session_id)

        # Refund window (priority 13): clock <= session end + refund_window_hours
        # AND settlement_status in {SETTLED, DISPUTED}.
        if session["settlement_status"] not in ("SETTLED", "DISPUTED"):
            raise ApiError(*E.ERR_REFUND_WINDOW_CLOSED,
                           message="session is not in a refund-eligible state")
        policy = svc.active_policy()
        refund_window_hours = policy["refund_window_hours"] if policy else 168
        from datetime import timedelta
        booking_start = parse_iso(booking["scheduled_start"]) if booking else None
        # Session end = scheduled_start + planned_minutes (the lesson window).
        session_end = booking_start + timedelta(minutes=booking["planned_minutes"]) if booking else db.get_clock()
        window_close = session_end + timedelta(hours=refund_window_hours)
        if db.get_clock() > window_close:
            raise ApiError(*E.ERR_REFUND_WINDOW_CLOSED, message="refund window has closed")

        # claimed_amount in (0, gross_amount_cents] (priority 16).
        gross = settlement["gross_amount_cents"] if settlement else 0
        if claimed_amount <= 0 or claimed_amount > gross:
            raise ApiError(*E.ERR_AMOUNT_OUT_OF_RANGE,
                           message="claimed_amount_cents outside (0, gross_amount_cents]")

        e = {
            "id": db.new_id(),
            "session_id": session_id,
            "parent_account_id": parent_account_id,
            "tutor_id": session["tutor_id"],
            "supersedes_case_id": supersedes,
            "claimed_amount_cents": claimed_amount,
            "parent_offer_cents": claimed_amount,
            "tutor_offer_cents": None,
            "round_count": 0,
            "granted_amount_cents": 0,
            "status": "PARENT_PROPOSED",
            "_resolved_via_arbitration": False,
        }
        stamp_create(e)
        db.refund_cases[e["id"]] = e
        # Session settlement_status -> REFUND_OPEN.
        session["settlement_status"] = "REFUND_OPEN"
        touch(session)
        return success(S.refund_case(e), status=201)


@app.route("/refund-cases", methods=["GET"])
def list_refund_cases():
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    limit, offset = parse_pagination(request.args)
    f_session = request.args.get("session_id")
    f_parent = request.args.get("parent_account_id")
    f_tutor = request.args.get("tutor_id")
    f_supersedes = request.args.get("supersedes_case_id")
    f_status = request.args.get("status")
    rows = [r for r in db.refund_cases.values()
            if (f_session is None or r["session_id"] == f_session)
            and (f_parent is None or r["parent_account_id"] == f_parent)
            and (f_tutor is None or r["tutor_id"] == f_tutor)
            and (f_supersedes is None or r["supersedes_case_id"] == f_supersedes)
            and (f_status is None or r["status"] == f_status)]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([S.refund_case(r) for r in page], status=200, pagination=meta)


@app.route("/refund-cases/<rid>", methods=["GET"])
def get_refund_case(rid):
    uid, role = get_user_context()
    require_role(role, ["PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"])
    e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
    return success(S.refund_case(e), status=200)


def _check_occ(refund_case, body):
    """OCC check (priority 7) for the four version-guarded refund operations."""
    expected = req_int(body, "expected_refund_case_version")
    if expected != refund_case["version"]:
        raise ApiError(*E.ERR_STALE_REFUND_CASE_VERSION,
                       message="expected_refund_case_version does not match")


@app.route("/refund-cases/<rid>/counter", methods=["POST"])
def refund_counter(rid):
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    body = get_json_body()
    counter_amount = req_int(body, "counter_amount_cents")
    expected_version = req_int(body, "expected_refund_case_version")
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        require_owner(uid, role, "Tutor", e["tutor_id"])
        # State applicability before OCC (PRD 4 order).
        if e["status"] != "PARENT_PROPOSED":
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not PARENT_PROPOSED")
        # OCC.
        if expected_version != e["version"]:
            raise ApiError(*E.ERR_STALE_REFUND_CASE_VERSION,
                           message="stale refund case version")
        # Bounds: counter <= parent_offer_cents.
        if counter_amount > e["parent_offer_cents"]:
            raise ApiError(*E.ERR_OFFER_OUT_OF_BOUNDS,
                           message="counter exceeds parent offer")
        e["status"] = "TUTOR_COUNTERED"
        e["tutor_offer_cents"] = counter_amount
        touch(e)
        return success(S.refund_case(e), status=200)


@app.route("/refund-cases/<rid>/repropose", methods=["POST"])
def refund_repropose(rid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    body = get_json_body()
    new_offer = req_int(body, "new_offer_cents")
    expected_version = req_int(body, "expected_refund_case_version")
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] != "TUTOR_COUNTERED":
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not TUTOR_COUNTERED")
        if expected_version != e["version"]:
            raise ApiError(*E.ERR_STALE_REFUND_CASE_VERSION,
                           message="stale refund case version")
        # round_count cap (priority 15): blocked once round_count >= 3.
        if e["round_count"] >= 3:
            raise ApiError(*E.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
                           message="negotiation rounds exhausted")
        # Bounds (priority 14): tutor_offer <= new_offer <= parent_offer.
        if new_offer < e["tutor_offer_cents"] or new_offer > e["parent_offer_cents"]:
            raise ApiError(*E.ERR_OFFER_OUT_OF_BOUNDS,
                           message="re-proposal outside narrowing band")
        e["status"] = "PARENT_PROPOSED"
        e["parent_offer_cents"] = new_offer
        e["round_count"] += 1
        touch(e)
        return success(S.refund_case(e), status=200)


@app.route("/refund-cases/<rid>/accept-counter", methods=["POST"])
def refund_accept_counter(rid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    body = get_json_body()
    expected_version = req_int(body, "expected_refund_case_version")
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] != "TUTOR_COUNTERED":
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not TUTOR_COUNTERED")
        if expected_version != e["version"]:
            raise ApiError(*E.ERR_STALE_REFUND_CASE_VERSION,
                           message="stale refund case version")
        e["granted_amount_cents"] = e["tutor_offer_cents"]
        e["status"] = "RESOLVED_REFUND"
        e["_resolved_via_arbitration"] = False
        touch(e)
        _apply_settlement_reversal(e)
        return success(S.refund_case(e), status=200)


@app.route("/refund-cases/<rid>/accept-offer", methods=["POST"])
def refund_accept_offer(rid):
    uid, role = get_user_context()
    require_role(role, ["Tutor"])
    body = get_json_body()
    expected_version = req_int(body, "expected_refund_case_version")
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        require_owner(uid, role, "Tutor", e["tutor_id"])
        if e["status"] != "PARENT_PROPOSED":
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not PARENT_PROPOSED")
        if expected_version != e["version"]:
            raise ApiError(*E.ERR_STALE_REFUND_CASE_VERSION,
                           message="stale refund case version")
        e["granted_amount_cents"] = e["parent_offer_cents"]
        e["status"] = "RESOLVED_REFUND"
        e["_resolved_via_arbitration"] = False
        touch(e)
        _apply_settlement_reversal(e)
        return success(S.refund_case(e), status=200)


@app.route("/refund-cases/<rid>/escalate", methods=["POST"])
def refund_escalate(rid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] not in ("PARENT_PROPOSED", "TUTOR_COUNTERED"):
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not escalatable")
        # Escalation requires round_count >= 1 (priority 15).
        if e["round_count"] < 1:
            raise ApiError(*E.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
                           message="escalation requires at least one completed round")
        e["status"] = "ARBITRATION"
        touch(e)
        return success(S.refund_case(e), status=200)


@app.route("/refund-cases/<rid>/arbitrate", methods=["POST"])
def refund_arbitrate(rid):
    uid, role = get_user_context()
    require_role(role, ["Arbiter"])
    body = get_json_body()
    ruling = req_enum(body, "ruling", {"REFUND", "DENY"})
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        if e["status"] != "ARBITRATION":
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not in ARBITRATION")
        if ruling == "REFUND":
            awarded = req_int(body, "awarded_amount_cents")
            # 0 < awarded <= parent_offer_cents (priority 14).
            if awarded <= 0 or awarded > e["parent_offer_cents"]:
                raise ApiError(*E.ERR_OFFER_OUT_OF_BOUNDS,
                               message="awarded amount outside (0, parent_offer_cents]")
            e["granted_amount_cents"] = awarded
            e["status"] = "RESOLVED_REFUND"
            e["_resolved_via_arbitration"] = True
            touch(e)
            _apply_settlement_reversal(e)
            # Acute reliability penalty already captured by recompute (arbitrated count).
            tutor = db.tutors.get(e["tutor_id"])
            if tutor:
                svc.recompute_tutor_lifetime_and_reliability(tutor)
                svc.recompute_tutor_derived(tutor)
                touch(tutor)
        else:  # DENY
            e["granted_amount_cents"] = 0
            e["status"] = "RESOLVED_DENY"
            touch(e)
            session = db.sessions.get(e["session_id"])
            if session:
                session["settlement_status"] = "SETTLED"
                touch(session)
        return success(S.refund_case(e), status=200)


@app.route("/refund-cases/<rid>/withdraw", methods=["POST"])
def refund_withdraw(rid):
    uid, role = get_user_context()
    require_role(role, ["ParentGuardian"])
    with db.lock:
        e = get_or_404(db.refund_cases, rid, E.ERR_REFUND_CASE_NOT_FOUND)
        require_owner(uid, role, "ParentGuardian", e["parent_account_id"])
        if e["status"] not in ("PARENT_PROPOSED", "TUTOR_COUNTERED"):
            raise ApiError(*E.ERR_INVALID_STATE, message="case is not withdrawable")
        e["status"] = "WITHDRAWN"
        touch(e)
        session = db.sessions.get(e["session_id"])
        if session:
            session["settlement_status"] = "SETTLED"
            touch(session)
        return success(S.refund_case(e), status=200)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

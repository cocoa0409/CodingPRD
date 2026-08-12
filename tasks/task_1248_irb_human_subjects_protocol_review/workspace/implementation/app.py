"""IRB Human Subjects Protocol Review API — Flask entry point."""

import os
from datetime import timedelta

from flask import Flask, jsonify

import db
from core import (
    ApiError, Caller, authenticate, require_role, require_chair, get_or_404,
    body, req_string, opt_string, req_enum, opt_enum, opt_bool, req_int,
    opt_int, req_iso, parse_iso, fmt_iso, new_record, touch, success_object,
    paginate, error_body, now, set_clock,
)
from errors import *
from services import (
    BASE_FEE_CENTS, ASSIGNMENT_RESPONSE_WINDOW_DAYS, MAX_ACTIVE_ASSIGNMENTS,
    AGENDA_CAPACITY, CR_SUBMISSION_WINDOW_DAYS, AE_WINDOW_DAYS,
    PROTOCOL_TERMINAL, OPEN_CASE_STATUSES,
    provisional_fee, settled_base_fee, reliance_site_fee,
    recompute_investigator_scores, recompute_member_assignment_count,
    recompute_meeting_item_count, suspend_protocol, reinstate_protocol,
    open_case, create_continuing_review, approve_protocol, has_conflict,
    open_cases_for_protocol, approved_consent_exists,
    submitted_recommendations, run_sweep,
)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    payload = error_body(err.error_id, err.message)
    return jsonify(payload), err.http_status


@app.errorhandler(404)
def handle_404(err):
    return jsonify(error_body(ERR_PROTOCOL_NOT_FOUND, "Route not found")), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify(error_body(ERR_VALIDATION, "Method not allowed")), 405


# ===========================================================================
# Clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    data = body()
    to_dt = req_iso(data, "to_iso8601")
    set_clock(to_dt)
    lapsed, failed, expired = run_sweep()
    return success_object({
        "current_utc": fmt_iso(now()),
        "lapsed_continuing_reviews": lapsed,
        "failed_quorum_meetings": failed,
        "expired_assignments": expired,
    })


# ===========================================================================
# Serializers
# ===========================================================================

def ser_investigator(r):
    return dict(r)


def ser_member(r):
    return dict(r)


def ser_protocol(r):
    return dict(r)


def ser_consent(r):
    return dict(r)


def ser_assignment(r):
    return dict(r)


def ser_declaration(r):
    return dict(r)


def ser_meeting(r):
    return dict(r)


def ser_agenda_item(r):
    return dict(r)


def ser_modification(r):
    return dict(r)


def ser_cr(r):
    return dict(r)


def ser_ae(r):
    return dict(r)


def ser_case(r):
    return dict(r)


def ser_reliance(r):
    return dict(r)


# ===========================================================================
# Investigators
# ===========================================================================

@app.route("/irb/investigators", methods=["POST"])
def create_investigator():
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    data = body()
    full_name = req_string(data, "full_name")
    email = req_string(data, "email")
    department = req_string(data, "department")
    training = req_iso(data, "training_expires_at")
    if any(i for i in db.investigators.values() if i.get("email") == email):
        raise ApiError(ERR_VALIDATION, 400, "email must be unique across investigators")
    rec = new_record({
        "full_name": full_name,
        "email": email,
        "department": department,
        "training_expires_at": fmt_iso(training),
        "provisional_compliance_score": 100,
        "final_compliance_score": 100,
        "status": "ACTIVE",
    })
    db.investigators[rec["id"]] = rec
    return success_object(ser_investigator(rec), 201)


@app.route("/irb/investigators/<iid>", methods=["GET"])
def get_investigator(iid):
    authenticate()
    rec = get_or_404(db.investigators, iid, "investigator")
    return success_object(ser_investigator(rec))


@app.route("/irb/investigators", methods=["GET"])
def list_investigators():
    authenticate()
    from flask import request
    rows = list(db.investigators.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_investigator)


# ===========================================================================
# IRB members
# ===========================================================================

@app.route("/irb/irb-members", methods=["POST"])
def create_member():
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    data = body()
    full_name = req_string(data, "full_name")
    email = req_string(data, "email")
    category = req_enum(data, "member_category",
                        {"SCIENTIST", "NON_SCIENTIST", "UNAFFILIATED",
                         "PRISONER_REPRESENTATIVE"})
    is_chair = opt_bool(data, "is_chair", False)
    if any(m for m in db.irb_members.values() if m.get("email") == email):
        raise ApiError(ERR_VALIDATION, 400, "email must be unique across members")
    rec = new_record({
        "full_name": full_name,
        "email": email,
        "member_category": category,
        "is_chair": is_chair,
        "status": "ACTIVE",
        "active_assignment_count": 0,
    })
    db.irb_members[rec["id"]] = rec
    return success_object(ser_member(rec), 201)


@app.route("/irb/irb-members/<mid>", methods=["GET"])
def get_member(mid):
    authenticate()
    rec = get_or_404(db.irb_members, mid, "member")
    return success_object(ser_member(rec))


@app.route("/irb/irb-members", methods=["GET"])
def list_members():
    authenticate()
    from flask import request
    rows = list(db.irb_members.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    cat = request.args.get("member_category")
    if cat is not None:
        rows = [r for r in rows if r.get("member_category") == cat]
    return paginate(rows, ser_member)


@app.route("/irb/irb-members/<mid>/deactivate", methods=["POST"])
def deactivate_member(mid):
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    rec = get_or_404(db.irb_members, mid, "member")
    rec["status"] = "INACTIVE"
    touch(rec)
    return success_object(ser_member(rec))


@app.route("/irb/irb-members/<mid>/reactivate", methods=["POST"])
def reactivate_member(mid):
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    rec = get_or_404(db.irb_members, mid, "member")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(ser_member(rec))


# ===========================================================================
# Protocols
# ===========================================================================

@app.route("/irb/protocols", methods=["POST"])
def create_protocol():
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    data = body()
    title = req_string(data, "title")
    claimed = req_enum(data, "claimed_review_level",
                       {"EXEMPT", "EXPEDITED", "FULL_BOARD"})
    risk = req_enum(data, "risk_level", {"MINIMAL", "GREATER_THAN_MINIMAL"})
    prisoners = opt_bool(data, "involves_prisoners", False)
    industry = opt_bool(data, "is_industry_sponsored", False)
    rec = new_record({
        "pi_id": caller.user_id,
        "title": title,
        "claimed_review_level": claimed,
        "risk_level": risk,
        "involves_prisoners": prisoners,
        "is_industry_sponsored": industry,
        "determined_review_level": None,
        "provisional_fee_cents": None,
        "settled_fee_cents": None,
        "fee_delta_cents": None,
        "approval_expires_at": None,
        "continuing_review_interval_days": None,
        "pre_suspension_state": None,
        "status": "DRAFT",
    })
    db.protocols[rec["id"]] = rec
    return success_object(ser_protocol(rec), 201)


@app.route("/irb/protocols/<pid>", methods=["GET"])
def get_protocol(pid):
    authenticate()
    rec = get_or_404(db.protocols, pid, "protocol")
    return success_object(ser_protocol(rec))


@app.route("/irb/protocols", methods=["GET"])
def list_protocols():
    authenticate()
    from flask import request
    rows = list(db.protocols.values())
    pi = request.args.get("pi_id")
    if pi is not None:
        rows = [r for r in rows if r.get("pi_id") == pi]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_protocol)


def submission_gates(protocol, caller):
    """Ownership + investigator eligibility gates in fixed order."""
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    inv = db.investigators.get(protocol.get("pi_id"))
    if inv is None:
        raise ApiError(ERR_INVESTIGATOR_NOT_FOUND, 404,
                       "Protocol's investigator does not resolve")
    if inv.get("status") == "DEBARRED":
        raise ApiError(ERR_INVESTIGATOR_DEBARRED, 422,
                       "Investigator is debarred")
    if parse_iso(inv["training_expires_at"], "training_expires_at") <= now():
        raise ApiError(ERR_PI_TRAINING_LAPSED, 422,
                       "Investigator training has lapsed")
    if inv.get("provisional_compliance_score", 100) < 60:
        raise ApiError(ERR_COMPLIANCE_SCORE_TOO_LOW, 422,
                       "Provisional compliance score below 60")
    has_consent = any(
        d for d in db.consent_documents.values()
        if d.get("protocol_id") == protocol["id"]
        and d.get("status") in ("SUBMITTED", "APPROVED"))
    if not has_consent:
        raise ApiError(ERR_NO_CONSENT_DOCUMENT, 422,
                       "No consent document in SUBMITTED or APPROVED")


@app.route("/irb/protocols/<pid>/submit", methods=["POST"])
def submit_protocol(pid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol["status"] not in ("DRAFT", "RETURNED", "CHANGES_REQUESTED",
                                  "BOARD_CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol not in a submittable state")
    submission_gates(protocol, caller)
    origin = protocol["status"]
    if origin == "DRAFT":
        protocol["provisional_fee_cents"] = provisional_fee(protocol)
        protocol["status"] = "SUBMITTED"
    elif origin == "RETURNED":
        protocol["status"] = "SUBMITTED"
    elif origin == "CHANGES_REQUESTED":
        protocol["status"] = "UNDER_EXPEDITED_REVIEW"
    else:  # BOARD_CHANGES_REQUESTED
        protocol["status"] = "AWAITING_FULL_BOARD"
    touch(protocol)
    return success_object(ser_protocol(protocol))


@app.route("/irb/protocols/<pid>/return", methods=["POST"])
def return_protocol(pid):
    caller = authenticate()
    require_role(caller, "IrbCoordinator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Protocol not in SUBMITTED")
    data = body()
    opt_string(data, "reason")
    protocol["status"] = "RETURNED"
    touch(protocol)
    return success_object(ser_protocol(protocol))


@app.route("/irb/protocols/<pid>/determinations", methods=["POST"])
def determine_protocol(pid):
    caller = authenticate()
    require_role(caller, "IrbCoordinator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Protocol not in SUBMITTED")
    data = body()
    level = req_enum(data, "determined_review_level",
                     {"EXEMPT", "EXPEDITED", "FULL_BOARD"})
    if level == "EXEMPT" and protocol.get("risk_level") != "MINIMAL":
        raise ApiError(ERR_EXEMPT_REQUIRES_MINIMAL_RISK, 422,
                       "EXEMPT determination requires MINIMAL risk")
    protocol["determined_review_level"] = level
    protocol["settled_fee_cents"] = settled_base_fee(protocol)
    prov = protocol.get("provisional_fee_cents") or 0
    protocol["fee_delta_cents"] = protocol["settled_fee_cents"] - prov
    if level == "EXEMPT":
        protocol["status"] = "EXEMPT_ACTIVE"
    elif level == "EXPEDITED":
        protocol["status"] = "UNDER_EXPEDITED_REVIEW"
    else:
        protocol["status"] = "AWAITING_FULL_BOARD"
    touch(protocol)
    return success_object(ser_protocol(protocol))


@app.route("/irb/protocols/<pid>/expedited-determination", methods=["POST"])
def expedited_determination(pid):
    caller = authenticate()
    chair = require_chair(caller)
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol["status"] != "UNDER_EXPEDITED_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol not in UNDER_EXPEDITED_REVIEW")
    data = body()
    outcome = req_enum(data, "outcome",
                       {"APPROVE", "REQUIRE_CHANGES", "REFER_TO_FULL_BOARD"})
    if has_conflict(chair["id"], protocol["id"]):
        raise ApiError(ERR_CHAIR_CONFLICTED, 422,
                       "Chair holds a CONFLICTED declaration on this protocol")
    recs = submitted_recommendations(protocol["id"])
    if outcome == "APPROVE":
        if len(recs) < 2:
            raise ApiError(ERR_INSUFFICIENT_RECOMMENDATIONS, 422,
                           "Fewer than 2 non-voided SUBMITTED recommendations")
        if any(a.get("recommendation") == "DISAPPROVE" for a in recs):
            raise ApiError(ERR_EXPEDITED_DISAPPROVE_REQUIRES_BOARD, 422,
                           "A DISAPPROVE recommendation requires full board")
        if not approved_consent_exists(protocol["id"]):
            raise ApiError(ERR_NO_APPROVED_CONSENT, 422,
                           "No APPROVED consent document")
        approve_protocol(protocol, now())
    elif outcome == "REQUIRE_CHANGES":
        if len(recs) < 1:
            raise ApiError(ERR_INSUFFICIENT_RECOMMENDATIONS, 422,
                           "No non-voided SUBMITTED recommendation")
        protocol["status"] = "CHANGES_REQUESTED"
        touch(protocol)
    else:  # REFER_TO_FULL_BOARD
        protocol["status"] = "AWAITING_FULL_BOARD"
        touch(protocol)
    return success_object(ser_protocol(protocol))


@app.route("/irb/protocols/<pid>/withdraw", methods=["POST"])
def withdraw_protocol(pid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    if protocol["status"] not in ("DRAFT", "SUBMITTED", "RETURNED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol not in DRAFT/SUBMITTED/RETURNED")
    protocol["status"] = "WITHDRAWN"
    touch(protocol)
    return success_object(ser_protocol(protocol))


@app.route("/irb/protocols/<pid>/close", methods=["POST"])
def close_protocol(pid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    if protocol["status"] not in ("APPROVED", "EXEMPT_ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol not in APPROVED or EXEMPT_ACTIVE")
    if open_cases_for_protocol(protocol["id"]):
        raise ApiError(ERR_OPEN_CASES_REMAIN, 422,
                       "Open non-compliance cases remain")
    protocol["status"] = "CLOSED"
    touch(protocol)
    # Moot open continuing reviews
    for cr in db.continuing_reviews.values():
        if cr.get("protocol_id") == protocol["id"] and cr.get("status") in (
                "PENDING_SUBMISSION", "SUBMITTED", "CHANGES_REQUESTED"):
            cr["status"] = "APPROVED"  # terminal, treated as moot
            touch(cr)
    return success_object(ser_protocol(protocol))


@app.route("/irb/protocols/<pid>/reinstate", methods=["POST"])
def reinstate_protocol_endpoint(pid):
    caller = authenticate()
    require_chair(caller)
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Protocol not in SUSPENDED")
    if open_cases_for_protocol(protocol["id"]):
        raise ApiError(ERR_OPEN_CASES_REMAIN, 422,
                       "Open non-compliance cases remain")
    reinstate_protocol(protocol)
    return success_object(ser_protocol(protocol))


# ===========================================================================
# Consent documents
# ===========================================================================

@app.route("/irb/protocols/<pid>/consent-documents", methods=["POST"])
def upload_consent(pid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    data = body()
    file_ref = req_string(data, "file_ref")
    waiver_type = opt_enum(data, "waiver_type",
                           {"NONE", "WAIVER_OF_CONSENT", "WAIVER_OF_DOCUMENTATION",
                            "ALTERATION_OF_CONSENT"}, "NONE")
    c1 = opt_bool(data, "waiver_criterion_minimal_risk", False)
    c2 = opt_bool(data, "waiver_criterion_rights_not_adversely_affected", False)
    c3 = opt_bool(data, "waiver_criterion_impracticable_without_waiver", False)
    c4 = opt_bool(data, "waiver_criterion_debrief_when_appropriate", False)
    max_seq = max(
        (d["version_seq"] for d in db.consent_documents.values()
         if d.get("protocol_id") == protocol["id"]),
        default=0)
    rec = new_record({
        "protocol_id": protocol["id"],
        "version_seq": max_seq + 1,
        "file_ref": file_ref,
        "waiver_type": waiver_type,
        "waiver_criterion_minimal_risk": c1,
        "waiver_criterion_rights_not_adversely_affected": c2,
        "waiver_criterion_impracticable_without_waiver": c3,
        "waiver_criterion_debrief_when_appropriate": c4,
        "status": "SUBMITTED",
    })
    db.consent_documents[rec["id"]] = rec
    return success_object(ser_consent(rec), 201)


@app.route("/irb/consent-documents/<cid>", methods=["GET"])
def get_consent(cid):
    authenticate()
    rec = get_or_404(db.consent_documents, cid, "consent")
    return success_object(ser_consent(rec))


@app.route("/irb/protocols/<pid>/consent-documents", methods=["GET"])
def list_consents(pid):
    authenticate()
    get_or_404(db.protocols, pid, "protocol")
    from flask import request
    rows = [d for d in db.consent_documents.values()
            if d.get("protocol_id") == pid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_consent)


@app.route("/irb/consent-documents/<cid>/modifications", methods=["GET"])
def list_consent_modifications(cid):
    authenticate()
    get_or_404(db.consent_documents, cid, "consent")
    rows = [m for m in db.modifications.values()
            if m.get("new_consent_document_id") == cid]
    return paginate(rows, ser_modification)


def approve_consent_document(doc):
    """Approve a SUBMITTED consent doc; supersedes previously APPROVED ones."""
    for other in db.consent_documents.values():
        if (other.get("protocol_id") == doc["protocol_id"]
                and other["id"] != doc["id"]
                and other.get("status") == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    doc["status"] = "APPROVED"
    touch(doc)


def check_waiver_criteria(doc):
    if doc.get("waiver_type") != "NONE":
        if not (doc.get("waiver_criterion_minimal_risk")
                and doc.get("waiver_criterion_rights_not_adversely_affected")
                and doc.get("waiver_criterion_impracticable_without_waiver")
                and doc.get("waiver_criterion_debrief_when_appropriate")):
            raise ApiError(ERR_WAIVER_CRITERIA_NOT_MET, 422,
                           "All four waiver criteria must be true")


@app.route("/irb/consent-documents/<cid>/review", methods=["POST"])
def review_consent(cid):
    caller = authenticate()
    require_chair(caller)
    doc = get_or_404(db.consent_documents, cid, "consent")
    if doc["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Consent document not SUBMITTED")
    data = body()
    outcome = req_enum(data, "outcome", {"APPROVE", "REQUIRE_CHANGES"})
    if outcome == "APPROVE":
        check_waiver_criteria(doc)
        approve_consent_document(doc)
    else:
        doc["status"] = "CHANGES_REQUIRED"
        touch(doc)
    return success_object(ser_consent(doc))


# ===========================================================================
# Review assignments
# ===========================================================================

@app.route("/irb/protocols/<pid>/review-assignments", methods=["POST"])
def offer_assignment(pid):
    caller = authenticate()
    require_role(caller, "IrbCoordinator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    data = body()
    reviewer_id = opt_string(data, "reviewer_id")
    reviewer_role = opt_enum(data, "reviewer_role", {"PRIMARY", "SECONDARY"},
                             "SECONDARY")

    def dup_check(rid):
        if any(a for a in db.review_assignments.values()
               if a.get("protocol_id") == protocol["id"]
               and a.get("reviewer_id") == rid
               and a.get("status") in ("OFFERED", "ACCEPTED", "SUBMITTED")):
            raise ApiError(ERR_DUPLICATE_ASSIGNMENT, 409,
                           "Reviewer already has a non-terminal assignment")

    if reviewer_id is not None:
        member = get_or_404(db.irb_members, reviewer_id, "member")
        if member.get("status") != "ACTIVE":
            raise ApiError(ERR_NO_ELIGIBLE_REVIEWER, 422,
                           "Reviewer is not ACTIVE")
        # PRD §2.9: conflict safety gates (5) precede business constraints (6).
        if has_conflict(reviewer_id, protocol["id"]):
            raise ApiError(ERR_REVIEWER_CONFLICTED, 422,
                           "Reviewer holds a CONFLICTED declaration")
        dup_check(reviewer_id)
    else:
        # deterministic auto-selection
        candidates = []
        for m in db.irb_members.values():
            if m.get("status") != "ACTIVE":
                continue
            if m.get("active_assignment_count", 0) >= MAX_ACTIVE_ASSIGNMENTS:
                continue
            if has_conflict(m["id"], protocol["id"]):
                continue
            if any(a for a in db.review_assignments.values()
                   if a.get("protocol_id") == protocol["id"]
                   and a.get("reviewer_id") == m["id"]
                   and a.get("status") in ("OFFERED", "ACCEPTED", "SUBMITTED")):
                continue
            candidates.append(m)
        if not candidates:
            raise ApiError(ERR_NO_ELIGIBLE_REVIEWER, 422,
                           "No eligible reviewer in the pool")
        candidates.sort(key=lambda m: (m.get("active_assignment_count", 0),
                                       m["created_at"]))
        reviewer_id = candidates[0]["id"]

    offered = now()
    rec = new_record({
        "protocol_id": protocol["id"],
        "reviewer_id": reviewer_id,
        "reviewer_role": reviewer_role,
        "offered_at": fmt_iso(offered),
        "response_deadline_at": fmt_iso(
            offered + timedelta(days=ASSIGNMENT_RESPONSE_WINDOW_DAYS)),
        "recommendation": None,
        "recommendation_voided": False,
        "status": "OFFERED",
    })
    db.review_assignments[rec["id"]] = rec
    recompute_member_assignment_count(reviewer_id)
    return success_object(ser_assignment(rec), 201)


@app.route("/irb/review-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    authenticate()
    rec = get_or_404(db.review_assignments, aid, "assignment")
    return success_object(ser_assignment(rec))


@app.route("/irb/review-assignments", methods=["GET"])
def list_assignments():
    authenticate()
    from flask import request
    rows = list(db.review_assignments.values())
    pid = request.args.get("protocol_id")
    if pid is not None:
        rows = [r for r in rows if r.get("protocol_id") == pid]
    rid = request.args.get("reviewer_id")
    if rid is not None:
        rows = [r for r in rows if r.get("reviewer_id") == rid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_assignment)


@app.route("/irb/review-assignments/<aid>/respond", methods=["POST"])
def respond_assignment(aid):
    caller = authenticate()
    require_role(caller, "Reviewer")
    rec = get_or_404(db.review_assignments, aid, "assignment")
    if rec.get("reviewer_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller is not the assigned reviewer")
    if rec["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment not OFFERED")
    data = body()
    response = req_enum(data, "response", {"ACCEPT", "DECLINE", "RECUSE"})
    if response == "ACCEPT" and has_conflict(rec["reviewer_id"],
                                             rec["protocol_id"]):
        raise ApiError(ERR_REVIEWER_CONFLICTED, 422,
                       "Reviewer holds a CONFLICTED declaration")
    if response == "ACCEPT":
        rec["status"] = "ACCEPTED"
    elif response == "DECLINE":
        rec["status"] = "DECLINED"
    else:
        rec["status"] = "RECUSED"
    touch(rec)
    recompute_member_assignment_count(rec["reviewer_id"])
    return success_object(ser_assignment(rec))


@app.route("/irb/review-assignments/<aid>/recommendations", methods=["POST"])
def recommend_assignment(aid):
    caller = authenticate()
    require_role(caller, "Reviewer")
    rec = get_or_404(db.review_assignments, aid, "assignment")
    if rec.get("reviewer_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller is not the assigned reviewer")
    if rec["status"] != "ACCEPTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Assignment not ACCEPTED")
    protocol = db.protocols.get(rec.get("protocol_id"))
    if protocol is None or protocol.get("status") not in (
            "UNDER_EXPEDITED_REVIEW", "AWAITING_FULL_BOARD"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol not under expedited or full-board review")
    if has_conflict(rec["reviewer_id"], rec["protocol_id"]):
        raise ApiError(ERR_REVIEWER_CONFLICTED, 422,
                       "Reviewer holds a CONFLICTED declaration")
    data = body()
    recommendation = req_enum(
        data, "recommendation",
        {"APPROVE", "MINOR_REVISIONS", "MAJOR_REVISIONS", "DISAPPROVE"})
    rec["recommendation"] = recommendation
    rec["status"] = "SUBMITTED"
    touch(rec)
    recompute_member_assignment_count(rec["reviewer_id"])
    return success_object(ser_assignment(rec))


# ===========================================================================
# Conflict declarations
# ===========================================================================

@app.route("/irb/protocols/<pid>/conflict-declarations", methods=["POST"])
def declare_conflict(pid):
    caller = authenticate()
    require_role(caller, "Reviewer")
    protocol = get_or_404(db.protocols, pid, "protocol")
    data = body()
    dtype = req_enum(data, "declaration_type",
                     {"NONE", "FINANCIAL", "PERSONAL", "SCIENTIFIC"})
    detail = opt_string(data, "detail")
    rec = new_record({
        "protocol_id": protocol["id"],
        "reviewer_id": caller.user_id,
        "declaration_type": dtype,
        "detail": detail,
        "status": "PENDING_REVIEW",
    })
    db.conflict_declarations[rec["id"]] = rec
    return success_object(ser_declaration(rec), 201)


@app.route("/irb/conflict-declarations/<did>", methods=["GET"])
def get_declaration(did):
    authenticate()
    rec = get_or_404(db.conflict_declarations, did, "declaration")
    return success_object(ser_declaration(rec))


@app.route("/irb/conflict-declarations", methods=["GET"])
def list_declarations():
    authenticate()
    from flask import request
    rows = list(db.conflict_declarations.values())
    pid = request.args.get("protocol_id")
    if pid is not None:
        rows = [r for r in rows if r.get("protocol_id") == pid]
    rid = request.args.get("reviewer_id")
    if rid is not None:
        rows = [r for r in rows if r.get("reviewer_id") == rid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_declaration)


@app.route("/irb/conflict-declarations/<did>/adjudicate", methods=["POST"])
def adjudicate_declaration(did):
    caller = authenticate()
    require_chair(caller)
    rec = get_or_404(db.conflict_declarations, did, "declaration")
    if rec["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Declaration not PENDING_REVIEW")
    data = body()
    outcome = req_enum(data, "outcome", {"CLEARED", "CONFLICTED"})
    if outcome == "CLEARED":
        rec["status"] = "CLEARED"
        touch(rec)
    else:
        rec["status"] = "CONFLICTED"
        touch(rec)
        # Recusal cascade
        for a in db.review_assignments.values():
            if (a.get("protocol_id") == rec["protocol_id"]
                    and a.get("reviewer_id") == rec["reviewer_id"]):
                if a.get("status") in ("OFFERED", "ACCEPTED"):
                    a["status"] = "RECUSED"
                    touch(a)
                    recompute_member_assignment_count(a["reviewer_id"])
                elif a.get("status") == "SUBMITTED":
                    a["recommendation_voided"] = True
                    touch(a)
    return success_object(ser_declaration(rec))


# ===========================================================================
# Board meetings & agenda
# ===========================================================================

def room_conflict(room_id, start, duration_minutes, exclude_meeting_id=None):
    end = start + timedelta(minutes=duration_minutes)
    for m in db.board_meetings.values():
        if m.get("room_id") != room_id:
            continue
        if m.get("status") not in ("SCHEDULED", "CONVENED"):
            continue
        if exclude_meeting_id and m["id"] == exclude_meeting_id:
            continue
        m_start = parse_iso(m["scheduled_at"], "scheduled_at")
        m_end = m_start + timedelta(minutes=m.get("duration_minutes", 0))
        # half-open [start, end) overlap
        if start < m_end and m_start < end:
            return True
    return False


@app.route("/irb/board-meetings", methods=["POST"])
def create_meeting():
    caller = authenticate()
    require_role(caller, "IrbCoordinator")
    data = body()
    room_id = req_string(data, "room_id")
    scheduled_at = req_iso(data, "scheduled_at")
    duration = req_int(data, "duration_minutes")
    if scheduled_at <= now():
        raise ApiError(ERR_SCHEDULE_IN_PAST, 422,
                       "scheduled_at must be strictly after current time")
    if room_conflict(room_id, scheduled_at, duration):
        raise ApiError(ERR_MEETING_ROOM_CONFLICT, 409,
                       "Room occupation overlaps another meeting")
    rec = new_record({
        "room_id": room_id,
        "scheduled_at": fmt_iso(scheduled_at),
        "duration_minutes": duration,
        "attendee_member_ids": None,
        "quorum_threshold": None,
        "item_count": 0,
        "status": "SCHEDULED",
    })
    db.board_meetings[rec["id"]] = rec
    return success_object(ser_meeting(rec), 201)


@app.route("/irb/board-meetings/<mid>", methods=["GET"])
def get_meeting(mid):
    authenticate()
    rec = get_or_404(db.board_meetings, mid, "meeting")
    return success_object(ser_meeting(rec))


@app.route("/irb/board-meetings", methods=["GET"])
def list_meetings():
    authenticate()
    from flask import request
    rows = list(db.board_meetings.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_meeting)


PRIORITY_RANK = {"SUSPENSION_REVIEW": 0, "INITIAL_REVIEW": 1, "MODIFICATION": 2}


@app.route("/irb/board-meetings/<mid>/agenda-items", methods=["POST"])
def add_agenda_item(mid):
    caller = authenticate()
    require_role(caller, "IrbCoordinator")
    meeting = get_or_404(db.board_meetings, mid, "meeting")
    data = body()
    protocol_id = req_string(data, "protocol_id")
    modification_id = opt_string(data, "modification_id")
    expected_version = data.get("expected_meeting_version")
    protocol = get_or_404(db.protocols, protocol_id, "protocol")
    modification = None
    if modification_id is not None:
        modification = get_or_404(db.modifications, modification_id,
                                  "modification")
    # State legality
    if meeting["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Meeting not SCHEDULED")
    if modification_id is None:
        if protocol["status"] not in ("AWAITING_FULL_BOARD", "SUSPENDED",
                                      "EXPIRED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Initial-review listing requires protocol state")
    else:
        if modification.get("status") != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Modification not SUBMITTED")
        if protocol["status"] not in ("APPROVED", "SUSPENDED", "EXPIRED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Modification listing requires protocol APPROVED")
    # Capacity
    listed = [it for it in db.agenda_items.values()
              if it.get("meeting_id") == meeting["id"]
              and it.get("status") == "LISTED"]
    if len(listed) >= AGENDA_CAPACITY:
        raise ApiError(ERR_AGENDA_CAPACITY_EXCEEDED, 422,
                       "Meeting already has 8 LISTED items")
    # Duplicate listing across SCHEDULED/CONVENED meetings
    for it in db.agenda_items.values():
        if it.get("protocol_id") != protocol["id"]:
            continue
        if it.get("status") != "LISTED":
            continue
        other_meeting = db.board_meetings.get(it.get("meeting_id"))
        if other_meeting is not None and other_meeting.get("status") in (
                "SCHEDULED", "CONVENED"):
            raise ApiError(ERR_DUPLICATE_AGENDA_LISTING, 409,
                           "Protocol already LISTED on a scheduled/convened meeting")
    # OCC
    if expected_version is not None:
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise ApiError(ERR_VALIDATION, 400,
                           "expected_meeting_version must be an integer")
        if expected_version != meeting["version"]:
            raise ApiError(ERR_STALE_MEETING_VERSION, 412,
                           "expected_meeting_version does not match current version")

    # Derive priority class
    if protocol["status"] in ("SUSPENDED", "EXPIRED"):
        priority = "SUSPENSION_REVIEW"
    elif modification_id is not None:
        priority = "MODIFICATION"
    else:
        priority = "INITIAL_REVIEW"

    rec = new_record({
        "meeting_id": meeting["id"],
        "protocol_id": protocol["id"],
        "modification_id": modification_id,
        "priority_class": priority,
        "votes_for": None,
        "votes_against": None,
        "votes_abstain": None,
        "eligible_voter_count": None,
        "outcome": None,
        "status": "LISTED",
    })
    db.agenda_items[rec["id"]] = rec
    # PRD §3.6: one version increment per successful addition; the item_count
    # recompute IS that mutation (§2.5), so recompute performs the touch.
    recompute_meeting_item_count(meeting["id"])
    return success_object(ser_agenda_item(rec), 201)


@app.route("/irb/board-meetings/<mid>/agenda-items", methods=["GET"])
def list_meeting_agenda(mid):
    authenticate()
    meeting = get_or_404(db.board_meetings, mid, "meeting")
    rows = [it for it in db.agenda_items.values()
            if it.get("meeting_id") == meeting["id"]]

    def sort_key(it):
        proto = db.protocols.get(it.get("protocol_id"))
        proto_created = proto["created_at"] if proto else ""
        return (PRIORITY_RANK.get(it.get("priority_class"), 3), proto_created,
                it["id"])

    return paginate(rows, ser_agenda_item, sort_key=sort_key)


@app.route("/irb/agenda-items/<aid>", methods=["GET"])
def get_agenda_item(aid):
    authenticate()
    rec = get_or_404(db.agenda_items, aid, "agenda_item")
    return success_object(ser_agenda_item(rec))


@app.route("/irb/agenda-items", methods=["GET"])
def list_agenda_items():
    authenticate()
    from flask import request
    rows = list(db.agenda_items.values())
    pid = request.args.get("protocol_id")
    if pid is not None:
        rows = [r for r in rows if r.get("protocol_id") == pid]
    midq = request.args.get("meeting_id")
    if midq is not None:
        rows = [r for r in rows if r.get("meeting_id") == midq]
    modq = request.args.get("modification_id")
    if modq is not None:
        rows = [r for r in rows if r.get("modification_id") == modq]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_agenda_item)


@app.route("/irb/board-meetings/<mid>/convene", methods=["POST"])
def convene_meeting(mid):
    caller = authenticate()
    require_chair(caller)
    meeting = get_or_404(db.board_meetings, mid, "meeting")
    if meeting["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Meeting not SCHEDULED")
    data = body()
    attendees = data.get("attendee_member_ids")
    if not isinstance(attendees, list) or not all(
            isinstance(a, str) for a in attendees):
        raise ApiError(ERR_VALIDATION, 400,
                       "attendee_member_ids must be a list of strings")
    # Eligibility
    attendee_members = []
    for aid_ in attendees:
        member = db.irb_members.get(aid_)
        if member is None or member.get("status") != "ACTIVE":
            raise ApiError(ERR_ATTENDEE_NOT_ELIGIBLE, 422,
                           f"Attendee {aid_} is not an ACTIVE member")
        attendee_members.append(member)
    # Quorum count
    active_count = sum(1 for m in db.irb_members.values()
                       if m.get("status") == "ACTIVE")
    threshold = active_count // 2 + 1
    if len(attendees) < threshold:
        raise ApiError(ERR_QUORUM_NOT_MET, 422,
                       "Attendee count below quorum threshold")
    # Composition
    cats = {m["member_category"] for m in attendee_members}
    if "NON_SCIENTIST" not in cats or "UNAFFILIATED" not in cats:
        raise ApiError(ERR_QUORUM_COMPOSITION_MISSING, 422,
                       "Missing NON_SCIENTIST or UNAFFILIATED attendee")
    involves_prisoners = any(
        (db.protocols.get(it.get("protocol_id")) or {}).get("involves_prisoners")
        for it in db.agenda_items.values()
        if it.get("meeting_id") == meeting["id"] and it.get("status") == "LISTED")
    if involves_prisoners and "PRISONER_REPRESENTATIVE" not in cats:
        raise ApiError(ERR_QUORUM_COMPOSITION_MISSING, 422,
                       "Missing PRISONER_REPRESENTATIVE attendee")
    meeting["attendee_member_ids"] = list(attendees)
    meeting["quorum_threshold"] = threshold
    meeting["status"] = "CONVENED"
    touch(meeting)
    return success_object(ser_meeting(meeting))


@app.route("/irb/board-meetings/<mid>/adjourn", methods=["POST"])
def adjourn_meeting(mid):
    caller = authenticate()
    require_chair(caller)
    meeting = get_or_404(db.board_meetings, mid, "meeting")
    if meeting["status"] != "CONVENED":
        raise ApiError(ERR_INVALID_STATE, 409, "Meeting not CONVENED")
    meeting["status"] = "ADJOURNED"
    touch(meeting)
    for it in db.agenda_items.values():
        if it.get("meeting_id") == meeting["id"] and it.get("status") == "LISTED":
            it["status"] = "DEFERRED"
            touch(it)
    recompute_meeting_item_count(meeting["id"])
    return success_object(ser_meeting(meeting))


@app.route("/irb/board-meetings/<mid>/reschedule", methods=["POST"])
def reschedule_meeting(mid):
    caller = authenticate()
    require_role(caller, "IrbCoordinator")
    meeting = get_or_404(db.board_meetings, mid, "meeting")
    if meeting["status"] != "FAILED_QUORUM":
        raise ApiError(ERR_INVALID_STATE, 409, "Meeting not FAILED_QUORUM")
    data = body()
    new_start = req_iso(data, "scheduled_at")
    new_room = opt_string(data, "room_id", meeting.get("room_id"))
    new_duration = opt_int(data, "duration_minutes",
                           meeting.get("duration_minutes"))
    if new_start <= now():
        raise ApiError(ERR_SCHEDULE_IN_PAST, 422,
                       "scheduled_at must be strictly after current time")
    if room_conflict(new_room, new_start, new_duration,
                     exclude_meeting_id=meeting["id"]):
        raise ApiError(ERR_MEETING_ROOM_CONFLICT, 409,
                       "Room occupation overlaps another meeting")
    meeting["scheduled_at"] = fmt_iso(new_start)
    meeting["room_id"] = new_room
    meeting["duration_minutes"] = new_duration
    meeting["status"] = "SCHEDULED"
    touch(meeting)
    return success_object(ser_meeting(meeting))


@app.route("/irb/agenda-items/<aid>/vote", methods=["POST"])
def vote_agenda_item(aid):
    caller = authenticate()
    chair = require_chair(caller)
    item = get_or_404(db.agenda_items, aid, "agenda_item")
    if item["status"] != "LISTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Agenda item not LISTED")
    meeting = db.board_meetings.get(item.get("meeting_id"))
    if meeting is None or meeting.get("status") != "CONVENED":
        raise ApiError(ERR_INVALID_STATE, 409, "Meeting not CONVENED")
    protocol = db.protocols.get(item.get("protocol_id"))
    if protocol is None:
        raise ApiError(ERR_PROTOCOL_NOT_FOUND, 404, "Protocol missing")
    if has_conflict(chair["id"], protocol["id"]):
        raise ApiError(ERR_CHAIR_CONFLICTED, 422,
                       "Chair holds a CONFLICTED declaration on this protocol")
    data = body()
    motion = req_enum(data, "motion", {"APPROVE", "REQUIRE_CHANGES"})
    votes_for = req_int(data, "votes_for")
    votes_against = req_int(data, "votes_against")
    votes_abstain = req_int(data, "votes_abstain")
    # eligible voter count snapshot
    attendees = meeting.get("attendee_member_ids") or []
    conflicted = sum(
        1 for m in attendees if has_conflict(m, protocol["id"]))
    eligible = len(attendees) - conflicted
    if votes_for + votes_against + votes_abstain != eligible:
        raise ApiError(ERR_VOTE_TALLY_MISMATCH, 422,
                       "Tallies must sum to eligible_voter_count")
    passes = votes_for * 2 > eligible
    if motion == "APPROVE":
        outcome = "APPROVE" if passes else "DISAPPROVE"
    else:
        outcome = "REQUIRE_CHANGES" if passes else "DEFER"

    modification = None
    if item.get("modification_id"):
        modification = db.modifications.get(item["modification_id"])

    # Pre-mutation business gates (atomicity: validate before committing)
    if modification is None and outcome == "APPROVE":
        if not approved_consent_exists(protocol["id"]):
            raise ApiError(ERR_NO_APPROVED_CONSENT, 422,
                           "No APPROVED consent document")
    if modification is not None and outcome == "APPROVE":
        if modification.get("new_consent_document_id"):
            doc = db.consent_documents.get(
                modification["new_consent_document_id"])
            if doc is None:
                raise ApiError(ERR_CONSENT_DOC_NOT_FOUND, 404,
                               "Referenced consent document not found")
            if doc.get("status") != "SUBMITTED":
                raise ApiError(ERR_CONSENT_DOC_NOT_SUBMITTED, 422,
                               "Referenced consent document not SUBMITTED")
            check_waiver_criteria(doc)

    item["votes_for"] = votes_for
    item["votes_against"] = votes_against
    item["votes_abstain"] = votes_abstain
    item["eligible_voter_count"] = eligible
    item["outcome"] = outcome

    if outcome == "DEFER":
        item["status"] = "DEFERRED"
        touch(item)
    else:
        item["status"] = "VOTED"
        touch(item)

    # Apply outcome
    if modification is not None:
        if outcome == "APPROVE":
            modification["status"] = "APPROVED"
            touch(modification)
            if modification.get("new_consent_document_id"):
                doc = db.consent_documents[
                    modification["new_consent_document_id"]]
                approve_consent_document(doc)
            touch(protocol)  # protocol version increments on any mutation
        else:  # DISAPPROVE or REQUIRE_CHANGES -> modification DENIED
            modification["status"] = "DENIED"
            touch(modification)
    else:
        if outcome == "APPROVE":
            approve_protocol(protocol, now())
        elif outcome == "DISAPPROVE":
            protocol["status"] = "DISAPPROVED"
            touch(protocol)
        elif outcome == "REQUIRE_CHANGES":
            protocol["status"] = "BOARD_CHANGES_REQUESTED"
            touch(protocol)
    return success_object(ser_agenda_item(item))


# ===========================================================================
# Modifications
# ===========================================================================

@app.route("/irb/protocols/<pid>/modifications", methods=["POST"])
def create_modification(pid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    data = body()
    scope = req_enum(data, "scope", {"MINOR", "MAJOR"})
    description = req_string(data, "description")
    new_doc_id = opt_string(data, "new_consent_document_id")
    expected_version = data.get("expected_protocol_version")
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    # State legality
    if protocol["status"] == "APPROVED":
        pass
    elif protocol["status"] == "SUSPENDED" and scope == "MINOR":
        pass
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol must be APPROVED (or SUSPENDED for MINOR)")
    # OCC
    if expected_version is not None:
        if not isinstance(expected_version, int) or isinstance(expected_version, bool):
            raise ApiError(ERR_VALIDATION, 400,
                           "expected_protocol_version must be an integer")
        if expected_version != protocol["version"]:
            raise ApiError(ERR_STALE_PROTOCOL_VERSION, 412,
                           "expected_protocol_version does not match current version")
    rec = new_record({
        "protocol_id": protocol["id"],
        "scope": scope,
        "description": description,
        "new_consent_document_id": new_doc_id,
        "status": "SUBMITTED",
    })
    db.modifications[rec["id"]] = rec
    touch(protocol)  # filing a modification mutates the protocol
    return success_object(ser_modification(rec), 201)


@app.route("/irb/modifications/<mid>", methods=["GET"])
def get_modification(mid):
    authenticate()
    rec = get_or_404(db.modifications, mid, "modification")
    return success_object(ser_modification(rec))


@app.route("/irb/protocols/<pid>/modifications", methods=["GET"])
def list_protocol_modifications(pid):
    authenticate()
    get_or_404(db.protocols, pid, "protocol")
    from flask import request
    rows = [m for m in db.modifications.values()
            if m.get("protocol_id") == pid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_modification)


@app.route("/irb/modifications/<mid>/adjudicate", methods=["POST"])
def adjudicate_modification(mid):
    caller = authenticate()
    chair = require_chair(caller)
    mod = get_or_404(db.modifications, mid, "modification")
    if mod["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Modification not SUBMITTED")
    data = body()
    outcome = req_enum(data, "outcome", {"APPROVE", "DENY"})
    protocol = db.protocols.get(mod.get("protocol_id"))
    if protocol is None:
        raise ApiError(ERR_PROTOCOL_NOT_FOUND, 404, "Protocol missing")
    if has_conflict(chair["id"], protocol["id"]):
        raise ApiError(ERR_CHAIR_CONFLICTED, 422,
                       "Chair holds a CONFLICTED declaration on this protocol")
    if outcome == "APPROVE" and mod.get("scope") == "MAJOR":
        raise ApiError(ERR_MAJOR_REQUIRES_BOARD, 422,
                       "MAJOR modification requires convened-board vote")
    if outcome == "APPROVE":
        if mod.get("new_consent_document_id"):
            doc = db.consent_documents.get(mod["new_consent_document_id"])
            if doc is None:
                raise ApiError(ERR_CONSENT_DOC_NOT_FOUND, 404,
                               "Referenced consent document not found")
            if doc.get("status") != "SUBMITTED":
                raise ApiError(ERR_CONSENT_DOC_NOT_SUBMITTED, 422,
                               "Referenced consent document not SUBMITTED")
            check_waiver_criteria(doc)
        mod["status"] = "APPROVED"
        touch(mod)
        if mod.get("new_consent_document_id"):
            doc = db.consent_documents[mod["new_consent_document_id"]]
            approve_consent_document(doc)
        touch(protocol)  # protocol version increments on approval
    else:
        mod["status"] = "DENIED"
        touch(mod)
    return success_object(ser_modification(mod))


# ===========================================================================
# Continuing reviews
# ===========================================================================

@app.route("/irb/continuing-reviews/<cid>", methods=["GET"])
def get_cr(cid):
    authenticate()
    rec = get_or_404(db.continuing_reviews, cid, "cr")
    return success_object(ser_cr(rec))


@app.route("/irb/protocols/<pid>/continuing-reviews", methods=["GET"])
def list_crs(pid):
    authenticate()
    get_or_404(db.protocols, pid, "protocol")
    from flask import request
    rows = [c for c in db.continuing_reviews.values()
            if c.get("protocol_id") == pid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_cr)


@app.route("/irb/continuing-reviews/<cid>/submit", methods=["POST"])
def submit_cr(cid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    cr = get_or_404(db.continuing_reviews, cid, "cr")
    if cr["status"] not in ("PENDING_SUBMISSION", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Continuing review not in a submittable state")
    protocol = db.protocols.get(cr.get("protocol_id"))
    if protocol is None:
        raise ApiError(ERR_PROTOCOL_NOT_FOUND, 404, "Protocol missing")
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    window = parse_iso(cr["window_opens_at"], "window_opens_at")
    due = parse_iso(cr["due_at"], "due_at")
    current = now()
    if current < window:
        raise ApiError(ERR_CR_WINDOW_NOT_OPEN, 422,
                       "Submission window has not opened")
    if current > due:
        # Sweep would have LAPSED it; treat as invalid state
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Continuing review past due date")
    cr["submitted_at"] = fmt_iso(current)
    cr["status"] = "SUBMITTED"
    touch(cr)
    return success_object(ser_cr(cr))


@app.route("/irb/continuing-reviews/<cid>/adjudicate", methods=["POST"])
def adjudicate_cr(cid):
    caller = authenticate()
    chair = require_chair(caller)
    cr = get_or_404(db.continuing_reviews, cid, "cr")
    data = body()
    outcome = req_enum(data, "outcome", {"APPROVE", "REQUIRE_CHANGES"})
    protocol = db.protocols.get(cr.get("protocol_id"))
    if protocol is None:
        raise ApiError(ERR_PROTOCOL_NOT_FOUND, 404, "Protocol missing")
    if has_conflict(chair["id"], protocol["id"]):
        raise ApiError(ERR_CHAIR_CONFLICTED, 422,
                       "Chair holds a CONFLICTED declaration on this protocol")
    if outcome == "APPROVE":
        if cr["status"] == "SUBMITTED":
            interval = protocol.get("continuing_review_interval_days") or 365
            expires = now() + timedelta(days=interval)
            protocol["approval_expires_at"] = fmt_iso(expires)
            touch(protocol)
            cr["status"] = "APPROVED"
            touch(cr)
            create_continuing_review(protocol, cr["cycle_index"] + 1, expires)
        elif cr["status"] == "LAPSED":
            if protocol.get("status") != "EXPIRED":
                raise ApiError(ERR_INVALID_STATE, 409,
                               "Protocol not EXPIRED for LAPSED CR approval")
            interval = protocol.get("continuing_review_interval_days") or 365
            expires = now() + timedelta(days=interval)
            protocol["approval_expires_at"] = fmt_iso(expires)
            protocol["status"] = "APPROVED"
            touch(protocol)
            cr["status"] = "APPROVED"
            touch(cr)
            create_continuing_review(protocol, cr["cycle_index"] + 1, expires)
        else:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Continuing review not SUBMITTED or LAPSED")
    else:  # REQUIRE_CHANGES
        if cr["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Continuing review not SUBMITTED")
        cr["status"] = "CHANGES_REQUESTED"
        touch(cr)
    return success_object(ser_cr(cr))


# ===========================================================================
# Adverse events
# ===========================================================================

@app.route("/irb/protocols/<pid>/adverse-events", methods=["POST"])
def file_adverse_event(pid):
    caller = authenticate()
    require_role(caller, "PrincipalInvestigator")
    protocol = get_or_404(db.protocols, pid, "protocol")
    if protocol.get("pi_id") != caller.user_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Caller does not own this protocol")
    if protocol["status"] not in ("APPROVED", "SUSPENDED", "EXPIRED",
                                  "EXEMPT_ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol not in a post-approval reporting state")
    data = body()
    event_type = req_enum(data, "event_type",
                          {"SERIOUS_ADVERSE_EVENT", "UNANTICIPATED_PROBLEM",
                           "PROTOCOL_DEVIATION_WITH_HARM"})
    occurred = req_iso(data, "occurred_at")
    description = req_string(data, "description")
    if occurred > now():
        raise ApiError(ERR_AE_OCCURRED_IN_FUTURE, 422,
                       "occurred_at must not be after current time")
    reported = now()
    deadline = occurred + timedelta(days=AE_WINDOW_DAYS[event_type])
    is_late = reported > deadline
    rec = new_record({
        "protocol_id": protocol["id"],
        "event_type": event_type,
        "occurred_at": fmt_iso(occurred),
        "description": description,
        "reported_at": fmt_iso(reported),
        "deadline_at": fmt_iso(deadline),
        "is_late": is_late,
        "triage_note": None,
        "action_type": None,
        "status": "FILED",
    })
    db.adverse_events[rec["id"]] = rec
    if is_late:
        recompute_investigator_scores(protocol.get("pi_id"))
    return success_object(ser_ae(rec), 201)


@app.route("/irb/adverse-events/<aid>", methods=["GET"])
def get_ae(aid):
    authenticate()
    rec = get_or_404(db.adverse_events, aid, "ae")
    return success_object(ser_ae(rec))


@app.route("/irb/protocols/<pid>/adverse-events", methods=["GET"])
def list_aes(pid):
    authenticate()
    get_or_404(db.protocols, pid, "protocol")
    from flask import request
    rows = [a for a in db.adverse_events.values()
            if a.get("protocol_id") == pid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_ae)


@app.route("/irb/adverse-events/<aid>/triage", methods=["POST"])
def triage_ae(aid):
    caller = authenticate()
    require_role(caller, "ComplianceOfficer")
    rec = get_or_404(db.adverse_events, aid, "ae")
    if rec["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "Report not FILED")
    data = body()
    note = opt_string(data, "triage_note")
    if note is not None:
        rec["triage_note"] = note
    rec["status"] = "TRIAGED"
    touch(rec)
    if rec.get("is_late"):
        protocol = db.protocols.get(rec.get("protocol_id"))
        if protocol is not None:
            open_case(protocol, "LATE_AE")
            recompute_investigator_scores(protocol.get("pi_id"))
    return success_object(ser_ae(rec))


@app.route("/irb/adverse-events/<aid>/disposition", methods=["POST"])
def disposition_ae(aid):
    caller = authenticate()
    require_role(caller, "ComplianceOfficer")
    rec = get_or_404(db.adverse_events, aid, "ae")
    if rec["status"] != "TRIAGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Report not TRIAGED")
    data = body()
    disposition = req_enum(data, "disposition",
                           {"CLOSED_NO_ACTION", "CLOSED_WITH_ACTION"})
    if disposition == "CLOSED_NO_ACTION":
        rec["status"] = "CLOSED_NO_ACTION"
        touch(rec)
    else:
        action_type = req_enum(data, "action_type",
                               {"REQUIRE_MODIFICATION", "SUSPEND_PROTOCOL"})
        rec["action_type"] = action_type
        rec["status"] = "CLOSED_WITH_ACTION"
        touch(rec)
        protocol = db.protocols.get(rec.get("protocol_id"))
        if action_type == "SUSPEND_PROTOCOL" and protocol is not None:
            if protocol.get("status") in ("APPROVED", "EXEMPT_ACTIVE"):
                suspend_protocol(protocol)
            open_case(protocol, "AE_ACTION")
            recompute_investigator_scores(protocol.get("pi_id"))
    return success_object(ser_ae(rec))


# ===========================================================================
# Non-compliance cases
# ===========================================================================

@app.route("/irb/protocols/<pid>/non-compliance-cases", methods=["POST"])
def create_case(pid):
    caller = authenticate()
    require_role(caller, "ComplianceOfficer")
    protocol = get_or_404(db.protocols, pid, "protocol")
    data = body()
    reason = req_string(data, "reason")
    case = open_case(protocol, "MANUAL", reason=reason)
    recompute_investigator_scores(protocol.get("pi_id"))
    return success_object(ser_case(case), 201)


@app.route("/irb/non-compliance-cases/<cid>", methods=["GET"])
def get_case(cid):
    authenticate()
    rec = get_or_404(db.non_compliance_cases, cid, "case")
    return success_object(ser_case(rec))


@app.route("/irb/protocols/<pid>/non-compliance-cases", methods=["GET"])
def list_cases(pid):
    authenticate()
    get_or_404(db.protocols, pid, "protocol")
    from flask import request
    rows = [c for c in db.non_compliance_cases.values()
            if c.get("protocol_id") == pid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_case)


@app.route("/irb/non-compliance-cases/<cid>/open-investigation",
           methods=["POST"])
def open_investigation(cid):
    caller = authenticate()
    require_role(caller, "ComplianceOfficer")
    rec = get_or_404(db.non_compliance_cases, cid, "case")
    if rec["status"] != "OPENED":
        raise ApiError(ERR_INVALID_STATE, 409, "Case not OPENED")
    rec["status"] = "INVESTIGATION"
    touch(rec)
    return success_object(ser_case(rec))


@app.route("/irb/non-compliance-cases/<cid>/issue-finding", methods=["POST"])
def issue_finding(cid):
    caller = authenticate()
    require_role(caller, "ComplianceOfficer")
    rec = get_or_404(db.non_compliance_cases, cid, "case")
    if rec["status"] != "INVESTIGATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Case not INVESTIGATION")
    data = body()
    finding = req_enum(data, "finding", {"CONFIRMED", "NOT_CONFIRMED"})
    protocol = db.protocols.get(rec.get("protocol_id"))
    if finding == "CONFIRMED":
        rec["finding_confirmed"] = True
        rec["status"] = "FINDING_CONFIRMED"
        touch(rec)
        if protocol is not None and protocol.get("status") in (
                "APPROVED", "EXEMPT_ACTIVE"):
            suspend_protocol(protocol)
    else:
        rec["finding_confirmed"] = False
        rec["status"] = "FINDING_NOT_CONFIRMED"
        touch(rec)
    if protocol is not None:
        recompute_investigator_scores(protocol.get("pi_id"))
    return success_object(ser_case(rec))


@app.route("/irb/non-compliance-cases/<cid>/close", methods=["POST"])
def close_case(cid):
    caller = authenticate()
    require_role(caller, "ComplianceOfficer")
    rec = get_or_404(db.non_compliance_cases, cid, "case")
    if rec["status"] not in ("FINDING_CONFIRMED", "FINDING_NOT_CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case not in a finding state")
    data = body()
    opt_string(data, "closure_note")
    rec["status"] = "CLOSED"
    touch(rec)
    protocol = db.protocols.get(rec.get("protocol_id"))
    if protocol is not None:
        recompute_investigator_scores(protocol.get("pi_id"))
    return success_object(ser_case(rec))


# ===========================================================================
# Reliance agreements
# ===========================================================================

@app.route("/irb/reliance-agreements", methods=["POST"])
def create_reliance():
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    data = body()
    protocol_id = req_string(data, "protocol_id")
    ceding = req_string(data, "ceding_institution_code")
    reviewing = req_string(data, "reviewing_institution_code")
    start = req_iso(data, "effective_start_date")
    end = req_iso(data, "effective_end_date")
    protocol = get_or_404(db.protocols, protocol_id, "protocol")
    if protocol.get("status") in PROTOCOL_TERMINAL:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Protocol in a terminal state")
    if start > end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "effective_start_date must be <= effective_end_date")
    rec = new_record({
        "protocol_id": protocol_id,
        "ceding_institution_code": ceding,
        "reviewing_institution_code": reviewing,
        "effective_start_date": fmt_iso(start),
        "effective_end_date": fmt_iso(end),
        "status": "PROPOSED",
    })
    db.reliance_agreements[rec["id"]] = rec
    return success_object(ser_reliance(rec), 201)


@app.route("/irb/reliance-agreements/<rid>", methods=["GET"])
def get_reliance(rid):
    authenticate()
    rec = get_or_404(db.reliance_agreements, rid, "reliance")
    return success_object(ser_reliance(rec))


@app.route("/irb/reliance-agreements", methods=["GET"])
def list_reliances():
    authenticate()
    from flask import request
    rows = list(db.reliance_agreements.values())
    pid = request.args.get("protocol_id")
    if pid is not None:
        rows = [r for r in rows if r.get("protocol_id") == pid]
    ceding = request.args.get("ceding_institution_code")
    if ceding is not None:
        rows = [r for r in rows if r.get("ceding_institution_code") == ceding]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, ser_reliance)


@app.route("/irb/reliance-agreements/<rid>/execute", methods=["POST"])
def execute_reliance(rid):
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    rec = get_or_404(db.reliance_agreements, rid, "reliance")
    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Agreement not PROPOSED")
    protocol = db.protocols.get(rec.get("protocol_id"))
    if protocol is None:
        raise ApiError(ERR_PROTOCOL_NOT_FOUND, 404, "Protocol missing")
    if protocol.get("status") != "APPROVED":
        raise ApiError(ERR_PROTOCOL_NOT_APPROVED, 422,
                       "Protocol not APPROVED")
    start = parse_iso(rec["effective_start_date"], "effective_start_date")
    end = parse_iso(rec["effective_end_date"], "effective_end_date")
    for other in db.reliance_agreements.values():
        if other["id"] == rec["id"]:
            continue
        if other.get("protocol_id") != rec["protocol_id"]:
            continue
        if other.get("ceding_institution_code") != rec["ceding_institution_code"]:
            continue
        if other.get("status") != "EXECUTED":
            continue
        o_start = parse_iso(other["effective_start_date"],
                            "effective_start_date")
        o_end = parse_iso(other["effective_end_date"], "effective_end_date")
        # closed-window overlap; touching endpoints intersect
        if start <= o_end and o_start <= end:
            raise ApiError(ERR_RELIANCE_WINDOW_OVERLAP, 409,
                           "Overlapping EXECUTED agreement window")
    rec["status"] = "EXECUTED"
    touch(rec)
    # fee surcharge
    protocol["settled_fee_cents"] = (
        (protocol.get("settled_fee_cents") or 0) + reliance_site_fee(protocol))
    prov = protocol.get("provisional_fee_cents") or 0
    protocol["fee_delta_cents"] = protocol["settled_fee_cents"] - prov
    touch(protocol)
    return success_object(ser_reliance(rec))


@app.route("/irb/reliance-agreements/<rid>/terminate", methods=["POST"])
def terminate_reliance(rid):
    caller = authenticate()
    require_role(caller, "IrbAdmin")
    rec = get_or_404(db.reliance_agreements, rid, "reliance")
    if rec["status"] not in ("EXECUTED", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Agreement not EXECUTED or SUSPENDED")
    rec["status"] = "TERMINATED"
    touch(rec)
    return success_object(ser_reliance(rec))


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

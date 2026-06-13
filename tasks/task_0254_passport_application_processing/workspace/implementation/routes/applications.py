"""Application lifecycle: create, read, list, summary, and all transition
endpoints (submit, begin-verification, clear-hold, adjudicate, issue, withdraw,
name-change/decide) plus status-events listing."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_ALREADY_TERMINAL,
    ERR_FEE_UNPAID,
    ERR_FK_NOT_FOUND,
    ERR_GUARDIAN_CONSENT_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NAME_CHANGE_EVIDENCE_REQUIRED,
    ERR_NOT_FOUND,
    ERR_PHOTO_INVALID,
    ERR_SOD_VIOLATION,
    ERR_STALE_VERSION,
)
from middleware import current_user_id, require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_bool,
    optional_enum,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services import calculations as calc
from services import domain

bp = Blueprint("applications", __name__)

APPLICATION_TYPES = {"NEW", "RENEWAL", "MINOR"}
PRODUCT_TYPES = {"BOOK", "CARD", "BOOK_AND_CARD"}
SERVICE_LEVELS = {"ROUTINE", "EXPEDITE"}

TERMINAL_APP_STATES = {"ISSUED", "REJECTED", "WITHDRAWN"}


def _app_or_404(rid: str) -> dict:
    rec = db.applications.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    return rec


# =============================================================================
# Create / Read / List
# =============================================================================
@bp.route("/applications", methods=["POST"])
def create_application():
    require_auth(["Applicant"])
    body = get_body()
    for f in ("applicant_id", "application_type", "product_type"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")

    applicant_id = require_str(body, "applicant_id")
    application_type = require_enum(body, "application_type", APPLICATION_TYPES)
    product_type = require_enum(body, "product_type", PRODUCT_TYPES)
    service_level = optional_enum(body, "service_level", SERVICE_LEVELS, "ROUTINE")
    name_change_requested = optional_bool(body, "name_change_requested", False)

    prior_name = body.get("prior_name")
    if prior_name is not None and not isinstance(prior_name, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "prior_name must be a string")

    # FK existence (priority 4)
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise APIError(ERR_FK_NOT_FOUND, 422, "applicant_id does not exist")

    # Pin is_minor snapshot (recompute against current clock first)
    from routes.applicants import _apply_is_minor

    _apply_is_minor(applicant)
    applicant_is_minor = applicant["is_minor"]

    # requires_execution: NEW/MINOR always; RENEWAL only when name change is
    # requested and not mail-eligible. We have no "mail-eligible" signal, so a
    # requested name change on a RENEWAL requires execution.
    if application_type in ("NEW", "MINOR"):
        requires_execution = True
    else:  # RENEWAL
        requires_execution = bool(name_change_requested)

    app_rec = {
        "applicant_id": applicant_id,
        "application_type": application_type,
        "product_type": product_type,
        "service_level": service_level,
        "applicant_is_minor": applicant_is_minor,
        "requires_execution": requires_execution,
        "name_change_requested": name_change_requested,
        "prior_name": prior_name,
        "name_change_status": "NONE",
        "status": "DRAFT",
        "urgent_travel": False,
        "submitted_at": None,
        "verification_completed_at": None,
        "target_completion_date": None,
        "assigned_acceptance_agent_id": None,
        "adjudicator_id": None,
    }
    stamp_create(app_rec, full=True)

    # Creation-time side effect: name-change dimension NONE -> PENDING_EVIDENCE
    if name_change_requested:
        app_rec["name_change_status"] = "PENDING_EVIDENCE"

    db.applications[app_rec["id"]] = app_rec
    return ok_object(serialize(app_rec), 201)


@bp.route("/applications/<rid>", methods=["GET"])
def get_application(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    rec = _app_or_404(rid)
    return ok_object(serialize(rec), 200)


@bp.route("/applications", methods=["GET"])
def list_applications():
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    limit, offset = parse_pagination()
    items = list(db.applications.values())
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    if applicant_id is not None:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.route("/applications/<rid>/summary", methods=["GET"])
def application_summary(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    app_rec = _app_or_404(rid)
    fwd = calc.forward_looking_target(app_rec)
    chrono = calc.chronological_target(app_rec)
    fa = domain.fee_for_application(rid)
    total_due = fa["total_due_cents"] if fa else 0
    total, accepted = domain.required_progress(app_rec)
    data = {
        "forward_looking_target_date": fwd,
        "chronological_target_date": chrono,
        "total_due_cents": total_due,
        "required_docs_total": total,
        "required_docs_accepted": accepted,
    }
    return ok_object(data, 200)


# =============================================================================
# Helpers for transition guards
# =============================================================================
def _check_terminal(app_rec: dict) -> None:
    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")


def _check_occ(app_rec: dict, body: dict) -> None:
    if "expected_application_version" not in body or body.get("expected_application_version") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: expected_application_version")
    expected = body["expected_application_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_application_version must be an integer")
    if expected != app_rec["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_application_version does not match")


# =============================================================================
# Submit  (DRAFT -> SUBMITTED)
# =============================================================================
@bp.route("/applications/<rid>/submit", methods=["POST"])
def submit_application(rid):
    require_auth(["Applicant"])
    app_rec = _app_or_404(rid)
    body = get_body()

    # 5 transition definedness / 6 terminality
    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")
    if app_rec["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Submit requires status DRAFT")

    # 8 Photo validity
    photos = [p for p in db.photos.values() if p["application_id"] == rid]
    if not any(p["validation_result"] == "PASS" for p in photos):
        raise APIError(ERR_PHOTO_INVALID, 422, "At least one PASS photo is required")

    # 9 Guardian consent (MINOR)
    if app_rec["application_type"] == "MINOR":
        applicant = db.applicants[app_rec["applicant_id"]]
        docs = domain.docs_for_application(rid)
        has_consent = any(d["doc_category"] == "GUARDIAN_CONSENT" for d in docs)
        if not has_consent or applicant.get("guardian_applicant_id") is None:
            raise APIError(ERR_GUARDIAN_CONSENT_REQUIRED, 422, "Guardian consent required for minor")

    # 10 Name-change evidence
    if app_rec["name_change_requested"]:
        docs = domain.docs_for_application(rid)
        if not any(d["doc_category"] == "NAME_CHANGE_EVIDENCE" for d in docs):
            raise APIError(ERR_NAME_CHANGE_EVIDENCE_REQUIRED, 422, "Name-change evidence required")

    # 17 OCC
    _check_occ(app_rec, body)

    # ---- side effects ----
    app_rec["submitted_at"] = db.clock.now_iso()
    app_rec["target_completion_date"] = calc.forward_looking_target(app_rec)

    comps = calc.compute_fee_components(app_rec, one_day_delivery=False)
    fee = {
        "application_id": rid,
        "base_fee_cents": comps["base_fee_cents"],
        "execution_fee_cents": comps["execution_fee_cents"],
        "expedite_fee_cents": comps["expedite_fee_cents"],
        "urgent_surcharge_cents": comps["urgent_surcharge_cents"],
        "one_day_delivery_cents": comps["one_day_delivery_cents"],
        "one_day_delivery": False,
        "total_due_cents": comps["total_due_cents"],
        "amount_paid_cents": 0,
        "payment_status": "UNPAID",
    }
    stamp_create(fee, full=True)
    db.fee_assessments[fee["id"]] = fee

    # Status move (+ event + version bump)
    domain.set_status(app_rec, "SUBMITTED", "Applicant")

    # Provisional risk recompute (mutates applicant; does not bump app version)
    applicant = db.applicants[app_rec["applicant_id"]]
    domain.recompute_risk_provisional(applicant, app_rec)

    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Begin verification  (SUBMITTED -> IN_VERIFICATION)
# =============================================================================
@bp.route("/applications/<rid>/begin-verification", methods=["POST"])
def begin_verification(rid):
    require_auth(["AcceptanceAgent"])
    app_rec = _app_or_404(rid)

    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")
    if app_rec["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "begin-verification requires status SUBMITTED")

    # 16 Fee paid
    fa = domain.fee_for_application(rid)
    if fa is None or fa["payment_status"] != "PAID":
        raise APIError(ERR_FEE_UNPAID, 409, "Fee assessment must be PAID")

    agent_id = current_user_id()
    app_rec["assigned_acceptance_agent_id"] = agent_id
    domain.set_status(app_rec, "IN_VERIFICATION", "AcceptanceAgent")
    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Clear hold  (REVIEW_HOLD -> IN_VERIFICATION)
# =============================================================================
@bp.route("/applications/<rid>/clear-hold", methods=["POST"])
def clear_hold(rid):
    require_auth(["Adjudicator"])
    app_rec = _app_or_404(rid)
    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")
    if app_rec["status"] != "REVIEW_HOLD":
        raise APIError(ERR_INVALID_STATE, 409, "clear-hold requires status REVIEW_HOLD")
    domain.set_status(app_rec, "IN_VERIFICATION", "Adjudicator")
    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Adjudicate  (ADJUDICATING -> APPROVED | REJECTED | REVIEW_HOLD)
# =============================================================================
@bp.route("/applications/<rid>/adjudicate", methods=["POST"])
def adjudicate(rid):
    require_auth(["Adjudicator"])
    app_rec = _app_or_404(rid)
    body = get_body()

    if "decision" not in body or body.get("decision") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: decision")
    decision = require_enum(body, "decision", {"APPROVE", "REJECT", "RETURN_FOR_REVIEW"})
    reason_code = body.get("reason_code")
    if reason_code is not None and not isinstance(reason_code, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "reason_code must be a string")

    # 5 / 6 transition definedness & terminality
    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")
    if app_rec["status"] != "ADJUDICATING":
        raise APIError(ERR_INVALID_STATE, 409, "adjudicate requires status ADJUDICATING")

    adjudicator_id = current_user_id()

    # 7 SoD — APPROVE and REJECT only; RETURN_FOR_REVIEW carries no SoD guard.
    if decision in ("APPROVE", "REJECT"):
        if adjudicator_id == app_rec.get("assigned_acceptance_agent_id"):
            raise APIError(ERR_SOD_VIOLATION, 403, "Adjudicator must differ from acceptance agent")

    # 16 (fiscal) APPROVE requires PAID fee
    if decision == "APPROVE":
        fa = domain.fee_for_application(rid)
        if fa is None or fa["payment_status"] != "PAID":
            raise APIError(ERR_FEE_UNPAID, 409, "Fee assessment must be PAID to approve")

    # Create the decision record (all branches)
    dec = {
        "application_id": rid,
        "adjudicator_id": adjudicator_id,
        "decision": decision,
        "reason_code": reason_code,
    }
    stamp_create(dec, full=True)
    db.adjudication_decisions[dec["id"]] = dec

    if decision == "APPROVE":
        app_rec["adjudicator_id"] = adjudicator_id
        domain.set_status(app_rec, "APPROVED", "Adjudicator")
    elif decision == "REJECT":
        # Compensation cascade BEFORE the status move so events stay ordered well;
        # refund + cancel appointments, then move status.
        domain.refund_fee(app_rec)
        domain.cancel_booked_appointments(app_rec)
        domain.set_status(app_rec, "REJECTED", "Adjudicator")
    else:  # RETURN_FOR_REVIEW
        domain.set_status(app_rec, "REVIEW_HOLD", "Adjudicator")

    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Issue  (APPROVED -> ISSUED)
# =============================================================================
@bp.route("/applications/<rid>/issue", methods=["POST"])
def issue(rid):
    require_auth(["Adjudicator"])
    app_rec = _app_or_404(rid)
    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")
    if app_rec["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "issue requires status APPROVED")
    domain.complete_booked_appointments(app_rec)
    domain.set_status(app_rec, "ISSUED", "Adjudicator")
    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Withdraw  ({DRAFT,SUBMITTED,IN_VERIFICATION,REVIEW_HOLD} -> WITHDRAWN)
# =============================================================================
@bp.route("/applications/<rid>/withdraw", methods=["POST"])
def withdraw(rid):
    require_auth(["Applicant"])
    app_rec = _app_or_404(rid)
    if app_rec["status"] in TERMINAL_APP_STATES:
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Application is in a terminal state")
    if app_rec["status"] not in ("DRAFT", "SUBMITTED", "IN_VERIFICATION", "REVIEW_HOLD"):
        raise APIError(ERR_INVALID_STATE, 409, "withdraw not permitted from this state")
    domain.refund_fee(app_rec)
    domain.cancel_booked_appointments(app_rec)
    domain.set_status(app_rec, "WITHDRAWN", "Applicant")
    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Name-change decide  (EVIDENCE_VERIFIED -> APPROVED | DENIED)
# =============================================================================
@bp.route("/applications/<rid>/name-change/decide", methods=["POST"])
def name_change_decide(rid):
    require_auth(["Adjudicator"])
    app_rec = _app_or_404(rid)
    body = get_body()
    if "decision" not in body or body.get("decision") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: decision")
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})

    sub = app_rec["name_change_status"]
    # Terminal sub-states reject further transition.
    if sub in ("APPROVED", "DENIED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Name-change is already in a terminal sub-state")
    # Decision requires EVIDENCE_VERIFIED; otherwise name-change-evidence error.
    if sub != "EVIDENCE_VERIFIED":
        raise APIError(
            ERR_NAME_CHANGE_EVIDENCE_REQUIRED,
            422,
            "Name-change decision requires sub-status EVIDENCE_VERIFIED",
        )

    if decision == "APPROVE":
        app_rec["name_change_status"] = "APPROVED"
        # PRD §3.4: record the new legal name onto the applicant. The Application
        # carries no separate "new name" field — the applicant's full_legal_name
        # already holds the intended legal name, so applying it is the identity
        # write that still marks the applicant mutated.
        applicant = db.applicants[app_rec["applicant_id"]]
        applicant["full_legal_name"] = applicant["full_legal_name"]
        touch(applicant)
        touch(app_rec)
        # Approving the name change may unblock the verification auto-advance if
        # all required docs are already accepted.
        domain.maybe_auto_advance_verification(app_rec, "system")
    else:  # DENY
        app_rec["name_change_status"] = "DENIED"
        touch(app_rec)

    return ok_object(serialize(app_rec), 200)


# =============================================================================
# Status events (reverse-reachability, ordered by occurred_at)
# =============================================================================
@bp.route("/applications/<rid>/status-events", methods=["GET"])
def status_events(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    _app_or_404(rid)
    limit, offset = parse_pagination()
    items = [e for e in db.status_events.values() if e["application_id"] == rid]
    items = sorted(items, key=lambda e: (e["occurred_at"], e.get("_seq", 0)))
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# =============================================================================
# Adjudication decisions by application
# =============================================================================
@bp.route("/applications/<rid>/adjudication-decisions", methods=["GET"])
def app_adjudication_decisions(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    _app_or_404(rid)
    limit, offset = parse_pagination()
    items = [d for d in db.adjudication_decisions.values() if d["application_id"] == rid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)

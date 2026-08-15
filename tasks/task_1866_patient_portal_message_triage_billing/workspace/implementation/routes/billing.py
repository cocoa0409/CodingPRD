"""Billing and care-support routes: time entries, education notices, consent
records, e-visit claims, escalations."""

from flask import Blueprint, request

import db
from db import CLOCK, fmt_ts
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MESSAGE_INVALID_STATE,
    ERR_MESSAGE_NOT_RESOLVED,
    ERR_MESSAGE_NOT_CHARGEABLE,
    ERR_RENDERING_PROVIDER_NOT_ON_THREAD,
    ERR_CLAIM_ALREADY_EXISTS,
    ERR_EVISIT_MINUTES_BELOW_MINIMUM,
    ERR_DISCLOSED_FEE_EXCEEDED,
    ERR_CLAIM_INVALID_STATE,
    ERR_CONSENT_ALREADY_RESPONDED,
    ERR_NOTICE_ALREADY_ACKNOWLEDGED,
    ERR_ESCALATION_INVALID_STATE,
    ERR_NOT_ASSIGNEE,
    ERR_PATIENT_OWNERSHIP_MISMATCH,
)
from middleware import (
    authenticate, get_body, req_string, req_enum, req_int, opt_field,
    new_entity, touch, public, get_or_404, sorted_by_created,
    parse_pagination, require_patient_entity, require_patient_ownership,
)
from response import success_object, success_list
from services import domain

bp = Blueprint("billing", __name__)

STAFF_READ = ["PracticeAdmin", "TriageNurse", "FrontDesk", "Provider", "BillingSpecialist"]
ALL_READ = STAFF_READ + ["Patient"]
NOTICE_KINDS = {"EMERGENT_MISUSE", "PORTAL_SCOPE_GUIDANCE", "BILLING_EXPLAINER"}
WORKING_STATUSES = {"IN_REVIEW", "PENDING_CONSENT", "PENDING_COSIGN", "ESCALATED", "REOPENED"}


def _patient_list_filter(ctx, patient_id):
    """Tier-4 rule for Patient-role list calls: patient_id must equal own id."""
    if ctx.role == "Patient":
        require_patient_entity(ctx)
        if patient_id != ctx.user_id:
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH,
                      "Patient-role list calls must pass patient_id equal to X-User-ID")


# ---------------------------------------------------------------------------
# Time entries
# ---------------------------------------------------------------------------

@bp.route("/inbox/time-entries", methods=["POST"])
def create_time_entry():
    ctx = authenticate(["TriageNurse", "FrontDesk", "Provider"])
    body = get_body()
    message_id = req_string(body, "message_id")
    entry_kind = req_enum(body, "entry_kind", {"CLINICAL_REVIEW", "ADMINISTRATIVE"})
    minutes = req_int(body, "minutes", lo=1, hi=480)
    note = opt_field(body, "note")

    message = get_or_404(db.portal_messages, message_id, "message")
    if message["status"] not in WORKING_STATUSES:
        raise_err(ERR_MESSAGE_INVALID_STATE,
                  "Time entries require a working status (IN_REVIEW, PENDING_CONSENT, PENDING_COSIGN, ESCALATED, REOPENED)")

    entry = new_entity({
        "message_id": message_id,
        "staff_id": ctx.user_id,
        "entry_kind": entry_kind,
        "minutes": minutes,
        "note": note,
    })
    db.time_entries[entry["id"]] = entry

    # Recompute message.clinical_minutes_total (derived-field recomputation
    # bumps the message version per §2.4).
    domain.recompute_clinical_minutes(message)
    touch(message)

    return success_object(public(entry), 201)


@bp.route("/inbox/time-entries", methods=["GET"])
def list_time_entries():
    authenticate(STAFF_READ)
    limit, offset = parse_pagination()
    message_id = opt_field(request.args, "message_id")
    staff_id = opt_field(request.args, "staff_id")
    entry_kind = opt_field(request.args, "entry_kind")
    items = list(db.time_entries.values())
    if message_id is not None:
        items = [e for e in items if e["message_id"] == message_id]
    if staff_id is not None:
        items = [e for e in items if e["staff_id"] == staff_id]
    if entry_kind is not None:
        items = [e for e in items if e["entry_kind"] == entry_kind]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(e) for e in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/time-entries/<eid>", methods=["GET"])
def get_time_entry(eid):
    authenticate(STAFF_READ)
    entry = get_or_404(db.time_entries, eid, "time entry")
    return success_object(public(entry))


# ---------------------------------------------------------------------------
# Education notices
# ---------------------------------------------------------------------------

@bp.route("/inbox/education-notices", methods=["POST"])
def create_education_notice():
    ctx = authenticate(["TriageNurse"])
    body = get_body()
    message_id = req_string(body, "message_id")
    notice_kind = req_enum(body, "notice_kind", NOTICE_KINDS)
    text = req_string(body, "body")
    blocking = body.get("blocking", True)
    if not isinstance(blocking, bool):
        raise_err(ERR_INVALID_REQUEST, "blocking must be a boolean")

    message = get_or_404(db.portal_messages, message_id, "message")

    notice = new_entity({
        "message_id": message_id,
        "patient_id": message["patient_id"],
        "notice_kind": notice_kind,
        "blocking": blocking,
        "body": text,
        "status": "ISSUED",
        "acknowledged_at": None,
    })
    db.education_notices[notice["id"]] = notice
    domain.recompute_education_gate(message["patient_id"])
    return success_object(public(notice), 201)


@bp.route("/inbox/education-notices", methods=["GET"])
def list_education_notices():
    ctx = authenticate(ALL_READ)
    limit, offset = parse_pagination()
    message_id = opt_field(request.args, "message_id")
    patient_id = opt_field(request.args, "patient_id")
    status = opt_field(request.args, "status")
    _patient_list_filter(ctx, patient_id)
    items = list(db.education_notices.values())
    if message_id is not None:
        items = [n for n in items if n["message_id"] == message_id]
    if patient_id is not None:
        items = [n for n in items if n["patient_id"] == patient_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(n) for n in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/education-notices/<nid>", methods=["GET"])
def get_education_notice(nid):
    ctx = authenticate(ALL_READ)
    notice = db.education_notices.get(nid)
    if ctx.role == "Patient":
        if ctx.patient is None or (notice is not None and notice["patient_id"] != ctx.user_id):
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH, "Patients may only read their own notices")
    if notice is None:
        raise_err(ERR_NOT_FOUND, "education notice not found: %s" % nid)
    return success_object(public(notice))


@bp.route("/inbox/education-notices/<nid>/acknowledge", methods=["POST"])
def acknowledge_notice(nid):
    ctx = authenticate(["Patient"])
    notice = get_or_404(db.education_notices, nid, "education notice")
    require_patient_ownership(ctx, notice["patient_id"])
    if notice["status"] != "ISSUED":
        raise_err(ERR_NOTICE_ALREADY_ACKNOWLEDGED, "Notice is not in ISSUED")
    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = CLOCK.now_iso()
    touch(notice)
    domain.recompute_education_gate(notice["patient_id"])
    return success_object(public(notice))


# ---------------------------------------------------------------------------
# Consent records
# ---------------------------------------------------------------------------

@bp.route("/inbox/consent-records", methods=["GET"])
def list_consent_records():
    ctx = authenticate(ALL_READ)
    limit, offset = parse_pagination()
    message_id = opt_field(request.args, "message_id")
    patient_id = opt_field(request.args, "patient_id")
    status = opt_field(request.args, "status")
    _patient_list_filter(ctx, patient_id)
    items = list(db.consent_records.values())
    if message_id is not None:
        items = [c for c in items if c["message_id"] == message_id]
    if patient_id is not None:
        items = [c for c in items if c["patient_id"] == patient_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(c) for c in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/consent-records/<cid>", methods=["GET"])
def get_consent_record(cid):
    ctx = authenticate(ALL_READ)
    consent = db.consent_records.get(cid)
    if ctx.role == "Patient":
        if ctx.patient is None or (consent is not None and consent["patient_id"] != ctx.user_id):
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH, "Patients may only read their own consent records")
    if consent is None:
        raise_err(ERR_NOT_FOUND, "consent record not found: %s" % cid)
    return success_object(public(consent))


@bp.route("/inbox/consent-records/<cid>/respond", methods=["POST"])
def respond_consent(cid):
    ctx = authenticate(["Patient"])
    consent = get_or_404(db.consent_records, cid, "consent record")
    require_patient_ownership(ctx, consent["patient_id"])
    body = get_body()
    decision = req_enum(body, "decision", {"GRANTED", "DECLINED"})

    if consent["status"] != "REQUESTED":
        raise_err(ERR_CONSENT_ALREADY_RESPONDED, "Consent record is not in REQUESTED")

    message = db.portal_messages.get(consent["message_id"])
    consent["status"] = decision
    consent["responded_at"] = CLOCK.now_iso()
    touch(consent)

    if message is not None:
        message["billing_disposition"] = "CHARGEABLE" if decision == "GRANTED" else "NOT_BILLABLE"
        # PENDING_CONSENT -> IN_REVIEW with assignee retained.
        if message["status"] == "PENDING_CONSENT":
            message["status"] = "IN_REVIEW"
        touch(message)

    return success_object(public(consent))


# ---------------------------------------------------------------------------
# E-visit claims
# ---------------------------------------------------------------------------

@bp.route("/inbox/e-visit-claims", methods=["POST"])
def create_claim():
    ctx = authenticate(["BillingSpecialist"])
    body = get_body()
    message_id = req_string(body, "message_id")
    rendering_provider_id = req_string(body, "rendering_provider_id")

    # Existence left-to-right: message, then rendering provider.
    message = get_or_404(db.portal_messages, message_id, "message")
    provider = get_or_404(db.staff, rendering_provider_id, "staff member")

    # Business rules in PRD §3.6 order: RESOLVED -> CHARGEABLE -> rendering
    # provider on thread -> single active claim -> min minutes -> fee ceiling.
    if message["status"] != "RESOLVED":
        raise_err(ERR_MESSAGE_NOT_RESOLVED, "Claim creation requires message.status == RESOLVED")
    if message.get("billing_disposition") != "CHARGEABLE":
        raise_err(ERR_MESSAGE_NOT_CHARGEABLE,
                  "Claim creation requires billing_disposition == CHARGEABLE")

    has_clinical_entry = any(
        e["message_id"] == message_id
        and e["staff_id"] == rendering_provider_id
        and e["entry_kind"] == "CLINICAL_REVIEW"
        for e in db.time_entries.values()
    )
    if provider["staff_type"] != "PROVIDER" or not has_clinical_entry:
        raise_err(ERR_RENDERING_PROVIDER_NOT_ON_THREAD,
                  "Rendering provider must be a PROVIDER with a CLINICAL_REVIEW entry on the message")

    for claim in domain.claims_for_message(message_id):
        if claim["status"] in domain.CLAIM_ACTIVE_STATUSES:
            raise_err(ERR_CLAIM_ALREADY_EXISTS,
                      "An active claim (DRAFT/SUBMITTED/DENIED) already exists for this message")

    minutes = message.get("clinical_minutes_total", 0)
    tier = domain.evisit_tier(minutes)
    if tier is None:
        raise_err(ERR_EVISIT_MINUTES_BELOW_MINIMUM,
                  "clinical_minutes_total must be at least 5 for claim creation")
    code, fee = tier

    consent = domain.granted_consent_for_message(message_id)
    if consent is not None and fee > consent["disclosed_fee_cents"]:
        raise_err(ERR_DISCLOSED_FEE_EXCEEDED,
                  "Computed fee exceeds the disclosed_fee_cents on the GRANTED consent")

    patient = db.patients.get(message["patient_id"])
    responsibility = domain.patient_responsibility(patient, fee)

    claim = new_entity({
        "message_id": message_id,
        "patient_id": message["patient_id"],
        "rendering_provider_id": rendering_provider_id,
        "code": code,
        "fee_cents": fee,
        "patient_responsibility_cents": responsibility,
        "status": "DRAFT",
        "denial_reason": None,
        "submitted_at": None,
        "adjudicated_at": None,
    })
    db.e_visit_claims[claim["id"]] = claim
    return success_object(public(claim), 201)


@bp.route("/inbox/e-visit-claims", methods=["GET"])
def list_claims():
    ctx = authenticate(ALL_READ)
    limit, offset = parse_pagination()
    message_id = opt_field(request.args, "message_id")
    patient_id = opt_field(request.args, "patient_id")
    rendering_provider_id = opt_field(request.args, "rendering_provider_id")
    status = opt_field(request.args, "status")
    _patient_list_filter(ctx, patient_id)
    items = list(db.e_visit_claims.values())
    if message_id is not None:
        items = [c for c in items if c["message_id"] == message_id]
    if patient_id is not None:
        items = [c for c in items if c["patient_id"] == patient_id]
    if rendering_provider_id is not None:
        items = [c for c in items if c["rendering_provider_id"] == rendering_provider_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(c) for c in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/e-visit-claims/<cid>", methods=["GET"])
def get_claim(cid):
    ctx = authenticate(ALL_READ)
    claim = db.e_visit_claims.get(cid)
    if ctx.role == "Patient":
        if ctx.patient is None or (claim is not None and claim["patient_id"] != ctx.user_id):
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH, "Patients may only read their own claims")
    if claim is None:
        raise_err(ERR_NOT_FOUND, "claim not found: %s" % cid)
    return success_object(public(claim))


@bp.route("/inbox/e-visit-claims/<cid>/submit", methods=["POST"])
def submit_claim(cid):
    ctx = authenticate(["BillingSpecialist"])
    claim = get_or_404(db.e_visit_claims, cid, "claim")
    if claim["status"] != "DRAFT":
        raise_err(ERR_CLAIM_INVALID_STATE, "Submit requires status DRAFT")

    # Disclosed-fee ceiling re-checked at submit (REQUESTED/GRANTED consent).
    consent = None
    for c in db.consent_records.values():
        if c["message_id"] == claim["message_id"] and c["status"] in ("REQUESTED", "GRANTED"):
            # Prefer the GRANTED record when both exist.
            if consent is None or c["status"] == "GRANTED":
                consent = c
    if consent is not None and claim["fee_cents"] > consent["disclosed_fee_cents"]:
        raise_err(ERR_DISCLOSED_FEE_EXCEEDED,
                  "Claim fee exceeds the disclosed_fee_cents of the message's consent")

    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = CLOCK.now_iso()
    touch(claim)
    domain.recompute_outstanding(claim["patient_id"])
    return success_object(public(claim))


@bp.route("/inbox/e-visit-claims/<cid>/record-adjudication", methods=["POST"])
def record_adjudication(cid):
    ctx = authenticate(["BillingSpecialist"])
    claim = get_or_404(db.e_visit_claims, cid, "claim")
    body = get_body()
    outcome = req_enum(body, "outcome", {"PAID", "DENIED"})
    denial_reason = opt_field(body, "denial_reason")

    if claim["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_INVALID_STATE, "Record-adjudication requires status SUBMITTED")
    if outcome == "DENIED" and not denial_reason:
        raise_err(ERR_INVALID_REQUEST, "denial_reason is required when outcome == DENIED")

    claim["status"] = outcome
    claim["adjudicated_at"] = CLOCK.now_iso()
    if outcome == "DENIED":
        claim["denial_reason"] = denial_reason
    touch(claim)

    message = db.portal_messages.get(claim["message_id"])
    if outcome == "PAID":
        domain.recompute_outstanding(claim["patient_id"])
        # CASCADE: message RESOLVED -> CLOSED.
        if message is not None and message["status"] == "RESOLVED":
            message["status"] = "CLOSED"
            touch(message)
    else:
        # DENIED: outstanding UNCHANGED (DENIED remains in outstanding set).
        # Cascade hop 1: message RESOLVED -> REOPENED to rendering provider.
        if message is not None and message["status"] == "RESOLVED":
            message["status"] = "REOPENED"
            message["assignee_id"] = claim["rendering_provider_id"]
            message["reopen_count"] += 1
            message["response_due_at"] = None
            touch(message)
            # Cascade hops 2+3: count increment + overload re-evaluation.
            domain.recompute_staff_counts(claim["rendering_provider_id"])
    return success_object(public(claim))


@bp.route("/inbox/e-visit-claims/<cid>/rework", methods=["POST"])
def rework_claim(cid):
    ctx = authenticate(["BillingSpecialist"])
    claim = get_or_404(db.e_visit_claims, cid, "claim")
    if claim["status"] != "DENIED":
        raise_err(ERR_CLAIM_INVALID_STATE, "Rework requires status DENIED")
    message = db.portal_messages.get(claim["message_id"])
    if message is None or message["status"] != "RESOLVED":
        raise_err(ERR_MESSAGE_NOT_RESOLVED, "Rework requires the message to be RESOLVED")

    domain.recompute_clinical_minutes(message)
    minutes = message.get("clinical_minutes_total", 0)
    tier = domain.evisit_tier(minutes)
    if tier is None:
        raise_err(ERR_EVISIT_MINUTES_BELOW_MINIMUM,
                  "clinical_minutes_total must be at least 5 for claim rework")
    code, fee = tier
    patient = db.patients.get(claim["patient_id"])
    responsibility = domain.patient_responsibility(patient, fee)

    claim["code"] = code
    claim["fee_cents"] = fee
    claim["patient_responsibility_cents"] = responsibility
    claim["status"] = "DRAFT"
    claim["denial_reason"] = None
    touch(claim)
    # DENIED leaves the outstanding set (-r_old).
    domain.recompute_outstanding(claim["patient_id"])
    return success_object(public(claim))


@bp.route("/inbox/e-visit-claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    ctx = authenticate(["BillingSpecialist"])
    claim = get_or_404(db.e_visit_claims, cid, "claim")
    if claim["status"] not in ("DRAFT", "DENIED"):
        raise_err(ERR_CLAIM_INVALID_STATE, "Void requires status DRAFT or DENIED")
    was_denied = claim["status"] == "DENIED"
    claim["status"] = "VOID"
    touch(claim)
    if was_denied:
        domain.recompute_outstanding(claim["patient_id"])
    return success_object(public(claim))


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

@bp.route("/inbox/escalations", methods=["GET"])
def list_escalations():
    authenticate(STAFF_READ)
    limit, offset = parse_pagination()
    message_id = opt_field(request.args, "message_id")
    provider_id = opt_field(request.args, "provider_id")
    status = opt_field(request.args, "status")
    items = list(db.escalations.values())
    if message_id is not None:
        items = [e for e in items if e["message_id"] == message_id]
    if provider_id is not None:
        items = [e for e in items if e["provider_id"] == provider_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(e) for e in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/escalations/<eid>", methods=["GET"])
def get_escalation(eid):
    authenticate(STAFF_READ)
    esc = get_or_404(db.escalations, eid, "escalation")
    return success_object(public(esc))


@bp.route("/inbox/escalations/<eid>/acknowledge", methods=["POST"])
def acknowledge_escalation(eid):
    ctx = authenticate(["Provider"])
    esc = get_or_404(db.escalations, eid, "escalation")
    if esc["status"] != "OPEN":
        raise_err(ERR_ESCALATION_INVALID_STATE, "Escalation is not OPEN")
    if ctx.user_id != esc["provider_id"]:
        raise_err(ERR_NOT_ASSIGNEE, "Only the escalation's on-call provider may acknowledge it")

    esc["status"] = "ACKNOWLEDGED"
    esc["acknowledged_at"] = CLOCK.now_iso()
    touch(esc)

    message = db.portal_messages.get(esc["message_id"])
    if message is not None and message["status"] == "ESCALATED":
        message["status"] = "IN_REVIEW"  # assignee retained; counts unchanged
        touch(message)
    return success_object(public(esc))

"""Portal message workflow routes: intake, triage, assign, start-review,
reply, complete, cosign, escalate, determine-billing, close."""

from datetime import timedelta

from flask import Blueprint, request

import db
from db import CLOCK, fmt_ts, _parse_dt
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_MESSAGE_INVALID_STATE,
    ERR_EDUCATION_ACK_REQUIRED,
    ERR_PATIENT_OWNERSHIP_MISMATCH,
    ERR_POOL_ROLE_MISMATCH,
    ERR_NO_ACTIVE_COVERAGE,
    ERR_NOT_ASSIGNEE,
    ERR_NOT_AWAITING_COSIGN,
    ERR_NOT_AUTHORIZED_COSIGNER,
    ERR_CATEGORY_NOT_CLINICAL,
    ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS,
    ERR_CONSENT_REQUEST_PENDING,
    ERR_CLAIM_IN_FLIGHT,
    ERR_EVISIT_MINUTES_BELOW_MINIMUM,
    ERR_URGENCY_NOT_ESCALATABLE,
    ERR_NO_ONCALL_COVERAGE,
)
from middleware import (
    authenticate, get_body, req_string, req_enum, req_int, opt_field,
    new_entity, touch, public, get_or_404, sorted_by_created,
    parse_pagination, require_patient_entity, require_patient_ownership,
)
from response import success_object, success_list
from services import domain

bp = Blueprint("messages", __name__)

STAFF_READ = ["PracticeAdmin", "TriageNurse", "FrontDesk", "Provider", "BillingSpecialist"]
ALL_READ = STAFF_READ + ["Patient"]
URGENCIES = {"EMERGENT", "URGENT", "ROUTINE"}
CATEGORIES = {"CLINICAL", "ADMINISTRATIVE"}
WORKING_STATUSES = {"IN_REVIEW", "PENDING_CONSENT", "PENDING_COSIGN", "ESCALATED", "REOPENED"}


def _check_occ(message, body):
    expected = body.get("expected_message_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_message_version is required and must be an integer")
    if expected != message["version"]:
        raise_err(ERR_STALE_VERSION, "expected_message_version does not match current message version")


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages", methods=["POST"])
def create_message():
    ctx = authenticate(["Patient"])
    require_patient_entity(ctx)
    body = get_body()
    subject = req_string(body, "subject")
    text = req_string(body, "body")

    # Tier 8 business safety: education gate.
    if ctx.patient.get("education_gate_open"):
        raise_err(ERR_EDUCATION_ACK_REQUIRED,
                  "Patient has a blocking ISSUED education notice; acknowledge it before sending messages")

    message = new_entity({
        "patient_id": ctx.user_id,
        "subject": subject,
        "body": text,
        "received_at": CLOCK.now_iso(),
        "urgency": None,
        "category": None,
        "triaged_at": None,
        "assigned_pool_id": None,
        "assignee_id": None,
        "pending_cosign_by_id": None,
        "resolved_by_id": None,
        "resolved_at": None,
        "first_response_at": None,
        "response_due_at": None,
        "sla_breached": False,
        "billing_disposition": "UNDETERMINED",
        "clinical_minutes_total": 0,
        "reopen_count": 0,
        "resolution_summary": None,
        "status": "RECEIVED",
    })
    db.portal_messages[message["id"]] = message
    return success_object(public(message), 201)


@bp.route("/inbox/portal-messages", methods=["GET"])
def list_messages():
    ctx = authenticate(ALL_READ)
    limit, offset = parse_pagination()

    patient_id = opt_field(request.args, "patient_id")
    # Tier 4: Patient-role list calls MUST pass patient_id == own X-User-ID.
    if ctx.role == "Patient":
        require_patient_entity(ctx)
        if patient_id != ctx.user_id:
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH,
                      "Patient-role list calls must pass patient_id equal to X-User-ID")

    assigned_pool_id = opt_field(request.args, "assigned_pool_id")
    assignee_id = opt_field(request.args, "assignee_id")
    pending_cosign_by_id = opt_field(request.args, "pending_cosign_by_id")
    resolved_by_id = opt_field(request.args, "resolved_by_id")
    status = opt_field(request.args, "status")

    items = list(db.portal_messages.values())
    if patient_id is not None:
        items = [m for m in items if m["patient_id"] == patient_id]
    if assigned_pool_id is not None:
        items = [m for m in items if m.get("assigned_pool_id") == assigned_pool_id]
    if assignee_id is not None:
        items = [m for m in items if m.get("assignee_id") == assignee_id]
    if pending_cosign_by_id is not None:
        items = [m for m in items if m.get("pending_cosign_by_id") == pending_cosign_by_id]
    if resolved_by_id is not None:
        items = [m for m in items if m.get("resolved_by_id") == resolved_by_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    return success_list([public(m) for m in items[offset:offset + limit]], limit, offset, total)


@bp.route("/inbox/portal-messages/<mid>", methods=["GET"])
def get_message(mid):
    ctx = authenticate(ALL_READ)
    message = db.portal_messages.get(mid)
    if ctx.role == "Patient":
        # Ownership tier before existence for cross-patient access.
        if ctx.patient is None or (message is not None and message["patient_id"] != ctx.user_id):
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH, "Patients may only read their own messages")
        if message is None:
            # A Patient asking for a nonexistent id gets the ownership error
            # only when it could be someone else's; nonexistent -> 404.
            raise_err(ERR_NOT_FOUND, "message not found: %s" % mid)
    if message is None:
        raise_err(ERR_NOT_FOUND, "message not found: %s" % mid)
    return success_object(public(message))


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/triage", methods=["POST"])
def triage_message(mid):
    ctx = authenticate(["TriageNurse"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()

    _check_occ(message, body)  # tier 6 OCC

    if message["status"] not in ("RECEIVED", "TRIAGED", "REOPENED"):
        raise_err(ERR_MESSAGE_INVALID_STATE,
                  "Triage is valid only from RECEIVED, TRIAGED, or REOPENED")

    urgency = req_enum(body, "urgency", URGENCIES)
    category = req_enum(body, "category", CATEGORIES)
    pool_id = req_string(body, "pool_id")
    pool = get_or_404(db.pools, pool_id, "pool")

    was_reopened = message["status"] == "REOPENED"
    prior_assignee = message.get("assignee_id")

    message["urgency"] = urgency
    message["category"] = category
    message["assigned_pool_id"] = pool_id
    message["triaged_at"] = CLOCK.now_iso()
    message["status"] = "TRIAGED"
    # response_due_at per response_deadline; FROM_RECEIPT keeps ORIGINAL
    # received_at, FROM_TRIAGE uses latest triaged_at.
    message["response_due_at"] = domain.compute_response_due_at(message, pool)
    # sla_breached is sticky — never reset here.
    if was_reopened and prior_assignee:
        message["assignee_id"] = None  # returns to pool queue
    touch(message)

    if was_reopened and prior_assignee:
        domain.recompute_staff_counts(prior_assignee)

    return success_object(public(message))


# ---------------------------------------------------------------------------
# Assign / re-route
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/assign", methods=["POST"])
def assign_message(mid):
    ctx = authenticate(["TriageNurse"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()

    if message["status"] not in ("TRIAGED", "ASSIGNED"):
        raise_err(ERR_MESSAGE_INVALID_STATE, "Assign is valid only from TRIAGED or ASSIGNED")

    staff_id = opt_field(body, "staff_id")
    new_assignee = None
    if staff_id is not None:
        new_assignee = get_or_404(db.staff, staff_id, "staff member")

    prior_id = message.get("assignee_id")
    message["assignee_id"] = new_assignee["id"] if new_assignee else None
    message["status"] = "ASSIGNED"
    touch(message)

    # open_inbox_count maintenance (zero-sum reassign).
    affected = set()
    if prior_id:
        affected.add(prior_id)
    if new_assignee:
        affected.add(new_assignee["id"])
    for sid in affected:
        domain.recompute_staff_counts(sid)

    return success_object(public(message))


# ---------------------------------------------------------------------------
# Start review (claim from pool queue)
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/start-review", methods=["POST"])
def start_review(mid):
    ctx = authenticate(["TriageNurse", "FrontDesk", "Provider"])
    message = get_or_404(db.portal_messages, mid, "message")

    if message["status"] != "ASSIGNED":
        raise_err(ERR_MESSAGE_INVALID_STATE, "Start-review requires status ASSIGNED")

    pool = db.pools.get(message.get("assigned_pool_id"))
    pool_kind = pool["pool_kind"] if pool else None

    # Gate 1: pool-kind eligibility (or ACTIVE delegation for PROVIDER_INBOX).
    if not domain.pool_kind_eligible(ctx.staff["staff_type"], pool_kind, ctx.user_id,
                                     message.get("assigned_pool_id")):
        raise_err(ERR_POOL_ROLE_MISMATCH,
                  "Caller staff_type not eligible for the message's pool kind and no covering delegation grant")

    # Gate 2: active coverage (own window or ACTIVE grant) covering now.
    if not domain.has_coverage(ctx.user_id, message.get("assigned_pool_id")):
        raise_err(ERR_NO_ACTIVE_COVERAGE,
                  "Caller has no covering CoverageWindow and no covering ACTIVE DelegationGrant")

    # Claim only when unowned; never seize from a different owner.
    if message.get("assignee_id") is None:
        message["assignee_id"] = ctx.user_id
        message["status"] = "IN_REVIEW"
        touch(message)
        domain.recompute_staff_counts(ctx.user_id)
    elif message["assignee_id"] == ctx.user_id:
        message["status"] = "IN_REVIEW"
        touch(message)
    else:
        # Owned by someone else: claiming cannot seize it.
        raise_err(ERR_NOT_ASSIGNEE, "Message is assigned to a different staff member")

    return success_object(public(message))


# ---------------------------------------------------------------------------
# Reply (staff response / patient reopen)
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/reply", methods=["POST"])
def reply_message(mid):
    ctx = authenticate(["Patient", "TriageNurse", "FrontDesk", "Provider"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()
    req_string(body, "body")

    if ctx.role == "Patient":
        require_patient_ownership(ctx, message["patient_id"])
        if message["status"] != "RESOLVED":
            raise_err(ERR_MESSAGE_INVALID_STATE,
                      "Patient reply reopens only a RESOLVED message")
        message["status"] = "REOPENED"
        message["reopen_count"] += 1
        message["response_due_at"] = None  # cleared until next triage
        # resolved_by_id / resolved_at retained as history.
        assignee_id = message.get("assignee_id")
        touch(message)
        if assignee_id:
            domain.recompute_staff_counts(assignee_id)
        return success_object(public(message))

    # Staff reply: assignee only.
    if message.get("assignee_id") != ctx.user_id:
        raise_err(ERR_NOT_ASSIGNEE, "Staff reply requires caller == message.assignee_id")
    if message["status"] not in ("ASSIGNED", "IN_REVIEW", "PENDING_CONSENT",
                                 "PENDING_COSIGN", "ESCALATED", "REOPENED"):
        raise_err(ERR_MESSAGE_INVALID_STATE,
                  "Staff reply requires the message to be in an open working status")

    if message.get("first_response_at") is None:
        message["first_response_at"] = CLOCK.now_iso()
    domain.latch_sla_at_staff_reply(message)
    touch(message)
    return success_object(public(message))


# ---------------------------------------------------------------------------
# Complete (resolve or route to cosign)
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/complete", methods=["POST"])
def complete_message(mid):
    ctx = authenticate(["TriageNurse", "FrontDesk", "Provider"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()
    summary = req_string(body, "resolution_summary")

    if message["status"] != "IN_REVIEW":
        raise_err(ERR_MESSAGE_INVALID_STATE, "Complete requires status IN_REVIEW")
    if message.get("assignee_id") != ctx.user_id:
        raise_err(ERR_NOT_ASSIGNEE, "Complete requires caller == message.assignee_id")

    message["resolution_summary"] = summary

    # Cosign required iff category == CLINICAL AND assignee not PROVIDER.
    assignee = db.staff.get(message["assignee_id"])
    cosign_required = (message.get("category") == "CLINICAL"
                       and assignee is not None
                       and assignee["staff_type"] != "PROVIDER")

    if cosign_required:
        grant = domain.find_active_grant(message["assignee_id"], message.get("assigned_pool_id"))
        message["pending_cosign_by_id"] = grant["delegator_provider_id"] if grant else None
        message["status"] = "PENDING_COSIGN"
        touch(message)  # counts unchanged — PENDING_COSIGN is counted
    else:
        message["resolved_by_id"] = ctx.user_id
        message["resolved_at"] = CLOCK.now_iso()
        message["status"] = "RESOLVED"
        domain.latch_sla_at_resolution(message)
        touch(message)
        domain.recompute_staff_counts(ctx.user_id)

    return success_object(public(message))


# ---------------------------------------------------------------------------
# Cosign
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/cosign", methods=["POST"])
def cosign_message(mid):
    ctx = authenticate(["Provider"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()
    action = req_enum(body, "action", {"COSIGN", "RETURN"})

    if message["status"] != "PENDING_COSIGN":
        raise_err(ERR_NOT_AWAITING_COSIGN, "Message is not in PENDING_COSIGN")

    designee = message.get("pending_cosign_by_id")
    if designee is not None and ctx.user_id != designee:
        raise_err(ERR_NOT_AUTHORIZED_COSIGNER,
                  "Only the designated pending_cosign_by_id provider may cosign")

    assignee_id = message.get("assignee_id")
    if action == "COSIGN":
        message["resolved_by_id"] = ctx.user_id
        message["resolved_at"] = CLOCK.now_iso()
        message["status"] = "RESOLVED"
        domain.latch_sla_at_resolution(message)
        touch(message)
        if assignee_id:
            domain.recompute_staff_counts(assignee_id)
    else:  # RETURN
        message["pending_cosign_by_id"] = None
        message["status"] = "IN_REVIEW"
        touch(message)  # counts unchanged — both counted statuses

    return success_object(public(message))


# ---------------------------------------------------------------------------
# Escalate
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/escalate", methods=["POST"])
def escalate_message(mid):
    ctx = authenticate(["TriageNurse", "Provider"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()
    reason = req_string(body, "reason")

    if message["status"] not in ("TRIAGED", "ASSIGNED", "IN_REVIEW"):
        raise_err(ERR_MESSAGE_INVALID_STATE,
                  "Escalate requires status TRIAGED, ASSIGNED, or IN_REVIEW")
    if message.get("urgency") not in ("URGENT", "EMERGENT"):
        raise_err(ERR_URGENCY_NOT_ESCALATABLE,
                  "Escalation requires urgency URGENT or EMERGENT")

    provider = domain.select_on_call_provider()
    if provider is None:
        raise_err(ERR_NO_ONCALL_COVERAGE, "No PROVIDER with an on-call shift covering now")

    escalation = new_entity({
        "message_id": message["id"],
        "provider_id": provider["id"],
        "reason": reason,
        "status": "OPEN",
        "acknowledged_at": None,
    })
    db.escalations[escalation["id"]] = escalation

    prior_id = message.get("assignee_id")
    message["assignee_id"] = provider["id"]
    message["status"] = "ESCALATED"
    touch(message)

    affected = {provider["id"]}
    if prior_id:
        affected.add(prior_id)
    for sid in affected:
        domain.recompute_staff_counts(sid)

    return success_object(public(escalation), 201)


# ---------------------------------------------------------------------------
# Determine billing
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/determine-billing", methods=["POST"])
def determine_billing(mid):
    ctx = authenticate(["Provider"])
    message = get_or_404(db.portal_messages, mid, "message")
    body = get_body()

    _check_occ(message, body)  # tier 6 OCC

    if message["status"] != "IN_REVIEW":
        raise_err(ERR_MESSAGE_INVALID_STATE, "Determine-billing requires status IN_REVIEW")

    disposition = req_enum(body, "disposition", {"BILLABLE_CANDIDATE", "NOT_BILLABLE"})

    if disposition == "BILLABLE_CANDIDATE":
        # Business-rule order per PRD §3.6: category, 7-day dedupe, pending
        # consent, claim in flight, minimum minutes.
        if message.get("category") != "CLINICAL":
            raise_err(ERR_CATEGORY_NOT_CLINICAL,
                      "BILLABLE_CANDIDATE determination requires category CLINICAL")

        # 7-day dedupe: (received_at - 168h, received_at] — exclusive lower.
        received = _parse_dt(message["received_at"])
        lower = received - timedelta(hours=168)
        for other in db.portal_messages.values():
            if other["id"] == message["id"]:
                continue
            if other["patient_id"] != message["patient_id"]:
                continue
            if other.get("billing_disposition") != "CHARGEABLE":
                continue
            other_received = _parse_dt(other["received_at"])
            if lower < other_received <= received:
                raise_err(ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS,
                          "Another CHARGEABLE message of this patient was received within the trailing 168h")

        if domain.requested_consent_for_message(message["id"]) is not None:
            raise_err(ERR_CONSENT_REQUEST_PENDING,
                      "A REQUESTED ConsentRecord already exists for this message")

        for claim in domain.claims_for_message(message["id"]):
            if claim["status"] in domain.CLAIM_IN_FLIGHT_FOR_REDETERMINE:
                raise_err(ERR_CLAIM_IN_FLIGHT,
                          "A claim in SUBMITTED or DENIED blocks re-determination")

        minutes = message.get("clinical_minutes_total", 0)
        tier = domain.evisit_tier(minutes)
        if tier is None:
            raise_err(ERR_EVISIT_MINUTES_BELOW_MINIMUM,
                      "clinical_minutes_total must be at least 5 for BILLABLE_CANDIDATE")
        code, fee = tier

        # Supersede prior GRANTED/DECLINED consents, then create the new
        # REQUESTED record with version-pinned disclosed code/fee.
        domain.supersede_responded_consents(message["id"])
        consent = new_entity({
            "message_id": message["id"],
            "patient_id": message["patient_id"],
            "status": "REQUESTED",
            "disclosed_code": code,
            "disclosed_fee_cents": fee,
            "requested_at": CLOCK.now_iso(),
            "responded_at": None,
        })
        db.consent_records[consent["id"]] = consent

        message["billing_disposition"] = "BILLABLE_CANDIDATE"
        message["status"] = "PENDING_CONSENT"
        touch(message)  # counts unchanged — both counted statuses
        return success_object(public(message))

    # NOT_BILLABLE
    if domain.requested_consent_for_message(message["id"]) is not None:
        raise_err(ERR_CONSENT_REQUEST_PENDING,
                  "A REQUESTED ConsentRecord already exists for this message")
    for claim in domain.claims_for_message(message["id"]):
        if claim["status"] in domain.CLAIM_IN_FLIGHT_FOR_REDETERMINE:
            raise_err(ERR_CLAIM_IN_FLIGHT,
                      "A claim in SUBMITTED or DENIED blocks re-determination")
    domain.supersede_responded_consents(message["id"])
    message["billing_disposition"] = "NOT_BILLABLE"
    touch(message)  # stays IN_REVIEW
    return success_object(public(message))


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------

@bp.route("/inbox/portal-messages/<mid>/close", methods=["POST"])
def close_message(mid):
    ctx = authenticate(["TriageNurse", "Provider"])
    message = get_or_404(db.portal_messages, mid, "message")

    if message["status"] != "RESOLVED":
        raise_err(ERR_MESSAGE_INVALID_STATE, "Close requires status RESOLVED")
    for claim in domain.claims_for_message(message["id"]):
        if claim["status"] in domain.CLAIM_IN_FLIGHT_FOR_CLOSE:
            raise_err(ERR_CLAIM_IN_FLIGHT,
                      "Close blocked by a claim in DRAFT, SUBMITTED, or DENIED")

    message["status"] = "CLOSED"
    touch(message)
    return success_object(public(message))

"""Restitution payments, enforcement referrals, scam alerts, audit events."""

from flask import Blueprint, request

import domain
from domain import (
    alert_view, compute_allocations, eligible_obligations, event_view,
    payment_view, referral_view, recompute_pattern_score, run_closure_ritual,
    write_event,
)
from helpers import (
    auth, caller_role, check_complaint_party, complaint_visible_to, fail,
    json_body, list_response, new_record, ok_object, opt_string_list,
    req_enum, req_int, req_string, touch,
)
from store import db

bp = Blueprint("resolution", __name__)

READERS = (
    "Consumer", "Business", "IntakeOfficer", "Mediator",
    "EnforcementAttorney", "UnitDirector",
)
ALL = READERS + ("Anonymous",)


def _get_payment(paymentId):
    rec = db.payments.get(paymentId)
    if rec is None:
        fail("ERR_PAYMENT_NOT_FOUND", "payment does not exist")
    return rec


def _get_referral(referralId):
    rec = db.referrals.get(referralId)
    if rec is None:
        fail("ERR_REFERRAL_NOT_FOUND", "referral does not exist")
    return rec


def _get_alert(alertId):
    rec = db.alerts.get(alertId)
    if rec is None:
        fail("ERR_ALERT_NOT_FOUND", "alert does not exist")
    return rec


def _payment_visible_to(payment, uid, role):
    if role == "Business":
        return payment["business_id"] == uid
    if role == "Consumer":
        # A consumer sees payments that funded one of their complaints.
        for alloc in payment["allocations"]:
            complaint = db.complaints.get(alloc["complaint_id"])
            if complaint is not None and complaint["consumer_id"] == uid:
                return True
        return False
    return True


def _check_payment_read(payment, uid, role):
    if not _payment_visible_to(payment, uid, role):
        fail("ERR_NOT_RESOURCE_OWNER", "payment is outside the caller's scope")


# ---------------------------------------------------------------------------
# Restitution payments (PRD section 3.7)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/businesses/<businessId>/restitution-payments")
def pledge_payment(businessId):
    uid = auth("Business")
    data = json_body()

    # Priority 3 (ownership): the payment's business must be the caller.
    body_business_id = data.get("business_id")
    if isinstance(body_business_id, str) and body_business_id != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "business_id must equal the caller's X-User-ID")

    # Priority 4 (existence): path identifier, then body foreign key.
    business = db.businesses.get(businessId)
    if business is None:
        fail("ERR_BUSINESS_NOT_FOUND", "business does not exist")
    if isinstance(body_business_id, str) and body_business_id not in db.businesses:
        fail("ERR_BUSINESS_NOT_FOUND", "business_id does not resolve")

    # Priority 5 (shape).
    if not isinstance(body_business_id, str) or not body_business_id:
        fail("ERR_INVALID_REQUEST", "business_id is required and must be a string")
    if body_business_id != businessId:
        fail("ERR_INVALID_REQUEST", "business_id must match the path business")
    amount = data.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        fail("ERR_INVALID_REQUEST", "amount_cents is required and must be an integer")
    if amount <= 0:
        fail("ERR_INVALID_AMOUNT", "amount_cents must be strictly greater than zero")
    allocation_method = data.get("allocation_method", "CHRONOLOGICAL")
    if allocation_method not in domain.ALLOCATION_METHODS:
        fail("ERR_INVALID_REQUEST", "allocation_method must be CHRONOLOGICAL or PRO_RATA")

    rec = new_record()
    rec.update({
        "business_id": businessId,
        "amount_cents": amount,
        "allocation_method": allocation_method,
        "payment_status": "PLEDGED",
        "allocations": [],
        "received_at": None,
    })
    db.payments[rec["id"]] = rec
    return ok_object(payment_view(rec), 201)


@bp.get("/consumer-protection/restitution-payments")
def list_payments():
    uid = auth(*READERS)
    role = caller_role()
    items = [p for p in db.payments.values() if _payment_visible_to(p, uid, role)]
    f_business = request.args.get("business_id")
    if f_business is not None:
        items = [p for p in items if p["business_id"] == f_business]
    return list_response(items, payment_view)


@bp.get("/consumer-protection/restitution-payments/<paymentId>")
def get_payment(paymentId):
    uid = auth(*READERS)
    role = caller_role()
    rec = _get_payment(paymentId)
    _check_payment_read(rec, uid, role)
    return ok_object(payment_view(rec))


@bp.post("/consumer-protection/restitution-payments/<paymentId>/mark-received")
def mark_received(paymentId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_payment(paymentId)
    # Priority 6 (state) precedes the priority-11 fiscal gate.
    if rec["payment_status"] != "PLEDGED":
        fail("ERR_INVALID_STATE", "only a PLEDGED payment can be marked received")
    obligations = eligible_obligations(rec["business_id"])
    total_open = sum(s["outstanding_cents"] for _, s in obligations)
    if rec["amount_cents"] > total_open:
        fail("ERR_RESTITUTION_EXCEEDS_OUTSTANDING",
             "payment exceeds the business's total open outstanding")

    lines = compute_allocations(rec, obligations)
    rec["payment_status"] = "ALLOCATED"
    rec["received_at"] = db.now
    rec["allocations"] = [
        {
            "settlement_id": settlement["id"],
            "complaint_id": complaint["id"],
            "filing_seq": filing_seq,
            "allocated_cents": cents,
        }
        for settlement, complaint, filing_seq, cents in lines
    ]
    touch(rec)

    # Allocation cascade: settlement fulfillment, then complaint settlement.
    for settlement, complaint, filing_seq, cents in lines:
        settlement["fulfilled_cents"] += cents
        settlement["outstanding_cents"] -= cents
        fulfilled_now = False
        if settlement["outstanding_cents"] == 0:
            settlement["settlement_status"] = "FULFILLED"
            settlement["fulfilled_at"] = db.now
            fulfilled_now = True
        touch(settlement)
        settled_now = False
        frm = complaint["case_status"]
        if fulfilled_now and frm == "SETTLEMENT_PENDING":
            run_closure_ritual(complaint, "SETTLED")
            touch(complaint)
            settled_now = True
        write_event(
            complaint["id"], "PAYMENT_ALLOCATED",
            frm if settled_now else None,
            "SETTLED" if settled_now else None,
            role, uid,
            "allocated %d cents to settlement %s (filing_seq %d)"
            % (cents, settlement["id"], filing_seq),
        )
    return ok_object(payment_view(rec))


@bp.post("/consumer-protection/restitution-payments/<paymentId>/mark-returned")
def mark_returned(paymentId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_payment(paymentId)
    if rec["payment_status"] != "ALLOCATED":
        fail("ERR_INVALID_STATE", "only an ALLOCATED payment can be returned")
    # Blocked once any funded complaint has reached SETTLED.
    affected = []
    for alloc in rec["allocations"]:
        complaint = db.complaints.get(alloc["complaint_id"])
        if complaint is not None and complaint["case_status"] == "SETTLED":
            fail("ERR_INVALID_STATE", "a funded complaint is already SETTLED")
        settlement = db.settlements.get(alloc["settlement_id"])
        if complaint is not None and settlement is not None:
            affected.append((settlement, complaint, alloc))

    for settlement, complaint, alloc in affected:
        settlement["fulfilled_cents"] -= alloc["allocated_cents"]
        settlement["outstanding_cents"] += alloc["allocated_cents"]
        if settlement["settlement_status"] == "FULFILLED":
            settlement["settlement_status"] = "EXECUTED"
            settlement["fulfilled_at"] = None
        touch(settlement)
    rec["payment_status"] = "RETURNED"
    rec["allocations"] = []
    touch(rec)
    for settlement, complaint, alloc in affected:
        write_event(
            complaint["id"], "PAYMENT_RETURNED", None, None, role, uid,
            "returned %d cents from settlement %s"
            % (alloc["allocated_cents"], settlement["id"]),
        )
    return ok_object(payment_view(rec))


@bp.post("/consumer-protection/restitution-payments/<paymentId>/disburse")
def disburse_payment(paymentId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_payment(paymentId)
    if rec["payment_status"] != "ALLOCATED":
        fail("ERR_INVALID_STATE", "only an ALLOCATED payment can be disbursed")
    rec["payment_status"] = "DISBURSED"
    touch(rec)
    for alloc in rec["allocations"]:
        complaint = db.complaints.get(alloc["complaint_id"])
        if complaint is not None:
            write_event(
                complaint["id"], "PAYMENT_DISBURSED", None, None, role, uid,
                "disbursed %d cents to the consumer" % alloc["allocated_cents"],
            )
    return ok_object(payment_view(rec))


# ---------------------------------------------------------------------------
# Enforcement referrals (PRD section 3.8)
# ---------------------------------------------------------------------------

@bp.get("/consumer-protection/enforcement-referrals")
def list_referrals():
    uid = auth(*READERS)
    role = caller_role()
    items = []
    for r in db.referrals.values():
        complaint = db.complaints.get(r["complaint_id"])
        if complaint is not None and complaint_visible_to(complaint, uid, role):
            items.append(r)
    f_complaint = request.args.get("complaint_id")
    if f_complaint is not None:
        items = [r for r in items if r["complaint_id"] == f_complaint]
    f_business = request.args.get("business_id")
    if f_business is not None:
        items = [r for r in items if r["business_id"] == f_business]
    f_status = request.args.get("referral_status")
    if f_status is not None:
        items = [r for r in items if r["referral_status"] == f_status]
    return list_response(items, referral_view)


@bp.get("/consumer-protection/enforcement-referrals/<referralId>")
def get_referral(referralId):
    uid = auth(*READERS)
    role = caller_role()
    rec = _get_referral(referralId)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return ok_object(referral_view(rec))


@bp.post("/consumer-protection/enforcement-referrals/<referralId>/review")
def review_referral(referralId):
    uid = auth("EnforcementAttorney")
    role = caller_role()
    rec = _get_referral(referralId)
    data = json_body()
    decision = req_enum(data, "decision", domain.REFERRAL_DECISIONS)
    if rec["referral_status"] != "PENDING_REVIEW":
        fail("ERR_INVALID_STATE", "only a PENDING_REVIEW referral can be reviewed")
    if uid == rec["referred_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the referrer may not review this referral")
    rec["reviewed_by_user_id"] = uid
    complaint = db.complaints.get(rec["complaint_id"])
    if decision == "ACCEPT":
        rec["referral_status"] = "ACCEPTED"
        touch(rec)
    else:
        rec["referral_status"] = "RETURNED_TO_MEDIATION"
        touch(rec)
        if complaint is not None:
            frm = complaint["case_status"]
            complaint["case_status"] = "MEDIATION_IMPASSE"
            complaint["closed_at"] = None
            if complaint["publication_status"] == "EMBARGOED":
                complaint["publication_status"] = "UNPUBLISHED"
            touch(complaint)
            business = db.businesses.get(complaint["business_id"])
            if business is not None:
                recompute_pattern_score(business)
            write_event(complaint["id"], "REFERRAL_RETURNED", frm, "MEDIATION_IMPASSE",
                        role, uid, "referral returned to mediation")
    return ok_object(referral_view(rec))


# ---------------------------------------------------------------------------
# Scam alerts (PRD section 3.9)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/scam-alerts")
def draft_alert():
    uid = auth("IntakeOfficer", "UnitDirector")
    data = json_body()

    # Priority 4 (existence): optional body foreign keys resolve.
    related_business_id = data.get("related_business_id")
    if related_business_id is not None:
        if not isinstance(related_business_id, str):
            fail("ERR_INVALID_REQUEST", "related_business_id must be a string")
        if related_business_id not in db.businesses:
            fail("ERR_BUSINESS_NOT_FOUND", "related_business_id does not resolve")
    related_complaint_id = data.get("related_complaint_id")
    if related_complaint_id is not None:
        if not isinstance(related_complaint_id, str):
            fail("ERR_INVALID_REQUEST", "related_complaint_id must be a string")
        if related_complaint_id not in db.complaints:
            fail("ERR_COMPLAINT_NOT_FOUND", "related_complaint_id does not resolve")

    # Priority 5 (shape).
    title = req_string(data, "title")
    body = req_string(data, "body")
    scam_category = req_enum(data, "scam_category", domain.SCAM_CATEGORIES)
    severity = req_enum(data, "severity", domain.SEVERITIES)
    education_topics = opt_string_list(data, "education_topics", [])

    rec = new_record()
    rec.update({
        "title": title,
        "body": body,
        "scam_category": scam_category,
        "severity": severity,
        "related_business_id": related_business_id,
        "related_complaint_id": related_complaint_id,
        "education_topics": list(education_topics),
        "drafted_by_user_id": uid,
        "alert_status": "DRAFT",
        "published_at": None,
    })
    db.alerts[rec["id"]] = rec
    return ok_object(alert_view(rec), 201)


@bp.get("/consumer-protection/scam-alerts")
def list_alerts():
    auth(*ALL)
    items = list(db.alerts.values())
    f_business = request.args.get("related_business_id")
    if f_business is not None:
        items = [a for a in items if a["related_business_id"] == f_business]
    f_complaint = request.args.get("related_complaint_id")
    if f_complaint is not None:
        items = [a for a in items if a["related_complaint_id"] == f_complaint]
    f_status = request.args.get("alert_status")
    if f_status is not None:
        items = [a for a in items if a["alert_status"] == f_status]
    return list_response(items, alert_view)


@bp.get("/consumer-protection/scam-alerts/<alertId>")
def get_alert(alertId):
    auth(*ALL)
    return ok_object(alert_view(_get_alert(alertId)))


@bp.post("/consumer-protection/scam-alerts/<alertId>/publish")
def publish_alert(alertId):
    uid = auth("UnitDirector")
    rec = _get_alert(alertId)
    if rec["alert_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT alert can be published")
    # Priority 7 (segregation of duties) precedes the priority-8 duplicate gate.
    if uid == rec["drafted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the drafter may not publish this alert")
    for a in db.alerts.values():
        if (
            a["id"] != rec["id"]
            and a["title"] == rec["title"]
            and a["related_business_id"] == rec["related_business_id"]
            and a["alert_status"] in ("DRAFT", "PUBLISHED")
        ):
            fail("ERR_DUPLICATE_ACTIVE_ALERT",
                 "an active alert with the same title and related business exists")
    rec["alert_status"] = "PUBLISHED"
    rec["published_at"] = db.now
    touch(rec)
    return ok_object(alert_view(rec))


@bp.post("/consumer-protection/scam-alerts/<alertId>/archive")
def archive_alert(alertId):
    auth("UnitDirector")
    rec = _get_alert(alertId)
    if rec["alert_status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE", "only a PUBLISHED alert can be archived")
    rec["alert_status"] = "ARCHIVED"
    touch(rec)
    return ok_object(alert_view(rec))


# ---------------------------------------------------------------------------
# Case event trail (PRD section 2.4)
# ---------------------------------------------------------------------------

@bp.get("/consumer-protection/complaint-events")
def list_events():
    uid = auth(*READERS)
    role = caller_role()
    items = []
    for e in db.events.values():
        complaint = db.complaints.get(e["complaint_id"])
        if complaint is not None and complaint_visible_to(complaint, uid, role):
            items.append(e)
    f_complaint = request.args.get("complaint_id")
    if f_complaint is not None:
        items = [e for e in items if e["complaint_id"] == f_complaint]
    return list_response(items, event_view)


@bp.get("/consumer-protection/complaint-events/<eventId>")
def get_event(eventId):
    uid = auth(*READERS)
    role = caller_role()
    rec = db.events.get(eventId)
    if rec is None:
        # The error catalog defines no event-not-found id; fall back to the
        # generic request error.
        fail("ERR_INVALID_REQUEST", "event does not exist")
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return ok_object(event_view(rec))

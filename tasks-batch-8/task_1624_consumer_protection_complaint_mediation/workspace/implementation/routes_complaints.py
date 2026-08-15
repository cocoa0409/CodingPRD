"""Complaint intake, screening, response cycle, closure, referral routes."""

from datetime import timedelta

from flask import Blueprint, request

import domain
from domain import (
    complaint_view, recompute_rating, referral_view, response_view,
    run_closure_ritual, write_event,
)
from helpers import (
    auth, caller_role, check_complaint_party, complaint_visible_to, fail,
    json_body, list_response, new_record, ok_object, opt_bool, req_date,
    req_enum, req_int, req_string, touch,
)
from store import db

bp = Blueprint("complaints", __name__)

STAFF_AND_PARTIES = (
    "Consumer", "Business", "IntakeOfficer", "Mediator",
    "EnforcementAttorney", "UnitDirector",
)


def _get_complaint(complaintId):
    rec = db.complaints.get(complaintId)
    if rec is None:
        fail("ERR_COMPLAINT_NOT_FOUND", "complaint does not exist")
    return rec


def _transition(complaint, to_status, actor_role, actor_id, note=""):
    """Case-axis transition + STATE_CHANGED event + touch."""
    frm = complaint["case_status"]
    complaint["case_status"] = to_status
    touch(complaint)
    write_event(complaint["id"], "STATE_CHANGED", frm, to_status,
                actor_role, actor_id, note)


# ---------------------------------------------------------------------------
# Complaint filing and reads (PRD section 3.2)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints")
def create_complaint():
    uid = auth("Consumer")
    role = caller_role()
    data = json_body()

    # Priority 3 (ownership): consumer_id must be the caller's own identifier.
    consumer_id = data.get("consumer_id")
    if not isinstance(consumer_id, str) or not consumer_id:
        fail("ERR_INVALID_REQUEST", "consumer_id is required and must be a string")
    if consumer_id != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "consumer_id must equal the caller's X-User-ID")

    # Priority 4 (existence): body foreign keys resolve.
    consumer = db.consumers.get(consumer_id)
    if consumer is None:
        fail("ERR_CONSUMER_NOT_FOUND", "consumer does not exist")
    business_id = data.get("business_id")
    if not isinstance(business_id, str) or not business_id:
        fail("ERR_INVALID_REQUEST", "business_id is required and must be a string")
    business = db.businesses.get(business_id)
    if business is None:
        fail("ERR_BUSINESS_NOT_FOUND", "business does not exist")

    # Priority 5 (request shape).
    incident_date_raw = data.get("incident_date")
    incident_date = req_date(data, "incident_date")
    incident_state = req_string(data, "incident_state")
    category = req_enum(data, "category", domain.CATEGORIES)
    description = req_string(data, "description")
    amount = req_int(data, "amount_in_dispute_cents")
    if amount < 0:
        fail("ERR_INVALID_REQUEST", "amount_in_dispute_cents may be zero but never negative")
    publication_consent = opt_bool(data, "publication_consent", True)

    # Priority 7 (regulatory gate): the 365-day filing window, whole days;
    # exactly 365 is eligible.
    elapsed_days = (db.now.date() - incident_date).days
    within_window = elapsed_days <= domain.FILING_WINDOW_DAYS
    if not within_window:
        fail("ERR_FILING_WINDOW_EXPIRED", "incident is more than 365 days before filing")

    # Priority 8 (uniqueness): the same grievance is not worked twice unless
    # the earlier complaint sits in DECLINED.
    for c in db.complaints.values():
        if (
            c["consumer_id"] == consumer_id
            and c["business_id"] == business_id
            and c["incident_date"] == incident_date_raw
            and c["category"] == category
            and c["case_status"] != "DECLINED"
        ):
            fail("ERR_DUPLICATE_COMPLAINT", "a matching open complaint already exists")

    rec = new_record()
    rec.update({
        "consumer_id": consumer_id,
        "business_id": business_id,
        "incident_date": incident_date_raw,
        "incident_state": incident_state,
        "category": category,
        "description": description,
        "amount_in_dispute_cents": amount,
        "publication_consent": publication_consent,
        "filing_seq": business["next_filing_seq"],
        "filed_at": db.now,
        "case_status": "RECEIVED",
        "publication_status": "UNPUBLISHED",
        "decline_reason": None,
        "appeal_used": False,
        "jurisdiction_factors": {
            "incident_in_state": incident_state == "OR",
            "business_operates_in_state": "OR" in business["operates_in_states"],
            "within_filing_window": within_window,
        },
        "accepted_by_officer_id": None,
        "closed_by_officer_id": None,
        "closed_at": None,
        "response_deadline": None,
        "response_received_at": None,
        "response_attempts": 0,
        "latest_response_id": None,
        "ever_response_overdue": False,
        "active_settlement_id": None,
        "alternative_options": None,
        "closure_summary": None,
    })
    db.complaints[rec["id"]] = rec
    business["next_filing_seq"] += 1
    touch(business)
    write_event(rec["id"], "CREATED", None, None, role, uid, "complaint filed")
    return ok_object(complaint_view(rec), 201)


@bp.get("/consumer-protection/complaints")
def list_complaints():
    uid = auth(*STAFF_AND_PARTIES)
    role = caller_role()
    args = request.args
    f_consumer = args.get("consumer_id")
    f_business = args.get("business_id")
    # Priority 3: party callers' own-kind filters must equal their identifier.
    if role == "Consumer" and f_consumer is not None and f_consumer != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "consumer_id filter must equal the caller's id")
    if role == "Business" and f_business is not None and f_business != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "business_id filter must equal the caller's id")
    items = [c for c in db.complaints.values() if complaint_visible_to(c, uid, role)]
    if f_consumer is not None:
        items = [c for c in items if c["consumer_id"] == f_consumer]
    if f_business is not None:
        items = [c for c in items if c["business_id"] == f_business]
    f_case = args.get("case_status")
    if f_case is not None:
        items = [c for c in items if c["case_status"] == f_case]
    f_pub = args.get("publication_status")
    if f_pub is not None:
        items = [c for c in items if c["publication_status"] == f_pub]
    return list_response(items, complaint_view)


@bp.get("/consumer-protection/complaints/<complaintId>")
def get_complaint(complaintId):
    uid = auth(*STAFF_AND_PARTIES)
    role = caller_role()
    rec = _get_complaint(complaintId)
    check_complaint_party(rec, uid, role)
    return ok_object(complaint_view(rec))


# ---------------------------------------------------------------------------
# Screening, appeal, withdrawal (PRD section 3.2)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints/<complaintId>/screen")
def screen_complaint(complaintId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    data = json_body()
    decision = req_enum(data, "decision", domain.DECISIONS)
    decline_reason = None
    if decision == "DECLINE":
        decline_reason = data.get("decline_reason")
        if decline_reason not in domain.DECLINE_REASONS:
            fail(
                "ERR_INVALID_REQUEST",
                "decline_reason must be one of NO_JURISDICTION, OUT_OF_AUTHORITY, DUPLICATE",
            )
    if rec["case_status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "only a RECEIVED complaint can be screened")
    if decision == "ACCEPT":
        business = db.businesses[rec["business_id"]]
        has_jurisdiction = (
            rec["incident_state"] == "OR"
            or "OR" in business["operates_in_states"]
        )
        if not has_jurisdiction:
            fail("ERR_NO_JURISDICTION", "no Oregon nexus for this complaint")
        rec["accepted_by_officer_id"] = uid
        _transition(rec, "ACCEPTED", role, uid, "screened: accepted")
    else:
        rec["decline_reason"] = decline_reason
        rec["closed_at"] = db.now
        _transition(rec, "DECLINED", role, uid, "screened: declined")
    return ok_object(complaint_view(rec))


@bp.post("/consumer-protection/complaints/<complaintId>/appeal")
def appeal_complaint(complaintId):
    uid = auth("Consumer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    check_complaint_party(rec, uid, role)
    if rec["case_status"] != "DECLINED":
        fail("ERR_INVALID_STATE", "only a DECLINED complaint can be appealed")
    if rec["decline_reason"] == "WITHDRAWN":
        fail("ERR_INVALID_STATE", "a withdrawn complaint can never be appealed")
    if rec["appeal_used"]:
        fail("ERR_APPEAL_ALREADY_USED", "the single permitted appeal was already used")
    rec["appeal_used"] = True
    rec["decline_reason"] = None
    rec["closed_at"] = None
    _transition(rec, "RECEIVED", role, uid, "appeal reopens the complaint")
    return ok_object(complaint_view(rec))


@bp.post("/consumer-protection/complaints/<complaintId>/withdraw")
def withdraw_complaint(complaintId):
    uid = auth("Consumer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    check_complaint_party(rec, uid, role)
    if rec["case_status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "only an unscreened (RECEIVED) complaint can be withdrawn")
    rec["decline_reason"] = "WITHDRAWN"
    rec["closed_at"] = db.now
    _transition(rec, "DECLINED", role, uid, "consumer withdrew the complaint")
    return ok_object(complaint_view(rec))


# ---------------------------------------------------------------------------
# Notification and the response cycle (PRD section 3.3)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints/<complaintId>/notify-business")
def notify_business(complaintId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    if rec["case_status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "only an ACCEPTED complaint can be notified")
    business = db.businesses[rec["business_id"]]
    days = domain.RESPONSE_BASE_DAYS
    if business["home_state"] != rec["incident_state"]:
        days += domain.OUT_OF_STATE_EXTENSION_DAYS
    rec["response_deadline"] = db.now + timedelta(days=days)
    _transition(rec, "BUSINESS_NOTIFIED", role, uid, "business notified; response deadline set")
    return ok_object(complaint_view(rec))


@bp.post("/consumer-protection/complaints/<complaintId>/business-responses")
def submit_response(complaintId):
    uid = auth("Business")
    role = caller_role()
    rec = _get_complaint(complaintId)
    check_complaint_party(rec, uid, role)
    data = json_body()
    response_text = req_string(data, "response_text")
    if rec["case_status"] not in ("BUSINESS_NOTIFIED", "RESPONSE_OVERDUE"):
        fail("ERR_INVALID_STATE", "complaint is not awaiting a business response")
    if rec["response_attempts"] >= 3:
        fail("ERR_RESUBMISSION_CAP_REACHED", "a complaint accepts at most three responses")
    resp = new_record()
    resp.update({
        "complaint_id": rec["id"],
        "business_id": rec["business_id"],
        "response_text": response_text,
        "submitted_at": db.now,
        "is_late": db.now > rec["response_deadline"],
        "response_status": "SUBMITTED",
        "attempt_number": rec["response_attempts"] + 1,
    })
    db.responses[resp["id"]] = resp
    frm = rec["case_status"]
    rec["response_received_at"] = db.now
    rec["response_attempts"] += 1
    rec["latest_response_id"] = resp["id"]
    rec["case_status"] = "RESPONSE_RECEIVED"
    touch(rec)
    write_event(rec["id"], "RESPONSE_FILED", frm, "RESPONSE_RECEIVED",
                role, uid, "business response attempt %d" % resp["attempt_number"])
    return ok_object(response_view(resp), 201)


@bp.post("/consumer-protection/complaints/<complaintId>/offer-mediation")
def offer_mediation(complaintId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    if rec["case_status"] == "RESPONSE_RECEIVED":
        latest = db.responses.get(rec["latest_response_id"])
        if latest is None or latest["response_status"] != "SUFFICIENT":
            fail("ERR_INVALID_STATE", "latest response must be SUFFICIENT before mediation")
    elif rec["case_status"] != "RESPONSE_OVERDUE":
        fail("ERR_INVALID_STATE", "complaint is not in a mediable state")
    business = db.businesses[rec["business_id"]]
    if business["watch_status"] == "FLAGGED":
        fail("ERR_PATTERN_REFERRAL_REQUIRED",
             "business is FLAGGED; the case belongs with enforcement")
    _transition(rec, "MEDIATION_OFFERED", role, uid, "voluntary mediation offered")
    return ok_object(complaint_view(rec))


# ---------------------------------------------------------------------------
# Closure, retraction, referral (PRD sections 3.8 / 3.9)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints/<complaintId>/close-unresolved")
def close_unresolved(complaintId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    data = json_body()
    options = data.get("alternative_options")
    if (
        not isinstance(options, list)
        or len(options) == 0
        or any(o not in domain.ALTERNATIVE_OPTIONS for o in options)
    ):
        fail("ERR_INVALID_REQUEST",
             "alternative_options must be a non-empty subset of SMALL_CLAIMS, "
             "PRIVATE_ATTORNEY, BBB, FEDERAL_AGENCY, CLASS_ACTION")
    closure_summary = req_string(data, "closure_summary")
    if rec["case_status"] not in (
        "RESPONSE_RECEIVED", "RESPONSE_OVERDUE", "MEDIATION_OFFERED",
        "MEDIATION_ACTIVE", "MEDIATION_IMPASSE",
    ):
        fail("ERR_INVALID_STATE", "complaint is not in a closable state")
    # Nothing may be left in flight (state-category preconditions).
    for o in db.offers.values():
        if o["complaint_id"] == rec["id"] and o["offer_status"] in ("TENDERED", "ACCEPTED"):
            fail("ERR_INVALID_STATE", "an open settlement offer blocks closure")
    for s in db.settlements.values():
        if s["complaint_id"] == rec["id"] and s["settlement_status"] in (
            "DRAFT", "EXECUTED", "BREACHED"
        ):
            fail("ERR_INVALID_STATE", "an open settlement blocks closure")
    for s in db.sessions.values():
        if s["complaint_id"] == rec["id"] and s["session_status"] in ("PROPOSED", "CONFIRMED"):
            fail("ERR_INVALID_STATE", "an open mediation session blocks closure")
    # Segregation of duties: the acceptor may not close the case.
    if uid == rec["accepted_by_officer_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the accepting officer may not close this complaint")
    frm = rec["case_status"]
    rec["closed_by_officer_id"] = uid
    rec["alternative_options"] = list(options)
    rec["closure_summary"] = closure_summary
    run_closure_ritual(rec, "CLOSED_UNRESOLVED")
    touch(rec)
    write_event(rec["id"], "CASE_CLOSED", frm, "CLOSED_UNRESOLVED",
                role, uid, "closed unresolved; alternatives: %s" % ", ".join(options))
    return ok_object(complaint_view(rec))


@bp.post("/consumer-protection/complaints/<complaintId>/retract-publication")
def retract_publication(complaintId):
    uid = auth("Consumer")
    role = caller_role()
    rec = _get_complaint(complaintId)
    check_complaint_party(rec, uid, role)
    if rec["publication_status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE", "only a PUBLISHED complaint can be retracted")
    rec["publication_status"] = "REDACTED"
    touch(rec)
    business = db.businesses.get(rec["business_id"])
    if business is not None:
        business["published_complaint_count"] -= 1
        touch(business)
        recompute_rating(business)
    write_event(rec["id"], "REDACTED", "PUBLISHED", "REDACTED",
                role, uid, "consumer retracted publication")
    return ok_object(complaint_view(rec))


@bp.post("/consumer-protection/complaints/<complaintId>/refer-enforcement")
def refer_enforcement(complaintId):
    uid = auth("IntakeOfficer", "Mediator", "UnitDirector")
    role = caller_role()
    rec = _get_complaint(complaintId)
    data = json_body()
    reason = req_string(data, "reason")
    if rec["case_status"] not in (
        "ACCEPTED", "BUSINESS_NOTIFIED", "RESPONSE_RECEIVED", "RESPONSE_OVERDUE",
        "MEDIATION_OFFERED", "MEDIATION_ACTIVE", "MEDIATION_IMPASSE",
    ):
        fail("ERR_INVALID_STATE", "complaint is not in a referable state")
    business = db.businesses[rec["business_id"]]
    referral = new_record()
    referral.update({
        "complaint_id": rec["id"],
        "business_id": rec["business_id"],
        "referred_by_user_id": uid,
        "referred_by_role": role,
        "reason": reason,
        "pattern_score_at_referral": business["pattern_score"],
        "referral_status": "PENDING_REVIEW",
        "reviewed_by_user_id": None,
    })
    db.referrals[referral["id"]] = referral
    frm = rec["case_status"]
    run_closure_ritual(rec, "REFERRED_ENFORCEMENT")
    touch(rec)
    write_event(rec["id"], "REFERRAL_FILED", frm, "REFERRED_ENFORCEMENT",
                role, uid, "referred to enforcement: %s" % reason)
    return ok_object(referral_view(referral), 201)


# ---------------------------------------------------------------------------
# Business responses: collection and review (PRD section 3.3)
# ---------------------------------------------------------------------------

@bp.get("/consumer-protection/business-responses")
def list_responses():
    uid = auth(*STAFF_AND_PARTIES)
    role = caller_role()
    items = []
    for r in db.responses.values():
        complaint = db.complaints.get(r["complaint_id"])
        if complaint is not None and complaint_visible_to(complaint, uid, role):
            items.append(r)
    f_complaint = request.args.get("complaint_id")
    if f_complaint is not None:
        items = [r for r in items if r["complaint_id"] == f_complaint]
    f_business = request.args.get("business_id")
    if f_business is not None:
        items = [r for r in items if r["business_id"] == f_business]
    return list_response(items, response_view)


def _get_response(responseId):
    rec = db.responses.get(responseId)
    if rec is None:
        fail("ERR_RESPONSE_NOT_FOUND", "response does not exist")
    return rec


@bp.get("/consumer-protection/business-responses/<responseId>")
def get_response(responseId):
    uid = auth(*STAFF_AND_PARTIES)
    role = caller_role()
    rec = _get_response(responseId)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return ok_object(response_view(rec))


@bp.post("/consumer-protection/business-responses/<responseId>/review")
def review_response(responseId):
    uid = auth("IntakeOfficer")
    role = caller_role()
    rec = _get_response(responseId)
    data = json_body()
    verdict = req_enum(data, "verdict", domain.VERDICTS)
    complaint = db.complaints.get(rec["complaint_id"])
    if (
        rec["response_status"] != "SUBMITTED"
        or complaint is None
        or complaint["latest_response_id"] != rec["id"]
    ):
        fail("ERR_INVALID_STATE", "only the latest SUBMITTED response can be reviewed")
    if verdict == "SUFFICIENT":
        rec["response_status"] = "SUFFICIENT"
        touch(rec)
        write_event(complaint["id"], "RESPONSE_REVIEWED", None, None,
                    role, uid, "response reviewed SUFFICIENT")
    else:
        rec["response_status"] = "INSUFFICIENT_RETURNED"
        touch(rec)
        frm = complaint["case_status"]
        complaint["case_status"] = "BUSINESS_NOTIFIED"
        touch(complaint)
        write_event(complaint["id"], "RESPONSE_REVIEWED", frm, "BUSINESS_NOTIFIED",
                    role, uid, "response INSUFFICIENT; returned for resubmission")
    return ok_object(response_view(rec))

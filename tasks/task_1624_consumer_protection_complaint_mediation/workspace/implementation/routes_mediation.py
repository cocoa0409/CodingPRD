"""Mediation sessions, settlement offers (negotiation), settlements."""

from datetime import timedelta

from flask import Blueprint, request

import domain
from domain import (
    offer_view, run_closure_ritual, session_view, settlement_fee_cents,
    settlement_view, write_event,
)
from helpers import (
    auth, caller_role, check_complaint_party, complaint_visible_to, fail,
    json_body, list_response, new_record, ok_object, opt_bool, opt_string,
    req_datetime, req_enum, req_int, req_string, set_fields, touch,
)
from store import db

bp = Blueprint("mediation", __name__)

READERS = (
    "Consumer", "Business", "Mediator", "IntakeOfficer",
    "EnforcementAttorney", "UnitDirector",
)

MEDIABLE = ("MEDIATION_OFFERED", "MEDIATION_ACTIVE", "MEDIATION_IMPASSE")
NEGOTIATING = ("MEDIATION_ACTIVE", "MEDIATION_IMPASSE")
OPEN_SESSION = ("PROPOSED", "CONFIRMED")
ABSORBING = ("SETTLED", "CLOSED_UNRESOLVED", "DECLINED")


def _get_complaint(complaintId):
    rec = db.complaints.get(complaintId)
    if rec is None:
        fail("ERR_COMPLAINT_NOT_FOUND", "complaint does not exist")
    return rec


def _get_session(sessionId):
    rec = db.sessions.get(sessionId)
    if rec is None:
        fail("ERR_SESSION_NOT_FOUND", "session does not exist")
    return rec


def _get_offer(offerId):
    rec = db.offers.get(offerId)
    if rec is None:
        fail("ERR_OFFER_NOT_FOUND", "offer does not exist")
    return rec


def _get_settlement(settlementId):
    rec = db.settlements.get(settlementId)
    if rec is None:
        fail("ERR_SETTLEMENT_NOT_FOUND", "settlement does not exist")
    return rec


def _recompute_caseload(mediator):
    """active_case_count == own sessions in {PROPOSED, CONFIRMED} (invariant)."""
    count = sum(
        1 for s in db.sessions.values()
        if s["mediator_id"] == mediator["id"] and s["session_status"] in OPEN_SESSION
    )
    set_fields(mediator, active_case_count=count)


def _session_party_check(session, uid, role):
    complaint = db.complaints.get(session["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return complaint


# ---------------------------------------------------------------------------
# Mediation sessions (PRD section 3.4)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints/<complaintId>/mediation-sessions")
def create_session(complaintId):
    uid = auth("Mediator")
    role = caller_role()
    complaint = _get_complaint(complaintId)
    data = json_body()

    # Priority 3 (ownership): the named mediator must be the caller.
    mediator_id = data.get("mediator_id")
    if not isinstance(mediator_id, str) or not mediator_id:
        fail("ERR_INVALID_REQUEST", "mediator_id is required and must be a string")
    if mediator_id != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "mediator_id must equal the caller's X-User-ID")

    # Priority 4 (existence): body foreign keys resolve.
    mediator = db.mediators.get(mediator_id)
    if mediator is None:
        fail("ERR_MEDIATOR_NOT_FOUND", "mediator does not exist")
    room_id = data.get("room_id")
    if not isinstance(room_id, str) or not room_id:
        fail("ERR_INVALID_REQUEST", "room_id is required and must be a string")
    room = db.rooms.get(room_id)
    if room is None:
        fail("ERR_ROOM_NOT_FOUND", "room does not exist")

    # Priority 5 (shape): both timestamps, ends_at strictly after starts_at.
    starts_at = req_datetime(data, "starts_at")
    ends_at = req_datetime(data, "ends_at")
    if ends_at <= starts_at:
        fail("ERR_INVALID_REQUEST", "ends_at must fall strictly after starts_at")

    # Priority 6 (state): complaint must be in a mediable state.
    if complaint["case_status"] not in MEDIABLE:
        fail("ERR_INVALID_STATE", "complaint is not in a mediation state")

    # Priority 7 (regulatory): conflict-of-interest screening.
    if complaint["business_id"] in mediator["conflicted_business_ids"]:
        fail("ERR_MEDIATOR_CONFLICT_OF_INTEREST",
             "mediator is conflicted with this complaint's business")

    # Priority 8 (capacity / calendar conflicts).
    live = [
        s for s in db.sessions.values()
        if s["session_status"] in OPEN_SESSION
    ]
    own = [s for s in live if s["mediator_id"] == mediator["id"]]
    if len(own) >= mediator["max_concurrent_cases"]:
        fail("ERR_MEDIATOR_CASELOAD_FULL", "mediator has no caseload headroom")
    buffer = timedelta(minutes=domain.MEDIATOR_BUFFER_MINUTES)
    for s in own:
        # Half-open intervals plus a 30-minute turnover buffer.
        if starts_at < s["ends_at"] + buffer and s["starts_at"] < ends_at + buffer:
            fail("ERR_MEDIATOR_TIME_CONFLICT", "mediator calendar conflict")
    for s in [s for s in live if s["room_id"] == room["id"]]:
        # Closed intervals, no buffer: touching at the boundary conflicts.
        if starts_at <= s["ends_at"] and s["starts_at"] <= ends_at:
            fail("ERR_ROOM_TIME_CONFLICT", "room booking conflict")

    # Priority 9 (referenced configuration usable).
    if mediator["mediator_status"] != "ACTIVE" or room["room_status"] != "OPERATIONAL":
        fail("ERR_REFERENCED_ENTITY_INACTIVE",
             "session requires an ACTIVE mediator and an OPERATIONAL room")

    # Priority 10 (clock): the start must lie strictly in the future.
    if starts_at <= db.now:
        fail("ERR_SESSION_IN_PAST", "starts_at must be strictly after the current time")

    rec = new_record()
    rec.update({
        "complaint_id": complaint["id"],
        "mediator_id": mediator_id,
        "room_id": room_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "session_status": "PROPOSED",
        "consumer_confirmed": False,
        "business_confirmed": False,
        "outcome": None,
    })
    db.sessions[rec["id"]] = rec
    _recompute_caseload(mediator)
    write_event(complaint["id"], "SESSION_SCHEDULED", None, None,
                role, uid, "session proposed")
    return ok_object(session_view(rec), 201)


@bp.get("/consumer-protection/mediation-sessions")
def list_sessions():
    uid = auth(*READERS)
    role = caller_role()
    items = []
    for s in db.sessions.values():
        complaint = db.complaints.get(s["complaint_id"])
        if complaint is not None and complaint_visible_to(complaint, uid, role):
            items.append(s)
    f_complaint = request.args.get("complaint_id")
    if f_complaint is not None:
        items = [s for s in items if s["complaint_id"] == f_complaint]
    f_mediator = request.args.get("mediator_id")
    if f_mediator is not None:
        items = [s for s in items if s["mediator_id"] == f_mediator]
    f_room = request.args.get("room_id")
    if f_room is not None:
        items = [s for s in items if s["room_id"] == f_room]
    return list_response(items, session_view)


@bp.get("/consumer-protection/mediation-sessions/<sessionId>")
def get_session(sessionId):
    uid = auth(*READERS)
    role = caller_role()
    rec = _get_session(sessionId)
    _session_party_check(rec, uid, role)
    return ok_object(session_view(rec))


@bp.post("/consumer-protection/mediation-sessions/<sessionId>/confirm")
def confirm_session(sessionId):
    uid = auth("Consumer", "Business")
    role = caller_role()
    rec = _get_session(sessionId)
    complaint = _session_party_check(rec, uid, role)
    if rec["session_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED session can be confirmed")
    # Each party confirms only its own side.
    if role == "Consumer":
        rec["consumer_confirmed"] = True
    else:
        rec["business_confirmed"] = True
    touch(rec)
    if rec["consumer_confirmed"] and rec["business_confirmed"]:
        rec["session_status"] = "CONFIRMED"
        touch(rec)
        mediator = db.mediators.get(rec["mediator_id"])
        if mediator is not None:
            _recompute_caseload(mediator)  # unchanged: PROPOSED and CONFIRMED both count
        if complaint is not None and complaint["case_status"] in (
            "MEDIATION_OFFERED", "MEDIATION_IMPASSE"
        ):
            frm = complaint["case_status"]
            complaint["case_status"] = "MEDIATION_ACTIVE"
            touch(complaint)
            write_event(complaint["id"], "SESSION_CONFIRMED", frm, "MEDIATION_ACTIVE",
                        role, uid, "both parties confirmed; mediation active")
        elif complaint is not None:
            write_event(complaint["id"], "SESSION_CONFIRMED", None, None,
                        role, uid, "both parties confirmed")
    return ok_object(session_view(rec))


@bp.post("/consumer-protection/mediation-sessions/<sessionId>/decline")
def decline_session(sessionId):
    uid = auth("Consumer", "Business")
    role = caller_role()
    rec = _get_session(sessionId)
    _session_party_check(rec, uid, role)
    if rec["session_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED session can be declined")
    rec["session_status"] = "DECLINED"
    touch(rec)
    mediator = db.mediators.get(rec["mediator_id"])
    if mediator is not None:
        _recompute_caseload(mediator)
    return ok_object(session_view(rec))


@bp.post("/consumer-protection/mediation-sessions/<sessionId>/cancel")
def cancel_session(sessionId):
    uid = auth("Mediator", "UnitDirector")
    role = caller_role()
    rec = _get_session(sessionId)
    if role == "Mediator" and rec["mediator_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "a mediator cancels only its own sessions")
    if rec["session_status"] not in OPEN_SESSION:
        fail("ERR_INVALID_STATE", "only a PROPOSED or CONFIRMED session can be cancelled")
    rec["session_status"] = "CANCELLED"
    touch(rec)
    mediator = db.mediators.get(rec["mediator_id"])
    if mediator is not None:
        _recompute_caseload(mediator)
    return ok_object(session_view(rec))


@bp.post("/consumer-protection/mediation-sessions/<sessionId>/complete")
def complete_session(sessionId):
    uid = auth("Mediator")
    role = caller_role()
    rec = _get_session(sessionId)
    if rec["mediator_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "a mediator completes only its own sessions")
    data = json_body()
    outcome = data.get("outcome")
    no_show = data.get("no_show")
    if outcome is not None and outcome not in domain.OUTCOMES:
        fail("ERR_INVALID_REQUEST", "outcome must be one of PROGRESS, IMPASSE, SETTLEMENT_REACHED")
    if no_show is not None and not isinstance(no_show, bool):
        fail("ERR_INVALID_REQUEST", "no_show must be a boolean")
    if outcome is None and no_show is not True:
        fail("ERR_INVALID_REQUEST", "complete requires an outcome or no_show=true")
    if rec["session_status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "only a CONFIRMED session can be completed")
    if db.now < rec["starts_at"]:
        fail("ERR_INVALID_STATE", "the session's start has not yet arrived")
    complaint = db.complaints.get(rec["complaint_id"])
    if outcome is not None:
        rec["session_status"] = "COMPLETED"
        rec["outcome"] = outcome
        touch(rec)
        if outcome == "IMPASSE" and complaint is not None \
                and complaint["case_status"] == "MEDIATION_ACTIVE":
            complaint["case_status"] = "MEDIATION_IMPASSE"
            touch(complaint)
            write_event(complaint["id"], "SESSION_COMPLETED", "MEDIATION_ACTIVE",
                        "MEDIATION_IMPASSE", role, uid, "session ended in impasse")
        elif complaint is not None:
            write_event(complaint["id"], "SESSION_COMPLETED", None, None,
                        role, uid, "session completed: %s" % outcome)
    else:
        rec["session_status"] = "NO_SHOW"
        touch(rec)
        if complaint is not None:
            write_event(complaint["id"], "SESSION_COMPLETED", None, None,
                        role, uid, "session recorded as no-show")
    mediator = db.mediators.get(rec["mediator_id"])
    if mediator is not None:
        _recompute_caseload(mediator)
    return ok_object(session_view(rec))


# ---------------------------------------------------------------------------
# Settlement offers (PRD section 3.5)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints/<complaintId>/settlement-offers")
def tender_offer(complaintId):
    uid = auth("Consumer", "Business")
    role = caller_role()
    complaint = _get_complaint(complaintId)

    # Priority 3 (ownership): the caller must be a party to the complaint.
    check_complaint_party(complaint, uid, role)

    # Priority 5 (shape).
    data = json_body()
    offered_by_role = req_enum(data, "offered_by_role", domain.OFFERED_BY_ROLES)
    if offered_by_role != role.upper():
        fail("ERR_INVALID_REQUEST", "offered_by_role must match the caller's role")
    restitution = req_int(data, "restitution_amount_cents")
    if restitution < 0:
        fail("ERR_INVALID_AMOUNT", "restitution_amount_cents may be zero but never negative")
    expected_version = data.get("expected_complaint_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        fail("ERR_INVALID_REQUEST", "expected_complaint_version is required and must be an integer")
    non_monetary_terms = opt_string(data, "non_monetary_terms")

    # Priority 6 (state): negotiation requires an active mediation track.
    if complaint["case_status"] not in NEGOTIATING:
        fail("ERR_INVALID_STATE", "complaint is not in an active mediation state")

    # Priority 8 (OCC): refuse writes against a stale view of the complaint.
    if complaint["version"] > expected_version:
        fail("ERR_STALE_VERSION", "complaint version has advanced; re-read before writing")

    # Supersede the complaint's currently TENDERED offer, if any.
    superseded = None
    max_seq = 0
    for o in db.offers.values():
        if o["complaint_id"] != complaint["id"]:
            continue
        max_seq = max(max_seq, o["offer_seq"])
        if o["offer_status"] == "TENDERED":
            superseded = o
    if superseded is not None:
        superseded["offer_status"] = "SUPERSEDED"
        touch(superseded)

    rec = new_record()
    rec.update({
        "complaint_id": complaint["id"],
        "parent_offer_id": superseded["id"] if superseded is not None else None,
        "offer_seq": max_seq + 1,
        "offered_by_role": offered_by_role,
        "offered_by_id": uid,
        "restitution_amount_cents": restitution,
        "non_monetary_terms": non_monetary_terms,
        "offer_status": "TENDERED",
        "tendered_at": db.now,
        "expires_at": db.now + timedelta(days=domain.OFFER_TTL_DAYS),
        "accepted_at": None,
        "cooling_off_until": None,
    })
    db.offers[rec["id"]] = rec
    touch(complaint)  # the tender advances Complaint.version by one (OCC anchor)
    write_event(complaint["id"], "OFFER_TENDERED", None, None,
                role, uid, "offer %d tendered for %d cents" % (rec["offer_seq"], restitution))
    return ok_object(offer_view(rec), 201)


@bp.get("/consumer-protection/settlement-offers")
def list_offers():
    uid = auth(*READERS)
    role = caller_role()
    items = []
    for o in db.offers.values():
        complaint = db.complaints.get(o["complaint_id"])
        if complaint is not None and complaint_visible_to(complaint, uid, role):
            items.append(o)
    f_complaint = request.args.get("complaint_id")
    if f_complaint is not None:
        items = [o for o in items if o["complaint_id"] == f_complaint]
    f_parent = request.args.get("parent_offer_id")
    if f_parent is not None:
        items = [o for o in items if o["parent_offer_id"] == f_parent]
    f_status = request.args.get("offer_status")
    if f_status is not None:
        items = [o for o in items if o["offer_status"] == f_status]
    return list_response(items, offer_view)


@bp.get("/consumer-protection/settlement-offers/<offerId>")
def get_offer(offerId):
    uid = auth(*READERS)
    role = caller_role()
    rec = _get_offer(offerId)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return ok_object(offer_view(rec))


def _counter_party_check(offer, uid, role):
    """Only the counter-party may answer an offer: a consumer-tendered offer
    requires a Business caller (and vice versa), and the caller must be a
    party to the underlying complaint."""
    complaint = db.complaints.get(offer["complaint_id"])
    if offer["offered_by_role"] == "CONSUMER":
        if role != "Business":
            fail("ERR_NOT_RESOURCE_OWNER", "a consumer-tendered offer requires a Business caller")
    else:
        if role != "Consumer":
            fail("ERR_NOT_RESOURCE_OWNER", "a business-tendered offer requires a Consumer caller")
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return complaint


@bp.post("/consumer-protection/settlement-offers/<offerId>/accept")
def accept_offer(offerId):
    uid = auth("Consumer", "Business")
    role = caller_role()
    rec = _get_offer(offerId)
    complaint = _counter_party_check(rec, uid, role)
    if rec["offer_status"] != "TENDERED":
        fail("ERR_INVALID_STATE", "only a TENDERED offer can be accepted")
    if complaint is not None and complaint["case_status"] not in NEGOTIATING:
        fail("ERR_INVALID_STATE", "complaint is not in an active mediation state")
    rec["offer_status"] = "ACCEPTED"
    rec["accepted_at"] = db.now
    rec["cooling_off_until"] = db.now + timedelta(hours=domain.COOLING_OFF_HOURS)
    touch(rec)
    write_event(rec["complaint_id"], "OFFER_ACCEPTED", None, None,
                role, uid, "offer accepted; cooling-off until %s" % rec["cooling_off_until"])
    return ok_object(offer_view(rec))


@bp.post("/consumer-protection/settlement-offers/<offerId>/reject")
def reject_offer(offerId):
    uid = auth("Consumer", "Business")
    auth_role = caller_role()
    rec = _get_offer(offerId)
    _counter_party_check(rec, uid, auth_role)
    if rec["offer_status"] != "TENDERED":
        fail("ERR_INVALID_STATE", "only a TENDERED offer can be rejected")
    rec["offer_status"] = "REJECTED"
    touch(rec)
    return ok_object(offer_view(rec))


@bp.post("/consumer-protection/settlement-offers/<offerId>/withdraw")
def withdraw_offer(offerId):
    uid = auth("Consumer", "Business")
    role = caller_role()
    rec = _get_offer(offerId)
    # Only the tendering party may withdraw its own offer.
    expected_role = "Consumer" if rec["offered_by_role"] == "CONSUMER" else "Business"
    if role != expected_role or rec["offered_by_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "only the tendering party may withdraw this offer")
    if rec["offer_status"] != "TENDERED":
        fail("ERR_INVALID_STATE", "only a TENDERED offer can be withdrawn")
    rec["offer_status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(offer_view(rec))


@bp.post("/consumer-protection/settlement-offers/<offerId>/rescind")
def rescind_offer(offerId):
    uid = auth("Consumer")
    role = caller_role()
    rec = _get_offer(offerId)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    if rec["offer_status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "only an ACCEPTED offer can be rescinded")
    sourced = [
        s for s in db.settlements.values() if s["source_offer_id"] == rec["id"]
    ]
    for s in sourced:
        if s["settlement_status"] in ("EXECUTED", "FULFILLED", "BREACHED"):
            fail("ERR_INVALID_STATE",
                 "a settlement sourced from this offer has already executed")
    if db.now >= rec["cooling_off_until"]:
        fail("ERR_RESCISSION_WINDOW_EXPIRED", "the cooling-off period has ended")
    rec["offer_status"] = "RESCINDED"
    touch(rec)
    for s in sourced:
        if s["settlement_status"] == "DRAFT":
            s["settlement_status"] = "SUPERSEDED"
            s["outstanding_cents"] = 0  # write-off; fulfilled_cents preserved
            touch(s)
            if complaint is not None and complaint["active_settlement_id"] == s["id"]:
                complaint["active_settlement_id"] = None
                touch(complaint)
    write_event(rec["complaint_id"], "OFFER_RESCINDED", None, None,
                role, uid, "consumer rescinded within the cooling-off period")
    return ok_object(offer_view(rec))


# ---------------------------------------------------------------------------
# Settlements (PRD section 3.6)
# ---------------------------------------------------------------------------

@bp.post("/consumer-protection/complaints/<complaintId>/settlements")
def create_settlement(complaintId):
    uid = auth("Mediator")
    role = caller_role()
    complaint = _get_complaint(complaintId)
    data = json_body()
    expected_version = data.get("expected_complaint_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        fail("ERR_INVALID_REQUEST", "expected_complaint_version is required and must be an integer")

    # State: an absorbing case takes no further actions, and documentation
    # requires a non-rescinded ACCEPTED offer (highest offer_seq wins).
    if complaint["case_status"] in ABSORBING:
        fail("ERR_INVALID_STATE", "a finished case takes no further actions")
    accepted = [
        o for o in db.offers.values()
        if o["complaint_id"] == complaint["id"] and o["offer_status"] == "ACCEPTED"
    ]
    if not accepted:
        fail("ERR_INVALID_STATE", "no ACCEPTED offer exists to document")
    source = max(accepted, key=lambda o: o["offer_seq"])

    # Priority 8 (OCC).
    if complaint["version"] > expected_version:
        fail("ERR_STALE_VERSION", "complaint version has advanced; re-read before writing")

    # Supersede an existing open settlement (write-off of its outstanding).
    for s in db.settlements.values():
        if s["complaint_id"] == complaint["id"] and s["settlement_status"] in (
            "DRAFT", "EXECUTED", "BREACHED"
        ):
            s["settlement_status"] = "SUPERSEDED"
            s["outstanding_cents"] = 0  # forced write-off; fulfilled preserved
            touch(s)

    restitution = source["restitution_amount_cents"]
    fee = settlement_fee_cents(restitution)
    rec = new_record()
    rec.update({
        "complaint_id": complaint["id"],
        "source_offer_id": source["id"],
        "business_id": complaint["business_id"],
        "consumer_id": complaint["consumer_id"],
        "restitution_amount_cents": restitution,
        "mediation_fee_cents": fee,
        "total_due_cents": restitution + fee,
        "fulfilled_cents": 0,
        "outstanding_cents": restitution,
        "settlement_status": "DRAFT",
        "executed_at": None,
        "due_date": None,
        "fulfilled_at": None,
    })
    db.settlements[rec["id"]] = rec
    complaint["active_settlement_id"] = rec["id"]
    touch(complaint)  # documenting a settlement advances Complaint.version by one
    write_event(complaint["id"], "SETTLEMENT_CREATED", None, None,
                role, uid, "settlement documented from offer %d" % source["offer_seq"])
    return ok_object(settlement_view(rec), 201)


@bp.get("/consumer-protection/settlements")
def list_settlements():
    uid = auth(*READERS)
    role = caller_role()
    items = []
    for s in db.settlements.values():
        complaint = db.complaints.get(s["complaint_id"])
        if complaint is not None and complaint_visible_to(complaint, uid, role):
            items.append(s)
    f_complaint = request.args.get("complaint_id")
    if f_complaint is not None:
        items = [s for s in items if s["complaint_id"] == f_complaint]
    f_business = request.args.get("business_id")
    if f_business is not None:
        items = [s for s in items if s["business_id"] == f_business]
    f_consumer = request.args.get("consumer_id")
    if f_consumer is not None:
        items = [s for s in items if s["consumer_id"] == f_consumer]
    f_offer = request.args.get("source_offer_id")
    if f_offer is not None:
        items = [s for s in items if s["source_offer_id"] == f_offer]
    return list_response(items, settlement_view)


@bp.get("/consumer-protection/settlements/<settlementId>")
def get_settlement(settlementId):
    uid = auth(*READERS)
    role = caller_role()
    rec = _get_settlement(settlementId)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        check_complaint_party(complaint, uid, role)
    return ok_object(settlement_view(rec))


@bp.post("/consumer-protection/settlements/<settlementId>/execute")
def execute_settlement(settlementId):
    uid = auth("Mediator")
    role = caller_role()
    rec = _get_settlement(settlementId)
    if rec["settlement_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT settlement can be executed")
    source = db.offers.get(rec["source_offer_id"])
    cooling_off_until = source["cooling_off_until"] if source is not None else None
    if cooling_off_until is not None and db.now < cooling_off_until:
        fail("ERR_COOLING_OFF_ACTIVE", "the cooling-off period is still running")
    rec["settlement_status"] = "EXECUTED"
    rec["executed_at"] = db.now
    rec["due_date"] = db.now + timedelta(days=domain.SETTLEMENT_DUE_DAYS)
    touch(rec)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        frm = complaint["case_status"]
        complaint["active_settlement_id"] = rec["id"]
        if rec["restitution_amount_cents"] == 0:
            # Zero-restitution settlements pass straight through to SETTLED
            # within the same request, with the full closure ritual.
            complaint["case_status"] = "SETTLEMENT_PENDING"
            run_closure_ritual(complaint, "SETTLED")
            touch(complaint)
            write_event(complaint["id"], "SETTLEMENT_EXECUTED", frm, "SETTLED",
                        role, uid, "settlement executed; no restitution due")
        else:
            if frm in NEGOTIATING:
                complaint["case_status"] = "SETTLEMENT_PENDING"
            touch(complaint)
            write_event(complaint["id"], "SETTLEMENT_EXECUTED",
                        frm if frm in NEGOTIATING else None,
                        "SETTLEMENT_PENDING" if frm in NEGOTIATING else None,
                        role, uid, "settlement executed; payment due %s" % rec["due_date"])
    return ok_object(settlement_view(rec))


@bp.post("/consumer-protection/settlements/<settlementId>/mark-breached")
def mark_breached(settlementId):
    uid = auth("IntakeOfficer", "UnitDirector")
    role = caller_role()
    rec = _get_settlement(settlementId)
    if rec["settlement_status"] != "EXECUTED":
        fail("ERR_INVALID_STATE", "only an EXECUTED settlement can be marked breached")
    if rec["due_date"] is None or db.now <= rec["due_date"] or rec["outstanding_cents"] <= 0:
        fail("ERR_BREACH_NOT_DUE",
             "breach requires the due date to have passed with money outstanding")
    rec["settlement_status"] = "BREACHED"
    touch(rec)
    complaint = db.complaints.get(rec["complaint_id"])
    if complaint is not None:
        frm = complaint["case_status"]
        if frm == "SETTLEMENT_PENDING":
            complaint["case_status"] = "MEDIATION_IMPASSE"
            touch(complaint)
        write_event(complaint["id"], "SETTLEMENT_BREACHED",
                    frm if frm == "SETTLEMENT_PENDING" else None,
                    "MEDIATION_IMPASSE" if frm == "SETTLEMENT_PENDING" else None,
                    role, uid, "settlement breached; negotiation reopens")
    return ok_object(settlement_view(rec))

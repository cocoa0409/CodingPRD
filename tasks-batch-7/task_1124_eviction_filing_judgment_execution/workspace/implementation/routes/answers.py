from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth
from response import ok_list, ok_object
from services import serialize as ser
from services.resolution import get_answer, get_case, get_referral
from utils import body_json, pagination, v_bool, v_date, v_enum, v_str

bp = Blueprint("answers", __name__)

DEFENSE_CODES = {"PAYMENT_TENDERED", "HABITABILITY", "RETALIATION", "PROCEDURAL"}


@bp.post("/api/cases/<cid>/answers")
@auth({"CourtClerk"})
def create_answer(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        b = body_json()
        codes = b.get("defense_codes")
        if (
            not isinstance(codes, list)
            or len(codes) < 1
            or any(not isinstance(c, str) or c not in DEFENSE_CODES for c in codes)
        ):
            raise ApiError(
                "ERR_VALIDATION",
                400,
                "defense_codes must be a non-empty list of valid defense codes",
            )
        mediation_requested = v_bool(b, "mediation_requested")
        if case["status"] != "HEARING_SCHEDULED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Case status does not permit an answer"
            )
        r = db.new_record(
            {
                "case_id": cid,
                "defense_codes": list(codes),
                "mediation_requested": mediation_requested,
                "status": "FILED",
                "filed_by_clerk_id": _uid,
            }
        )
        STORE.answers[r["id"]] = r
        case["status"] = "ANSWERED"
        db.bump(case)
        return ok_object(ser.answer(r), 201)


@bp.get("/api/answers/<aid>")
@auth({"Landlord", "CourtClerk", "Mediator", "PlatformAdmin"})
def read_answer(aid, _uid, _role):
    with LOCK:
        return ok_object(ser.answer(get_answer(aid)))


@bp.get("/api/cases/<cid>/answers")
@auth({"Landlord", "CourtClerk", "Mediator", "PlatformAdmin"})
def list_case_answers(cid, _uid, _role):
    with LOCK:
        get_case(cid)
        limit, offset = pagination()
        items = [a for a in db.sorted_items(STORE.answers) if a["case_id"] == cid]
        page = items[offset : offset + limit]
        return ok_list([ser.answer(r) for r in page], len(items), limit, offset)


@bp.post("/api/answers/<aid>/mediation-referrals")
@auth({"CourtClerk"})
def create_referral(aid, _uid, _role):
    with LOCK:
        answer = get_answer(aid)
        b = body_json()
        mediator_id = v_str(b, "mediator_id")
        session_date = v_date(b, "session_date")
        if answer["status"] != "FILED" or not answer["mediation_requested"]:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Answer must be FILED with mediation_requested true",
            )
        case = STORE.cases[answer["case_id"]]
        r = db.new_record(
            {
                "answer_id": aid,
                "mediator_id": mediator_id,
                "session_date": session_date.isoformat(),
                "status": "PENDING",
                "outcome_notes": None,
                "outcome_recorded_at": None,
            }
        )
        STORE.referrals[r["id"]] = r
        answer["status"] = "REFERRED"
        db.bump(answer)
        case["status"] = "MEDIATION_PENDING"
        db.bump(case)
        for h in STORE.hearings.values():
            if h["case_id"] == case["id"] and h["status"] == "SCHEDULED":
                h["status"] = "STAYED"
                db.bump(h)
        return ok_object(ser.referral(r), 201)


@bp.get("/api/referrals/<rid>")
@auth({"Landlord", "CourtClerk", "Mediator", "PlatformAdmin"})
def read_referral(rid, _uid, _role):
    with LOCK:
        return ok_object(ser.referral(get_referral(rid)))


@bp.get("/api/answers/<aid>/mediation-referrals")
@auth({"Landlord", "CourtClerk", "Mediator", "PlatformAdmin"})
def list_answer_referrals(aid, _uid, _role):
    with LOCK:
        get_answer(aid)
        limit, offset = pagination()
        items = [r for r in db.sorted_items(STORE.referrals) if r["answer_id"] == aid]
        page = items[offset : offset + limit]
        return ok_list([ser.referral(r) for r in page], len(items), limit, offset)


@bp.post("/api/referrals/<rid>/outcome")
@auth({"Mediator"})
def record_outcome(rid, _uid, _role):
    with LOCK:
        referral = get_referral(rid)
        # actor binding (rung 4): recorder must be the referral's mediator
        if _uid != referral["mediator_id"]:
            raise ApiError(
                "ERR_NOT_ASSIGNED_MEDIATOR",
                403,
                "Outcome recorder is not the referral's mediator_id",
            )
        b = body_json()
        outcome = v_enum(b, "outcome", {"SETTLED", "FAILED"})
        notes = v_str(b, "notes", required=False)
        if referral["status"] != "PENDING":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Referral is not PENDING"
            )
        answer = STORE.answers[referral["answer_id"]]
        case = STORE.cases[answer["case_id"]]
        referral["status"] = outcome
        referral["outcome_notes"] = notes
        referral["outcome_recorded_at"] = db.now()
        db.bump(referral)
        answer["status"] = "RESOLVED" if outcome == "SETTLED" else "RETURNED"
        db.bump(answer)
        case["status"] = "SETTLED" if outcome == "SETTLED" else "HEARING_SCHEDULED"
        db.bump(case)
        for h in STORE.hearings.values():
            if h["case_id"] == case["id"] and h["status"] == "STAYED":
                h["status"] = "CANCELLED"
                db.bump(h)
        return ok_object(ser.referral(referral))

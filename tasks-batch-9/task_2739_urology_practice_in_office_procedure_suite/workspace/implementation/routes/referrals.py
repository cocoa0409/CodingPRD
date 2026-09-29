"""Pelvic health referrals and their conserved visit ledger."""

from flask import Blueprint

import constants
import db
import response
import util
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import query, serialize

bp = Blueprint("referrals", __name__)

ACCEPT_FROM = ("REQUESTED", "WAITLISTED")
DECLINE_FROM = ("REQUESTED", "WAITLISTED")
WAITLIST_FROM = ("REQUESTED",)
WITHDRAW_FROM = ("ACCEPTED", "WAITLISTED", "COMPLETED")
# LOG and VOID_LAST are both declared on an accepted or completed referral; voiding an
# empty ledger therefore passes the transition guard and is caught by priority 76.
VISIT_FROM = ("ACCEPTED", "COMPLETED")


def _referral(referral_id):
    row = store.get("referrals", referral_id)
    if row is None:
        raise ApiError("ERR_REFERRAL_NOT_FOUND")
    return row


@bp.route("/pelvic-health-referrals", methods=["POST"])
@authenticate([constants.ROLE_UROLOGIST, constants.ROLE_PELVIC_COORDINATOR])
def create_referral():
    body = validate.get_body()
    patient_id = validate.str_field(body, "patient_id")
    source_case_id = validate.str_field(body, "source_case_id", required=False, default=None)
    program = validate.enum_field(body, "program", constants.REFERRAL_PROGRAMS)
    requested_visits = validate.int_field(body, "requested_visits", minimum=1)

    # Priority 10.
    if store.get("patients", patient_id) is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    source_case = None
    if source_case_id is not None:
        source_case = store.get("cases", source_case_id)
        if source_case is None:
            raise ApiError("ERR_CASE_NOT_FOUND")
    # Priority 26 — a named source case must have reached COMPLETED.
    if source_case is not None and source_case["schedule_status"] != "COMPLETED":
        raise ApiError("ERR_SOURCE_CASE_NOT_COMPLETED")

    row = db.new_row(
        "referrals",
        {
            "patient_id": patient_id,
            "source_case_id": source_case_id,
            "program": program,
            "requested_visits": requested_visits,
            "visits_authorized": 0,
            "visits_used": 0,
            "visits_remaining": 0,
            "visits_forfeited": 0,
            "status": "REQUESTED",
            "waitlist_position": None,
            "therapy_start_by": None,
            "first_visit_date": None,
            "decline_reason": None,
            "_visits": [],
        },
    )
    return response.created_response(serialize.dump("referrals", row))


@bp.route("/pelvic-health-referrals/<referral_id>/decision", methods=["POST"])
@authenticate([constants.ROLE_PELVIC_COORDINATOR])
def decide_referral(referral_id):
    body = validate.get_body()
    decision = validate.enum_field(body, "decision", constants.REFERRAL_DECISIONS)
    authorized_visits = None
    decline_reason = None
    if decision == "ACCEPT":
        authorized_visits = validate.int_field(body, "authorized_visits", minimum=1)
    elif decision == "DECLINE":
        decline_reason = validate.str_field(body, "decline_reason")

    referral = _referral(referral_id)
    # Priority 22.
    declared = {
        "ACCEPT": ACCEPT_FROM,
        "DECLINE": DECLINE_FROM,
        "WAITLIST": WAITLIST_FROM,
        "WITHDRAW": WITHDRAW_FROM,
    }[decision]
    if referral["status"] not in declared:
        raise ApiError("ERR_INVALID_REFERRAL_TRANSITION")

    if decision == "ACCEPT":
        source_case = store.get("cases", referral["source_case_id"])
        if source_case is not None and source_case["schedule_status"] != "COMPLETED":
            raise ApiError("ERR_SOURCE_CASE_NOT_COMPLETED")
        # Priority 74 — the therapy start window, measured off the source completion.
        if source_case is not None and source_case["completed_at"] is not None:
            deadline = util.add_days_to_date(
                source_case["completed_at"].date(), constants.THERAPY_START_WINDOW_DAYS
            )
        else:
            deadline = util.add_days_to_date(store.today(), constants.THERAPY_START_WINDOW_DAYS)
        if source_case is not None and store.today() > deadline:
            raise ApiError("ERR_THERAPY_START_WINDOW_MISSED")

        authorized = min(
            referral["requested_visits"],
            authorized_visits,
            constants.PROGRAM_VISIT_CAP[referral["program"]],
        )
        referral["visits_authorized"] = authorized
        referral["visits_remaining"] = authorized
        referral["visits_used"] = 0
        referral["visits_forfeited"] = 0
        referral["waitlist_position"] = None
        referral["therapy_start_by"] = deadline
        referral["status"] = "ACCEPTED"
    elif decision == "DECLINE":
        referral["decline_reason"] = decline_reason
        referral["status"] = "DECLINED"
    elif decision == "WAITLIST":
        # Counted immediately before this mutation is applied.
        ahead = len(
            [
                row
                for row in store.all_rows("referrals")
                if row["program"] == referral["program"] and row["status"] == "WAITLISTED"
            ]
        )
        referral["waitlist_position"] = ahead + 1
        referral["status"] = "WAITLISTED"
    else:
        was_waitlisted = referral["status"] == "WAITLISTED"
        referral["visits_forfeited"] += referral["visits_remaining"]
        referral["visits_remaining"] = 0
        if was_waitlisted:
            referral["waitlist_position"] = None
        referral["status"] = "WITHDRAWN"

    db.touch(referral)
    return response.object_response(serialize.dump("referrals", referral))


@bp.route("/pelvic-health-referrals/<referral_id>/visits", methods=["POST"])
@authenticate([constants.ROLE_PELVIC_COORDINATOR])
def record_visit(referral_id):
    body = validate.get_body()
    action = validate.enum_field(body, "action", constants.VISIT_ACTIONS)
    visit_date = None
    if action == "LOG":
        visit_date = validate.date_field(body, "visit_date")

    referral = _referral(referral_id)
    # Priority 22.
    if referral["status"] not in VISIT_FROM:
        raise ApiError("ERR_INVALID_REFERRAL_TRANSITION")
    # Priority 76 — the ledger guards itself.
    if action == "LOG" and referral["visits_remaining"] < 1:
        raise ApiError("ERR_VISIT_ALLOCATION_EXHAUSTED")
    if action == "VOID_LAST" and referral["visits_used"] < 1:
        raise ApiError("ERR_VISIT_ALLOCATION_EXHAUSTED")

    if action == "LOG":
        referral["_visits"] = referral["_visits"] + [visit_date]
        referral["visits_used"] += 1
        referral["visits_remaining"] -= 1
        if referral["visits_remaining"] == 0:
            referral["status"] = "COMPLETED"
    else:
        referral["_visits"] = referral["_visits"][:-1]
        referral["visits_used"] -= 1
        referral["visits_remaining"] += 1
        # Voiding the very visit that completed the referral reopens the authorisation.
        if referral["status"] == "COMPLETED":
            referral["status"] = "ACCEPTED"

    referral["first_visit_date"] = min(referral["_visits"]) if referral["_visits"] else None
    db.touch(referral)
    return response.object_response(serialize.dump("referrals", referral))


@bp.route("/pelvic-health-referrals/<referral_id>", methods=["GET"])
@authenticate(ALL)
def get_referral(referral_id):
    return response.object_response(serialize.dump("referrals", _referral(referral_id)))


@bp.route("/pelvic-health-referrals", methods=["GET"])
@authenticate(ALL)
def list_referrals():
    return query.collection(
        "referrals",
        {
            "patient_id": validate.query_str("patient_id"),
            "source_case_id": validate.query_str("source_case_id"),
            "program": validate.query_enum("program", constants.REFERRAL_PROGRAMS),
            "status": validate.query_enum("status", constants.REFERRAL_STATUSES),
        },
    )

"""Open-access referral intake and triage."""
from flask import Blueprint

from core import by_seq, db, fail, new_record, touch
from core import respond_list, respond_object
from calcs import open_access_risk_screen
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    opt_int,
    opt_string,
    pagination,
    req_enum,
    req_id,
    req_int,
    req_string,
)
from services import get_patient, get_referral

bp = Blueprint("referrals", __name__)

REASONS = (
    "AVERAGE_RISK_SCREENING",
    "FAMILY_HISTORY",
    "POSITIVE_FIT",
    "SURVEILLANCE",
    "SYMPTOMATIC_BLEEDING",
)
REFERRAL_STATUSES = (
    "SUBMITTED",
    "UNDER_TRIAGE",
    "INFO_REQUESTED",
    "ACCEPTED_OPEN_ACCESS",
    "ACCEPTED_OFFICE_VISIT",
    "DECLINED",
)
MAX_INFO_REQUEST_ROUNDS = 2


@bp.post("/referrals")
def create_referral():
    auth("ReferralCoordinator")
    data = body()
    patient_id = req_id(data, "patient_id")
    referring_provider_npi = req_string(data, "referring_provider_npi")
    reason = req_enum(data, "reason", REASONS)
    asa_class_reported = req_int(data, "asa_class_reported", 1, 5)
    anticoagulant_reported = opt_bool(data, "anticoagulant_reported", False)

    get_patient(patient_id)

    referral = new_record({
        "patient_id": patient_id,
        "referring_provider_npi": referring_provider_npi,
        "reason": reason,
        "asa_class_reported": asa_class_reported,
        "anticoagulant_reported": anticoagulant_reported,
        "status": "SUBMITTED",
        "info_request_rounds": 0,
        "risk_screen_result": "PENDING",
        "triage_decision_note": None,
    })
    db.referrals[referral["id"]] = referral
    return respond_object(referral, 201)


@bp.get("/referrals/<referral_id>")
def read_referral(referral_id):
    auth("ReferralCoordinator", "PracticeAdmin")
    return respond_object(get_referral(referral_id))


@bp.get("/referrals")
def list_referrals():
    auth("ReferralCoordinator", "PracticeAdmin")
    limit, offset = pagination()
    patient_id = filter_value("patient_id")
    status = filter_enum("status", REFERRAL_STATUSES)
    reason = filter_enum("reason", REASONS)
    rows = by_seq(list(db.referrals.values()))
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason is not None:
        rows = [r for r in rows if r["reason"] == reason]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.post("/referrals/<referral_id>/triage-actions")
def triage_action(referral_id):
    auth("ReferralCoordinator")
    data = body()
    action = req_enum(data, "action", (
        "BEGIN_TRIAGE", "REQUEST_INFO", "RESPOND_INFO",
        "ACCEPT_OPEN_ACCESS", "ACCEPT_OFFICE_VISIT", "DECLINE",
    ))
    note = opt_string(data, "note")
    updated_asa_class = opt_int(data, "updated_asa_class", 1, 5)
    updated_anticoagulant = opt_bool(data, "updated_anticoagulant")

    referral = get_referral(referral_id)
    status = referral["status"]

    if action == "BEGIN_TRIAGE":
        if status != "SUBMITTED":
            fail("ERR_INVALID_REFERRAL_STATE", "BEGIN_TRIAGE is not admitted from %s." % status)
        referral["status"] = "UNDER_TRIAGE"
        referral["risk_screen_result"] = open_access_risk_screen(referral)
    elif action == "REQUEST_INFO":
        if status != "UNDER_TRIAGE":
            fail("ERR_INVALID_REFERRAL_STATE", "REQUEST_INFO is not admitted from %s." % status)
        if referral["info_request_rounds"] < MAX_INFO_REQUEST_ROUNDS:
            referral["status"] = "INFO_REQUESTED"
            referral["info_request_rounds"] += 1
            if note is not None:
                referral["triage_decision_note"] = note
        else:
            referral["status"] = "DECLINED"
            referral["triage_decision_note"] = "AUTO_DECLINED_INFO_EXHAUSTED"
    elif action == "RESPOND_INFO":
        if status != "INFO_REQUESTED":
            fail("ERR_INVALID_REFERRAL_STATE", "RESPOND_INFO is not admitted from %s." % status)
        referral["status"] = "UNDER_TRIAGE"
        if updated_asa_class is not None:
            referral["asa_class_reported"] = updated_asa_class
        if updated_anticoagulant is not None:
            referral["anticoagulant_reported"] = updated_anticoagulant
        referral["risk_screen_result"] = open_access_risk_screen(referral)
    elif action == "ACCEPT_OPEN_ACCESS":
        if status != "UNDER_TRIAGE":
            fail("ERR_INVALID_REFERRAL_STATE",
                 "ACCEPT_OPEN_ACCESS is not admitted from %s." % status)
        if open_access_risk_screen(referral) != "CLEARED_OPEN_ACCESS":
            fail("ERR_OPEN_ACCESS_RISK_SCREEN_FAILED",
                 "The pre-procedure risk screen requires an office visit.")
        referral["status"] = "ACCEPTED_OPEN_ACCESS"
        if note is not None:
            referral["triage_decision_note"] = note
    elif action == "ACCEPT_OFFICE_VISIT":
        if status != "UNDER_TRIAGE":
            fail("ERR_INVALID_REFERRAL_STATE",
                 "ACCEPT_OFFICE_VISIT is not admitted from %s." % status)
        referral["status"] = "ACCEPTED_OFFICE_VISIT"
        if note is not None:
            referral["triage_decision_note"] = note
    else:
        if status != "UNDER_TRIAGE":
            fail("ERR_INVALID_REFERRAL_STATE", "DECLINE is not admitted from %s." % status)
        referral["status"] = "DECLINED"
        if note is not None:
            referral["triage_decision_note"] = note

    touch(referral)
    return respond_object(referral)

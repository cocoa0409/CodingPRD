"""Appellate review: filing, the supplementation loop, decision and withdrawal."""

from flask import Blueprint

import calc
import cascade
import serial
from core import (ApiError, authorize, base_record, body, db, days, fk, lookup,
                  opt_enum, ordered, page, pagination, query_filter, req_enum,
                  req_str, respond_object, touch)

bp = Blueprint("appeals", __name__)

APPEAL_READ_ROLES = ("EnforcementPlanner", "HearingOfficer", "AppealsBoardMember",
                     "Rider", "EquityAnalyst")


def _segregation_guard(actor, appeal):
    """PRD 3.7: the officer who decided the hearing may not act on its appeal."""
    hearing = db.hearings.get(appeal["hearing_id"])
    if hearing is not None and hearing["hearing_officer_user_id"] is not None \
            and actor.user_id == hearing["hearing_officer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The deciding hearing officer may not act on this appeal.")


@bp.post("/appeals")
def file_appeal():
    actor = authorize("Rider")
    payload = body()
    req_str(payload, "citation_id", min_len=1)
    req_str(payload, "hearing_id", min_len=1)
    grounds_code = req_enum(payload, "grounds_code", calc.APPEAL_GROUNDS)
    statement = req_str(payload, "statement", min_len=1)

    citation = fk(payload, "citation_id", db.citations, "ERR_CITATION_NOT_FOUND")
    hearing = fk(payload, "hearing_id", db.hearings, "ERR_HEARING_NOT_FOUND")

    if actor.user_id != citation["rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the cited rider may file this appeal.")
    if hearing["status"] != "HELD" or hearing["decision"] not in ("UPHOLD", "REDUCE"):
        raise ApiError("ERR_HEARING_NOT_APPEALABLE",
                       "Only a HELD hearing that upheld or reduced the citation is appealable.")
    if hearing["citation_id"] != citation["id"]:
        raise ApiError("ERR_HEARING_CITATION_MISMATCH",
                       "The hearing does not belong to the named citation.")
    for existing in db.appeals.values():
        if existing["citation_id"] == citation["id"] and existing["status"] != "WITHDRAWN":
            raise ApiError("ERR_APPEAL_ALREADY_OPEN",
                           "Appellate review of this citation is already open or exhausted.")
    if db.now() > hearing["decided_at"] + days(calc.APPEAL_WINDOW_DAYS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED",
                       "The 21-day appeal window has closed.")

    appeal = base_record()
    appeal.update({
        "citation_id": citation["id"],
        "hearing_id": hearing["id"],
        "appellant_rider_id": citation["rider_id"],
        "grounds_code": grounds_code,
        "statement": statement,
        "round_index": 1,
        "submitted_at": db.now(),
        "supplement_deadline_at": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "dismissal_reason_code": None,
        "status": "SUBMITTED",
    })
    db.appeals[appeal["id"]] = appeal
    return respond_object(serial.appeal_out(appeal), 201)


@bp.post("/appeals/<appeal_id>/request-supplement")
def request_supplement(appeal_id):
    actor = authorize("AppealsBoardMember")
    appeal = lookup(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    _segregation_guard(actor, appeal)
    if appeal["status"] != "SUBMITTED":
        raise ApiError("ERR_APPEAL_STATUS_INVALID",
                       "Appeal is %s, not SUBMITTED." % appeal["status"])
    if appeal["round_index"] >= calc.APPEAL_MAX_ROUNDS:
        raise ApiError("ERR_APPEAL_ROUND_LIMIT",
                       "The supplementation loop is bounded at 2 rounds.")
    appeal["status"] = "SUPPLEMENT_REQUESTED"
    appeal["supplement_deadline_at"] = db.now() + days(calc.SUPPLEMENT_WINDOW_DAYS)
    touch(appeal)
    return respond_object(serial.appeal_out(appeal))


@bp.post("/appeals/<appeal_id>/resubmit")
def resubmit_appeal(appeal_id):
    actor = authorize("Rider")
    payload = body()
    statement = req_str(payload, "statement", min_len=1)
    appeal = lookup(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    if actor.user_id != appeal["appellant_rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appellant rider may resubmit this appeal.")
    if appeal["status"] != "SUPPLEMENT_REQUESTED":
        raise ApiError("ERR_APPEAL_STATUS_INVALID",
                       "Appeal is %s, not SUPPLEMENT_REQUESTED." % appeal["status"])
    if appeal["supplement_deadline_at"] is not None \
            and db.now() > appeal["supplement_deadline_at"]:
        raise ApiError("ERR_SUPPLEMENT_WINDOW_CLOSED",
                       "The 14-day supplement window has closed.")
    if appeal["round_index"] >= calc.APPEAL_MAX_ROUNDS:
        raise ApiError("ERR_APPEAL_ROUND_LIMIT",
                       "The supplementation loop is bounded at 2 rounds.")
    appeal["status"] = "SUBMITTED"
    appeal["statement"] = statement
    appeal["round_index"] = appeal["round_index"] + 1
    appeal["submitted_at"] = db.now()
    appeal["supplement_deadline_at"] = None
    touch(appeal)
    return respond_object(serial.appeal_out(appeal))


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    actor = authorize("AppealsBoardMember")
    payload = body()
    decision = req_enum(payload, "decision", calc.APPEAL_DECISIONS)
    dismissal_reason_code = opt_enum(payload, "dismissal_reason_code",
                                     calc.DISMISSAL_REASONS)
    appeal = lookup(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    _segregation_guard(actor, appeal)
    if appeal["status"] not in calc.APPEAL_LIVE_STATUSES:
        raise ApiError("ERR_APPEAL_STATUS_INVALID",
                       "Appeal is %s; only a live appeal may be decided." % appeal["status"])
    citation = db.citations[appeal["citation_id"]]
    if citation["adjudication_status"] not in ("UPHELD", "REDUCED"):
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s, not standing on an adverse finding."
                       % citation["adjudication_status"])

    if decision == "GRANTED":
        if dismissal_reason_code is None:
            raise ApiError("ERR_DECISION_FIELDS_INVALID",
                           "A GRANTED appeal must supply dismissal_reason_code.")
    else:
        if dismissal_reason_code is not None:
            raise ApiError("ERR_DECISION_FIELDS_INVALID",
                           "A DENIED appeal must not supply dismissal_reason_code.")
    if dismissal_reason_code == "FIRST_OFFENSE_DIVERSION" and citation["offense_sequence"] != 1:
        raise ApiError("ERR_DIVERSION_NOT_ELIGIBLE",
                       "FIRST_OFFENSE_DIVERSION requires offense_sequence 1.")

    appeal["status"] = decision
    appeal["dismissal_reason_code"] = dismissal_reason_code
    appeal["decided_at"] = db.now()
    appeal["decided_by_user_id"] = actor.user_id
    touch(appeal)

    if decision == "GRANTED":
        citation["adjudication_status"] = "DISMISSED"
        citation["dismissal_reason_code"] = dismissal_reason_code
        citation["dismissed_at"] = db.now()
        cascade.dismissal_unwind(citation)
        touch(citation)
    return respond_object(serial.appeal_out(appeal))


@bp.post("/appeals/<appeal_id>/withdraw")
def withdraw_appeal(appeal_id):
    actor = authorize("Rider")
    appeal = lookup(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    if actor.user_id != appeal["appellant_rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appellant rider may withdraw this appeal.")
    if appeal["status"] not in calc.APPEAL_LIVE_STATUSES:
        raise ApiError("ERR_APPEAL_STATUS_INVALID",
                       "Appeal is %s; only a live appeal may be withdrawn." % appeal["status"])
    appeal["status"] = "WITHDRAWN"
    appeal["decided_at"] = db.now()
    touch(appeal)
    return respond_object(serial.appeal_out(appeal))


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    authorize(*APPEAL_READ_ROLES)
    appeal = lookup(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    return respond_object(serial.appeal_out(appeal))


@bp.get("/appeals")
def list_appeals():
    authorize(*APPEAL_READ_ROLES)
    limit, offset = pagination()
    citation_id = query_filter("citation_id")
    hearing_id = query_filter("hearing_id")
    appellant_rider_id = query_filter("appellant_rider_id")
    status = query_filter("status")
    rows = [a for a in db.appeals.values()
            if (citation_id is None or a["citation_id"] == citation_id)
            and (hearing_id is None or a["hearing_id"] == hearing_id)
            and (appellant_rider_id is None
                 or a["appellant_rider_id"] == appellant_rider_id)
            and (status is None or a["status"] == status)]
    return page(ordered(rows), limit, offset, serial.appeal_out)

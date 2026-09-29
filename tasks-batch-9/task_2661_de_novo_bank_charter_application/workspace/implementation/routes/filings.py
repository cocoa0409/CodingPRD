"""Regulatory filing and approval condition writes."""
from flask import Blueprint, g

import calc
import cascade
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate, require_organizer_identity
from routes.helpers import must_get

bp = Blueprint("filings", __name__)

AUTHORITIES = ("CHARTERING_AUTHORITY", "DEPOSIT_INSURER")
DECISIONS = ("ADDITIONAL_INFO_REQUESTED", "CONDITIONALLY_APPROVED", "DENIED", "FINAL_APPROVED")
DECISION_SOURCES = {
    "ADDITIONAL_INFO_REQUESTED": ("FILED",),
    "CONDITIONALLY_APPROVED": ("FILED",),
    "DENIED": ("FILED",),
    "FINAL_APPROVED": ("CONDITIONALLY_APPROVED",),
}
CATEGORIES = ("CAPITAL", "MANAGEMENT", "POLICY", "VENDOR", "INSURANCE")
DISPOSITIONS = ("SATISFIED", "FAILED", "WAIVED", "REOPENED")
DISPOSITION_SOURCES = {
    "SATISFIED": ("EVIDENCE_SUBMITTED",),
    "FAILED": ("EVIDENCE_SUBMITTED",),
    "WAIVED": ("OPEN", "EVIDENCE_SUBMITTED", "FAILED"),
    "REOPENED": ("SATISFIED",),
}
AUTHORITY_ROLE = {
    "CHARTERING_AUTHORITY": "CharteringExaminer",
    "DEPOSIT_INSURER": "InsuranceExaminer",
}


def _require_authority(filing):
    if g.user_role != AUTHORITY_ROLE[filing["authority"]]:
        raise err("ERR_EXAMINER_AUTHORITY_MISMATCH")


@bp.post("/de-novo/regulatory-filings")
def create_filing():
    authenticate(("CharterCounsel",))
    data = v.body()
    group_id = v.req_id(data, "group_id")
    authority = v.req_enum(data, "authority", AUTHORITIES)
    pinned_business_plan_id = v.req_id(data, "pinned_business_plan_id")
    group = must_get("groups", group_id)
    plan = must_get("plans", pinned_business_plan_id)
    if plan["group_id"] != group["id"] or plan["status"] not in ("SUBMITTED", "PINNED"):
        raise err("ERR_PINNED_PLAN_NOT_SUBMITTED")
    if calc.filing_by_authority(group["id"], authority) is not None:
        raise err("ERR_FILING_AUTHORITY_DUPLICATE")
    filing = db.insert("filings", {
        "group_id": group["id"],
        "authority": authority,
        "pinned_business_plan_id": plan["id"],
        "status": "DRAFT",
        "info_request_round": 0,
        "filed_at": None,
        "decision_at": None,
        "condition_total_count": 0,
        "open_blocking_condition_count": 0,
        "settled_condition_count": 0,
        "pre_opening_clearance": False,
    })
    calc.recompute_filing_posture(filing)
    db.touch(group)
    db.commit()
    return response.object_response(serialize.filing(filing), 201)


@bp.post("/de-novo/regulatory-filings/<filing_id>/file")
def file_filing(filing_id):
    authenticate(("CharterCounsel",))
    v.body()
    filing = must_get("filings", filing_id)
    if filing["status"] not in ("DRAFT", "ADDITIONAL_INFO_REQUESTED"):
        raise err("ERR_FILING_NOT_FILEABLE")
    group = db.get("groups", filing["group_id"])
    if group is None or group["stage"] not in ("FILING_READY", "UNDER_REVIEW"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    filing["status"] = "FILED"
    filing["filed_at"] = db.clock()
    calc.recompute_filing_posture(filing)
    db.touch(filing)
    if group["stage"] == "FILING_READY":
        group["stage"] = "UNDER_REVIEW"
        db.touch(group)
    db.commit()
    return response.object_response(serialize.filing(filing))


@bp.post("/de-novo/regulatory-filings/<filing_id>/decision")
def decide_filing(filing_id):
    authenticate(("CharteringExaminer", "InsuranceExaminer"))
    data = v.body()
    decision = v.req_enum(data, "decision", DECISIONS)
    decision_note = v.opt_str(data, "decision_note", 1, None)
    filing = must_get("filings", filing_id)
    if filing["status"] not in DECISION_SOURCES[decision]:
        raise err("ERR_FILING_DECISION_NOT_ALLOWED")
    _require_authority(filing)
    group = db.get("groups", filing["group_id"])
    if decision == "FINAL_APPROVED":
        # PRD 254: three further gates, in this order.
        if filing["open_blocking_condition_count"] != 0:
            raise err("ERR_PRE_OPENING_CONDITIONS_OPEN")
        if group is None or group["stage"] != "PRE_OPENING":
            raise err("ERR_GROUP_NOT_IN_PRE_OPENING")
        if not any(e["status"] == "PASSED" for e in calc.exams_of(filing["group_id"])):
            raise err("ERR_READINESS_EXAM_NOT_PASSED")

    if decision_note is not None:
        filing["decision_note"] = decision_note
    filing["decision_at"] = db.clock()

    if decision == "ADDITIONAL_INFO_REQUESTED":
        if filing["info_request_round"] < calc.MAX_INFO_ROUNDS:
            filing["info_request_round"] += 1
            filing["status"] = "ADDITIONAL_INFO_REQUESTED"
            calc.recompute_filing_posture(filing)
            db.touch(filing)
        else:
            # PRD 248: the ceiling converts a fourth request into an outright denial.
            filing["status"] = "DENIED"
            calc.recompute_filing_posture(filing)
            db.touch(filing)
            cascade.filing_denied_cascade(filing)
    elif decision == "CONDITIONALLY_APPROVED":
        filing["status"] = "CONDITIONALLY_APPROVED"
        if filing["authority"] == "CHARTERING_AUTHORITY":
            plan = db.get("plans", filing["pinned_business_plan_id"])
            if plan is not None and plan["status"] == "SUBMITTED":
                plan["status"] = "PINNED"
                db.touch(plan)
        calc.recompute_filing_posture(filing)
        db.touch(filing)
        approved = [f for f in calc.filings_of(filing["group_id"])
                    if f["status"] == "CONDITIONALLY_APPROVED"]
        if group is not None and group["stage"] == "UNDER_REVIEW" and len(approved) == 2:
            group["stage"] = "CONDITIONALLY_APPROVED"
            group["opening_blocked_reason"] = "NONE"
            db.touch(group)
    elif decision == "DENIED":
        filing["status"] = "DENIED"
        calc.recompute_filing_posture(filing)
        db.touch(filing)
        cascade.filing_denied_cascade(filing)
    else:
        filing["status"] = "FINAL_APPROVED"
        calc.recompute_filing_posture(filing)
        db.touch(filing)
    db.commit()
    return response.object_response(serialize.filing(filing))


@bp.post("/de-novo/regulatory-filings/<filing_id>/conditions")
def create_condition(filing_id):
    authenticate(("CharteringExaminer", "InsuranceExaminer"))
    data = v.body()
    condition_code = v.req_str(data, "condition_code", 1, 40)
    category = v.req_enum(data, "category", CATEGORIES)
    is_blocking = v.req_bool(data, "is_pre_opening_blocking")
    deadline_utc = v.req_dt(data, "deadline_utc")
    filing = must_get("filings", filing_id)
    if filing["status"] != "CONDITIONALLY_APPROVED":
        raise err("ERR_CONDITIONS_NOT_ATTACHABLE")
    _require_authority(filing)
    for row in calc.conditions_of(filing["id"]):
        if row["condition_code"] == condition_code:
            raise err("ERR_CONDITION_CODE_DUPLICATE")
    if deadline_utc <= db.clock():
        raise err("ERR_CONDITION_DEADLINE_IN_PAST")
    condition = db.insert("conditions", {
        "filing_id": filing["id"],
        "condition_code": condition_code,
        "category": category,
        "is_pre_opening_blocking": is_blocking,
        "deadline_utc": deadline_utc,
        "status": "OPEN",
        "evidence_reference": None,
        "adjudication_count": 0,
    })
    calc.recompute_filing_posture(filing)
    db.touch(filing)
    db.commit()
    return response.object_response(serialize.condition(condition), 201)


@bp.post("/de-novo/approval-conditions/<condition_id>/evidence")
def submit_evidence(condition_id):
    authenticate(("CharterCounsel", "LeadOrganizer"))
    data = v.body()
    evidence_reference = v.req_str(data, "evidence_reference", 20, None)
    condition = must_get("conditions", condition_id)
    filing = db.get("filings", condition["filing_id"])
    require_organizer_identity(filing["group_id"] if filing is not None else None)
    if condition["status"] not in ("OPEN", "FAILED"):
        raise err("ERR_CONDITION_NOT_OPEN")
    if db.clock() >= condition["deadline_utc"]:
        raise err("ERR_CONDITION_DEADLINE_PASSED")
    condition["status"] = "EVIDENCE_SUBMITTED"
    condition["evidence_reference"] = evidence_reference
    db.touch(condition)
    if filing is not None:
        calc.recompute_filing_posture(filing)
        db.touch(filing)
    db.commit()
    return response.object_response(serialize.condition(condition))


@bp.post("/de-novo/approval-conditions/<condition_id>/adjudicate")
def adjudicate_condition(condition_id):
    authenticate(("CharteringExaminer", "InsuranceExaminer"))
    data = v.body()
    disposition = v.req_enum(data, "disposition", DISPOSITIONS)
    condition = must_get("conditions", condition_id)
    filing = db.get("filings", condition["filing_id"])
    if condition["status"] not in DISPOSITION_SOURCES[disposition]:
        raise err("ERR_CONDITION_DISPOSITION_NOT_ALLOWED")
    if filing is not None:
        _require_authority(filing)
    if disposition == "WAIVED" and condition["is_pre_opening_blocking"]:
        raise err("ERR_BLOCKING_CONDITION_NOT_WAIVABLE")
    if disposition == "REOPENED" and filing is not None and filing["status"] == "FINAL_APPROVED":
        raise err("ERR_FILING_ALREADY_FINAL")
    condition["status"] = "OPEN" if disposition == "REOPENED" else disposition
    condition["adjudication_count"] += 1
    db.touch(condition)
    if filing is not None:
        cascade.filing_posture_cascade(filing)
        db.touch(filing)
    db.commit()
    return response.object_response(serialize.condition(condition))

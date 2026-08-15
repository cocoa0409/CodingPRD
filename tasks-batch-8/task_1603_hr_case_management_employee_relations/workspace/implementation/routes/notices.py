"""Closure notices: drafting, confidentiality tiers, delivery lifecycle (PRD §3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_CONFIDENTIALITY_VIOLATION,
    ERR_RECIPIENT_MISMATCH,
)
from middleware import authorize
from response import success_object
from services.core import (
    new_record, touch, require_path, require_ref, list_response,
    serialize_notice, check_case_not_held, touch_case_manifest,
)
from util import CLOCK, fmt_dt
from validate import Payload

bp = Blueprint("notices", __name__)

READ_ROLES = {"ERManager", "LegalCounsel"}
RECIPIENT_ROLES = {"REPORTER", "SUBJECT"}
CONFIDENTIALITY_TIERS = {"TIER_1_SUMMARY", "TIER_2_LIMITED", "TIER_3_FULL"}


def _check_confidentiality(case, recipient_role, tier, body_text,
                           recipient_employee_id):
    """Priority 11 — confidentiality rules for notice content/tier."""
    if recipient_role == "SUBJECT" and tier == "TIER_3_FULL":
        raise_error(ERR_CONFIDENTIALITY_VIOLATION,
                    "SUBJECT recipients may receive at most TIER_2_LIMITED")
    if tier == "TIER_1_SUMMARY" and isinstance(body_text, str):
        # the body must not name other involved employees
        involved = {case["subject_employee_id"]}
        if case["reporter_employee_id"] is not None:
            involved.add(case["reporter_employee_id"])
        involved.discard(recipient_employee_id)
        for emp_id in involved:
            emp = db["employees"].get(emp_id)
            if emp is not None and emp["full_name"] and \
                    emp["full_name"] in body_text:
                raise_error(ERR_CONFIDENTIALITY_VIOLATION,
                            "TIER_1_SUMMARY body must not name other involved "
                            "employees")


@bp.post("/er/cases/<cid>/closure-notices")
def draft_notice(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    recipient_employee_id = p.get_str("recipient_employee_id", required=True)
    recipient_role = p.get_enum("recipient_role", RECIPIENT_ROLES, required=True)
    confidentiality_tier = p.get_enum("confidentiality_tier",
                                      CONFIDENTIALITY_TIERS, required=True)
    body_text = p.get_str("body_text", required=True)

    # priority 5
    if recipient_employee_id is not None:
        require_ref("employees", recipient_employee_id, "recipient_employee_id")

    # priority 6 — notices are drafted once the case reaches PENDING_CLOSURE
    if case["status"] != "PENDING_CLOSURE":
        raise_error(ERR_INVALID_STATE,
                    f"cannot draft closure notices while the case is "
                    f"{case['status']}")
    # priority 7
    check_case_not_held(case)

    # priority 11 — confidentiality
    _check_confidentiality(case, recipient_role, confidentiality_tier,
                           body_text, recipient_employee_id)

    # priority 20 — recipient must actually be the case's reporter or subject
    if recipient_role is not None and recipient_employee_id is not None:
        expected = (case["reporter_employee_id"] if recipient_role == "REPORTER"
                    else case["subject_employee_id"])
        if expected is None or recipient_employee_id != expected:
            raise_error(ERR_RECIPIENT_MISMATCH,
                        "notice recipient is not the case's reporter or "
                        "subject for the declared recipient_role")

    # priority 24
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "case_id": cid,
        "closure_sequence": case["reopen_count"] + 1,
        "recipient_employee_id": recipient_employee_id,
        "recipient_role": recipient_role,
        "confidentiality_tier": confidentiality_tier,
        "body_text": body_text,
        "sent_at": None,
        "delivery_status": "QUEUED",
    })
    db["closure_notices"][rec["id"]] = rec
    return success_object(serialize_notice(rec), status=201)


@bp.get("/er/cases/<cid>/closure-notices")
def list_case_notices(cid):
    authorize(READ_ROLES)
    require_path("cases", cid)
    items = [n for n in db["closure_notices"].values() if n["case_id"] == cid]
    for field in ("delivery_status", "recipient_role"):
        v = request.args.get(field)
        if v is not None:
            items = [n for n in items if n.get(field) == v]
    return list_response(items, serialize_notice)


@bp.get("/er/closure-notices/<nid>")
def get_notice(nid):
    authorize(READ_ROLES)
    rec = require_path("closure_notices", nid)
    return success_object(serialize_notice(rec))


@bp.get("/er/closure-notices")
def list_notices():
    authorize(READ_ROLES)
    items = list(db["closure_notices"].values())
    for field in ("recipient_employee_id", "delivery_status", "recipient_role"):
        v = request.args.get(field)
        if v is not None:
            items = [n for n in items if n.get(field) == v]
    return list_response(items, serialize_notice)


@bp.post("/er/closure-notices/<nid>/send")
def send_notice(nid):
    authorize({"ERManager"})
    notice = require_path("closure_notices", nid)
    case = db["cases"][notice["case_id"]]

    # priority 6 — QUEUED notice under a PENDING_CLOSURE case
    if notice["delivery_status"] != "QUEUED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot send a notice in status "
                    f"{notice['delivery_status']}")
    if case["status"] != "PENDING_CLOSURE":
        raise_error(ERR_INVALID_STATE,
                    f"cannot send notices while the case is {case['status']}")
    # priority 7
    check_case_not_held(case)
    # priority 11 — tier must remain valid for the recipient role
    _check_confidentiality(case, notice["recipient_role"],
                           notice["confidentiality_tier"], notice["body_text"],
                           notice["recipient_employee_id"])

    notice["delivery_status"] = "SENT"
    notice["sent_at"] = fmt_dt(CLOCK.now())
    touch(notice)
    touch_case_manifest(notice["case_id"])
    return success_object(serialize_notice(notice))


@bp.post("/er/closure-notices/<nid>/mark-failed")
def mark_failed(nid):
    authorize({"ERManager"})
    notice = require_path("closure_notices", nid)
    p = Payload(request.get_json(silent=True))
    failure_reason = p.get_str("failure_reason", required=True)

    # priority 6
    if notice["delivery_status"] != "QUEUED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot mark failed a notice in status "
                    f"{notice['delivery_status']}")
    # priority 7
    case = db["cases"][notice["case_id"]]
    check_case_not_held(case)
    # priority 24
    p.raise_if_errors()

    notice["delivery_status"] = "FAILED"
    touch(notice)
    return success_object(serialize_notice(notice))


@bp.post("/er/closure-notices/<nid>/retry")
def retry_notice(nid):
    authorize({"ERManager"})
    notice = require_path("closure_notices", nid)

    # priority 6 — retry is defined only from FAILED
    if notice["delivery_status"] != "FAILED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot retry a notice in status "
                    f"{notice['delivery_status']}")
    # priority 7
    case = db["cases"][notice["case_id"]]
    check_case_not_held(case)

    notice["delivery_status"] = "QUEUED"
    touch(notice)
    return success_object(serialize_notice(notice))


@bp.post("/er/closure-notices/<nid>/suppress")
def suppress_notice(nid):
    authorize({"LegalCounsel"})
    notice = require_path("closure_notices", nid)
    case = db["cases"][notice["case_id"]]

    # priority 6 — suppression is defined only from QUEUED, and only while the
    # case is under litigation hold (this action is exempt from the freeze,
    # PRD §2.7)
    if notice["delivery_status"] != "QUEUED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot suppress a notice in status "
                    f"{notice['delivery_status']}")
    if not case["litigation_hold"]:
        raise_error(ERR_INVALID_STATE,
                    "notices may be suppressed only while the case is under "
                    "litigation hold")

    notice["delivery_status"] = "SUPPRESSED"
    touch(notice)
    return success_object(serialize_notice(notice))

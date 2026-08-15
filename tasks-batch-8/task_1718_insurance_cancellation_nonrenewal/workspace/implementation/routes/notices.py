"""NoticeRecord endpoints (PRD §3.4)."""

import db
import util
from errors import err_invalid_state
from middleware import require_roles
from response import success_list, success_object
from flask import Blueprint, request

bp = Blueprint("notices", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.get("/carrier/notices/<noticeId>")
@require_roles(*ALL_READERS)
def get_notice(noticeId, _user_id, _role):
    rec = util.resolve(db.notices, noticeId)
    return success_object(util.public(rec), 200)


@bp.get("/carrier/notices")
@require_roles(*ALL_READERS)
def list_notices(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.notices.values()),
        {
            "cancellation_case_id": request.args.get("cancellation_case_id"),
            "nonrenewal_case_id": request.args.get("nonrenewal_case_id"),
            "insured_interest_id": request.args.get("insured_interest_id"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/notices/<noticeId>/confirm-delivery")
@require_roles("Underwriter")
def confirm_delivery(noticeId, _user_id, _role):
    rec = util.resolve(db.notices, noticeId)
    if rec["status"] != "MAILED":
        raise err_invalid_state("Only a MAILED notice can be confirmed")
    rec["status"] = "DELIVERY_CONFIRMED"
    util.touch(rec)
    return success_object(util.public(rec), 200)


@bp.post("/carrier/notices/<noticeId>/mark-undeliverable")
@require_roles("Underwriter")
def mark_undeliverable(noticeId, _user_id, _role):
    rec = util.resolve(db.notices, noticeId)
    if rec["status"] != "MAILED":
        raise err_invalid_state("Only a MAILED notice can be marked undeliverable")
    rec["status"] = "RETURNED_UNDELIVERABLE"
    util.touch(rec)
    return success_object(util.public(rec), 200)

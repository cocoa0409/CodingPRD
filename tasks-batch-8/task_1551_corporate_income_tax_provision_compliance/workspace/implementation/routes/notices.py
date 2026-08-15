"""TaxNotice endpoints: log, list, get, assign-review, respond (late response
from OVERDUE is permitted), resolve."""
from flask import Blueprint

from db import db, new_record, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE_TRANSITION,
    ERR_DATE_RANGE_INVALID,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize
from util import is_date_str, parse_date
from validate import (
    body_json, req_str, req_enum, req_date, req_nonempty_str, opt_nullable_id,
)

bp = Blueprint("notices", __name__)

NOTICE_TYPES = ("INFORMATION_REQUEST", "AUDIT_OPENING", "PROPOSED_ADJUSTMENT", "PENALTY_ASSESSMENT")


@bp.route("/tax/notices", methods=["POST"])
def create_notice():
    authorized(("TaxAccountant",))
    data = body_json()

    # Priority 3 (existence): body FK references resolve.
    jur_probe = data.get("jurisdiction_id")
    if isinstance(jur_probe, str):
        get_or_404(db.jurisdictions, jur_probe, "Jurisdiction")
    audit_probe = data.get("audit_case_id")
    if audit_probe is not None and isinstance(audit_probe, str):
        get_or_404(db.audits, audit_probe, "AuditCase")

    # Priority 8 (date-range sanity): the response deadline must not precede receipt.
    rec_raw, due_raw = data.get("received_on"), data.get("response_due_on")
    if is_date_str(rec_raw) and is_date_str(due_raw):
        if parse_date(due_raw) < parse_date(rec_raw):
            raise_error(ERR_DATE_RANGE_INVALID,
                        "response_due_on must not precede received_on")

    # Priority 11 (structural).
    jurisdiction_id = req_str(data, "jurisdiction_id")
    audit_case_id = opt_nullable_id(data, "audit_case_id")
    notice_type = req_enum(data, "notice_type", NOTICE_TYPES)
    received_on = req_date(data, "received_on")
    response_due_on = req_date(data, "response_due_on")
    get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")
    if audit_case_id is not None:
        get_or_404(db.audits, audit_case_id, "AuditCase")

    notice = new_record({
        "jurisdiction_id": jurisdiction_id,
        "audit_case_id": audit_case_id,
        "notice_type": notice_type,
        "received_on": received_on,
        "response_due_on": response_due_on,
        "response_text": None,
        "status": "RECEIVED",
    })
    db.notices[notice["id"]] = notice
    return success_object(serialize(notice), status=201)


@bp.route("/tax/notices", methods=["GET"])
def list_notices():
    authorized(READER_ROLES)
    recs = apply_filters(db.notices.values(), {
        "jurisdiction_id": "jurisdiction_id",
        "audit_case_id": "audit_case_id",
        "status": "status",
        "notice_type": "notice_type",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/notices/<noticeId>", methods=["GET"])
def get_notice(noticeId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.notices, noticeId, "TaxNotice")))


@bp.route("/tax/notices/<noticeId>/assign-review", methods=["POST"])
def assign_review(noticeId):
    authorized(("TaxManager",))
    notice = get_or_404(db.notices, noticeId, "TaxNotice")
    if notice["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"assign-review is not defined from notice status {notice['status']}")
    notice["status"] = "UNDER_REVIEW"
    touch(notice)
    return success_object(serialize(notice))


@bp.route("/tax/notices/<noticeId>/respond", methods=["POST"])
def respond_notice(noticeId):
    authorized(("TaxManager",))
    notice = get_or_404(db.notices, noticeId, "TaxNotice")
    if notice["status"] not in ("UNDER_REVIEW", "OVERDUE"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"respond is not defined from notice status {notice['status']}")
    data = body_json()
    notice["response_text"] = req_nonempty_str(data, "response_text")  # structural (p11)
    notice["status"] = "RESPONDED"
    touch(notice)
    return success_object(serialize(notice))


@bp.route("/tax/notices/<noticeId>/resolve", methods=["POST"])
def resolve_notice(noticeId):
    authorized(("TaxManager",))
    notice = get_or_404(db.notices, noticeId, "TaxNotice")
    if notice["status"] != "RESPONDED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"resolve is not defined from notice status {notice['status']}")
    notice["status"] = "RESOLVED"
    touch(notice)
    return success_object(serialize(notice))

"""Audit-log + approval-record read endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from db import STORE
from errors import APIError, ERR_VALIDATION
from middleware import require_auth
from response import success, parse_pagination, paginate
from serializers import audit_log as ser_audit, approval_record as ser_approval
from utils import parse_ts


bp = Blueprint("audit", __name__)


SUBJECT_TYPES_AUDIT = {"TRAVEL_APPLICATION", "REIMBURSEMENT_FORM", "PAYMENT", "INVOICE"}
SUBJECT_TYPES_APPROVAL = {"TRAVEL_APPLICATION", "REIMBURSEMENT_FORM"}
EVENT_TYPES = {"APPROVAL_ACTION", "PAYMENT_EVENT", "EXTERNAL_SYNC"}


@bp.route("/audit-logs", methods=["GET"])
@require_auth(["Admin", "Finance"])
def list_audit_logs():
    limit, offset = parse_pagination()
    rows = list(STORE.audit_logs.values())
    sub_type = request.args.get("subject_type")
    sub_id = request.args.get("subject_id")
    event_type = request.args.get("event_type")
    since = request.args.get("since")
    if sub_type is not None:
        if sub_type not in SUBJECT_TYPES_AUDIT:
            raise APIError(ERR_VALIDATION, "subject_type filter invalid", 422)
        rows = [r for r in rows if r["subject_type"] == sub_type]
    if sub_id is not None:
        rows = [r for r in rows if r["subject_id"] == sub_id]
    if event_type is not None:
        if event_type not in EVENT_TYPES:
            raise APIError(ERR_VALIDATION, "event_type filter invalid", 422)
        rows = [r for r in rows if r["event_type"] == event_type]
    if since is not None:
        since_dt = parse_ts(since)
        if since_dt is False or since_dt is None:
            raise APIError(ERR_VALIDATION, "since must be ISO 8601", 422)
        rows = [r for r in rows if parse_ts(r["created_at"]) >= since_dt]

    rows.sort(key=lambda r: r["created_at"])
    page, pag = paginate(rows, limit, offset)
    return success([ser_audit(r) for r in page], pagination=pag)


@bp.route("/approval-records", methods=["GET"])
@require_auth(["Admin", "Finance", "Applicant"])
def list_approval_records():
    limit, offset = parse_pagination()
    rows = list(STORE.approval_records.values())
    sub_type = request.args.get("subject_type")
    sub_id = request.args.get("subject_id")
    actor_id = request.args.get("actor_id")
    if sub_type is not None:
        if sub_type not in SUBJECT_TYPES_APPROVAL:
            raise APIError(ERR_VALIDATION, "subject_type filter invalid", 422)
        rows = [r for r in rows if r["subject_type"] == sub_type]
    if sub_id is not None:
        rows = [r for r in rows if r["subject_id"] == sub_id]
    if actor_id is not None:
        rows = [r for r in rows if r["actor_id"] == actor_id]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = paginate(rows, limit, offset)
    return success([ser_approval(r) for r in page], pagination=pag)

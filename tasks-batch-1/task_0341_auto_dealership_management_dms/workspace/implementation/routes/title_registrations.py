from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_roles
from routes.lookup import get_path
from services import serialize
from util import get_json_body, paginate, parse_pagination, require_enum, require_str, touch

bp = Blueprint("title_registrations", __name__)


def _has_document(deal_id, doc_type):
    return any(
        d["deal_id"] == deal_id and d["doc_type"] == doc_type
        for d in db.deal_jacket_documents.values()
    )


@bp.get("/title-registrations/<tid>")
@require_roles("TitleClerk", "FinanceManager")
def get_title(tid):
    rec = get_path(db.title_registrations, tid)
    return response.success(serialize.title_registration(rec))


@bp.get("/title-registrations")
@require_roles("TitleClerk", "FinanceManager")
def list_titles():
    limit, offset = parse_pagination()
    items = list(db.title_registrations.values())
    deal_id = request.args.get("deal_id")
    if deal_id is not None:
        items = [t for t in items if t["deal_id"] == deal_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list(
        [serialize.title_registration(t) for t in page], limit, offset, total, has_more
    )


@bp.patch("/title-registrations/<tid>")
@require_roles("TitleClerk")
def patch_title(tid):
    rec = get_path(db.title_registrations, tid)
    body = get_json_body()
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Title registration is not PENDING")
    if "owner_name" in body and body["owner_name"] is not None:
        rec["owner_name"] = require_str(body, "owner_name")
    if "plate_type" in body and body["plate_type"] is not None:
        rec["plate_type"] = require_enum(body, "plate_type", ("NEW_PLATE", "TRANSFER"))
    touch(rec)
    return response.success(serialize.title_registration(rec))


@bp.post("/title-registrations/<tid>/submit")
@require_roles("TitleClerk")
def submit_title(tid):
    rec = get_path(db.title_registrations, tid)
    if rec["status"] not in ("PENDING", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Title registration cannot be submitted from its state")

    deal = db.deals.get(rec["deal_id"])
    if deal is None or deal["status"] != "FUNDED":
        raise err("ERR_DEAL_NOT_FUNDED", "Referenced deal is not FUNDED")
    if not _has_document(rec["deal_id"], "ODOMETER"):
        raise err("ERR_STIP_MISSING", "ODOMETER document missing")

    if rec["status"] == "REJECTED":
        rec["resubmit_count"] += 1
        rec["rejection_reason"] = None
    rec["status"] = "SUBMITTED"
    touch(rec)
    return response.success(serialize.title_registration(rec))


@bp.post("/title-registrations/<tid>/dmv-result")
@require_roles("TitleClerk")
def dmv_result(tid):
    rec = get_path(db.title_registrations, tid)
    body = get_json_body()
    result = require_enum(body, "result", ("ACCEPT", "REJECT"))
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Title registration is not SUBMITTED")

    if result == "ACCEPT":
        rec["status"] = "ACCEPTED"
    else:
        reason = body.get("rejection_reason")
        if reason is None or not isinstance(reason, str) or reason == "":
            raise err("ERR_REJECTION_REASON_REQUIRED", "rejection_reason is required on REJECT")
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = reason
    touch(rec)
    return response.success(serialize.title_registration(rec))

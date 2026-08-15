"""314(b) information sharing records."""
from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from services.core import LE_OPEN_STATUSES
from util import (SHARE_DIRECTIONS, base_entity, opt_str, req_dt, req_enum,
                  req_str, serialize, sort_created, touch)

bp = Blueprint("shares", __name__)

CERTIFICATION_DAYS = 365
DUPLICATE_BUFFER_DAYS = 90


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


@bp.route("/info-share-requests", methods=["POST"])
def create_share():
    body = get_body()
    direction = req_enum(body, "direction", SHARE_DIRECTIONS)
    counterparty = req_str(body, "counterparty_institution_id")
    subject_customer_id = req_str(body, "subject_customer_id")
    case_id = opt_str(body, "case_id")
    certified_at = req_dt(body, "certified_at")
    purpose_note = req_str(body, "purpose_note")
    _, role = authn()
    authz(role, ["BSAAnalyst"])
    if certified_at > db.now():
        raise ApiError("ERR_INVALID_REQUEST",
                       "certified_at must not be in the future", 400)
    customer = _get(db.customers, subject_customer_id, "Customer")
    if case_id is not None:
        _get(db.cases, case_id, "Case")
    share = base_entity()
    share.update({
        "direction": direction,
        "counterparty_institution_id": counterparty,
        "subject_customer_id": customer["id"],
        "case_id": case_id,
        "certified_at": certified_at,
        "certification_expires_at": certified_at + timedelta(days=CERTIFICATION_DAYS),
        "purpose_note": purpose_note,
        "sent_at": None,
        "response_received_at": None,
        "status": "DRAFT",
    })
    db.shares[share["id"]] = share
    return response.success(serialize(share), status=201)


@bp.route("/info-share-requests", methods=["GET"])
def list_shares():
    _, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(db.shares.values())
    for field in ("subject_customer_id", "case_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [s for s in items if s.get(field) == value]
    items = sort_created(items)
    return response.paginated([serialize(s) for s in items], limit, offset)


@bp.route("/info-share-requests/<rid>", methods=["GET"])
def get_share(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    share = _get(db.shares, rid, "InfoShareRequest")
    return response.success(serialize(share), status=200)


@bp.route("/info-share-requests/<rid>/send", methods=["POST"])
def send_share(rid):
    _, role = authn()
    authz(role, ["BSAAnalyst"])
    share = _get(db.shares, rid, "InfoShareRequest")
    if share["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       f"InfoShareRequest in status {share['status']} cannot be sent", 409)
    # Priority 8: LE-inquiry safety hold (outranks duplicate window + expiry).
    if share["case_id"] is not None:
        open_inquiry = any(
            i.get("case_id") == share["case_id"] and i["status"] in LE_OPEN_STATUSES
            for i in db.inquiries.values())
        if open_inquiry:
            raise ApiError("ERR_LE_INQUIRY_OPEN",
                           "An open law-enforcement inquiry on the linked case "
                           "blocks sending", 409)
    now = db.now()
    # Priority 12: 90-day duplicate buffer (outranks certification expiry).
    if share["direction"] == "OUTBOUND":
        buffer_start = now - timedelta(days=DUPLICATE_BUFFER_DAYS)
        duplicate = any(
            s["id"] != share["id"]
            and s["direction"] == "OUTBOUND"
            and s["counterparty_institution_id"] == share["counterparty_institution_id"]
            and s["subject_customer_id"] == share["subject_customer_id"]
            and s["status"] in {"SENT", "RESPONDED"}
            and s["sent_at"] is not None and s["sent_at"] >= buffer_start
            for s in db.shares.values())
        if duplicate:
            raise ApiError("ERR_314B_DUPLICATE_WINDOW",
                           "An OUTBOUND share to the same counterparty about the "
                           "same subject was already sent within the trailing "
                           "90-day buffer", 409)
    # Priority 18: certification currency.
    if now > share["certification_expires_at"]:
        raise ApiError("ERR_CERTIFICATION_EXPIRED",
                       "The 314(b) certification has expired", 422)
    share["sent_at"] = now
    share["status"] = "SENT"
    touch(share)
    return response.success(serialize(share), status=200)


@bp.route("/info-share-requests/<rid>/record-response", methods=["POST"])
def record_response(rid):
    get_body()  # optional response_note; accepted and not persisted
    _, role = authn()
    authz(role, ["BSAAnalyst"])
    share = _get(db.shares, rid, "InfoShareRequest")
    if share["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE",
                       f"InfoShareRequest in status {share['status']} cannot "
                       "record a response", 409)
    share["response_received_at"] = db.now()
    share["status"] = "RESPONDED"
    touch(share)
    return response.success(serialize(share), status=200)

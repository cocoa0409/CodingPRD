"""EvidenceItem endpoints (PRD 3.6)."""

from flask import Blueprint, g, request

from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_evidence_item, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_evidence_item
from util import Body, EVIDENCE_STATUSES, EVIDENCE_TYPES, filter_enum

bp = Blueprint("evidence", __name__)


def _owning_merchant_id(item):
    cb = db.chargebacks.get(item["chargeback_id"])
    return cb["merchant_id"] if cb is not None else None


@bp.post("/acquirer/evidence-items")
def create_evidence_item():
    authenticate(("MerchantUser", "AcquirerOps"))
    b = Body(json_body())
    chargeback_id = b.req_str("chargeback_id")
    evidence_type = b.req_enum("evidence_type", EVIDENCE_TYPES)
    document_uri = b.req_str("document_uri")

    # Priority 3: body-referenced chargeback (+ MerchantUser ownership hiding).
    cb = None
    if chargeback_id is not None:
        cb = get_or_404(db.chargebacks, chargeback_id, "Chargeback")
        hide_if_cross_merchant(cb["merchant_id"])
    # Priority 5: upload only while the case is being fought.
    if cb is not None and cb["case_status"] not in ("MERCHANT_NOTIFIED", "REPRESENTED"):
        raise ApiError(409, "ERR_INVALID_CASE_STATE",
                       "Evidence upload requires the case to be MERCHANT_NOTIFIED or REPRESENTED")
    # Priority 6: suspension gate (applies to uploads for a suspended merchant's case).
    if cb is not None:
        merchant = db.merchants[cb["merchant_id"]]
        if merchant["status"] != "ACTIVE":
            raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    b.raise_pending()

    item = new_evidence_item(cb["id"], evidence_type, document_uri)
    db.evidence_items[item["id"]] = item
    return ok_object(serialize_evidence_item(item), status=201)


@bp.get("/acquirer/evidence-items")
def list_evidence_items():
    authenticate(ALL_ROLES)
    chargeback_id = request.args.get("chargeback_id")
    status = filter_enum(request.args, "status", EVIDENCE_STATUSES)
    records = list(db.evidence_items.values())
    if is_merchant_user():
        records = [e for e in records if _owning_merchant_id(e) == g.uid]
    if chargeback_id is not None:
        records = [e for e in records if e["chargeback_id"] == chargeback_id]
    if status is not None:
        records = [e for e in records if e["status"] == status]
    return list_response(records, serialize_evidence_item)


@bp.get("/acquirer/evidence-items/<eid>")
def get_evidence_item(eid):
    authenticate(ALL_ROLES)
    item = get_or_404(db.evidence_items, eid, "EvidenceItem")
    hide_if_cross_merchant(_owning_merchant_id(item))
    return ok_object(serialize_evidence_item(item))


@bp.post("/acquirer/evidence-items/<eid>/withdraw")
def withdraw_evidence_item(eid):
    authenticate(("MerchantUser",))
    item = get_or_404(db.evidence_items, eid, "EvidenceItem")
    hide_if_cross_merchant(_owning_merchant_id(item))
    if item["status"] != "DRAFT":
        raise ApiError(400, "ERR_INVALID_REQUEST", "Only a DRAFT evidence item can be withdrawn")
    item["status"] = "WITHDRAWN"
    touch(item)
    return ok_object(serialize_evidence_item(item))

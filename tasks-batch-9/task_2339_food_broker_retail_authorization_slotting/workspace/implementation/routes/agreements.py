"""Commission agreements: the rate card (PRD section 3.2)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize
from services import domain

bp = Blueprint("agreements", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "principal_id": rec["principal_id"],
        "retailer_id": rec["retailer_id"],
        "category_code": rec["category_code"],
        "effective_start_date": rec["effective_start_date"],
        "effective_end_date": rec["effective_end_date"],
        "base_commission_bps": rec["base_commission_bps"],
        "tier_threshold_cents": rec["tier_threshold_cents"],
        "tier_commission_bps": rec["tier_commission_bps"],
        "exclusive_in_category": rec["exclusive_in_category"],
        "status": rec["status"],
        "activated_at": rec["activated_at"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/commission-agreements")
def create_agreement():
    authorize("BrokerAdmin")
    data = v.body()

    principal_id = v.req_id(data, "principal_id")
    retailer_id = v.req_id(data, "retailer_id")
    category_code = v.req_enum(data, "category_code", v.CATEGORY_CODES)
    start = v.req_date(data, "effective_start_date")
    end = v.req_date(data, "effective_end_date")
    base_bps = v.req_bps(data, "base_commission_bps")
    threshold = v.req_int(data, "tier_threshold_cents", 0)
    tier_bps = v.req_bps(data, "tier_commission_bps")
    exclusive = v.opt_bool(data, "exclusive_in_category", False)

    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'effective_end_date' must be later than 'effective_start_date'.")

    db.get("principals", principal_id)
    db.get("retailers", retailer_id)

    rec = db.base_record()
    rec.update({
        "principal_id": principal_id,
        "retailer_id": retailer_id,
        "category_code": category_code,
        "effective_start_date": clock.date_str(start),
        "effective_end_date": clock.date_str(end),
        "base_commission_bps": base_bps,
        "tier_threshold_cents": threshold,
        "tier_commission_bps": tier_bps,
        "exclusive_in_category": exclusive,
        "status": "DRAFT",
        "activated_at": None,
    })
    db.insert("agreements", rec)
    return response.created(serialize(rec))


@bp.get("/commission-agreements/<agreement_id>")
def read_agreement(agreement_id):
    authorize(*ALL_ROLES)
    return response.ok(serialize(db.get("agreements", agreement_id)))


@bp.get("/commission-agreements")
def list_agreements():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    principal_id = v.filter_value("principal_id")
    retailer_id = v.filter_value("retailer_id")
    category_code = v.filter_value("category_code")
    status = v.filter_value("status")
    rows = []
    for rec in db.ordered("agreements"):
        if principal_id is not None and rec["principal_id"] != principal_id:
            continue
        if retailer_id is not None and rec["retailer_id"] != retailer_id:
            continue
        if category_code is not None and rec["category_code"] != category_code:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/commission-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authorize("BrokerAdmin")
    rec = db.get("agreements", agreement_id)

    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    principal = db.find("principals", rec["principal_id"])
    if principal is not None and principal["status"] == "TERMINATED":
        raise ApiError("ERR_PRINCIPAL_TERMINATED")

    start = clock.parse_date(rec["effective_start_date"])
    end = clock.parse_date(rec["effective_end_date"])
    for other in db.ordered("agreements"):
        if other["id"] == rec["id"] or other["status"] != "ACTIVE":
            continue
        if other["principal_id"] != rec["principal_id"]:
            continue
        if other["retailer_id"] != rec["retailer_id"]:
            continue
        if other["category_code"] != rec["category_code"]:
            continue
        other_start = clock.parse_date(other["effective_start_date"])
        other_end = clock.parse_date(other["effective_end_date"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_AGREEMENT_WINDOW_OVERLAP")

    db.assign(rec, status="ACTIVE", activated_at=clock.iso_now())
    return response.ok(serialize(rec))


@bp.post("/commission-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authorize("BrokerAdmin")
    rec = db.get("agreements", agreement_id)

    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    for deal in db.ordered("deals"):
        if deal["state"] not in ("PROPOSED", "COUNTERED"):
            continue
        presentation = db.find("presentations", deal["presentation_id"])
        if presentation is None or presentation["principal_id"] != rec["principal_id"]:
            continue
        review = db.find("reviews", presentation["review_id"])
        if review is None:
            continue
        if review["retailer_id"] == rec["retailer_id"] and review["category_code"] == rec["category_code"]:
            raise ApiError("ERR_AGREEMENT_HAS_OPEN_NEGOTIATION")

    db.assign(rec, status="TERMINATED")
    return response.ok(serialize(rec))

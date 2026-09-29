"""Deductions and post-audit recovery (PRD section 3.9)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_principal_scope, check_retailer_scope
from services import calc, domain

bp = Blueprint("deductions", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "retailer_id": rec["retailer_id"],
        "principal_id": rec["principal_id"],
        "promotion_event_id": rec["promotion_event_id"],
        "original_deduction_id": rec["original_deduction_id"],
        "reason_code": rec["reason_code"],
        "amount_cents": rec["amount_cents"],
        "deduction_date": rec["deduction_date"],
        "claim_amount_cents": rec["claim_amount_cents"],
        "recovered_cents": rec["recovered_cents"],
        "conceded_cents": rec["conceded_cents"],
        "open_cents": rec["open_cents"],
        "substantiation_doc_count": rec["substantiation_doc_count"],
        "filed_by_user_id": rec["filed_by_user_id"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "refile_count": rec["refile_count"],
        "settlement_state": rec["settlement_state"],
        "dispute_state": rec["dispute_state"],
        "denial_reason": rec["denial_reason"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _dispute_window_open(rec):
    retailer = db.find("retailers", rec["retailer_id"])
    days = retailer["deduction_dispute_window_days"] if retailer else 0
    deadline = clock.add_days(clock.parse_date(rec["deduction_date"]), days)
    return clock.today() <= deadline


@bp.post("/deductions")
def create_deduction():
    user_id, role = authorize("RetailerBuyer")
    data = v.body()

    retailer_id = v.req_id(data, "retailer_id")
    principal_id = v.req_id(data, "principal_id")
    reason_code = v.req_enum(data, "reason_code", v.REASON_CODES)
    amount = v.req_int(data, "amount_cents", 1)
    deduction_date = v.req_date(data, "deduction_date")

    # The link requirement itself is part of the link rule, not the shape band: a
    # PROMO_BILLBACK that carries no event answers ERR_PROMO_LINK_INVALID.
    if reason_code == "PROMO_BILLBACK":
        promotion_event_id = v.opt_id(data, "promotion_event_id")
    else:
        v.forbid(data, "promotion_event_id", "unless reason_code is PROMO_BILLBACK")
        promotion_event_id = None

    if reason_code == "DUPLICATE_BILLBACK":
        original_deduction_id = v.opt_id(data, "original_deduction_id")
    else:
        v.forbid(data, "original_deduction_id", "unless reason_code is DUPLICATE_BILLBACK")
        original_deduction_id = None

    retailer = db.get("retailers", retailer_id)
    principal = db.get("principals", principal_id)
    event = db.get("promotions", promotion_event_id) if promotion_event_id else None
    original = db.get("deductions", original_deduction_id) if original_deduction_id else None

    check_retailer_scope(role, user_id, retailer["id"])

    if reason_code == "PROMO_BILLBACK":
        if event is None:
            raise ApiError("ERR_PROMO_LINK_INVALID")
        auth = db.find("authorizations", event["authorization_id"])
        item = db.find("items", auth["item_id"]) if auth is not None else None
        if auth is None or item is None:
            raise ApiError("ERR_PROMO_LINK_INVALID")
        if auth["retailer_id"] != retailer["id"] or item["principal_id"] != principal["id"]:
            raise ApiError("ERR_PROMO_LINK_INVALID")

    if reason_code == "DUPLICATE_BILLBACK":
        if original is None:
            raise ApiError("ERR_DUPLICATE_LINK_INVALID")
        if original["retailer_id"] != retailer["id"] \
                or original["principal_id"] != principal["id"] \
                or original["amount_cents"] != amount:
            raise ApiError("ERR_DUPLICATE_LINK_INVALID")

    rec = db.base_record()
    rec.update({
        "retailer_id": retailer["id"],
        "principal_id": principal["id"],
        "promotion_event_id": promotion_event_id,
        "original_deduction_id": original_deduction_id,
        "reason_code": reason_code,
        "amount_cents": amount,
        "deduction_date": clock.date_str(deduction_date),
        "claim_amount_cents": 0,
        "recovered_cents": 0,
        "conceded_cents": 0,
        "open_cents": amount,
        "substantiation_doc_count": 0,
        "filed_by_user_id": None,
        "approved_by_user_id": None,
        "refile_count": 0,
        "settlement_state": "OPEN",
        "dispute_state": "NOT_DISPUTED",
        "denial_reason": None,
    })
    db.insert("deductions", rec)
    domain.recompute_principal(principal)
    return response.created(serialize(rec))


@bp.get("/deductions/<deduction_id>")
def read_deduction(deduction_id):
    user_id, role = authorize(*ALL_ROLES)
    rec = db.get("deductions", deduction_id)
    check_principal_scope(role, user_id, rec["principal_id"])
    return response.ok(serialize(rec))


@bp.get("/deductions")
def list_deductions():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    retailer_id = v.filter_value("retailer_id")
    principal_id = v.filter_value("principal_id")
    promotion_event_id = v.filter_value("promotion_event_id")
    original_deduction_id = v.filter_value("original_deduction_id")
    reason_code = v.filter_value("reason_code")
    settlement_state = v.filter_value("settlement_state")
    dispute_state = v.filter_value("dispute_state")
    rows = []
    for rec in db.ordered("deductions"):
        if retailer_id is not None and rec["retailer_id"] != retailer_id:
            continue
        if principal_id is not None and rec["principal_id"] != principal_id:
            continue
        if promotion_event_id is not None and rec["promotion_event_id"] != promotion_event_id:
            continue
        if original_deduction_id is not None and rec["original_deduction_id"] != original_deduction_id:
            continue
        if reason_code is not None and rec["reason_code"] != reason_code:
            continue
        if settlement_state is not None and rec["settlement_state"] != settlement_state:
            continue
        if dispute_state is not None and rec["dispute_state"] != dispute_state:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/deductions/<deduction_id>/dispute")
def dispute_deduction(deduction_id):
    user_id, _role = authorize("BrokerAccountManager")
    data = v.body()
    claim = v.req_int(data, "claim_amount_cents", 0)

    rec = db.get("deductions", deduction_id)

    if rec["settlement_state"] != "OPEN":
        raise ApiError("ERR_DEDUCTION_ALREADY_SETTLED")
    if rec["dispute_state"] not in ("NOT_DISPUTED", "DENIED"):
        raise ApiError("ERR_INVALID_STATE")

    if not _dispute_window_open(rec):
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED")

    refiling = rec["dispute_state"] == "DENIED"
    if refiling and rec["refile_count"] >= calc.MAX_REFILES:
        raise ApiError("ERR_REFILE_LIMIT_REACHED")
    if claim > rec["amount_cents"]:
        raise ApiError("ERR_CLAIM_EXCEEDS_DEDUCTION")

    rec["claim_amount_cents"] = claim
    rec["dispute_state"] = "FILED"
    rec["filed_by_user_id"] = user_id
    rec["substantiation_doc_count"] = 0
    if refiling:
        rec["refile_count"] = rec["refile_count"] + 1
        rec["denial_reason"] = None
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/deductions/<deduction_id>/substantiate")
def substantiate_deduction(deduction_id):
    authorize("BrokerAccountManager")
    data = v.body()
    v.req_string(data, "document_ref")

    rec = db.get("deductions", deduction_id)

    if rec["dispute_state"] not in ("FILED", "SUBSTANTIATED"):
        raise ApiError("ERR_INVALID_STATE")

    rec["substantiation_doc_count"] = rec["substantiation_doc_count"] + 1
    rec["dispute_state"] = "SUBSTANTIATED"
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/deductions/<deduction_id>/approve-recovery")
def approve_recovery(deduction_id):
    user_id, _role = authorize("BrokerAuditManager")
    rec = db.get("deductions", deduction_id)

    # Band 7 lists settlement_state before dispute_state for deductions.
    if rec["settlement_state"] != "OPEN":
        raise ApiError("ERR_DEDUCTION_ALREADY_SETTLED")
    if rec["dispute_state"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE")

    if user_id == rec["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if rec["substantiation_doc_count"] < calc.MIN_SUBSTANTIATION_DOCS:
        raise ApiError("ERR_SUBSTANTIATION_INSUFFICIENT")

    event = db.find("promotions", rec["promotion_event_id"])
    recoverable = calc.recoverable_amount(rec, event)

    rec["dispute_state"] = "APPROVED"
    rec["approved_by_user_id"] = user_id
    rec["recovered_cents"] = recoverable
    rec["conceded_cents"] = rec["amount_cents"] - recoverable
    rec["open_cents"] = 0
    rec["settlement_state"] = "RECOVERED" if recoverable > 0 else "CONCEDED"
    db.touch(rec)

    domain.promo_settlement_cascade(rec)
    domain.recompute_principal(db.find("principals", rec["principal_id"]))
    return response.ok(serialize(rec))


@bp.post("/deductions/<deduction_id>/deny-recovery")
def deny_recovery(deduction_id):
    user_id, _role = authorize("BrokerAuditManager")
    data = v.body()
    denial_reason = v.req_string(data, "denial_reason")

    rec = db.get("deductions", deduction_id)

    # Band 7 lists settlement_state before dispute_state for deductions.
    if rec["settlement_state"] != "OPEN":
        raise ApiError("ERR_DEDUCTION_ALREADY_SETTLED")
    if rec["dispute_state"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE")

    if user_id == rec["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    rec["dispute_state"] = "DENIED"
    rec["denial_reason"] = denial_reason
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/deductions/<deduction_id>/concede")
def concede_deduction(deduction_id):
    authorize("BrokerAccountManager")
    rec = db.get("deductions", deduction_id)

    if rec["settlement_state"] != "OPEN":
        raise ApiError("ERR_DEDUCTION_ALREADY_SETTLED")
    if rec["dispute_state"] not in ("NOT_DISPUTED", "SUBSTANTIATED", "DENIED"):
        raise ApiError("ERR_INVALID_STATE")

    rec["conceded_cents"] = rec["amount_cents"] - rec["recovered_cents"]
    rec["open_cents"] = 0
    rec["settlement_state"] = "CONCEDED"
    db.touch(rec)

    domain.promo_settlement_cascade(rec)
    domain.recompute_principal(db.find("principals", rec["principal_id"]))
    return response.ok(serialize(rec))

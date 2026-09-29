"""Principal onboarding, lifecycle, adjustment and the commission statement
(PRD sections 3.1, 3.2, 3.9)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_principal_scope
from services import calc, domain

bp = Blueprint("principals", __name__)

_TRANSITIONS = {
    ("PROSPECT", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}


def serialize(rec):
    return {
        "id": rec["id"],
        "name": rec["name"],
        "code": rec["code"],
        "slotting_budget_cents": rec["slotting_budget_cents"],
        "status": rec["status"],
        "slotting_committed_cents": rec["slotting_committed_cents"],
        "open_slotting_liability_cents": rec["open_slotting_liability_cents"],
        "open_deduction_cents": rec["open_deduction_cents"],
        "at_risk_authorization_count": rec["at_risk_authorization_count"],
        "liability_ratio_bps": rec["liability_ratio_bps"],
        "credit_posture": rec["credit_posture"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/principals")
def create_principal():
    authorize("BrokerAdmin")
    data = v.body()

    name = v.req_string(data, "name")
    code = v.req_string(data, "code", 1, 16)
    budget = v.req_int(data, "slotting_budget_cents", 0)

    for existing in db.ordered("principals"):
        if existing["code"] == code:
            raise ApiError("ERR_PRINCIPAL_CODE_DUPLICATE")

    rec = db.base_record()
    rec.update({
        "name": name,
        "code": code,
        "slotting_budget_cents": budget,
        "status": "PROSPECT",
        "slotting_committed_cents": 0,
        "open_slotting_liability_cents": 0,
        "open_deduction_cents": 0,
        "at_risk_authorization_count": 0,
        "liability_ratio_bps": 0,
        "credit_posture": "NORMAL",
    })
    db.insert("principals", rec)
    return response.created(serialize(rec))


@bp.get("/principals/<principal_id>")
def read_principal(principal_id):
    user_id, role = authorize(*ALL_ROLES)
    rec = db.get("principals", principal_id)
    check_principal_scope(role, user_id, rec["id"])
    return response.ok(serialize(rec))


@bp.get("/principals")
def list_principals():
    authorize("BrokerAdmin", "BrokerAccountManager", "BrokerAuditManager", "RetailerBuyer")
    limit, offset = v.pagination()
    code = v.filter_value("code")
    status = v.filter_value("status")
    posture = v.filter_value("credit_posture")
    rows = []
    for rec in db.ordered("principals"):
        if code is not None and rec["code"] != code:
            continue
        if status is not None and rec["status"] != status:
            continue
        if posture is not None and rec["credit_posture"] != posture:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.patch("/principals/<principal_id>")
def patch_principal(principal_id):
    authorize("BrokerAdmin")
    data = v.body()
    name = v.opt_string(data, "name")
    budget = v.opt_int(data, "slotting_budget_cents", None, 0)

    rec = db.get("principals", principal_id)

    if name is not None:
        rec["name"] = name
    if budget is not None:
        rec["slotting_budget_cents"] = budget
    db.touch(rec)
    domain.recompute_principal(rec)
    return response.ok(serialize(rec))


@bp.post("/principals/<principal_id>/status")
def move_principal_status(principal_id):
    authorize("BrokerAdmin")
    data = v.body()
    target = v.req_enum(data, "status", v.PRINCIPAL_STATUSES)

    rec = db.get("principals", principal_id)

    if (rec["status"], target) not in _TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE")

    if rec["status"] == "PROSPECT" and target == "ACTIVE":
        has_active = any(
            a["principal_id"] == rec["id"] and a["status"] == "ACTIVE"
            for a in db.ordered("agreements")
        )
        if not has_active:
            raise ApiError("ERR_PRINCIPAL_HAS_NO_AGREEMENT")

    if target == "TERMINATED":
        for auth in domain.authorizations_of_principal(rec["id"]):
            if auth["authorization_state"] in domain.LIVE_AUTHORIZATION_STATES:
                raise ApiError("ERR_PRINCIPAL_HAS_LIVE_AUTHORIZATIONS")

    rec["status"] = target
    db.touch(rec)

    if target == "TERMINATED":
        for agreement in db.ordered("agreements"):
            if agreement["principal_id"] == rec["id"] and agreement["status"] == "ACTIVE":
                db.assign(agreement, status="TERMINATED")

    domain.recompute_principal(rec)
    return response.ok(serialize(rec))


@bp.get("/principals/<principal_id>/commission-statement")
def commission_statement(principal_id):
    user_id, role = authorize(
        "BrokerAdmin", "BrokerAccountManager", "BrokerAuditManager", "PrincipalPortalUser"
    )
    retailer_id = v.query_required("retailer_id")
    category_code = v.query_required_enum("category_code", v.CATEGORY_CODES)

    principal = db.get("principals", principal_id)
    retailer = db.get("retailers", retailer_id)

    check_principal_scope(role, user_id, principal["id"])

    agreement = domain.active_agreement(principal["id"], retailer["id"], category_code)
    if agreement is None:
        raise ApiError("ERR_NO_ACTIVE_COMMISSION_AGREEMENT")

    qualifying = {}
    for auth in db.ordered("authorizations"):
        if auth["retailer_id"] != retailer["id"]:
            continue
        if auth["authorization_state"] not in ("AUTHORIZED", "AT_RISK", "DISCONTINUED"):
            continue
        review = db.find("reviews", auth["review_id"])
        if review is None or review["category_code"] != category_code:
            continue
        item = db.find("items", auth["item_id"])
        if item is None or item["principal_id"] != principal["id"]:
            continue
        qualifying.setdefault(item["id"], []).append(auth)

    raw_lines = []
    for item_id, auths in qualifying.items():
        item = db.find("items", item_id)
        volume = 0
        for auth in auths:
            for posting in domain.live_postings(auth["id"]):
                volume += posting["reported_case_volume"]
        raw_lines.append({
            "item_id": item_id,
            "upc": item["upc"],
            "line_shipped_cents": volume * item["list_price_cents"],
        })
    raw_lines.sort(key=lambda line: line["upc"])

    lines, total_shipped, total_commission = calc.commission_lines(
        raw_lines,
        agreement["base_commission_bps"],
        agreement["tier_threshold_cents"],
        agreement["tier_commission_bps"],
    )

    return response.ok({
        "principal_id": principal["id"],
        "retailer_id": retailer["id"],
        "category_code": category_code,
        "agreement_id": agreement["id"],
        "base_commission_bps": agreement["base_commission_bps"],
        "tier_threshold_cents": agreement["tier_threshold_cents"],
        "tier_commission_bps": agreement["tier_commission_bps"],
        "lines": lines,
        "total_shipped_cents": total_shipped,
        "total_commission_cents": total_commission,
    })

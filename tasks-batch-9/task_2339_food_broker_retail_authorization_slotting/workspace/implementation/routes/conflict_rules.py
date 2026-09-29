"""Principal conflict edges (PRD section 3.1)."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import authorize

bp = Blueprint("conflict_rules", __name__)

READ_ROLES = ("BrokerAdmin", "BrokerAccountManager", "BrokerAuditManager", "RetailerBuyer")


def serialize(rec):
    return {
        "id": rec["id"],
        "category_code": rec["category_code"],
        "principal_a_id": rec["principal_a_id"],
        "principal_b_id": rec["principal_b_id"],
        "scope": rec["scope"],
        "retailer_id": rec["retailer_id"],
        "status": rec["status"],
        "waiver_reason": rec["waiver_reason"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/conflict-rules")
def create_conflict_rule():
    authorize("BrokerAdmin")
    data = v.body()

    category_code = v.req_enum(data, "category_code", v.CATEGORY_CODES)
    principal_a_id = v.req_id(data, "principal_a_id")
    principal_b_id = v.req_id(data, "principal_b_id")
    scope = v.req_enum(data, "scope", v.CONFLICT_SCOPES)
    if scope == "RETAILER_LEVEL":
        retailer_id = v.req_id(data, "retailer_id")
    else:
        v.forbid(data, "retailer_id", "when scope is NATIONAL")
        retailer_id = None

    db.get("principals", principal_a_id)
    db.get("principals", principal_b_id)
    if retailer_id is not None:
        db.get("retailers", retailer_id)

    if principal_a_id == principal_b_id:
        raise ApiError("ERR_CONFLICT_RULE_SELF")

    pair = frozenset((principal_a_id, principal_b_id))
    for existing in db.ordered("conflict_rules"):
        if existing["category_code"] != category_code:
            continue
        if existing["scope"] != scope:
            continue
        if existing["retailer_id"] != retailer_id:
            continue
        if frozenset((existing["principal_a_id"], existing["principal_b_id"])) == pair:
            raise ApiError("ERR_CONFLICT_RULE_DUPLICATE")

    rec = db.base_record()
    rec.update({
        "category_code": category_code,
        "principal_a_id": principal_a_id,
        "principal_b_id": principal_b_id,
        "scope": scope,
        "retailer_id": retailer_id,
        "status": "ACTIVE",
        "waiver_reason": None,
    })
    db.insert("conflict_rules", rec)
    return response.created(serialize(rec))


@bp.get("/conflict-rules/<conflict_rule_id>")
def read_conflict_rule(conflict_rule_id):
    authorize(*READ_ROLES)
    return response.ok(serialize(db.get("conflict_rules", conflict_rule_id)))


@bp.get("/conflict-rules")
def list_conflict_rules():
    authorize(*READ_ROLES)
    limit, offset = v.pagination()
    category_code = v.filter_value("category_code")
    principal_a_id = v.filter_value("principal_a_id")
    principal_b_id = v.filter_value("principal_b_id")
    retailer_id = v.filter_value("retailer_id")
    scope = v.filter_value("scope")
    status = v.filter_value("status")
    rows = []
    for rec in db.ordered("conflict_rules"):
        if category_code is not None and rec["category_code"] != category_code:
            continue
        if principal_a_id is not None and rec["principal_a_id"] != principal_a_id:
            continue
        if principal_b_id is not None and rec["principal_b_id"] != principal_b_id:
            continue
        if retailer_id is not None and rec["retailer_id"] != retailer_id:
            continue
        if scope is not None and rec["scope"] != scope:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/conflict-rules/<conflict_rule_id>/waive")
def waive_conflict_rule(conflict_rule_id):
    authorize("BrokerAdmin")
    data = v.body()
    reason = v.req_string(data, "waiver_reason")

    rec = db.get("conflict_rules", conflict_rule_id)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    db.assign(rec, status="WAIVED", waiver_reason=reason)
    return response.ok(serialize(rec))

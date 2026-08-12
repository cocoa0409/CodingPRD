"""Benefit entitlements endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_ENTITLEMENT_NOT_FOUND,
    ERR_ENTITLEMENT_OVERLAP,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_entitlement
from services.cascade import clock_now_iso
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("entitlements", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
CLAIM_TYPES = ("SSI", "SSDI")


@bp.route("/benefit-entitlements", methods=["POST"])
def create_entitlement():
    require_roles("FiduciaryAdmin")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "claim_type", "monthly_benefit_cents",
        "effective_start_date", "effective_end_date",
    })
    client_id = get_string(body, "client_id")
    claim_type = get_enum(body, "claim_type", CLAIM_TYPES)
    monthly = get_int(body, "monthly_benefit_cents", min_value=1)
    start_s = get_string(body, "effective_start_date")
    start = parse_date(start_s, "effective_start_date")
    end = None
    if "effective_end_date" in body and body["effective_end_date"] is not None:
        end = parse_date(body["effective_end_date"], "effective_end_date")
        if end <= start:
            from errors import ERR_INVALID_REQUEST
            raise err(ERR_INVALID_REQUEST, 400, "effective_end_date must be > effective_start_date")

    if client_id not in store.clients:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")

    # overlap check among non-TERMINATED entitlements of same (client, claim_type)
    for e in store.entitlements.values():
        if e["client_id"] != client_id or e["claim_type"] != claim_type:
            continue
        if e["status"] == "TERMINATED":
            continue
        # windows [s, e) overlap iff s1 < e2 AND s2 < e1
        s1, e1 = start, end  # None means infinity
        s2, e2 = e["effective_start_date"], e["effective_end_date"]
        # treat None end as infinity
        overlap = (e2 is None or s1 < e2) and (e1 is None or s2 < e1)
        if overlap:
            raise err(ERR_ENTITLEMENT_OVERLAP, 409, "Window overlaps another non-TERMINATED entitlement")

    now = clock_now_iso()
    eid = new_id()
    ent = {
        "id": eid,
        "client_id": client_id,
        "claim_type": claim_type,
        "monthly_benefit_cents": monthly,
        "effective_start_date": start,
        "effective_end_date": end,
        "status": "PENDING_VERIFICATION",
        "verified_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.entitlements[eid] = ent
    return success_object(serialize_entitlement(ent), status=201)


@bp.route("/benefit-entitlements", methods=["GET"])
def list_entitlements():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    claim_type = request.args.get("claim_type")
    status = request.args.get("status")
    items = list(store.entitlements.values())
    if client_id is not None:
        items = [e for e in items if e["client_id"] == client_id]
    if claim_type is not None:
        items = [e for e in items if e["claim_type"] == claim_type]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_entitlement(e) for e in page], limit, offset, total)


@bp.route("/benefit-entitlements/<eid>", methods=["GET"])
def get_entitlement(eid):
    require_roles(*READ_ROLES)
    e = store.entitlements.get(eid)
    if not e:
        raise err(ERR_ENTITLEMENT_NOT_FOUND, 404, "entitlement not found")
    return success_object(serialize_entitlement(e))


@bp.route("/benefit-entitlements/<eid>/verify", methods=["POST"])
def verify_entitlement(eid):
    require_roles("FiduciaryAdmin")
    e = store.entitlements.get(eid)
    if not e:
        raise err(ERR_ENTITLEMENT_NOT_FOUND, 404, "entitlement not found")
    if e["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Entitlement is TERMINATED")
    if e["status"] != "PENDING_VERIFICATION":
        raise err(ERR_INVALID_STATE, 409, "Only PENDING_VERIFICATION -> VERIFIED")
    # client must not be TERMINATED
    c = store.clients.get(e["client_id"])
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    if c["status"] == "TERMINATED":
        from errors import ERR_CLIENT_NOT_ACTIVE
        raise err(ERR_CLIENT_NOT_ACTIVE, 409, "Client is TERMINATED")
    now = clock_now_iso()
    e["status"] = "VERIFIED"
    e["verified_at"] = now
    e["updated_at"] = now
    e["version"] += 1
    return success_object(serialize_entitlement(e))


@bp.route("/benefit-entitlements/<eid>/terminate", methods=["POST"])
def terminate_entitlement(eid):
    require_roles("FiduciaryAdmin")
    e = store.entitlements.get(eid)
    if not e:
        raise err(ERR_ENTITLEMENT_NOT_FOUND, 404, "entitlement not found")
    if e["status"] == "TERMINATED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Entitlement is TERMINATED")
    if e["status"] != "VERIFIED":
        raise err(ERR_INVALID_STATE, 409, "Only VERIFIED -> TERMINATED via this endpoint")
    now = clock_now_iso()
    e["status"] = "TERMINATED"
    e["updated_at"] = now
    e["version"] += 1
    return success_object(serialize_entitlement(e))

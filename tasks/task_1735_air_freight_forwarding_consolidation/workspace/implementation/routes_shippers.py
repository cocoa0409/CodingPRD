"""Shipper registration and known-shipper verification (PRD §3.1, §3.3)."""
from flask import Blueprint

import services as svc
from db import store
from errors import ApiError, ERR_DUPLICATE_WAYBILL_NUMBER, ERR_INVALID_STATE
from middleware import (
    ALL_ROLES,
    get_body,
    pagination_params,
    req_nonempty_str,
    require_roles,
)
from response import ok, ok_list

bp = Blueprint("shippers", __name__)


@bp.post("/shippers")
@require_roles("ForwarderOps")
def create_shipper():
    body = get_body()
    name = req_nonempty_str(body, "name")
    account_code = req_nonempty_str(body, "account_code")
    # Structural uniqueness guard (priority 8): duplicate account codes reuse
    # ERR_DUPLICATE_WAYBILL_NUMBER per PRD §3.1.
    if account_code in store.shipper_by_account_code:
        raise ApiError(
            ERR_DUPLICATE_WAYBILL_NUMBER,
            f"Account code '{account_code}' is already registered.",
            409,
        )
    s = svc.fresh_rec(
        name=name,
        account_code=account_code,
        known_shipper_status="UNVERIFIED",
        screening_rejection_count=0,
    )
    store.shippers[s.id] = s
    store.shipper_by_account_code[account_code] = s
    return ok(svc.shipper_json(s), 201)


@bp.get("/shippers/<sid>")
@require_roles(*ALL_ROLES)
def get_shipper(sid):
    return ok(svc.shipper_json(svc.get_shipper(sid)), 200)


@bp.post("/shippers/<sid>/verify-known-shipper")
@require_roles("ComplianceOfficer")
def verify_known_shipper(sid):
    s = svc.get_shipper(sid)
    if s.known_shipper_status not in ("UNVERIFIED", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"Shipper standing is {s.known_shipper_status}; only UNVERIFIED or SUSPENDED can be verified.",
            409,
        )
    reinstating = s.known_shipper_status == "SUSPENDED"
    s.known_shipper_status = "KNOWN"
    if reinstating:
        # Reinstatement clears the demerit ledger (PRD §3.3).
        s.screening_rejection_count = 0
    svc.touch(s)
    return ok(svc.shipper_json(s), 200)


@bp.get("/shippers/<sid>/rate-agreements")
@require_roles(*ALL_ROLES)
def list_shipper_rate_agreements(sid):
    svc.get_shipper(sid)
    limit, offset = pagination_params()
    items = svc.sorted_by_created(
        [a for a in store.rate_agreements.values() if a.shipper_id == sid]
    )
    page, total = svc.paginate(items, limit, offset)
    return ok_list([svc.rate_agreement_json(a) for a in page], total, limit, offset)

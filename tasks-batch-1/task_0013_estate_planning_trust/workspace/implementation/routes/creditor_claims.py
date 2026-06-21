"""CreditorClaim routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    get_body,
    pagination_params,
    parse_iso_datetime,
    require_enum,
    require_field,
    require_int,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_CREDITOR_WINDOW_CLOSED,
    ERR_INSUFFICIENT_ESTATE_FUNDS,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import created, list_response, success
from services.calculations import recompute_and_store_net, waterfall_pay
from views import view_claim


bp = Blueprint("creditor_claims", __name__)

CLAIM_CLASSES = {"SECURED", "ADMIN", "FUNERAL", "TAX", "UNSECURED"}


@bp.post("/creditor-claims")
@require_roles("Creditor", "Executor")
def create_claim():
    body = get_body()
    estate_id = require_string(body, "estate_id")
    estate = db.estates.get(estate_id)
    if estate is None:
        raise not_found("Estate")

    creditor_name = require_string(body, "creditor_name")
    amount = require_int(body, "amount_cents", strict_positive=True)
    claim_class = require_enum(body, "claim_class", CLAIM_CLASSES)
    filed_at = parse_iso_datetime(require_field(body, "filed_at"), "filed_at")

    # Creditor window check.
    if estate.get("probate_opened_at") is not None:
        window_end = estate["probate_opened_at"] + timedelta(days=120)
        if filed_at > window_end:
            raise APIError(
                ERR_CREDITOR_WINDOW_CLOSED,
                "Claim filed beyond 120-day creditor window.",
                422,
            )

    now = db.now_utc()
    c = {
        "estate_id": estate_id,
        "creditor_name": creditor_name,
        "amount_cents": amount,
        "claim_class": claim_class,
        "filed_at": filed_at,
        "paid_amount_cents": 0,
        "status": "FILED",
    }
    stamp_common_fields(c, now)
    db.creditor_claims[c["id"]] = c
    return created(view_claim(c))


@bp.get("/creditor-claims/<cid>")
@require_roles("EstatePlanner", "Executor", "Judge", "Creditor")
def get_claim(cid: str):
    c = db.creditor_claims.get(cid)
    if c is None:
        raise not_found("CreditorClaim")
    return success(view_claim(c))


@bp.get("/creditor-claims")
@require_roles("EstatePlanner", "Executor", "Judge")
def list_claims():
    limit, offset = pagination_params()
    estate_id = request.args.get("estate_id")
    status = request.args.get("status")
    claim_class = request.args.get("claim_class")

    items = list(db.creditor_claims.values())
    if estate_id is not None:
        items = [c for c in items if c["estate_id"] == estate_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if claim_class is not None:
        items = [c for c in items if c["claim_class"] == claim_class]

    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = [view_claim(c) for c in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


@bp.post("/creditor-claims/<cid>/allow")
@require_roles("Executor")
def allow_claim(cid: str):
    c = db.creditor_claims.get(cid)
    if c is None:
        raise not_found("CreditorClaim")
    estate = db.estates.get(c["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] != "ADMINISTRATION":
        raise invalid_state("Claims can only be allowed during ADMINISTRATION.")
    if c["status"] != "FILED":
        raise invalid_state("Claim must be FILED to allow.")
    # 120-day window also enforced at allowance.
    if estate.get("probate_opened_at") is not None:
        window_end = estate["probate_opened_at"] + timedelta(days=120)
        if c["filed_at"] > window_end:
            raise APIError(
                ERR_CREDITOR_WINDOW_CLOSED,
                "Claim filed beyond 120-day creditor window.",
                422,
            )

    now = db.now_utc()
    c["status"] = "ALLOWED"
    touch(c, now)
    recompute_and_store_net(estate)
    touch(estate, now)
    return success(view_claim(c))


@bp.post("/creditor-claims/<cid>/disallow")
@require_roles("Executor")
def disallow_claim(cid: str):
    c = db.creditor_claims.get(cid)
    if c is None:
        raise not_found("CreditorClaim")
    estate = db.estates.get(c["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] != "ADMINISTRATION":
        raise invalid_state("Claims can only be disallowed during ADMINISTRATION.")
    if c["status"] != "FILED":
        raise invalid_state("Claim must be FILED to disallow.")
    now = db.now_utc()
    c["status"] = "DISALLOWED"
    touch(c, now)
    return success(view_claim(c))


@bp.post("/creditor-claims/<cid>/pay")
@require_roles("Executor")
def pay_claim(cid: str):
    c = db.creditor_claims.get(cid)
    if c is None:
        raise not_found("CreditorClaim")
    estate = db.estates.get(c["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] != "ADMINISTRATION":
        raise invalid_state("Claims can only be paid during ADMINISTRATION.")
    if c["status"] != "ALLOWED":
        raise invalid_state("Claim must be ALLOWED to pay.")

    payable = waterfall_pay(estate, c)
    if payable is None or payable <= 0:
        raise APIError(
            ERR_INSUFFICIENT_ESTATE_FUNDS,
            "No funds remain to pay this claim under the waterfall.",
            422,
        )

    now = db.now_utc()
    c["paid_amount_cents"] = payable
    c["status"] = "PAID"
    touch(c, now)
    from services.calculations import recompute_and_store_net
    recompute_and_store_net(estate)
    touch(estate, now)
    return success(view_claim(c))

"""Investor endpoints: create, get, deposit, list investments."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import (
    err_forbidden_for_role,
    err_invalid_request,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_investor_role_resolves,
    get_investor,
    get_json,
    get_platform,
    paginate,
    parse_pagination,
    sort_for_list,
)
from services.engine import stamp_create, stamp_update
from services.serializers import serialize_investment, serialize_investor
from utils import is_nonneg_int, is_pos_int

bp = Blueprint("investors", __name__)


@bp.post("/platforms/<platform_id>/investors")
@require_auth(["PlatformOperator"])
def create_investor(platform_id):
    get_platform(platform_id)
    body = get_json()
    display_name = body.get("display_name")
    accreditation = body.get("accreditation_status")
    committed = body.get("committed_capital_cents")

    if not isinstance(display_name, str) or not display_name.strip():
        raise err_invalid_request("display_name is required.")
    if accreditation not in ("ACCREDITED", "NON_ACCREDITED"):
        raise err_invalid_request("accreditation_status must be ACCREDITED or NON_ACCREDITED.")
    if not is_nonneg_int(committed):
        raise err_invalid_request("committed_capital_cents must be a non-negative integer.")

    with store.lock:
        investor = {
            "platform_id": platform_id,
            "display_name": display_name,
            "accreditation_status": accreditation,
            "committed_capital_cents": committed,
            "cash_balance_cents": 0,
            "outstanding_principal_cents": 0,
            "status": "ACTIVE",
        }
        stamp_create(investor)
        store.investors[investor["id"]] = investor
    return success(serialize_investor(investor), 201)


@bp.get("/platforms/<platform_id>/investors/<investor_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Investor"])
def get_investor_route(platform_id, investor_id):
    inv = get_investor(platform_id, investor_id)
    enforce_investor_role_resolves(platform_id, investor_id)
    return success(serialize_investor(inv))


@bp.post("/platforms/<platform_id>/investors/<investor_id>/deposits")
@require_auth(["PlatformOperator"])
def deposit(platform_id, investor_id):
    investor = get_investor(platform_id, investor_id)
    body = get_json()
    amount = body.get("amount_cents")
    if not is_pos_int(amount):
        raise err_invalid_request("amount_cents must be a positive integer.")
    with store.lock:
        investor["cash_balance_cents"] += amount
        stamp_update(investor)
    return success(serialize_investor(investor))


@bp.get("/platforms/<platform_id>/investors/<investor_id>/investments")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Investor"])
def list_investor_investments(platform_id, investor_id):
    get_investor(platform_id, investor_id)
    enforce_investor_role_resolves(platform_id, investor_id)
    limit, offset = parse_pagination()

    status_filter = (g and None) or (None)  # placeholder; real filter below
    from flask import request as _req
    status_filter = _req.args.get("status")
    loan_id_filter = _req.args.get("loan_id")

    items = [i for i in store.investments.values() if i["investor_id"] == investor_id]
    # Ensure the investments belong to this platform.
    items = [
        i for i in items
        if (store.loan_listings.get(i["listing_id"]) or {}).get("platform_id") == platform_id
    ]
    if status_filter:
        items = [i for i in items if i["status"] == status_filter]
    if loan_id_filter:
        # Investment is bound to a loan via its listing → loan record.
        loan = store.loans.get(loan_id_filter)
        if loan is None:
            items = []
        else:
            items = [i for i in items if i["listing_id"] == loan["listing_id"]]
    items = sort_for_list(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize_investment(x) for x in page], limit, offset, total)

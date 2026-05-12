"""Investor routes."""
from flask import Blueprint, g, request

import db
from db import investors, stamp_create, stamp_update, public
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.util import get_body, require_field, check_version
from services.holdings import list_holdings_for_investor


bp = Blueprint("investors", __name__)


VALID_INVESTOR_TYPES = {"INDIVIDUAL", "INSTITUTIONAL"}
VALID_RISK_TOLERANCE = {"C1", "C2", "C3", "C4", "C5"}
VALID_TAX_STATUS = {"DOMESTIC", "FOREIGN", "EXEMPT"}


@bp.route("/investors", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_investor():
    body = get_body()
    for field in ("legal_name", "investor_type", "country_code", "risk_tolerance",
                  "tax_resident_status", "bank_account_number"):
        require_field(body, field)
    if body["investor_type"] not in VALID_INVESTOR_TYPES:
        raise err("ERR_VALIDATION", "invalid investor_type")
    if body["risk_tolerance"] not in VALID_RISK_TOLERANCE:
        raise err("ERR_VALIDATION", "invalid risk_tolerance")
    if body["tax_resident_status"] not in VALID_TAX_STATUS:
        raise err("ERR_VALIDATION", "invalid tax_resident_status")
    inv = {
        "legal_name": body["legal_name"],
        "investor_type": body["investor_type"],
        "country_code": body["country_code"],
        "risk_tolerance": body["risk_tolerance"],
        "tax_resident_status": body["tax_resident_status"],
        "kyc_status": "PENDING",
        "bank_account_number": body["bank_account_number"],
        "cash_balance_cents": 0,
    }
    stamp_create(inv, common_fields=True)
    investors[inv["id"]] = inv
    return success(public(inv), 201)


@bp.route("/investors/<id>/approve-kyc", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def approve_kyc(id):
    inv = investors.get(id)
    if not inv:
        raise err("ERR_NOT_FOUND", "Investor not found")
    body = get_body()
    check_version(body, inv)
    if inv["kyc_status"] == "APPROVED":
        # idempotent re-approval is treated as invalid state per state-machine? PRD doesn't explicitly
        # but the KYC flow only flips PENDING -> APPROVED. Treat repeat as ERR_INVALID_STATE.
        raise err("ERR_INVALID_STATE", "Investor KYC already approved")
    if inv["kyc_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Investor KYC not in PENDING")
    inv["kyc_status"] = "APPROVED"
    stamp_update(inv)
    return success(public(inv), 200)


@bp.route("/investors/<id>/credit-cash", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def credit_cash(id):
    inv = investors.get(id)
    if not inv:
        raise err("ERR_NOT_FOUND", "Investor not found")
    body = get_body()
    check_version(body, inv)
    require_field(body, "amount_cents")
    amt = body["amount_cents"]
    if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
        raise err("ERR_VALIDATION", "amount_cents must be positive integer")
    inv["cash_balance_cents"] += amt
    stamp_update(inv)
    return success(public(inv), 200)


@bp.route("/investors/<id>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "Investor"})
def get_investor(id):
    inv = investors.get(id)
    if not inv:
        raise err("ERR_NOT_FOUND", "Investor not found")
    if g.user_role == "Investor" and g.user_id != id:
        raise err("ERR_FORBIDDEN", "Investor may only read their own record")
    return success(public(inv), 200)


@bp.route("/investors/<id>/holdings", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "Investor"})
def list_holdings(id):
    inv = investors.get(id)
    if not inv:
        raise err("ERR_NOT_FOUND", "Investor not found")
    if g.user_role == "Investor" and g.user_id != id:
        raise err("ERR_FORBIDDEN", "Investor may only read their own holdings")
    items = list_holdings_for_investor(id)
    items.sort(key=lambda h: (h["created_at"], h["_seq"]))
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([public(h) for h in page], limit, offset, total, 200)

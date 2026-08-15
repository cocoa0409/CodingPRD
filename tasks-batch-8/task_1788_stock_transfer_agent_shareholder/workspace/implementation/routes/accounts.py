"""Shareholder account endpoints: registration, patch, restriction, statement, positions."""
from flask import Blueprint

from db import STORE
from errors import fail
from helpers import (get_body, req_str, opt_enum, req_int, opt_int,
                     pagination_params)
from middleware import auth, require_role, shareholder_owns
from response import success_object, success_list
from services import (stamp_new, touch, audit, sorted_recs, account_view, position_view,
                      positions_of_account, find_position, reactivate_account,
                      now_iso)

bp = Blueprint("accounts", __name__)

ALL_ROLES = {"AgentAdmin", "Shareholder", "TransferExaminer", "TransferSupervisor",
             "IssuerOfficer", "ComplianceOfficer", "ServiceAgent"}


def get_account_or_404(account_id):
    account = STORE["accounts"].get(account_id)
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % account_id)
    return account


@bp.post("/accounts")
def create_account():
    user_id, role = auth()
    require_role(role, {"AgentAdmin"})
    body = get_body()
    account = stamp_new({
        "holder_name": req_str(body, "holder_name"),
        "address_line1": req_str(body, "address_line1"),
        "city": req_str(body, "city"),
        "state_code": req_str(body, "state_code"),
        "postal_code": req_str(body, "postal_code"),
        "country_code": req_str(body, "country_code"),
        "tax_id": req_str(body, "tax_id"),
        "residency": opt_enum(body, "residency", {"US", "FOREIGN"}, "US"),
        "tin_status": opt_enum(body, "tin_status", {"MISSING", "CERTIFIED", "UNCERTIFIED"}, "MISSING"),
        "treaty_tier": opt_enum(body, "treaty_tier", {"STANDARD", "TREATY"}, "STANDARD"),
        "account_status": "ACTIVE",
        "address_verified": True,
        "last_qualifying_contact_date": None,  # set to created_at below
        "pending_transfer_count": 0,
        "stale_dividend_cents": 0,
    })
    account["last_qualifying_contact_date"] = account["created_at"]
    STORE["accounts"][account["id"]] = account
    audit("ShareholderAccount", account["id"], role, user_id, "account.create",
          "", "ACTIVE", "shareholder account registered")
    return success_object(account_view(account), 201)


@bp.get("/accounts/<account_id>")
def read_account(account_id):
    user_id, role = auth()
    require_role(role, ALL_ROLES)
    if role == "Shareholder":
        shareholder_owns(user_id, account_id)
    account = get_account_or_404(account_id)
    return success_object(account_view(account))


@bp.patch("/accounts/<account_id>")
def patch_account(account_id):
    user_id, role = auth()
    require_role(role, {"Shareholder", "AgentAdmin"})
    if role == "Shareholder":
        shareholder_owns(user_id, account_id)
    account = get_account_or_404(account_id)
    if account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account_id)
    body = get_body()
    for field in ("address_line1", "city", "state_code", "postal_code", "country_code"):
        if field in body and body[field] is not None:
            if not isinstance(body[field], str):
                fail("ERR_INVALID_REQUEST", "%s must be a string" % field)
            account[field] = body[field]
    if "tin_status" in body and body["tin_status"] is not None:
        account["tin_status"] = opt_enum(body, "tin_status",
                                         {"MISSING", "CERTIFIED", "UNCERTIFIED"})
    if "treaty_tier" in body and body["treaty_tier"] is not None:
        account["treaty_tier"] = opt_enum(body, "treaty_tier", {"STANDARD", "TREATY"})
    account["address_verified"] = True
    was_dormant = account["account_status"] == "DORMANT"
    # qualifying owner contact: refresh contact date (+ dormancy reactivation cascade)
    reactivate_account(account, role, user_id)
    if not was_dormant:
        # reactivate_account already touched; record the maintenance audit
        pass
    audit("ShareholderAccount", account["id"], role, user_id, "account.patch",
          "DORMANT" if was_dormant else account["account_status"],
          account["account_status"], "address / W-9 maintenance")
    return success_object(account_view(account))


@bp.post("/accounts/<account_id>/restrict")
def restrict_account(account_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    account = get_account_or_404(account_id)
    if account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account_id)
    if account["account_status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "only an ACTIVE account can be restricted")
    account["account_status"] = "RESTRICTED"
    touch(account)
    audit("ShareholderAccount", account["id"], role, user_id, "account.restrict",
          "ACTIVE", "RESTRICTED", "legal-hold restriction placed")
    return success_object(account_view(account))


@bp.post("/accounts/<account_id>/release-restriction")
def release_restriction(account_id):
    user_id, role = auth()
    require_role(role, {"ComplianceOfficer"})
    account = get_account_or_404(account_id)
    if account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account_id)
    if account["account_status"] != "RESTRICTED":
        fail("ERR_INVALID_STATE", "only a RESTRICTED account can be released")
    account["account_status"] = "ACTIVE"
    touch(account)
    audit("ShareholderAccount", account["id"], role, user_id, "account.release",
          "RESTRICTED", "ACTIVE", "legal-hold restriction lifted")
    return success_object(account_view(account))


@bp.get("/accounts/<account_id>/statement")
def account_statement(account_id):
    user_id, role = auth()
    require_role(role, {"Shareholder", "AgentAdmin", "ServiceAgent"})
    if role == "Shareholder":
        shareholder_owns(user_id, account_id)
    account = get_account_or_404(account_id)
    positions = [position_view(p) for p in positions_of_account(account["id"])]
    total_book = sum(p["book_entry_shares"] for p in positions_of_account(account["id"]))
    total_cert = sum(p["certificated_shares"] for p in positions_of_account(account["id"]))
    statement = {
        "account_id": account["id"],
        "as_of": now_iso(),
        "positions": positions,
        "totals": {
            "total_book_entry_shares": total_book,
            "total_certificated_shares": total_cert,
            "total_shares": total_book + total_cert,
            "stale_dividend_cents": account["stale_dividend_cents"],
            "pending_transfer_count": account["pending_transfer_count"],
        },
    }
    return success_object(statement)


@bp.post("/accounts/<account_id>/positions")
def seed_position(account_id):
    user_id, role = auth()
    require_role(role, {"AgentAdmin"})
    account = get_account_or_404(account_id)
    body = get_body()
    issuer_id = req_str(body, "issuer_id")
    issuer = STORE["issuers"].get(issuer_id)
    if issuer is None:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    if account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account_id)
    if find_position(account["id"], issuer["id"]) is not None:
        fail("ERR_DUPLICATE_POSITION", "position already exists for this account and issuer")
    book_entry = req_int(body, "book_entry_shares")
    if book_entry < 0:
        fail("ERR_INVALID_REQUEST", "book_entry_shares must be >= 0")
    restricted = opt_int(body, "restricted_shares", 0)
    if restricted < 0 or restricted > book_entry:
        fail("ERR_INVALID_REQUEST",
             "restricted_shares must satisfy 0 <= restricted_shares <= book_entry_shares")
    position = stamp_new({
        "account_id": account["id"],
        "issuer_id": issuer["id"],
        "book_entry_shares": book_entry,
        "restricted_shares": restricted,
        "certificated_shares": 0,
        "status": "ACTIVE",
        "pending_legend_removal_count": 0,
    })
    STORE["positions"][position["id"]] = position
    audit("Position", position["id"], role, user_id, "position.create", "", "ACTIVE",
          "registered-holder position seeded")
    return success_object(position_view(position), 201)


@bp.get("/accounts/<account_id>/positions")
def list_account_positions(account_id):
    user_id, role = auth()
    require_role(role, ALL_ROLES)
    if role == "Shareholder":
        shareholder_owns(user_id, account_id)
    account = get_account_or_404(account_id)
    items = positions_of_account(account["id"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([position_view(p) for p in page], limit, offset, total)

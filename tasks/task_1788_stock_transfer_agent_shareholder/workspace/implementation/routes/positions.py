"""Position endpoints: filtered list, issuer list, certificate withdrawal."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_int, opt_bool, pagination_params
from middleware import auth, require_role, shareholder_owns, officer_owns
from response import success_list, success_object
from services import (stamp_new, touch, audit, sorted_recs, position_view,
                      new_certificate_number, now_iso)

bp = Blueprint("positions", __name__)

ALL_ROLES = {"AgentAdmin", "Shareholder", "TransferExaminer", "TransferSupervisor",
             "IssuerOfficer", "ComplianceOfficer", "ServiceAgent"}
ISSUER_POSITION_READ_ROLES = {"AgentAdmin", "IssuerOfficer", "TransferExaminer",
                              "TransferSupervisor", "ComplianceOfficer"}


def get_position_or_404(position_id):
    position = STORE["positions"].get(position_id)
    if position is None:
        fail("ERR_POSITION_NOT_FOUND", "position %s does not exist" % position_id)
    return position


@bp.get("/positions")
def list_positions():
    user_id, role = auth()
    require_role(role, ALL_ROLES)
    account_filter = request.args.get("account_id")
    issuer_filter = request.args.get("issuer_id")
    if role == "Shareholder" and account_filter is not None:
        shareholder_owns(user_id, account_filter)
    if role == "IssuerOfficer" and issuer_filter is not None:
        officer_owns(user_id, issuer_filter)
    items = sorted_recs("positions")
    if account_filter is not None:
        items = [p for p in items if p["account_id"] == account_filter]
    if issuer_filter is not None:
        items = [p for p in items if p["issuer_id"] == issuer_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([position_view(p) for p in page], limit, offset, total)


@bp.get("/issuers/<issuer_id>/positions")
def list_issuer_positions(issuer_id):
    user_id, role = auth()
    require_role(role, ISSUER_POSITION_READ_ROLES)
    if role == "IssuerOfficer":
        officer_owns(user_id, issuer_id)
    issuer = STORE["issuers"].get(issuer_id)
    if issuer is None:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    items = [p for p in sorted_recs("positions") if p["issuer_id"] == issuer["id"]]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([position_view(p) for p in page], limit, offset, total)


@bp.post("/positions/<position_id>/certificate-withdrawals")
def certificate_withdrawal(position_id):
    user_id, role = auth()
    require_role(role, {"TransferExaminer"})
    position = get_position_or_404(position_id)
    account = STORE["accounts"].get(position["account_id"])
    if account is not None and account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account["id"])
    body = get_body()
    share_quantity = req_int(body, "share_quantity")
    if share_quantity < 1:
        fail("ERR_ZERO_SHARE_QUANTITY", "share_quantity must be at least 1")
    legend_restricted = opt_bool(body, "legend_restricted", False)
    if share_quantity > position["book_entry_shares"]:
        fail("ERR_INSUFFICIENT_SHARES",
             "share_quantity exceeds available book_entry_shares")
    position["book_entry_shares"] -= share_quantity
    position["certificated_shares"] += share_quantity
    touch(position)
    audit("Position", position["id"], role, user_id, "position.certificate_withdrawal",
          position["status"], position["status"],
          "withdrew %d shares into certificate form" % share_quantity)
    certificate = stamp_new({
        "account_id": position["account_id"],
        "issuer_id": position["issuer_id"],
        "certificate_number": new_certificate_number(),
        "share_quantity": share_quantity,
        "status": "ISSUED",
        "legend_restricted": legend_restricted,
        "issued_at": now_iso(),
        "lost_reported_at": None,
    })
    STORE["certificates"][certificate["id"]] = certificate
    audit("Certificate", certificate["id"], role, user_id, "certificate.withdraw",
          "", "ISSUED", "certificate minted from book-entry withdrawal")
    from services import certificate_view
    return success_object(certificate_view(certificate), 201)

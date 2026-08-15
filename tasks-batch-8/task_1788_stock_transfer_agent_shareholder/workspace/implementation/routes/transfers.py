"""Transfer request endpoints: create, review desk, approval, settlement."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_str, opt_str, req_int, pagination_params
from middleware import auth, require_role, shareholder_owns, officer_owns
from response import success_list, success_object
from services import (stamp_new, touch, audit, sorted_recs, transfer_view,
                      find_position, freeze_window_blocks, now_dt, now_iso,
                      position_view)

bp = Blueprint("transfers", __name__)

TRANSFER_READ_ROLES = {"AgentAdmin", "TransferExaminer", "TransferSupervisor", "Shareholder"}
ISSUER_TRANSFER_READ_ROLES = {"AgentAdmin", "IssuerOfficer", "TransferExaminer",
                              "TransferSupervisor"}


def get_transfer_or_404(transfer_id):
    transfer = STORE["transfer_requests"].get(transfer_id)
    if transfer is None:
        fail("ERR_TRANSFER_NOT_FOUND", "transfer request %s does not exist" % transfer_id)
    return transfer


def _decrement_pending(account, role, user_id):
    account["pending_transfer_count"] -= 1
    touch(account)


@bp.post("/transfer-requests")
def create_transfer():
    user_id, role = auth()
    require_role(role, {"Shareholder", "TransferExaminer"})
    body = get_body()
    # ownership (stage 2): a Shareholder's X-User-ID must equal from_account_id
    if role == "Shareholder" and body.get("from_account_id") is not None:
        shareholder_owns(user_id, body.get("from_account_id"))
    # existence (stage 3): body references resolve here, left to right
    issuer_id = req_str(body, "issuer_id")
    issuer = STORE["issuers"].get(issuer_id)
    if issuer is None:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    from_account_id = req_str(body, "from_account_id")
    from_account = STORE["accounts"].get(from_account_id)
    if from_account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % from_account_id)
    to_account_id = req_str(body, "to_account_id")
    to_account = STORE["accounts"].get(to_account_id)
    if to_account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % to_account_id)
    source_certificate_id = opt_str(body, "source_certificate_id")
    certificate = None
    if source_certificate_id is not None:
        certificate = STORE["certificates"].get(source_certificate_id)
        if certificate is None:
            fail("ERR_CERTIFICATE_NOT_FOUND",
                 "certificate %s does not exist" % source_certificate_id)
    position = find_position(from_account["id"], issuer["id"])
    if position is None:
        fail("ERR_POSITION_NOT_FOUND",
             "no position seeded for the transferor account and issuer")
    # optimistic concurrency (stage 4)
    expected_version = req_int(body, "expected_account_version")
    if expected_version != from_account["version"]:
        fail("ERR_STALE_ACCOUNT_VERSION",
             "expected_account_version %d does not match current version %d"
             % (expected_version, from_account["version"]))
    # state gates (stage 5)
    if from_account["account_status"] == "RESTRICTED":
        fail("ERR_ACCOUNT_RESTRICTED", "transferor account is RESTRICTED (legal hold)")
    if from_account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "transferor account is ESCHEATED")
    if to_account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "transferee account is ESCHEATED")
    if issuer["status"] == "SUSPENDED":
        fail("ERR_ISSUER_SUSPENDED", "issuer is SUSPENDED")
    # shape (stage 8)
    share_quantity = req_int(body, "share_quantity")
    if share_quantity < 1:
        fail("ERR_ZERO_SHARE_QUANTITY", "share_quantity must be at least 1")
    if certificate is not None and share_quantity != certificate["share_quantity"]:
        fail("ERR_INVALID_REQUEST",
             "share_quantity must equal the certificate's face quantity")
    # cross-reference consistency (stage 9)
    if certificate is not None:
        if (certificate["account_id"] != from_account["id"]
                or certificate["issuer_id"] != issuer["id"]):
            fail("ERR_POSITION_ACCOUNT_MISMATCH",
                 "source certificate does not belong to the from-account and issuer")
    # sufficiency (stage 10)
    if certificate is None and share_quantity > position["book_entry_shares"]:
        fail("ERR_INSUFFICIENT_SHARES",
             "share_quantity exceeds available book_entry_shares")
    transfer = stamp_new({
        "from_account_id": from_account["id"],
        "to_account_id": to_account["id"],
        "issuer_id": issuer["id"],
        "source_certificate_id": source_certificate_id,
        "share_quantity": share_quantity,
        "transfer_value_cents": share_quantity * issuer["current_market_price_cents"],
        "status": "UNDER_REVIEW",
        "medallion_reference": None,
        "medallion_coverage_cents": None,
        "last_examiner_id": None,
        "deficiency_reason": None,
        "approved_by": None,
        "settled_at": None,
    })
    STORE["transfer_requests"][transfer["id"]] = transfer
    from_account["pending_transfer_count"] += 1
    touch(from_account)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.create",
          "", "UNDER_REVIEW", "transfer request submitted")
    return success_object(transfer_view(transfer), 201)


@bp.get("/transfer-requests")
def list_transfers():
    user_id, role = auth()
    require_role(role, TRANSFER_READ_ROLES)
    from_filter = request.args.get("from_account_id")
    to_filter = request.args.get("to_account_id")
    issuer_filter = request.args.get("issuer_id")
    cert_filter = request.args.get("source_certificate_id")
    status_filter = request.args.get("status")
    if role == "Shareholder":
        if from_filter is not None:
            shareholder_owns(user_id, from_filter)
        if to_filter is not None:
            shareholder_owns(user_id, to_filter)
    items = sorted_recs("transfer_requests")
    if from_filter is not None:
        items = [t for t in items if t["from_account_id"] == from_filter]
    if to_filter is not None:
        items = [t for t in items if t["to_account_id"] == to_filter]
    if issuer_filter is not None:
        items = [t for t in items if t["issuer_id"] == issuer_filter]
    if cert_filter is not None:
        items = [t for t in items if t["source_certificate_id"] == cert_filter]
    if status_filter is not None:
        items = [t for t in items if t["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([transfer_view(t) for t in page], limit, offset, total)


@bp.get("/transfer-requests/<transfer_id>")
def read_transfer(transfer_id):
    user_id, role = auth()
    require_role(role, TRANSFER_READ_ROLES)
    transfer = get_transfer_or_404(transfer_id)
    if role == "Shareholder" and user_id not in (transfer["from_account_id"],
                                                 transfer["to_account_id"]):
        fail("ERR_UNAUTHORIZED_ROLE", "Shareholder may only read their own transfers")
    return success_object(transfer_view(transfer))


@bp.get("/accounts/<account_id>/transfer-requests")
def list_account_transfers(account_id):
    user_id, role = auth()
    require_role(role, TRANSFER_READ_ROLES)
    if role == "Shareholder":
        shareholder_owns(user_id, account_id)
    if account_id not in STORE["accounts"]:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % account_id)
    items = [t for t in sorted_recs("transfer_requests")
             if t["from_account_id"] == account_id or t["to_account_id"] == account_id]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([transfer_view(t) for t in page], limit, offset, total)


@bp.get("/issuers/<issuer_id>/transfer-requests")
def list_issuer_transfers(issuer_id):
    user_id, role = auth()
    require_role(role, ISSUER_TRANSFER_READ_ROLES)
    if role == "IssuerOfficer":
        officer_owns(user_id, issuer_id)
    if issuer_id not in STORE["issuers"]:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    items = [t for t in sorted_recs("transfer_requests") if t["issuer_id"] == issuer_id]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([transfer_view(t) for t in page], limit, offset, total)


@bp.post("/transfer-requests/<transfer_id>/submit-medallion")
def submit_medallion(transfer_id):
    user_id, role = auth()
    require_role(role, {"TransferExaminer"})
    transfer = get_transfer_or_404(transfer_id)
    if transfer["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "only an UNDER_REVIEW transfer can receive a medallion")
    body = get_body()
    reference = req_str(body, "medallion_reference")
    coverage = req_int(body, "coverage_cents")
    if coverage < 0:
        fail("ERR_INVALID_REQUEST", "coverage_cents must be >= 0")
    if coverage < transfer["transfer_value_cents"]:
        fail("ERR_MEDALLION_COVERAGE_INSUFFICIENT",
             "coverage_cents %d is below transfer_value_cents %d"
             % (coverage, transfer["transfer_value_cents"]))
    transfer["medallion_reference"] = reference
    transfer["medallion_coverage_cents"] = coverage
    transfer["last_examiner_id"] = user_id
    transfer["status"] = "MEDALLION_VERIFIED"
    touch(transfer)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.medallion_verified",
          "UNDER_REVIEW", "MEDALLION_VERIFIED", "medallion signature guarantee verified")
    return success_object(transfer_view(transfer))


@bp.post("/transfer-requests/<transfer_id>/flag-deficient")
def flag_deficient(transfer_id):
    user_id, role = auth()
    require_role(role, {"TransferExaminer"})
    transfer = get_transfer_or_404(transfer_id)
    if transfer["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "only an UNDER_REVIEW transfer can be flagged deficient")
    body = get_body()
    reason = req_str(body, "deficiency_reason")
    transfer["deficiency_reason"] = reason
    transfer["last_examiner_id"] = user_id
    transfer["status"] = "DEFICIENT"
    touch(transfer)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.flag_deficient",
          "UNDER_REVIEW", "DEFICIENT", "transfer flagged deficient")
    return success_object(transfer_view(transfer))


@bp.post("/transfer-requests/<transfer_id>/cure-deficiency")
def cure_deficiency(transfer_id):
    user_id, role = auth()
    require_role(role, {"Shareholder", "TransferExaminer"})
    transfer = get_transfer_or_404(transfer_id)
    if role == "Shareholder":
        shareholder_owns(user_id, transfer["from_account_id"])
    if transfer["status"] != "DEFICIENT":
        fail("ERR_INVALID_STATE", "only a DEFICIENT transfer can be cured")
    transfer["deficiency_reason"] = None
    transfer["status"] = "UNDER_REVIEW"
    touch(transfer)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.cure_deficiency",
          "DEFICIENT", "UNDER_REVIEW", "deficiency cured; back under review")
    return success_object(transfer_view(transfer))


@bp.post("/transfer-requests/<transfer_id>/approve")
def approve_transfer(transfer_id):
    user_id, role = auth()
    require_role(role, {"TransferSupervisor"})
    transfer = get_transfer_or_404(transfer_id)
    if transfer["status"] != "MEDALLION_VERIFIED":
        fail("ERR_INVALID_STATE", "only a MEDALLION_VERIFIED transfer can be approved")
    if user_id == transfer["last_examiner_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "approver must differ from the examiner who last acted on the transfer")
    transfer["approved_by"] = user_id
    transfer["status"] = "APPROVED"
    touch(transfer)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.approve",
          "MEDALLION_VERIFIED", "APPROVED", "transfer approved")
    return success_object(transfer_view(transfer))


@bp.post("/transfer-requests/<transfer_id>/reject")
def reject_transfer(transfer_id):
    user_id, role = auth()
    require_role(role, {"TransferSupervisor"})
    transfer = get_transfer_or_404(transfer_id)
    if transfer["status"] not in ("UNDER_REVIEW", "MEDALLION_VERIFIED", "DEFICIENT"):
        fail("ERR_INVALID_STATE", "transfer cannot be rejected from %s" % transfer["status"])
    frm = transfer["status"]
    transfer["status"] = "REJECTED"
    touch(transfer)
    from_account = STORE["accounts"].get(transfer["from_account_id"])
    if from_account is not None:
        _decrement_pending(from_account, role, user_id)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.reject",
          frm, "REJECTED", "transfer rejected")
    return success_object(transfer_view(transfer))


@bp.post("/transfer-requests/<transfer_id>/cancel")
def cancel_transfer(transfer_id):
    user_id, role = auth()
    require_role(role, {"Shareholder"})
    transfer = get_transfer_or_404(transfer_id)
    shareholder_owns(user_id, transfer["from_account_id"])
    if transfer["status"] not in ("UNDER_REVIEW", "DEFICIENT"):
        fail("ERR_INVALID_STATE", "transfer cannot be cancelled from %s" % transfer["status"])
    frm = transfer["status"]
    transfer["status"] = "CANCELLED"
    touch(transfer)
    from_account = STORE["accounts"].get(transfer["from_account_id"])
    if from_account is not None:
        _decrement_pending(from_account, role, user_id)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.cancel",
          frm, "CANCELLED", "transferor cancelled the request")
    return success_object(transfer_view(transfer))


@bp.post("/transfer-requests/<transfer_id>/settle")
def settle_transfer(transfer_id):
    user_id, role = auth()
    require_role(role, {"TransferSupervisor"})
    transfer = get_transfer_or_404(transfer_id)
    # state gates (stage 5) — all preconditions checked before any mutation
    if transfer["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED transfer can be settled")
    issuer = STORE["issuers"].get(transfer["issuer_id"])
    if issuer is None:
        fail("ERR_ISSUER_NOT_FOUND", "issuer does not exist")
    if issuer["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "issuer is not ACTIVE")
    certificate = None
    if transfer["source_certificate_id"] is not None:
        certificate = STORE["certificates"].get(transfer["source_certificate_id"])
        if certificate is None:
            fail("ERR_CERTIFICATE_NOT_FOUND", "source certificate does not exist")
        if certificate["status"] == "LOST_REPORTED":
            fail("ERR_CERTIFICATE_STOPPED",
                 "source certificate is under a stop-transfer order")
        if certificate["status"] != "ISSUED":
            fail("ERR_INVALID_STATE", "source certificate is no longer ISSUED")
    position = find_position(transfer["from_account_id"], transfer["issuer_id"])
    if position is None:
        fail("ERR_POSITION_NOT_FOUND", "source position does not exist")
    if certificate is None:
        if position["book_entry_shares"] < transfer["share_quantity"]:
            fail("ERR_INVALID_STATE",
                 "source book_entry_shares no longer cover the transfer quantity")
    else:
        if certificate["share_quantity"] != transfer["share_quantity"]:
            fail("ERR_INVALID_STATE",
                 "source certificate face quantity no longer equals the transfer quantity")
    # temporal gate (stage 7): freeze windows, closed interval
    if freeze_window_blocks(transfer["issuer_id"], now_dt()):
        fail("ERR_TRANSFER_FREEZE_CONFLICT",
             "settlement falls inside an issuer transfer freeze window")
    # ---- all gates passed; execute the cascade in order ----
    quantity = transfer["share_quantity"]
    if certificate is not None:
        # hop 1: certificated source certificate is cancelled
        certificate["status"] = "CANCELLED"
        touch(certificate)
        audit("Certificate", certificate["id"], role, user_id, "certificate.cancel",
              "ISSUED", "CANCELLED", "certificate cancelled by transfer settlement")
        position["certificated_shares"] -= quantity
    else:
        position["book_entry_shares"] -= quantity
    # hop 2: source debit / transferee credit (transferee position created if absent)
    touch(position)
    audit("Position", position["id"], role, user_id, "position.transfer_debit",
          position["status"], position["status"],
          "debited %d shares for transfer settlement" % quantity)
    destination = find_position(transfer["to_account_id"], transfer["issuer_id"])
    if destination is None:
        destination = stamp_new({
            "account_id": transfer["to_account_id"],
            "issuer_id": transfer["issuer_id"],
            "book_entry_shares": 0,
            "restricted_shares": 0,
            "certificated_shares": 0,
            "status": "ACTIVE",
            "pending_legend_removal_count": 0,
        })
        STORE["positions"][destination["id"]] = destination
        audit("Position", destination["id"], role, user_id, "position.create",
              "", "ACTIVE", "transferee position created at settlement")
    destination["book_entry_shares"] += quantity
    touch(destination)
    audit("Position", destination["id"], role, user_id, "position.transfer_credit",
          destination["status"], destination["status"],
          "credited %d book-entry shares from transfer settlement" % quantity)
    # hop 3: issuer totals are recomputed on read from positions (no stored drift)
    transfer["status"] = "SETTLED"
    transfer["settled_at"] = now_iso()
    touch(transfer)
    from_account = STORE["accounts"].get(transfer["from_account_id"])
    if from_account is not None:
        _decrement_pending(from_account, role, user_id)
    audit("TransferRequest", transfer["id"], role, user_id, "transfer.settle",
          "APPROVED", "SETTLED", "transfer settled")
    return success_object(transfer_view(transfer))

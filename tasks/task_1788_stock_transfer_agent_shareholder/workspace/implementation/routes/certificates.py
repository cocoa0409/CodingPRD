"""Certificate endpoints: list, deposit (convert-to-DRS), report-lost, recover."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_dt, pagination_params
from middleware import auth, require_role, shareholder_owns, officer_owns
from response import success_list, success_object
from services import (stamp_new, touch, audit, sorted_recs, certificate_view,
                      open_claim_for_certificate, now_iso, new_certificate_number)

bp = Blueprint("certificates", __name__)

CERT_READ_ROLES = {"AgentAdmin", "TransferExaminer", "TransferSupervisor",
                   "ComplianceOfficer", "Shareholder"}
ISSUER_CERT_READ_ROLES = {"AgentAdmin", "IssuerOfficer", "TransferExaminer",
                          "TransferSupervisor", "ComplianceOfficer"}


def get_certificate_or_404(certificate_id):
    cert = STORE["certificates"].get(certificate_id)
    if cert is None:
        fail("ERR_CERTIFICATE_NOT_FOUND", "certificate %s does not exist" % certificate_id)
    return cert


def _gate_escheated_account(cert):
    account = STORE["accounts"].get(cert["account_id"])
    if account is not None and account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account["id"])
    return account


@bp.get("/certificates")
def list_certificates():
    user_id, role = auth()
    require_role(role, CERT_READ_ROLES)
    account_filter = request.args.get("account_id")
    issuer_filter = request.args.get("issuer_id")
    status_filter = request.args.get("status")
    if role == "Shareholder" and account_filter is not None:
        shareholder_owns(user_id, account_filter)
    items = sorted_recs("certificates")
    if account_filter is not None:
        items = [c for c in items if c["account_id"] == account_filter]
    if issuer_filter is not None:
        items = [c for c in items if c["issuer_id"] == issuer_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([certificate_view(c) for c in page], limit, offset, total)


@bp.get("/accounts/<account_id>/certificates")
def list_account_certificates(account_id):
    user_id, role = auth()
    require_role(role, CERT_READ_ROLES)
    if role == "Shareholder":
        shareholder_owns(user_id, account_id)
    if account_id not in STORE["accounts"]:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % account_id)
    items = [c for c in sorted_recs("certificates") if c["account_id"] == account_id]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([certificate_view(c) for c in page], limit, offset, total)


@bp.get("/issuers/<issuer_id>/certificates")
def list_issuer_certificates(issuer_id):
    user_id, role = auth()
    require_role(role, ISSUER_CERT_READ_ROLES)
    if role == "IssuerOfficer":
        officer_owns(user_id, issuer_id)
    if issuer_id not in STORE["issuers"]:
        fail("ERR_ISSUER_NOT_FOUND", "issuer %s does not exist" % issuer_id)
    items = [c for c in sorted_recs("certificates") if c["issuer_id"] == issuer_id]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([certificate_view(c) for c in page], limit, offset, total)


@bp.post("/certificates/<certificate_id>/convert-to-drs")
def convert_to_drs(certificate_id):
    user_id, role = auth()
    require_role(role, {"TransferExaminer"})
    cert = get_certificate_or_404(certificate_id)
    _gate_escheated_account(cert)
    if cert["status"] == "LOST_REPORTED":
        fail("ERR_CERTIFICATE_STOPPED",
             "certificate is under a stop-transfer order and cannot be deposited")
    if cert["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "only an ISSUED certificate can be converted to DRS")
    position = None
    for p in STORE["positions"].values():
        if p["account_id"] == cert["account_id"] and p["issuer_id"] == cert["issuer_id"]:
            position = p
            break
    if position is None:
        fail("ERR_POSITION_NOT_FOUND", "no position for the certificate's account and issuer")
    quantity = cert["share_quantity"]
    position["certificated_shares"] -= quantity
    position["book_entry_shares"] += quantity
    touch(position)
    audit("Position", position["id"], role, user_id, "position.certificate_deposit",
          position["status"], position["status"],
          "deposited %d certificated shares back to book-entry" % quantity)
    cert["status"] = "CANCELLED"
    touch(cert)
    audit("Certificate", cert["id"], role, user_id, "certificate.convert_drs",
          "ISSUED", "CANCELLED", "certificate deposited into book-entry")
    return success_object(certificate_view(cert))


@bp.post("/certificates/<certificate_id>/report-lost")
def report_lost(certificate_id):
    user_id, role = auth()
    require_role(role, {"Shareholder", "TransferExaminer"})
    cert = get_certificate_or_404(certificate_id)
    if role == "Shareholder":
        shareholder_owns(user_id, cert["account_id"])
    _gate_escheated_account(cert)
    if open_claim_for_certificate(cert["id"]) is not None:
        fail("ERR_DUPLICATE_OPEN_CLAIM",
             "certificate already has an open lost-certificate claim")
    if cert["status"] != "ISSUED":
        fail("ERR_INVALID_STATE", "only an ISSUED certificate can be reported lost")
    body = get_body()
    loss_date = req_dt(body, "loss_date")
    from helpers import fmt_dt
    issuer = STORE["issuers"].get(cert["issuer_id"])
    price = issuer["current_market_price_cents"] if issuer else None
    cert["status"] = "LOST_REPORTED"
    cert["lost_reported_at"] = now_iso()
    touch(cert)
    audit("Certificate", cert["id"], role, user_id, "certificate.report_lost",
          "ISSUED", "LOST_REPORTED", "stop-transfer order placed")
    claim = stamp_new({
        "certificate_id": cert["id"],
        "claimant_account_id": cert["account_id"],
        "filed_by_examiner_id": user_id if role == "TransferExaminer" else None,
        "loss_date": fmt_dt(loss_date),
        "loss_report_price_cents": price,
        "bond_variant": None,
        "bond_amount_cents": None,
        "required_premium_cents": None,
        "premium_paid_cents": None,
        "status": "FILED",
        "replacement_certificate_id": None,
    })
    STORE["claims"][claim["id"]] = claim
    audit("LostCertificateClaim", claim["id"], role, user_id, "claim.create",
          "", "FILED", "lost-certificate claim filed")
    from services import claim_view
    return success_object(claim_view(claim), 201)


@bp.post("/certificates/<certificate_id>/recover")
def recover_certificate(certificate_id):
    user_id, role = auth()
    require_role(role, {"TransferExaminer"})
    cert = get_certificate_or_404(certificate_id)
    _gate_escheated_account(cert)
    if cert["status"] != "LOST_REPORTED":
        fail("ERR_INVALID_STATE", "only a LOST_REPORTED certificate can be recovered")
    cert["status"] = "ISSUED"
    cert["lost_reported_at"] = None
    touch(cert)
    # withdraw any open claim on the certificate; bond obligation voided
    for claim in sorted_recs("claims"):
        if claim["certificate_id"] == cert["id"] and claim["status"] in ("FILED", "BOND_POSTED"):
            frm = claim["status"]
            claim["status"] = "WITHDRAWN"
            touch(claim)
            audit("LostCertificateClaim", claim["id"], role, user_id, "claim.withdrawn",
                  frm, "WITHDRAWN", "certificate recovered; bond obligation voided")
    audit("Certificate", cert["id"], role, user_id, "certificate.recover",
          "LOST_REPORTED", "ISSUED", "stop-transfer order lifted")
    return success_object(certificate_view(cert))

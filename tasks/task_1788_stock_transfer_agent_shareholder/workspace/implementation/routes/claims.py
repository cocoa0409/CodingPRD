"""Lost-certificate claim endpoints: list/read, post-bond, approve, reject, issue-replacement."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_int, req_enum, pagination_params
from middleware import auth, require_role, shareholder_owns
from response import success_list, success_object
from services import (stamp_new, touch, audit, sorted_recs, claim_view,
                      bond_pricing, new_certificate_number, now_iso, certificate_view)

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = {"TransferExaminer", "TransferSupervisor", "AgentAdmin", "Shareholder"}


def get_claim_or_404(claim_id):
    claim = STORE["claims"].get(claim_id)
    if claim is None:
        fail("ERR_CLAIM_NOT_FOUND", "lost-certificate claim %s does not exist" % claim_id)
    return claim


@bp.get("/lost-certificate-claims")
def list_claims():
    user_id, role = auth()
    require_role(role, CLAIM_READ_ROLES)
    cert_filter = request.args.get("certificate_id")
    claimant_filter = request.args.get("claimant_account_id")
    replacement_filter = request.args.get("replacement_certificate_id")
    status_filter = request.args.get("status")
    if role == "Shareholder" and claimant_filter is not None:
        shareholder_owns(user_id, claimant_filter)
    items = sorted_recs("claims")
    if cert_filter is not None:
        items = [c for c in items if c["certificate_id"] == cert_filter]
    if claimant_filter is not None:
        items = [c for c in items if c["claimant_account_id"] == claimant_filter]
    if replacement_filter is not None:
        items = [c for c in items if c["replacement_certificate_id"] == replacement_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([claim_view(c) for c in page], limit, offset, total)


@bp.get("/lost-certificate-claims/<claim_id>")
def read_claim(claim_id):
    user_id, role = auth()
    require_role(role, CLAIM_READ_ROLES)
    claim = get_claim_or_404(claim_id)
    if role == "Shareholder":
        shareholder_owns(user_id, claim["claimant_account_id"])
    return success_object(claim_view(claim))


@bp.post("/lost-certificate-claims/<claim_id>/post-bond")
def post_bond(claim_id):
    user_id, role = auth()
    require_role(role, {"TransferExaminer"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "FILED":
        fail("ERR_INVALID_STATE", "only a FILED claim can post a bond")
    body = get_body()
    bond_variant = req_enum(body, "bond_variant", {"OPEN_PENALTY", "FIXED_PENALTY"})
    premium_paid = req_int(body, "premium_paid_cents")
    if premium_paid < 0:
        fail("ERR_INVALID_REQUEST", "premium_paid_cents must be >= 0")
    certificate = STORE["certificates"].get(claim["certificate_id"])
    issuer = STORE["issuers"].get(certificate["issuer_id"]) if certificate else None
    bond_amount, required_premium = bond_pricing(claim, certificate, issuer, bond_variant)
    if premium_paid < required_premium:
        fail("ERR_BOND_PREMIUM_INSUFFICIENT",
             "premium_paid_cents %d is below required_premium_cents %d"
             % (premium_paid, required_premium))
    claim["bond_variant"] = bond_variant
    claim["bond_amount_cents"] = bond_amount
    claim["required_premium_cents"] = required_premium
    claim["premium_paid_cents"] = premium_paid
    claim["status"] = "BOND_POSTED"
    touch(claim)
    audit("LostCertificateClaim", claim["id"], role, user_id, "claim.post_bond",
          "FILED", "BOND_POSTED", "indemnity bond posted (%s)" % bond_variant)
    return success_object(claim_view(claim))


@bp.post("/lost-certificate-claims/<claim_id>/approve")
def approve_claim(claim_id):
    user_id, role = auth()
    require_role(role, {"TransferSupervisor"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "BOND_POSTED":
        fail("ERR_INVALID_STATE", "only a BOND_POSTED claim can be approved")
    if claim["filed_by_examiner_id"] is not None and user_id == claim["filed_by_examiner_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "approver must differ from the examiner who filed the claim")
    claim["status"] = "APPROVED"
    touch(claim)
    audit("LostCertificateClaim", claim["id"], role, user_id, "claim.approve",
          "BOND_POSTED", "APPROVED", "claim approved")
    return success_object(claim_view(claim))


@bp.post("/lost-certificate-claims/<claim_id>/reject")
def reject_claim(claim_id):
    user_id, role = auth()
    require_role(role, {"TransferSupervisor"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "BOND_POSTED":
        fail("ERR_INVALID_STATE", "only a BOND_POSTED claim can be rejected")
    claim["status"] = "REJECTED"
    touch(claim)
    audit("LostCertificateClaim", claim["id"], role, user_id, "claim.reject",
          "BOND_POSTED", "REJECTED", "claim rejected; stop order remains in force")
    return success_object(claim_view(claim))


@bp.post("/lost-certificate-claims/<claim_id>/issue-replacement")
def issue_replacement(claim_id):
    user_id, role = auth()
    require_role(role, {"TransferSupervisor"})
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED claim can issue a replacement")
    original = STORE["certificates"].get(claim["certificate_id"])
    if original is None:
        fail("ERR_CERTIFICATE_NOT_FOUND", "original certificate does not exist")
    original["status"] = "REPLACED"
    touch(original)
    audit("Certificate", original["id"], role, user_id, "certificate.replaced",
          "LOST_REPORTED", "REPLACED", "original certificate marked replaced")
    replacement = stamp_new({
        "account_id": original["account_id"],
        "issuer_id": original["issuer_id"],
        "certificate_number": new_certificate_number(),
        "share_quantity": original["share_quantity"],
        "status": "ISSUED",
        "legend_restricted": original["legend_restricted"],
        "issued_at": now_iso(),
        "lost_reported_at": None,
    })
    STORE["certificates"][replacement["id"]] = replacement
    audit("Certificate", replacement["id"], role, user_id, "certificate.reissue",
          "", "ISSUED", "replacement certificate minted")
    claim["replacement_certificate_id"] = replacement["id"]
    claim["status"] = "REPLACED"
    touch(claim)
    audit("LostCertificateClaim", claim["id"], role, user_id, "claim.replaced",
          "APPROVED", "REPLACED", "replacement certificate issued")
    return success_object(claim_view(claim))

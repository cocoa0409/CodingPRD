"""Bank accounts, callback verifications, and compliance documents."""
import random
from datetime import timedelta

from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE_TRANSITION,
    ERR_CALLBACK_LOCKED,
    ERR_CALLBACK_EXPIRED,
    ERR_CALLBACK_CODE_MISMATCH,
    ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM,
    ERR_BANK_ACCOUNT_IN_USE,
    ERR_DOCUMENT_PERIOD_OVERLAP,
    raise_err,
)
from middleware import (
    require_auth,
    require_role,
    get_body,
    req_str,
    opt_bool,
    req_int,
    get_or_404,
    paginate,
    parse_iso_date,
)
from response import ok, ok_list

bp = Blueprint("bank", __name__)

BANK_ACCOUNT_CREATE_VENDOR_STATUSES = ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED")


def _mint_code():
    return "%06d" % random.randint(0, 999999)


def latest_verification_for(account_id):
    vers = [v for v in db.callback_verifications.values() if v["bank_account_id"] == account_id]
    if not vers:
        return None
    return sorted(vers, key=lambda v: v["created_at"])[-1]


@bp.route("/vendors/<vendor_id>/bank-accounts", methods=["POST"])
def create_bank_account(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist"])
    body = get_body()
    account_number = req_str(body, "account_number")
    routing_number = req_str(body, "routing_number")
    account_holder_name = req_str(body, "account_holder_name")
    is_primary = opt_bool(body, "is_primary", False)
    req_int(body, "expected_vendor_version")
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if body["expected_vendor_version"] != vendor["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_vendor_version does not match the vendor's current version.")
    if vendor["status"] not in BANK_ACCOUNT_CREATE_VENDOR_STATUSES:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Cannot add a bank account to a vendor in status %s." % vendor["status"])

    account = db.stamp_new({
        "id": db.new_id(),
        "vendor_id": vendor["id"],
        "account_number": account_number,
        "routing_number": routing_number,
        "account_holder_name": account_holder_name,
        "is_primary": is_primary,
        "status": "PENDING_VERIFICATION",
        "requested_by_user_id": ctx.user_id,
        "verified_at": None,
    })
    db.bank_accounts[account["id"]] = account
    db.touch(vendor)  # adding a bank account increments the vendor's version

    created = db.now()
    verification = db.stamp_new({
        "id": db.new_id(),
        "bank_account_id": account["id"],
        "verification_code": _mint_code(),
        "attempts": 0,
        "status": "PENDING",
        "expires_at": db.fmt_ts(created + timedelta(hours=svc.CALLBACK_EXPIRY_HOURS)),
        "confirmed_by_user_id": None,
    })
    db.callback_verifications[verification["id"]] = verification
    svc.audit("VendorBankAccount", account["id"], "CREATE", ctx)
    return ok(account, status=201)


@bp.route("/vendors/<vendor_id>/bank-accounts", methods=["GET"])
def list_vendor_bank_accounts(vendor_id):
    require_auth()
    get_or_404(db.vendors, vendor_id, "Vendor")
    items = [a for a in db.bank_accounts.values() if a["vendor_id"] == vendor_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/bank-accounts/<account_id>", methods=["GET"])
def get_bank_account(account_id):
    require_auth()
    return ok(get_or_404(db.bank_accounts, account_id, "VendorBankAccount"))


@bp.route("/bank-accounts/<account_id>/confirm-verification", methods=["POST"])
def confirm_verification(account_id):
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist", "VendorManager"])
    body = get_body()
    code = req_str(body, "verification_code")
    account = get_or_404(db.bank_accounts, account_id, "VendorBankAccount")
    verification = latest_verification_for(account_id)
    if verification is None:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Bank account has no callback verification to confirm.")

    # fixed guard order: CONFIRMED -> LOCKED -> EXPIRED -> SoD-3 -> code
    if verification["status"] == "CONFIRMED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Callback verification has already been confirmed.")
    if verification["status"] == "LOCKED":
        raise_err(ERR_CALLBACK_LOCKED, "Callback verification is locked.")
    if verification["status"] == "EXPIRED":
        raise_err(ERR_CALLBACK_EXPIRED, "Callback verification has expired.")
    # live expiry: still PENDING but past expires_at is not confirmable
    if db.now() > svc.datetime_from_iso(verification["expires_at"]):
        raise_err(ERR_CALLBACK_EXPIRED, "Callback verification has expired.")
    if account["status"] != "PENDING_VERIFICATION":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Bank account in status %s cannot be verified." % account["status"])
    if ctx.user_id == account["requested_by_user_id"]:
        raise_err(ERR_SOD_CALLBACK_REQUESTER_CANNOT_CONFIRM,
                  "The bank account's requester may not confirm its callback (SoD-3).")
    if code != verification["verification_code"]:
        verification["attempts"] += 1
        db.touch(verification)
        if verification["attempts"] < svc.CALLBACK_MAX_ATTEMPTS:
            raise_err(ERR_CALLBACK_CODE_MISMATCH, "Verification code does not match.")
        # third mismatch locks the verification and rejects the parent account
        verification["status"] = "LOCKED"
        db.touch(verification)
        account["status"] = "REJECTED"
        db.touch(account)
        svc.audit_status_change("VendorBankAccount", account["id"],
                                "PENDING_VERIFICATION", "REJECTED", ctx)
        raise_err(ERR_CALLBACK_LOCKED,
                  "Verification code mismatch limit reached; verification is locked.")

    # success: verification CONFIRMED, account VERIFIED, primary supersede chain
    verification["status"] = "CONFIRMED"
    verification["confirmed_by_user_id"] = ctx.user_id
    db.touch(verification)
    account["status"] = "VERIFIED"
    account["verified_at"] = db.fmt_ts(db.now())
    db.touch(account)
    if account["is_primary"]:
        vendor = db.vendors.get(account["vendor_id"])
        if vendor is not None:
            previous_id = vendor.get("primary_bank_account_id")
            if previous_id and previous_id != account["id"]:
                previous = db.bank_accounts.get(previous_id)
                if previous is not None and previous["status"] == "VERIFIED":
                    previous["status"] = "SUPERSEDED"
                    db.touch(previous)
                    svc.audit_status_change("VendorBankAccount", previous["id"],
                                            "VERIFIED", "SUPERSEDED", ctx)
            vendor["primary_bank_account_id"] = account["id"]
            db.touch(vendor)
    svc.audit("VendorBankAccount", account["id"], "VERIFY", ctx)
    return ok(account)


@bp.route("/bank-accounts/<account_id>/disable", methods=["POST"])
def disable_bank_account(account_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    account = get_or_404(db.bank_accounts, account_id, "VendorBankAccount")
    if account["status"] != "VERIFIED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Bank account in status %s cannot be disabled." % account["status"])
    for p in db.payments.values():
        if p["bank_account_id"] == account["id"] and p["status"] in ("PENDING", "RELEASED"):
            raise_err(ERR_BANK_ACCOUNT_IN_USE,
                      "Bank account is referenced by in-flight payments.")
    account["status"] = "DISABLED"
    db.touch(account)
    vendor = db.vendors.get(account["vendor_id"])
    if vendor is not None and vendor.get("primary_bank_account_id") == account["id"]:
        vendor["primary_bank_account_id"] = None
        db.touch(vendor)
    svc.audit_status_change("VendorBankAccount", account["id"], "VERIFIED", "DISABLED", ctx)
    return ok(account)


@bp.route("/bank-accounts/<account_id>/callback-verifications", methods=["GET"])
def list_callback_verifications(account_id):
    require_auth()
    get_or_404(db.bank_accounts, account_id, "VendorBankAccount")
    items = [v for v in db.callback_verifications.values() if v["bank_account_id"] == account_id]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


# -------------------------------------------------------------------------
# compliance documents
# -------------------------------------------------------------------------

DOC_TYPES = ("W9", "INSURANCE_CERT", "BANK_AUTHORIZATION")


@bp.route("/vendors/<vendor_id>/documents", methods=["POST"])
def create_document(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist"])
    body = get_body()
    doc_type = body.get("doc_type")
    if doc_type not in DOC_TYPES:
        raise_err(ERR_INVALID_REQUEST, "doc_type must be one of W9, INSURANCE_CERT, BANK_AUTHORIZATION.")
    valid_from = req_str(body, "valid_from")
    valid_until = req_str(body, "valid_until")
    vf = parse_iso_date(valid_from, "valid_from")
    vu = parse_iso_date(valid_until, "valid_until")
    if vf > vu:
        raise_err(ERR_INVALID_REQUEST, "valid_from must not fall after valid_until.")
    get_or_404(db.vendors, vendor_id, "Vendor")

    # closed-interval overlap gate per (vendor, doc_type): a shared endpoint day overlaps
    for doc in db.documents.values():
        if doc["vendor_id"] != vendor_id or doc["doc_type"] != doc_type:
            continue
        if valid_from <= doc["valid_until"] and doc["valid_from"] <= valid_until:
            raise_err(ERR_DOCUMENT_PERIOD_OVERLAP,
                      "Document window overlaps an existing %s document for this vendor." % doc_type)

    doc = db.stamp_new({
        "id": db.new_id(),
        "vendor_id": vendor_id,
        "doc_type": doc_type,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "VALID",
    })
    db.documents[doc["id"]] = doc
    svc.audit("VendorDocument", doc["id"], "CREATE", ctx)
    return ok(doc, status=201)


@bp.route("/vendors/<vendor_id>/documents", methods=["GET"])
def list_documents(vendor_id):
    require_auth()
    get_or_404(db.vendors, vendor_id, "Vendor")
    items = [d for d in db.documents.values() if d["vendor_id"] == vendor_id]
    doc_type = request.args.get("doc_type")
    if doc_type is not None:
        items = [d for d in items if d["doc_type"] == doc_type]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/documents/<doc_id>/supersede", methods=["POST"])
def supersede_document(doc_id):
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist"])
    doc = get_or_404(db.documents, doc_id, "VendorDocument")
    if doc["status"] != "VALID":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Document in status %s cannot be superseded." % doc["status"])
    doc["status"] = "SUPERSEDED"
    db.touch(doc)
    svc.audit_status_change("VendorDocument", doc["id"], "VALID", "SUPERSEDED", ctx)
    return ok(doc)

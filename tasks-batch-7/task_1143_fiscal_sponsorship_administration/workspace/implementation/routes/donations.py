"""Donation + TaxReceipt endpoints (PRD §3.3)."""

from flask import Blueprint, request

from db import (
    agreement_of_project,
    fund_of_project,
    iso,
    new_id,
    now,
    stamp_new,
    store,
    touch,
)
from envelope import ok_list, ok_obj
from errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AMOUNT_BELOW_MINIMUM,
    ERR_DONATION_NOT_FOUND,
    ERR_DONATION_STATE_INVALID,
    ERR_FUND_NOT_ACTIVE,
    ERR_PROJECT_NOT_ACTIVE,
    ERR_PROJECT_NOT_FOUND,
    ERR_RECEIPT_NOT_FOUND,
    ERR_REFUND_EXCEEDS_REMAINING,
    ERR_SEVERE_POSTURE_BLOCKS_SPEND,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    opt_bool,
    opt_str,
    req_enum,
    req_int,
    req_str,
    require_role,
)
from services import admin_fee_on_receipt, issue_receipt, issued_receipt_of, post_ledger

bp = Blueprint("donations", __name__)

PAYMENT_METHODS = ("CARD", "ACH", "CHECK", "WIRE")
REFUND_DECISIONS = ("APPROVE", "REJECT")
MIN_DONATION_CENTS = 100


def get_donation(donation_id):
    donation = store.donations.get(donation_id)
    if donation is None:
        raise_err(ERR_DONATION_NOT_FOUND, "donation not found")
    return donation


@bp.post("/fsa/projects/<project_id>/donations")
def create_donation(project_id):
    data = body()
    amount = req_int(data, "amount_cents")
    donor_name = req_str(data, "donor_name")
    donor_email = req_str(data, "donor_email")
    donor_tax_id = opt_str(data, "donor_tax_id")
    anonymous = opt_bool(data, "anonymous")
    payment_method = req_enum(data, "payment_method", PAYMENT_METHODS)
    uid, role = auth()
    require_role(role, {"Donor"})
    project = store.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    if project["status"] != "ACTIVE":
        raise_err(ERR_PROJECT_NOT_ACTIVE, "project is not ACTIVE")
    if amount < MIN_DONATION_CENTS:
        raise_err(ERR_AMOUNT_BELOW_MINIMUM, "amount_cents must be at least 100")
    fund = fund_of_project(project["id"])
    donation = stamp_new({
        "id": new_id(),
        "project_id": project["id"],
        "fund_account_id": fund["id"] if fund else None,
        "amount_cents": amount,
        "donor_name": donor_name,
        "donor_email": donor_email,
        "donor_tax_id": donor_tax_id,
        "anonymous": anonymous if anonymous is not None else False,
        "payment_method": payment_method,
        "status": "PLEDGED",
        "fee_cents": 0,
        "refunded_cents": 0,
        "pending_refund_amount_cents": None,
        "status_before_refund": None,
        "received_at": None,
        "refunded_at": None,
    })
    store.donations[donation["id"]] = donation
    return ok_obj(donation, 201)


@bp.get("/fsa/donations")
def list_donations():
    uid, role = auth()
    require_role(role, READ_ROLES)
    items = list(store.donations.values())
    for param, field in (
        ("project_id", "project_id"),
        ("fund_account_id", "fund_account_id"),
        ("status", "status"),
        ("donor_email", "donor_email"),
    ):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[field] == v]
    return ok_list(items)


@bp.get("/fsa/donations/<donation_id>")
def get_donation_route(donation_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    return ok_obj(get_donation(donation_id))


@bp.post("/fsa/donations/<donation_id>/receive")
def receive_donation(donation_id):
    uid, role = auth()
    require_role(role, {"FinanceOfficer"})
    donation = get_donation(donation_id)
    if donation["status"] != "PLEDGED":
        raise_err(ERR_DONATION_STATE_INVALID, "donation is not PLEDGED")
    project = store.projects.get(donation["project_id"])
    if project is None or project["status"] != "ACTIVE":
        raise_err(ERR_PROJECT_NOT_ACTIVE, "project is not ACTIVE")
    agreement = agreement_of_project(donation["project_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "agreement is not ACTIVE")
    fund = store.funds.get(donation["fund_account_id"])
    if fund is None or fund["status"] != "ACTIVE":
        raise_err(ERR_FUND_NOT_ACTIVE, "fund account is not ACTIVE")
    if project["oversight_posture"] == "SEVERE":
        raise_err(ERR_SEVERE_POSTURE_BLOCKS_SPEND, "SEVERE oversight posture blocks receiving donations")
    fee = admin_fee_on_receipt(donation["amount_cents"], fund["total_received_cents"], agreement["model"])
    fund["total_received_cents"] += donation["amount_cents"]
    fund["total_fees_charged_cents"] += fee
    post_ledger(fund["id"], "DONATION_CREDIT", donation["amount_cents"],
                "Donation %s received" % donation["id"], donation_id=donation["id"])
    post_ledger(fund["id"], "FEE_DEBIT", -fee,
                "Administrative fee on donation %s" % donation["id"], donation_id=donation["id"])
    touch(fund)
    donation["fee_cents"] = fee
    donation["received_at"] = iso(now())
    donation["status"] = "RECEIVED"
    touch(donation)
    return ok_obj(donation)


@bp.post("/fsa/donations/<donation_id>/issue-receipt")
def issue_receipt_route(donation_id):
    uid, role = auth()
    require_role(role, {"FinanceOfficer"})
    donation = get_donation(donation_id)
    if donation["status"] != "RECEIVED":
        raise_err(ERR_DONATION_STATE_INVALID, "donation is not RECEIVED")
    agreement = agreement_of_project(donation["project_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "agreement is not ACTIVE")
    issue_receipt(donation, donation["amount_cents"])
    donation["status"] = "RECEIPTED"
    touch(donation)
    return ok_obj(donation)


@bp.post("/fsa/donations/<donation_id>/request-refund")
def request_refund(donation_id):
    data = body()
    amount = req_int(data, "amount_cents")
    reason = req_str(data, "reason")
    uid, role = auth()
    require_role(role, {"Donor", "FinanceOfficer"})
    donation = get_donation(donation_id)
    if donation["status"] not in ("RECEIVED", "RECEIPTED"):
        raise_err(ERR_DONATION_STATE_INVALID, "donation is not RECEIVED or RECEIPTED")
    remaining = donation["amount_cents"] - donation["refunded_cents"]
    if amount < 1 or amount > remaining:
        raise_err(ERR_REFUND_EXCEEDS_REMAINING, "refund amount out of bounds")
    donation["status_before_refund"] = donation["status"]
    donation["pending_refund_amount_cents"] = amount
    donation["status"] = "REFUND_REQUESTED"
    touch(donation)
    return ok_obj(donation)


@bp.post("/fsa/donations/<donation_id>/decide-refund")
def decide_refund(donation_id):
    data = body()
    decision = req_enum(data, "decision", REFUND_DECISIONS)
    opt_str(data, "note")
    uid, role = auth()
    require_role(role, {"SponsorAdmin"})
    donation = get_donation(donation_id)
    if donation["status"] != "REFUND_REQUESTED":
        raise_err(ERR_DONATION_STATE_INVALID, "donation has no open refund request")
    pending = donation["pending_refund_amount_cents"]
    prior = donation["status_before_refund"]
    fund = store.funds.get(donation["fund_account_id"])
    if decision == "REJECT":
        donation["status"] = prior
        donation["pending_refund_amount_cents"] = None
        donation["status_before_refund"] = None
        touch(donation)
        return ok_obj(donation)
    # APPROVE
    is_full = (donation["refunded_cents"] + pending) == donation["amount_cents"]
    fund["total_refunded_cents"] += pending
    post_ledger(fund["id"], "DONATION_REFUND_DEBIT", -pending,
                "Refund on donation %s" % donation["id"], donation_id=donation["id"])
    touch(fund)
    donation["refunded_at"] = iso(now())
    donation["pending_refund_amount_cents"] = None
    if is_full:
        donation["refunded_cents"] = donation["amount_cents"]
        donation["status"] = "REFUNDED"
        receipt = issued_receipt_of(donation["id"])
        if receipt is not None:
            receipt["status"] = "VOIDED"
            receipt["void_reason"] = "FULL_REFUND"
            touch(receipt)
    else:
        donation["refunded_cents"] += pending
        donation["status"] = prior
        if prior == "RECEIPTED":
            receipt = issued_receipt_of(donation["id"])
            if receipt is not None:
                receipt["status"] = "VOIDED"
                receipt["void_reason"] = "PARTIAL_REFUND"
                touch(receipt)
            issue_receipt(donation, donation["amount_cents"] - donation["refunded_cents"])
    donation["status_before_refund"] = None
    touch(donation)
    return ok_obj(donation)


# ---------------------------------------------------------------------------
# TaxReceipt reads
# ---------------------------------------------------------------------------


@bp.get("/fsa/receipts/<receipt_id>")
def get_receipt(receipt_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    receipt = store.receipts.get(receipt_id)
    if receipt is None:
        raise_err(ERR_RECEIPT_NOT_FOUND, "receipt not found")
    return ok_obj(receipt)


@bp.get("/fsa/donations/<donation_id>/receipts")
def donation_receipts(donation_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    get_donation(donation_id)
    items = [r for r in store.receipts.values() if r["donation_id"] == donation_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list(items)

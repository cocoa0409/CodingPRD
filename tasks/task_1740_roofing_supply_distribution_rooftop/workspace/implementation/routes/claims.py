"""Delivery damage claims under segregation of duties (PRD 3.8)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_DELIVERY_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_FILED,
    ERR_CLAIM_NOT_UNDER_REVIEW,
    ERR_CLAIM_NOT_APPROVED,
    ERR_INVALID_APPROVED_AMOUNT,
    ERR_SOD_VIOLATION,
)
from middleware import authorized, check_contractor_owns
from routes.helpers import body, body_field, render_list, render_one, require_int
from services.core import create_record, get_or_404, mutate

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = ["PlatformAdmin", "BranchManager", "ClaimsAdjuster", "CreditAnalyst", "Contractor"]


def _claim_or_404(rid):
    return get_or_404("damage_claims", rid, ERR_CLAIM_NOT_FOUND)


def _claim_order(claim):
    delivery = db["deliveries"].get(claim["delivery_id"])
    return db["orders"].get(delivery["order_id"]) if delivery else None


def _own_claim_check(caller, claim):
    order = _claim_order(claim)
    job = db["job_accounts"].get(order["job_account_id"]) if order else None
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)


@bp.post("/roofing/deliveries/<did>/damage-claims")
def file_claim(did):
    caller = authorized(["Contractor"])
    delivery = get_or_404("deliveries", did, ERR_DELIVERY_NOT_FOUND)
    order = db["orders"].get(delivery["order_id"])
    job = db["job_accounts"].get(order["job_account_id"]) if order else None
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    data = body()
    claimed = require_int(body_field(data, "claimed_bundles", required=True),
                          "claimed_bundles", minimum=1)
    evidence_note = body_field(data, "evidence_note", required=True)

    # claim_amount = claimed bundles x the unit price of the affected lines.
    covered = [db["order_lines"].get(lid) for lid in delivery.get("_line_quantities", {})]
    covered = [l for l in covered if l is not None]
    if not covered and order is not None:
        covered = [l for l in db["order_lines"].values() if l["order_id"] == order["id"]]
    unit_price = covered[0]["unit_price_cents"] if covered else 0

    rec = create_record("damage_claims", {
        "delivery_id": delivery["id"],
        "claimed_bundles": claimed,
        "claim_amount_cents": claimed * unit_price,
        "approved_amount_cents": 0,
        "evidence_note": evidence_note,
        "review_round": 1,
        "status": "FILED",
    })
    return render_one("damage_claims", rec, status=201)


@bp.get("/roofing/deliveries/<did>/damage-claims")
def list_delivery_claims(did):
    caller = authorized(CLAIM_READ_ROLES)
    delivery = get_or_404("deliveries", did, ERR_DELIVERY_NOT_FOUND)
    order = db["orders"].get(delivery["order_id"])
    job = db["job_accounts"].get(order["job_account_id"]) if order else None
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    claims = [c for c in db["damage_claims"].values() if c["delivery_id"] == delivery["id"]]
    return render_list(caller, "damage_claims", base_records=claims)


@bp.get("/roofing/damage-claims/<rid>")
def get_claim(rid):
    caller = authorized(CLAIM_READ_ROLES)
    rec = _claim_or_404(rid)
    _own_claim_check(caller, rec)
    return render_one("damage_claims", rec)


@bp.post("/roofing/damage-claims/<rid>/start-review")
def start_review(rid):
    authorized(["ClaimsAdjuster"])
    rec = _claim_or_404(rid)
    if rec["status"] not in ("FILED", "DISPUTED"):
        raise_error(ERR_CLAIM_NOT_FILED, "start-review requires the claim to be FILED or DISPUTED")
    if rec["status"] == "DISPUTED":
        rec["review_round"] += 1  # re-entry from dispute starts a fresh round
    rec["status"] = "UNDER_REVIEW"
    mutate(rec)
    return render_one("damage_claims", rec)


@bp.post("/roofing/damage-claims/<rid>/approve")
def approve_claim(rid):
    caller = authorized(["ClaimsAdjuster"])
    rec = _claim_or_404(rid)
    if rec["status"] != "UNDER_REVIEW":
        raise_error(ERR_CLAIM_NOT_UNDER_REVIEW, "approve requires the claim to be UNDER_REVIEW")
    data = body()
    amount = require_int(body_field(data, "approved_amount_cents", required=True),
                         "approved_amount_cents")
    if amount <= 0 or amount > rec["claim_amount_cents"]:
        raise_error(ERR_INVALID_APPROVED_AMOUNT,
                    "approved_amount_cents must be > 0 and <= claim_amount_cents")
    rec["approved_amount_cents"] = amount
    rec["_approved_by"] = caller.user_id  # remembered for the SoD credit gate
    rec["status"] = "APPROVED"
    mutate(rec)
    return render_one("damage_claims", rec)


@bp.post("/roofing/damage-claims/<rid>/reject")
def reject_claim(rid):
    authorized(["ClaimsAdjuster"])
    rec = _claim_or_404(rid)
    if rec["status"] != "UNDER_REVIEW":
        raise_error(ERR_CLAIM_NOT_UNDER_REVIEW, "reject requires the claim to be UNDER_REVIEW")
    rec["status"] = "REJECTED"
    mutate(rec)
    return render_one("damage_claims", rec)


@bp.post("/roofing/damage-claims/<rid>/credit")
def credit_claim(rid):
    caller = authorized(["CreditAnalyst"])
    rec = _claim_or_404(rid)
    if rec["status"] != "APPROVED":
        raise_error(ERR_CLAIM_NOT_APPROVED, "credit requires the claim to be APPROVED")
    if rec.get("_approved_by") is not None and rec["_approved_by"] == caller.user_id:
        raise_error(ERR_SOD_VIOLATION,
                    "the crediting user must differ from the approving user")

    order = _claim_order(rec)
    job = db["job_accounts"].get(order["job_account_id"]) if order else None
    account = db["contractor_accounts"].get(job["contractor_account_id"]) if job else None
    approved = rec["approved_amount_cents"]
    if account is not None:
        account["open_balance_cents"] = max(0, account["open_balance_cents"] - approved)
        mutate(account)
    if job is not None:
        job["job_balance_cents"] = max(0, job["job_balance_cents"] - approved)
        mutate(job)
    if order is not None and order["payment_status"] in ("UNPAID", "INVOICED"):
        outstanding = order.get("_invoice_outstanding_cents", order["total_cents"])
        outstanding = max(0, outstanding - approved)
        order["_invoice_outstanding_cents"] = outstanding
        if outstanding == 0:
            # Approved amount fully covers the order's remaining unpaid invoice.
            order["payment_status"] = "CREDITED"
        mutate(order)
    rec["status"] = "CREDITED"
    mutate(rec)
    return render_one("damage_claims", rec)


@bp.post("/roofing/damage-claims/<rid>/dispute")
def dispute_claim(rid):
    caller = authorized(["Contractor"])
    rec = _claim_or_404(rid)
    _own_claim_check(caller, rec)
    if rec["status"] != "APPROVED":
        raise_error(ERR_CLAIM_NOT_APPROVED, "dispute requires the claim to be APPROVED")
    rec["status"] = "DISPUTED"
    mutate(rec)
    return render_one("damage_claims", rec)

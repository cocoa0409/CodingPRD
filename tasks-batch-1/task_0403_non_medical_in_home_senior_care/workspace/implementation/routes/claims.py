"""LtcClaim endpoints: assign, submit/resubmit, adjudicate (PRD §2.9, §3.11)."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth, require_roles
from money import round_half_up, D
from response import success, list_success
from services import requtil
from services.calc import compute_covered_amount
from services.lookup import get_client, get_invoice, get_claim

bp = Blueprint("claims", __name__)


def _public_claim(claim):
    return db.public(claim)


@bp.post("/ltc-claims")
def create_claim():
    _, role = get_auth()
    require_roles(role, {"BillingClerk", "AgencyAdmin"})
    body = requtil.get_body()

    client_id = requtil.require_str(body, "client_id")
    invoice_id = requtil.require_str(body, "invoice_id")
    # Existence left-to-right: client, then invoice.
    get_client(client_id)
    invoice = get_invoice(invoice_id)

    insurer_name = requtil.require_str(body, "insurer_name")
    policy_number = requtil.require_str(body, "policy_number")
    covered_pct = requtil.require_number(body, "covered_pct")
    daily_benefit_max = requtil.require_number(body, "daily_benefit_max")
    covered_days = requtil.require_present(body, "covered_days")
    expected_invoice_version = requtil.require_present(body, "expected_invoice_version")

    # Well-formedness (PRD §2.7).
    if covered_pct < 0 or covered_pct > 1:
        raise requtil.invalid("covered_pct must be in [0,1]")
    if daily_benefit_max <= 0:
        raise requtil.invalid("daily_benefit_max must be > 0")
    if isinstance(covered_days, bool) or not isinstance(covered_days, int) or covered_days <= 0:
        raise requtil.invalid("covered_days must be an integer > 0")
    if isinstance(expected_invoice_version, bool) or not isinstance(expected_invoice_version, int):
        raise requtil.invalid("expected_invoice_version must be an integer")

    # Optimistic concurrency on the invoice (PRD §2.9).
    if expected_invoice_version != invoice["version"]:
        raise ApiError(errors.ERR_STALE_INVOICE_VERSION, 412,
                       "expected_invoice_version does not match invoice version")

    claim = {
        "client_id": client_id,
        "invoice_id": invoice_id,
        "insurer_name": insurer_name,
        "policy_number": policy_number,
        "covered_pct": covered_pct,
        "daily_benefit_max": daily_benefit_max,
        "covered_days": covered_days,
        "expected_invoice_version": expected_invoice_version,
        "covered_amount": 0,
        "status": "DRAFT",
    }
    db.stamp_new(claim)
    db.ltc_claims[claim["id"]] = claim
    # Successful assignment increments the invoice version (PRD §2.9).
    db.touch(invoice)
    return success(_public_claim(claim), status=201)


@bp.get("/ltc-claims")
def list_claims():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "BillingClerk"})
    limit, offset = requtil.pagination()
    items = list(db.ltc_claims.values())
    for key in ("client_id", "invoice_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([_public_claim(c) for c in page], limit, offset, total)


@bp.get("/ltc-claims/<clid>")
def get_claim_route(clid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "BillingClerk"})
    claim = get_claim(clid)
    return success(_public_claim(claim))


@bp.post("/ltc-claims/<clid>/submit")
def submit_claim(clid):
    _, role = get_auth()
    require_roles(role, {"BillingClerk"})
    claim = get_claim(clid)

    if claim["status"] not in ("DRAFT", "APPEALED"):
        raise ApiError(errors.ERR_INVALID_STATE, 409, "submit requires DRAFT or APPEALED")
    invoice = db.invoices.get(claim["invoice_id"])
    if invoice is None or invoice["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVOICE_NOT_ISSUED, 409, "invoice must be ISSUED")

    covered = compute_covered_amount(
        invoice["invoice_total"], claim["covered_pct"],
        claim["daily_benefit_max"], claim["covered_days"],
    )
    claim["covered_amount"] = covered
    claim["status"] = "SUBMITTED"
    db.touch(claim)

    cra = round_half_up(D(invoice["invoice_total"]) - D(covered))
    invoice["client_responsible_amount"] = cra
    db.touch(invoice)
    return success(_public_claim(claim))


@bp.post("/ltc-claims/<clid>/transition")
def transition_claim(clid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "BillingClerk"})
    claim = get_claim(clid)
    body = requtil.get_body()
    action = requtil.require_enum(body, "action", {"APPROVE", "DENY", "APPEAL"})

    if action == "APPROVE":
        if claim["status"] != "SUBMITTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "APPROVE requires SUBMITTED")
        claim["status"] = "APPROVED"
        db.touch(claim)

    elif action == "DENY":
        if claim["status"] != "SUBMITTED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "DENY requires SUBMITTED")
        claim["status"] = "DENIED"
        claim["covered_amount"] = 0
        db.touch(claim)
        invoice = db.invoices.get(claim["invoice_id"])
        if invoice is not None:
            invoice["client_responsible_amount"] = invoice["invoice_total"]
            db.touch(invoice)

    elif action == "APPEAL":
        if claim["status"] != "DENIED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "APPEAL requires DENIED")
        claim["status"] = "APPEALED"
        db.touch(claim)

    return success(_public_claim(claim))

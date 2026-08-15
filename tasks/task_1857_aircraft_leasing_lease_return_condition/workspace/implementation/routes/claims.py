"""Reserve claims: file, list, decide, pay, reverse-payment."""
from flask import Blueprint

from db import STORE, base_entity, touch
from errors import (
    ERR_CLAIM_NOT_PAYABLE,
    ERR_RESERVE_BALANCE_EXCEEDED,
    ApiError,
    bad_request,
    invalid_state,
    not_found,
)
from middleware import require_lease_ownership, require_roles
from response import paginated, success
from services.calculations import recompute_balance
from validators import get_body, req_enum, req_int, req_str

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = (
    "LessorAdmin",
    "CreditOfficer",
    "LegalApprover",
    "FinanceManager",
    "LesseeRep",
)


def get_claim_or_404(claim_id):
    c = STORE["reserve_claims"].get(claim_id)
    if c is None:
        raise not_found("Reserve claim not found")
    return c


@bp.post("/leasing/leases/<lease_id>/reserve-claims")
@require_roles("LesseeRep")
def file_claim(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    b = get_body()
    maintenance_event_ref = req_str(b, "maintenance_event_ref")
    claimed_amount_cents = req_int(b, "claimed_amount_cents", min_v=1)
    c = base_entity()
    c.update(
        {
            "lease_id": lease["id"],
            "maintenance_event_ref": maintenance_event_ref,
            "claimed_amount_cents": claimed_amount_cents,
            "approved_amount_cents": None,
            "status": "SUBMITTED",
        }
    )
    STORE["reserve_claims"][c["id"]] = c
    return success(c, status=201)


@bp.get("/leasing/leases/<lease_id>/reserve-claims")
@require_roles(*CLAIM_READ_ROLES)
def list_claims(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    items = [c for c in STORE["reserve_claims"].values() if c["lease_id"] == lease["id"]]
    items.sort(key=lambda c: c["created_at"])
    return paginated(items)


@bp.post("/leasing/reserve-claims/<claim_id>/decide")
@require_roles("LessorAdmin")
def decide_claim(claim_id):
    c = get_claim_or_404(claim_id)
    b = get_body()
    decision = req_enum(b, "decision", {"APPROVE", "REJECT"})
    approved_amount_cents = None
    if decision == "APPROVE":
        if b.get("approved_amount_cents") is None:
            raise bad_request("Missing required field: approved_amount_cents")
    if c["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED claim can be decided")
    if decision == "APPROVE":
        approved_amount_cents = req_int(b, "approved_amount_cents")
        if not (0 < approved_amount_cents <= c["claimed_amount_cents"]):
            raise bad_request(
                "approved_amount_cents must be > 0 and <= claimed_amount_cents"
            )
        c["approved_amount_cents"] = approved_amount_cents
        c["status"] = "APPROVED"
    else:
        c["status"] = "REJECTED"
    touch(c)
    return success(c)


@bp.post("/leasing/reserve-claims/<claim_id>/pay")
@require_roles("FinanceManager")
def pay_claim(claim_id):
    c = get_claim_or_404(claim_id)
    if c["status"] != "APPROVED":
        raise ApiError(
            ERR_CLAIM_NOT_PAYABLE, "Only an APPROVED claim can be paid", 409
        )
    lease = STORE["leases"][c["lease_id"]]
    if lease["reserve_balance_cents"] < c["approved_amount_cents"]:
        raise ApiError(
            ERR_RESERVE_BALANCE_EXCEEDED,
            "Claim payment exceeds the lease reserve balance",
            422,
        )
    lease["reserve_reimbursed_cents"] += c["approved_amount_cents"]
    recompute_balance(lease)
    touch(lease)
    c["status"] = "PAID"
    touch(c)
    return success(c)


@bp.post("/leasing/reserve-claims/<claim_id>/reverse-payment")
@require_roles("FinanceManager")
def reverse_claim_payment(claim_id):
    c = get_claim_or_404(claim_id)
    if c["status"] != "PAID":
        raise invalid_state("Only a PAID claim can have its payment reversed")
    lease = STORE["leases"][c["lease_id"]]
    if lease["status"] in ("RETURNED", "CLOSED", "TERMINATED"):
        raise invalid_state(
            "Payment reversal is unavailable once the lease ledger is final"
        )
    lease["reserve_reimbursed_cents"] -= c["approved_amount_cents"]
    recompute_balance(lease)
    touch(lease)
    c["status"] = "APPROVED"
    touch(c)
    return success(c)

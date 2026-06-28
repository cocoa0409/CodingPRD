"""MedicaidClaim routes + payback waterfall."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from services.calc import medicaid_payback
from routes.common import get_body, find_or_404, require_int, paginate

bp = Blueprint("medicaid", __name__)


def _pending_approved(account_id):
    return sum(d["amount_cents"] for d in db.distributions.values()
               if d["account_id"] == account_id and d["status"] == "APPROVED")


@bp.post("/able/accounts/<aid>/medicaid-claims")
def file_claim(aid):
    _, role = get_identity()
    require_role(role, {"MedicaidAgency"})
    a = find_or_404(db.accounts, aid, "Account")
    body = get_body()
    claimed = require_int(body, "claimed_amount_cents")
    if claimed <= 0:
        raise err("ERR_INVALID_REQUEST", "claimed_amount_cents must be greater than zero")
    pending = _pending_approved(aid)
    allowed, residual = medicaid_payback(
        a["balance_cents"], pending, claimed, a["premiums_paid_by_beneficiary_cents"])
    m = {
        "account_id": aid,
        "claimed_amount_cents": claimed,
        "allowed_payback_cents": allowed,
        "residual_to_estate_cents": residual,
        "status": "FILED",
    }
    stamp_new(m)
    db.medicaid_claims[m["id"]] = m
    return created(domain.serialize_medicaid_claim(m))


@bp.get("/able/medicaid-claims/<mid>")
def get_claim(mid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator", "MedicaidAgency"})
    m = find_or_404(db.medicaid_claims, mid, "MedicaidClaim")
    return ok(domain.serialize_medicaid_claim(m))


@bp.get("/able/medicaid-claims")
def list_claims():
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator", "MedicaidAgency"})
    account_id = request.args.get("account_id")
    items = list(db.medicaid_claims.values())
    if account_id is not None:
        items = [m for m in items if m["account_id"] == account_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_medicaid_claim(m) for m in page],
                   limit, offset, total)


@bp.post("/able/accounts/<aid>/medicaid-claims/<mid>/settle")
def settle_claim(aid, mid):
    _, role = get_identity()
    require_role(role, {"ProgramAdministrator"})
    # left-to-right existence: account first, then claim
    a = find_or_404(db.accounts, aid, "Account")
    m = find_or_404(db.medicaid_claims, mid, "MedicaidClaim")
    if m["account_id"] != aid:
        raise err("ERR_NOT_FOUND", "MedicaidClaim not found on this account")
    # state: claim FILED and account FROZEN_DEATH (priority 6)
    if m["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim is not FILED")
    if a["status"] != "FROZEN_DEATH":
        raise err("ERR_INVALID_STATE", "Account is not FROZEN_DEATH")
    m["status"] = "SETTLED"
    touch(m)
    a["balance_cents"] -= m["allowed_payback_cents"]
    a["status"] = "CLOSED"
    touch(a)
    return ok(domain.serialize_medicaid_claim(m))

"""Escrow account, disbursement, and analysis routes."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
import response
from errors import (
    ApiError,
    ERR_CUSHION_OVERLIMIT,
    ERR_DISBURSEMENT_IN_PAST,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth
from services import calculations as calc
from services import transitions
from services.common import (
    bump,
    new_common_fields,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_iso_datetime,
    require_str,
    optional_int,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import (
    get_escrow_account,
    get_escrow_analysis,
    get_escrow_disbursement,
    get_fk_or_404,
    get_loan,
    borrower_owns_analysis,
    borrower_owns_disbursement,
    borrower_owns_escrow_account,
    borrower_owns_loan,
)

bp = Blueprint("escrow", __name__)


def _serialize(o: dict) -> dict:
    return strip_internal(o)


# ---------- POST /escrow-accounts ----------
@bp.post("/escrow-accounts")
@require_auth(roles=["LoanServicer"])
def create_account():
    body = get_json_body()
    loan_id = require_str(body, "loan_id")
    annual_tax_cents = require_int(body, "annual_tax_cents")
    annual_insurance_cents = require_int(body, "annual_insurance_cents")
    cushion_months = optional_int(body, "cushion_months")
    if cushion_months is None:
        cushion_months = 2

    # FK check
    loan = get_fk_or_404(db.loans, loan_id, name="Loan")

    if annual_tax_cents < 0 or annual_insurance_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Annual amounts must be >= 0.")

    if cushion_months < 0 or cushion_months > calc.MAX_CUSHION_MONTHS:
        raise ApiError(ERR_CUSHION_OVERLIMIT, "cushion_months must be in [0, 2].")

    with db.lock:
        # 1:1 with Loan: reject if one already exists
        existing = next((e for e in db.escrow_accounts.values() if e.get("loan_id") == loan_id), None)
        if existing is not None:
            raise ApiError(ERR_INVALID_STATE, "An escrow account already exists for this loan.")

        ea = new_common_fields()
        ea["loan_id"] = loan_id
        ea["balance_cents"] = 0
        ea["annual_tax_cents"] = annual_tax_cents
        ea["annual_insurance_cents"] = annual_insurance_cents
        ea["cushion_months"] = cushion_months
        ea["shortage_cents"] = 0
        ea["surplus_cents"] = 0
        db.escrow_accounts[ea["id"]] = ea

        # Side effects on the loan
        from decimal import Decimal
        new_monthly = calc.round_half_up(Decimal(annual_tax_cents + annual_insurance_cents) / Decimal(12))
        loan["escrow_monthly_cents"] = new_monthly
        transitions.recompute_total_monthly_payment(loan)
        bump(loan)

    return response.ok(_serialize(ea), status=201)


# ---------- GET /escrow-accounts/{id} ----------
@bp.get("/escrow-accounts/<eid>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_account(eid: str):
    ea = get_escrow_account(eid)
    if g.user_role == "Borrower" and not borrower_owns_escrow_account(ea, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this escrow account.")
    return response.ok(_serialize(ea))


# ---------- GET /escrow-accounts ----------
@bp.get("/escrow-accounts")
@require_auth(roles=["LoanServicer", "ComplianceOfficer"])
def list_accounts():
    limit, offset = parse_pagination()
    loan_id = request.args.get("loan_id")
    items = list(db.escrow_accounts.values())
    if loan_id is not None:
        items = [e for e in items if e.get("loan_id") == loan_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- POST /escrow-accounts/{id}/disbursements ----------
@bp.post("/escrow-accounts/<eid>/disbursements")
@require_auth(roles=["LoanServicer"])
def schedule_disbursement(eid: str):
    ea = get_escrow_account(eid)
    body = get_json_body()
    kind = require_enum(body, "kind", {"TAX", "INSURANCE"})
    amount_cents = require_int(body, "amount_cents")
    scheduled_for = require_iso_datetime(body, "scheduled_for")

    if amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be > 0.")

    now = db.utcnow()
    if scheduled_for <= now:
        raise ApiError(ERR_DISBURSEMENT_IN_PAST, "scheduled_for must be > current_utc.")

    with db.lock:
        d = new_common_fields()
        d["escrow_account_id"] = eid
        d["kind"] = kind
        d["amount_cents"] = amount_cents
        d["scheduled_for"] = db.fmt_ts(scheduled_for)
        d["status"] = "SCHEDULED"
        d["failure_reason"] = "NONE"
        d["paid_at"] = None
        db.escrow_disbursements[d["id"]] = d

    return response.ok(_serialize(d), status=201)


# ---------- GET /escrow-accounts/{id}/disbursements ----------
@bp.get("/escrow-accounts/<eid>/disbursements")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_disbursements(eid: str):
    ea = get_escrow_account(eid)
    if g.user_role == "Borrower" and not borrower_owns_escrow_account(ea, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this escrow account.")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [d for d in db.escrow_disbursements.values() if d.get("escrow_account_id") == eid]
    if status_filter:
        items = [d for d in items if d.get("status") == status_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- GET /escrow-disbursements/{id} ----------
@bp.get("/escrow-disbursements/<did>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_disbursement(did: str):
    d = get_escrow_disbursement(did)
    if g.user_role == "Borrower" and not borrower_owns_disbursement(d, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this disbursement.")
    return response.ok(_serialize(d))


# ---------- POST /escrow-disbursements/{id}/cancel ----------
@bp.post("/escrow-disbursements/<did>/cancel")
@require_auth(roles=["LoanServicer"])
def cancel_disbursement(did: str):
    d = get_escrow_disbursement(did)
    if d.get("status") != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Only SCHEDULED disbursements can be cancelled.")
    with db.lock:
        d["status"] = "CANCELLED"
        bump(d)
    return response.ok(_serialize(d))


# ---------- POST /escrow-accounts/{id}/analyses ----------
@bp.post("/escrow-accounts/<eid>/analyses")
@require_auth(roles=["LoanServicer"])
def run_analysis(eid: str):
    ea = get_escrow_account(eid)
    body = get_json_body()
    as_of_date = require_iso_datetime(body, "as_of_date")
    variant = require_enum(body, "variant", {"ACTUAL_TRAILING_12", "FORECAST_NEXT_12"})
    expected_version = require_int(body, "expected_escrow_account_version")

    # OCC check (priority 6)
    if expected_version != ea.get("version"):
        raise ApiError(ERR_STALE_VERSION, "expected_escrow_account_version does not match.")

    with db.lock:
        result = calc.escrow_analysis(ea, variant, as_of_date)
        a = new_common_fields()
        a["loan_id"] = ea.get("loan_id")
        a["as_of_date"] = db.fmt_ts(as_of_date)
        a["variant"] = variant
        a["projected_low_point_cents"] = result["projected_low_point_cents"]
        a["required_low_point_cents"] = result["required_low_point_cents"]
        a["shortage_cents"] = result["shortage_cents"]
        a["surplus_cents"] = result["surplus_cents"]
        a["new_escrow_monthly_cents"] = result["new_escrow_monthly_cents"]
        db.escrow_analyses[a["id"]] = a

        # Side effects: refresh ea shortage/surplus, set loan escrow_monthly_cents, bump versions
        ea["shortage_cents"] = result["shortage_cents"]
        ea["surplus_cents"] = result["surplus_cents"]
        bump(ea)

        loan = db.loans.get(ea.get("loan_id"))
        if loan is not None:
            loan["escrow_monthly_cents"] = result["new_escrow_monthly_cents"]
            transitions.recompute_total_monthly_payment(loan)
            bump(loan)

    return response.ok(_serialize(a), status=201)


# ---------- GET /escrow-accounts/{id}/analyses ----------
@bp.get("/escrow-accounts/<eid>/analyses")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_analyses_for_account(eid: str):
    ea = get_escrow_account(eid)
    if g.user_role == "Borrower" and not borrower_owns_escrow_account(ea, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this escrow account.")
    limit, offset = parse_pagination()
    items = [a for a in db.escrow_analyses.values() if a.get("loan_id") == ea.get("loan_id")]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- GET /escrow-analyses ----------
@bp.get("/escrow-analyses")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_analyses():
    limit, offset = parse_pagination()
    loan_id = request.args.get("loan_id")
    items = list(db.escrow_analyses.values())
    if loan_id is not None:
        items = [a for a in items if a.get("loan_id") == loan_id]
    if g.user_role == "Borrower":
        # Borrower must filter by own loan_id; only show analyses tied to own loans
        items = [a for a in items if borrower_owns_analysis(a, g.user_id)]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_serialize(x) for x in page], limit, offset, total)


# ---------- GET /escrow-analyses/{id} ----------
@bp.get("/escrow-analyses/<aid>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_analysis(aid: str):
    a = get_escrow_analysis(aid)
    if g.user_role == "Borrower" and not borrower_owns_analysis(a, g.user_id):
        raise ApiError(ERR_UNAUTHORIZED, "Borrower does not own this analysis.")
    return response.ok(_serialize(a))

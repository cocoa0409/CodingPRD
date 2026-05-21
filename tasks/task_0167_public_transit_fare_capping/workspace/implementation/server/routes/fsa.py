"""FSA: CommuterBenefitAccount, FSAContribution endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, now
from ..common import bump, check_occ, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import fsa_account_view, fsa_contribution_view
from ..store import gen_id, store


bp = Blueprint("fsa", __name__)


@bp.post("/transit/fsa-accounts")
@require_auth("EmployerAdmin")
def open_account():
    body = get_json_body()
    require_fields(body, "rider_id", "employer_id")
    rider_id = body["rider_id"]
    employer_id = body["employer_id"]

    with store.lock:
        if employer_id != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "employer_id must equal the calling EmployerAdmin's X-User-ID")
        if rider_id not in store.riders:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Rider not found")
        if employer_id not in store.employers:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Employer not found")
        emp = store.employers[employer_id]
        if emp.get("enrollment_status") == "TERMINATED":
            raise ApiError("ERR_INVALID_STATE", "Employer is TERMINATED")
        # One account per rider
        for acc in store.fsa_accounts.values():
            if acc.get("rider_id") == rider_id:
                raise ApiError("ERR_INVALID_STATE", "Rider already has an FSA account")
        account = {
            "rider_id": rider_id,
            "employer_id": employer_id,
            "balance_cents": 0,
            "status": "ACTIVE" if emp["enrollment_status"] == "ACTIVE" else "FROZEN",
        }
        stamp_new(account)
        store.fsa_accounts[account["id"]] = account
        # Set rider's employer_id link
        rider = store.riders[rider_id]
        rider["employer_id"] = employer_id
        bump(rider)
    return respond(fsa_account_view(account), 201)


@bp.post("/transit/fsa-contributions")
@require_auth("EmployerAdmin")
def post_contribution():
    body = get_json_body()
    require_fields(body, "account_id", "amount_cents", "contribution_month")
    account_id = body["account_id"]
    amount = positive_int(body["amount_cents"], "amount_cents")
    month = body["contribution_month"]
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise ApiError("ERR_VALIDATION", "contribution_month must be YYYY-MM")

    with store.lock:
        account = store.fsa_accounts.get(account_id)
        if account is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "FSA account not found")
        if account["employer_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Account is not owned by this employer")
        emp = store.employers.get(account["employer_id"])
        if emp is None or emp.get("enrollment_status") != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Employer is not ACTIVE")
        if account["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "FSA account is not ACTIVE")
        # Monthly cap enforcement
        cap = int(emp["monthly_contribution_cap_cents"])
        running = 0
        for c in store.fsa_contributions.values():
            if c.get("status") != "APPLIED":
                continue
            if c.get("contribution_month") != month:
                continue
            # All accounts under the same employer share the cap.
            acc_for = store.fsa_accounts.get(c["account_id"])
            if acc_for is None or acc_for.get("employer_id") != account["employer_id"]:
                continue
            running += int(c["amount_cents"])
        if running + amount > cap:
            raise ApiError("ERR_FSA_MONTHLY_CAP_EXCEEDED", "Monthly FSA cap exceeded")

        contrib = {
            "id": gen_id(),
            "account_id": account_id,
            "amount_cents": amount,
            "contribution_month": month,
            "status": "APPLIED",
            "created_at": iso_format(now()),
        }
        store.fsa_contributions[contrib["id"]] = contrib
        account["balance_cents"] = int(account["balance_cents"]) + amount
        bump(account)
    return respond(fsa_contribution_view(contrib), 201)


@bp.post("/transit/fsa-contributions/<contrib_id>/reverse")
@require_auth("EmployerAdmin")
def reverse_contribution(contrib_id: str):
    body = get_json_body()  # noqa: F841  — version not used on ledger entries
    with store.lock:
        original = store.fsa_contributions.get(contrib_id)
        if original is None:
            raise ApiError("ERR_NOT_FOUND", "FSAContribution not found")
        if original.get("status") != "APPLIED":
            raise ApiError("ERR_INVALID_STATE", "Contribution is not APPLIED")
        account = store.fsa_accounts.get(original["account_id"])
        if account is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "FSA account not found")
        if account["employer_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Account is not owned by this employer")
        original["status"] = "REVERSED"
        reversal = {
            "id": gen_id(),
            "account_id": original["account_id"],
            "amount_cents": -int(original["amount_cents"]),
            "contribution_month": original["contribution_month"],
            "status": "APPLIED",
            "created_at": iso_format(now()),
        }
        store.fsa_contributions[reversal["id"]] = reversal
        account["balance_cents"] = int(account["balance_cents"]) - int(original["amount_cents"])
        bump(account)
    return respond(fsa_contribution_view(reversal), 201)

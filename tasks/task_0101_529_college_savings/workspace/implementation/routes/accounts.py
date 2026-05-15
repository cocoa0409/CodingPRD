"""Account endpoints: create/get/list + restrict/release/close lifecycle."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import (
    require_body, require_field, require_state_code, parse_pagination,
)
from core.models import account_create, account_view, touch


bp = Blueprint("accounts", __name__)


def _check_donor_owns(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")


def _check_can_read_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")
    if g.user_role == "Beneficiary" and account["beneficiary_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Beneficiary may only read accounts they benefit from")


@bp.post("/accounts")
@require_roles("Donor")
def create_account():
    body = require_body(request)
    primary_donor_id = require_field(body, "primary_donor_id", kind="string")
    beneficiary_id = require_field(body, "beneficiary_id", kind="string")
    state_plan_code = require_state_code(body, "state_plan_code")

    with lock():
        donor = STORE.donors.get(primary_donor_id)
        if not donor:
            raise_error("ERR_NOT_FOUND", f"Donor {primary_donor_id} not found")
        ben = STORE.beneficiaries.get(beneficiary_id)
        if not ben:
            raise_error("ERR_NOT_FOUND", f"Beneficiary {beneficiary_id} not found")
        rule = STORE.state_rules.get(state_plan_code)
        if not rule:
            raise_error("ERR_NOT_FOUND", f"StateRule {state_plan_code} not found")
        # Donor must be opening the account on their own behalf.
        if primary_donor_id != g.user_id:
            raise_error("ERR_FORBIDDEN", "Donor may only open accounts as themselves")
        acct = account_create(primary_donor_id, beneficiary_id, state_plan_code, rule)
    return success_object(account_view(acct), 201)


@bp.get("/accounts/<aid>")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def get_account(aid):
    a = STORE.accounts.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
    _check_can_read_account(a)
    return success_object(account_view(a))


@bp.get("/accounts")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def list_accounts():
    limit, offset = parse_pagination(request)
    primary_donor_id = request.args.get("primary_donor_id")
    beneficiary_id = request.args.get("beneficiary_id")
    status = request.args.get("status")
    state_plan_code = request.args.get("state_plan_code")

    rows = list(STORE.accounts.values())
    if primary_donor_id is not None:
        rows = [r for r in rows if r["primary_donor_id"] == primary_donor_id]
    if beneficiary_id is not None:
        rows = [r for r in rows if r["beneficiary_id"] == beneficiary_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if state_plan_code is not None:
        rows = [r for r in rows if r["state_plan_code"] == state_plan_code]

    # Scope by role.
    if g.user_role == "Donor":
        rows = [r for r in rows if r["primary_donor_id"] == g.user_id]
    elif g.user_role == "Beneficiary":
        rows = [r for r in rows if r["beneficiary_id"] == g.user_id]

    rows.sort(key=lambda r: (r["_created_seq"], r["id"]))
    total = len(rows)
    page = [account_view(r) for r in rows[offset:offset + limit]]
    return success_array(page, limit, offset, total)


@bp.post("/accounts/<aid>/restrict")
@require_roles("PlanAdministrator")
def restrict_account(aid):
    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        if a["status"] != "OPEN":
            raise_error("ERR_INVALID_STATE",
                        f"Cannot restrict account in status {a['status']}")
        a["status"] = "RESTRICTED"
        touch(a)
        # Cascade: every ACTIVE RecurringPlan on this account becomes PAUSED.
        for plan in STORE.recurring_plans.values():
            if plan["account_id"] == aid and plan["status"] == "ACTIVE":
                plan["status"] = "PAUSED"
                touch(plan)
    return success_object(account_view(a))


@bp.post("/accounts/<aid>/release")
@require_roles("PlanAdministrator")
def release_account(aid):
    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        if a["status"] != "RESTRICTED":
            raise_error("ERR_INVALID_STATE",
                        f"Cannot release account in status {a['status']}")
        a["status"] = "OPEN"
        touch(a)
    return success_object(account_view(a))


@bp.post("/accounts/<aid>/close")
@require_roles("Donor")
def close_account(aid):
    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        _check_donor_owns(a)
        if a["status"] != "OPEN":
            raise_error("ERR_INVALID_STATE",
                        f"Cannot close account in status {a['status']}")
        if a["total_balance_cents"] != 0:
            raise_error("ERR_INVALID_STATE",
                        "Cannot close account with non-zero balance")
        for w in STORE.withdrawals.values():
            if w["account_id"] == aid and w["status"] in {"REQUESTED", "DISBURSED", "CLASSIFIED"}:
                raise_error("ERR_INVALID_STATE",
                            "Cannot close account with in-flight withdrawals")
        for bcr in STORE.beneficiary_change_requests.values():
            if bcr["account_id"] == aid and bcr["status"] == "SUBMITTED":
                raise_error("ERR_INVALID_STATE",
                            "Cannot close account with a pending beneficiary change request")
        a["status"] = "CLOSED"
        touch(a)
        # Cascade: every ACTIVE/PAUSED plan -> CANCELLED.
        for plan in STORE.recurring_plans.values():
            if plan["account_id"] == aid and plan["status"] in {"ACTIVE", "PAUSED"}:
                plan["status"] = "CANCELLED"
                touch(plan)
    return success_object(account_view(a))

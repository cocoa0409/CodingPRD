"""Accounts and money-source balances (PRD §3.2)."""

from flask import Blueprint, g, request

import errors
from db import create_entity, store
from middleware import ALL_ROLES, body, opt_int, paginate, req_str, require_roles
from response import ok, ok_list
from services import SOURCE_TYPES, serialize_account, serialize_msb, serialize_redeposit

bp = Blueprint("accounts", __name__)


def get_account_or_404(account_id, ownership_mask=True):
    a = store.accounts.get(account_id)
    if a is None:
        raise errors.err_account_not_found()
    if ownership_mask and g.role == "Participant" and a["participant_id"] != g.user_id:
        raise errors.err_account_not_found()
    return a


def _validate_initial_balances(data):
    raw = data.get("initial_balances")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise errors.err_validation("initial_balances must be a list")
    seen = set()
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise errors.err_validation("initial_balances entries must be objects")
        st = entry.get("source_type")
        if st not in SOURCE_TYPES:
            raise errors.err_validation("initial_balances.source_type must be one of %s" % sorted(SOURCE_TYPES))
        if st in seen:
            raise errors.err_validation("duplicate source_type in initial_balances: %s" % st)
        seen.add(st)
        balance = entry.get("balance_cents")
        if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
            raise errors.err_validation("balance_cents must be an integer >= 0")
        basis = entry.get("basis_cents", 0)
        if isinstance(basis, bool) or not isinstance(basis, int) or basis < 0:
            raise errors.err_validation("basis_cents must be an integer >= 0")
        if basis > 0 and basis > balance:
            raise errors.err_validation("basis_cents must not exceed balance_cents")
        vested_pct = entry.get("vested_pct", 100)
        if isinstance(vested_pct, bool) or not isinstance(vested_pct, int) or vested_pct < 0 or vested_pct > 100:
            raise errors.err_validation("vested_pct must be an integer in 0..100")
        if st != "EMPLOYER_PRETAX" and vested_pct != 100:
            raise errors.err_validation("non-employer sources are always vested at 100")
        out.append({"source_type": st, "balance_cents": balance, "basis_cents": basis, "vested_pct": vested_pct})
    return out


@bp.post("/v1/accounts")
@require_roles("PlanSponsorAdmin")
def create_account():
    data = body()
    participant_id = req_str(data, "participant_id")
    plan_id = req_str(data, "plan_id")
    balances = _validate_initial_balances(data)
    if participant_id not in store.participants:
        raise errors.err_participant_not_found()
    if plan_id not in store.plans:
        raise errors.err_plan_not_found()
    for a in store.accounts.values():
        if a["participant_id"] == participant_id and a["plan_id"] == plan_id:
            raise errors.err_account_already_exists()
    acct = create_entity(
        store.accounts,
        {"participant_id": participant_id, "plan_id": plan_id, "status": "ACTIVE"},
    )
    for b in balances:
        create_entity(
            store.msb,
            {
                "account_id": acct["id"],
                "source_type": b["source_type"],
                "balance_cents": b["balance_cents"],
                "basis_cents": b["basis_cents"],
                "vested_pct": b["vested_pct"],
            },
        )
    return ok(serialize_account(acct), status=201)


@bp.get("/v1/accounts")
@require_roles(*ALL_ROLES)
def list_accounts():
    rows = list(store.accounts.values())
    if g.role == "Participant":
        rows = [a for a in rows if a["participant_id"] == g.user_id]
    participant_id = request.args.get("participant_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    if participant_id is not None:
        rows = [a for a in rows if a["participant_id"] == participant_id]
    if plan_id is not None:
        rows = [a for a in rows if a["plan_id"] == plan_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: a["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_account(a) for a in page], total, limit, offset)


@bp.get("/v1/accounts/<account_id>")
@require_roles(*ALL_ROLES)
def get_account(account_id):
    return ok(serialize_account(get_account_or_404(account_id)))


@bp.get("/v1/accounts/<account_id>/source-balances")
@require_roles(*ALL_ROLES)
def list_source_balances(account_id):
    get_account_or_404(account_id)
    from services import msb_rows_of

    rows = msb_rows_of(account_id)
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_msb(r) for r in page], total, limit, offset)


@bp.get("/v1/accounts/<account_id>/redeposits")
@require_roles(*ALL_ROLES)
def list_account_redeposits(account_id):
    get_account_or_404(account_id)
    rows = [r for r in store.redeposits.values() if r["receiving_account_id"] == account_id]
    rows.sort(key=lambda r: r["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_redeposit(r) for r in page], total, limit, offset)

"""Disbursements endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_OPEN,
    ERR_ALREADY_TERMINAL,
    ERR_BUDGET_CATEGORY_EXCEEDED,
    ERR_BUDGET_PLAN_MISMATCH,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CLIENT_NOT_FOUND,
    ERR_CONSERVATOR_NOT_ACTIVE,
    ERR_COURT_ORDER_EXCEEDED,
    ERR_COURT_ORDER_NOT_FOUND,
    ERR_COURT_ORDER_NOT_GRANTABLE,
    ERR_COURT_ORDER_REQUIRED,
    ERR_DEDICATED_ACCOUNT_RESTRICTED,
    ERR_DISBURSEMENT_NOT_FOUND,
    ERR_INSUFFICIENT_FUNDS,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_BOND,
    ERR_PLAN_NOT_APPROVED,
    ERR_PLAN_NOT_FOUND,
    ERR_PLAN_PERIOD_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SPEND_DOWN_NOT_FOUND,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_disbursement
from services.calcs import compute_fiduciary_fee
from services.cascade import clock_now_iso, clock_date, clock_month_str
from services.derived import append_ledger, recompute_client_rollups, recompute_bond_rollups
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("disbursements", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
CATEGORIES = ("HOUSING", "FOOD", "CLOTHING", "PERSONAL", "MEDICAL", "EDUCATION", "SAVINGS")


@bp.route("/disbursements", methods=["POST"])
def create_disbursement():
    user_id, _ = require_roles("CaseManager")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "account_id", "budget_plan_id", "payee_name", "category",
        "amount_cents", "scheduled_release_date", "court_order_id", "spend_down_plan_id",
    })
    client_id = get_string(body, "client_id")
    account_id = get_string(body, "account_id")
    plan_id = get_string(body, "budget_plan_id")
    payee = get_string(body, "payee_name")
    category = get_enum(body, "category", CATEGORIES)
    amount = get_int(body, "amount_cents", min_value=1)
    sched = parse_date(get_string(body, "scheduled_release_date"), "scheduled_release_date")
    court_order_id = body.get("court_order_id")
    if court_order_id is not None and not isinstance(court_order_id, str):
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, 400, "court_order_id must be a string or null")
    spend_down_id = body.get("spend_down_plan_id")
    if spend_down_id is not None and not isinstance(spend_down_id, str):
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, 400, "spend_down_plan_id must be a string or null")

    # existence (declared field order: client_id, account_id, budget_plan_id, court_order_id, spend_down_plan_id)
    c = store.clients.get(client_id)
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    acct = store.accounts.get(account_id)
    if not acct:
        raise err(ERR_ACCOUNT_NOT_FOUND, 404, "account not found")
    plan = store.budget_plans.get(plan_id)
    if not plan:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan not found")
    if court_order_id is not None and court_order_id not in store.court_orders:
        raise err(ERR_COURT_ORDER_NOT_FOUND, 404, "court order not found")
    if spend_down_id is not None and spend_down_id not in store.spend_down_plans:
        raise err(ERR_SPEND_DOWN_NOT_FOUND, 404, "spend-down plan not found")

    # client-activity gate
    if c["status"] == "TERMINATED":
        raise err(ERR_CLIENT_NOT_ACTIVE, 409, "Client is TERMINATED")

    # business_safety ordering on create: court_order_required -> dedicated -> FK coherence
    if acct["account_type"] == "RESTRICTED" and not court_order_id:
        raise err(ERR_COURT_ORDER_REQUIRED, 422, "court_order_id required for RESTRICTED account")
    if acct["account_type"] == "DEDICATED" and category not in ("MEDICAL", "EDUCATION"):
        raise err(ERR_DEDICATED_ACCOUNT_RESTRICTED, 422, "DEDICATED accounts fund only MEDICAL/EDUCATION")

    # FK coherence: all referenced entities must belong to client_id
    if acct["client_id"] != client_id:
        raise err(ERR_BUDGET_PLAN_MISMATCH, 422, "account does not belong to client")
    if plan["client_id"] != client_id:
        raise err(ERR_BUDGET_PLAN_MISMATCH, 422, "budget plan does not belong to client")
    if court_order_id is not None:
        co = store.court_orders[court_order_id]
        if co["client_id"] != client_id:
            raise err(ERR_BUDGET_PLAN_MISMATCH, 422, "court order does not belong to client")
    if spend_down_id is not None:
        sp = store.spend_down_plans[spend_down_id]
        if sp["client_id"] != client_id:
            raise err(ERR_BUDGET_PLAN_MISMATCH, 422, "spend-down plan does not belong to client")

    now = clock_now_iso()
    did = new_id()
    d = {
        "id": did,
        "client_id": client_id,
        "account_id": account_id,
        "budget_plan_id": plan_id,
        "court_order_id": court_order_id,
        "spend_down_plan_id": spend_down_id,
        "payee_name": payee,
        "category": category,
        "amount_cents": amount,
        "scheduled_release_date": sched,
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "co_approved_by_conservator_id": None,
        "fee_cents": 0,
        "released_at": None,
        "returned_at": None,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.disbursements[did] = d
    return success_object(serialize_disbursement(d), status=201)


@bp.route("/disbursements", methods=["GET"])
def list_disbursements():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "client_id": request.args.get("client_id"),
        "account_id": request.args.get("account_id"),
        "budget_plan_id": request.args.get("budget_plan_id"),
        "court_order_id": request.args.get("court_order_id"),
        "spend_down_plan_id": request.args.get("spend_down_plan_id"),
        "co_approved_by_conservator_id": request.args.get("co_approved_by_conservator_id"),
        "status": request.args.get("status"),
        "category": request.args.get("category"),
    }
    items = list(store.disbursements.values())
    for k, v in filters.items():
        if v is None:
            continue
        items = [d for d in items if d.get(k) == v]
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_disbursement(d) for d in page], limit, offset, total)


def _get_or_404(did):
    d = store.disbursements.get(did)
    if not d:
        raise err(ERR_DISBURSEMENT_NOT_FOUND, 404, "disbursement not found")
    return d


@bp.route("/disbursements/<did>", methods=["GET"])
def get_disbursement(did):
    require_roles(*READ_ROLES)
    d = _get_or_404(did)
    return success_object(serialize_disbursement(d))


def _conservator_required(d):
    """Return True if some ACTIVE conservator of client requires co-approval."""
    for c in store.conservators.values():
        if c["client_id"] != d["client_id"]:
            continue
        if c["status"] != "ACTIVE":
            continue
        if c["authority_scope"] == "EXCLUSIVE":
            return True
        if c["authority_scope"] == "SHARED" and d["amount_cents"] >= 50000:
            return True
    return False


@bp.route("/disbursements/<did>/approve", methods=["POST"])
def approve_disbursement(did):
    user_id, _ = require_roles("FinancialOfficer")
    d = _get_or_404(did)
    if d["status"] in ("REJECTED", "RETURNED", "RELEASED"):
        # terminal states REJECTED, RETURNED -> ERR_ALREADY_TERMINAL; RELEASED isn't terminal but approve isn't valid
        if d["status"] in ("REJECTED", "RETURNED"):
            raise err(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
        raise err(ERR_INVALID_STATE, 409, "approve requires REQUESTED")
    if d["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, 409, "approve requires REQUESTED")
    if user_id == d.get("requested_by_user_id"):
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "Approver cannot equal requested_by_user_id")
    now = clock_now_iso()
    if _conservator_required(d):
        d["status"] = "PENDING_CONSERVATOR"
    else:
        d["status"] = "APPROVED"
    d["approved_by_user_id"] = user_id
    d["updated_at"] = now
    d["version"] += 1
    return success_object(serialize_disbursement(d))


@bp.route("/disbursements/<did>/co-approve", methods=["POST"])
def co_approve_disbursement(did):
    user_id, _ = require_roles("ConservatorOfficer")
    d = _get_or_404(did)
    if d["status"] in ("REJECTED", "RETURNED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "PENDING_CONSERVATOR":
        raise err(ERR_INVALID_STATE, 409, "co-approve requires PENDING_CONSERVATOR")
    # X-User-ID must equal id of an ACTIVE Conservator of this client
    cons = store.conservators.get(user_id)
    if not cons or cons["client_id"] != d["client_id"] or cons["status"] != "ACTIVE":
        raise err(ERR_CONSERVATOR_NOT_ACTIVE, 422, "Not an ACTIVE conservator of this client")
    now = clock_now_iso()
    d["status"] = "APPROVED"
    d["co_approved_by_conservator_id"] = user_id
    d["updated_at"] = now
    d["version"] += 1
    return success_object(serialize_disbursement(d))


@bp.route("/disbursements/<did>/reject", methods=["POST"])
def reject_disbursement(did):
    require_roles("FinancialOfficer")
    d = _get_or_404(did)
    if d["status"] in ("REJECTED", "RETURNED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] not in ("REQUESTED", "PENDING_CONSERVATOR"):
        raise err(ERR_INVALID_STATE, 409, "reject requires REQUESTED or PENDING_CONSERVATOR")
    now = clock_now_iso()
    d["status"] = "REJECTED"
    d["updated_at"] = now
    d["version"] += 1
    return success_object(serialize_disbursement(d))


@bp.route("/disbursements/<did>/release", methods=["POST"])
def release_disbursement(did):
    require_roles("FinancialOfficer")
    d = _get_or_404(did)
    if d["status"] in ("REJECTED", "RETURNED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, 409, "release requires APPROVED")

    acct = store.accounts[d["account_id"]]
    plan = store.budget_plans[d["budget_plan_id"]]
    clock_dt_date = clock_date()
    clock_month = clock_month_str()

    # 1) Court order grantability (restricted accounts)
    court_order = None
    if acct["account_type"] == "RESTRICTED":
        cid = d.get("court_order_id")
        if not cid:
            raise err(ERR_COURT_ORDER_NOT_GRANTABLE, 422, "court_order_id required")
        court_order = store.court_orders.get(cid)
        if not court_order:
            raise err(ERR_COURT_ORDER_NOT_GRANTABLE, 422, "court order not found")
        if court_order["status"] != "GRANTED":
            raise err(ERR_COURT_ORDER_NOT_GRANTABLE, 422, "order not GRANTED")
        if court_order["client_id"] != d["client_id"]:
            raise err(ERR_COURT_ORDER_NOT_GRANTABLE, 422, "order client mismatch")
        if court_order["order_type"] != "RESTRICTED_WITHDRAWAL":
            raise err(ERR_COURT_ORDER_NOT_GRANTABLE, 422, "wrong order_type")
        if clock_dt_date > court_order["expiry_date"]:
            raise err(ERR_COURT_ORDER_NOT_GRANTABLE, 422, "order expired")

    # 2) Court order amount cap
    if court_order is not None:
        if d["amount_cents"] > court_order.get("amount_limit_cents", 0):
            raise err(ERR_COURT_ORDER_EXCEEDED, 422, "amount exceeds order limit")

    # 3) Dedicated account category
    if acct["account_type"] == "DEDICATED" and d["category"] not in ("MEDICAL", "EDUCATION"):
        raise err(ERR_DEDICATED_ACCOUNT_RESTRICTED, 422, "DEDICATED accounts fund only MEDICAL/EDUCATION")

    # 4) Plan period == clock month
    if plan["period_month"] != clock_month:
        raise err(ERR_PLAN_PERIOD_MISMATCH, 422, "plan period_month != current clock month")

    # 5) Plan APPROVED
    if plan["status"] != "APPROVED":
        raise err(ERR_PLAN_NOT_APPROVED, 409, "Plan must be APPROVED")

    # 6) Sufficient funds
    if acct["balance_cents"] < d["amount_cents"]:
        raise err(ERR_INSUFFICIENT_FUNDS, 422, "insufficient funds")

    # 7) Category remaining
    allocated = next(
        (l for l in plan["allocated_lines"] if l["category"] == d["category"]),
        None,
    )
    allocated_amt = allocated["amount_cents"] if allocated else 0
    used = 0
    for other in store.disbursements.values():
        if other["budget_plan_id"] != plan["id"]:
            continue
        if other["category"] != d["category"]:
            continue
        if other["status"] == "RELEASED":
            used += other["amount_cents"]
        # "RELEASED non-RETURNED" — RETURNED means status==RETURNED, excluded
    if d["amount_cents"] > (allocated_amt - used):
        raise err(ERR_BUDGET_CATEGORY_EXCEEDED, 422, "category remaining exceeded")

    # 8) Active bond
    has_active_bond = any(b["status"] == "ACTIVE" for b in store.bonds.values())
    if not has_active_bond:
        raise err(ERR_NO_ACTIVE_BOND, 409, "no ACTIVE SuretyBond")

    # Account must be OPEN — also required
    if acct["status"] != "OPEN":
        raise err(ERR_ACCOUNT_NOT_OPEN, 409, "account not OPEN")

    # do release
    now = clock_now_iso()
    d["released_at"] = now
    fee = compute_fiduciary_fee(d["client_id"], d["amount_cents"], store.clock)
    d["fee_cents"] = fee
    d["status"] = "RELEASED"
    d["updated_at"] = now
    d["version"] += 1

    append_ledger(d["account_id"], "DISBURSEMENT_RELEASED", -d["amount_cents"], d["id"], now)
    recompute_client_rollups(d["client_id"])
    recompute_bond_rollups()

    # consume court order on restricted
    if acct["account_type"] == "RESTRICTED" and court_order is not None:
        court_order["status"] = "EXECUTED"
        court_order["executed_disbursement_id"] = d["id"]
        court_order["updated_at"] = now
        court_order["version"] += 1

    return success_object(serialize_disbursement(d))


@bp.route("/disbursements/<did>/return", methods=["POST"])
def return_disbursement(did):
    require_roles("FinancialOfficer")
    d = _get_or_404(did)
    if d["status"] in ("REJECTED", "RETURNED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Disbursement is terminal")
    if d["status"] != "RELEASED":
        raise err(ERR_INVALID_STATE, 409, "return requires RELEASED")
    now = clock_now_iso()
    d["status"] = "RETURNED"
    d["returned_at"] = now
    d["updated_at"] = now
    d["version"] += 1
    append_ledger(d["account_id"], "DISBURSEMENT_RETURNED", d["amount_cents"], d["id"], now)
    recompute_client_rollups(d["client_id"])
    recompute_bond_rollups()
    return success_object(serialize_disbursement(d))

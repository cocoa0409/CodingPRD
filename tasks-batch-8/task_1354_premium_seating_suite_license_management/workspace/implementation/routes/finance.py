"""Routes: accounts, license agreements, invoices, payments."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import db
import errors
import domain
from auth import require_roles, get_or_404, resolve_fk, check_scope, is_holder, ALL_ROLES
from domain import (pub_account, pub_agreement, pub_invoice, pub_payment, now)
from response import success, success_list
from util import body, req_str, req_int, req_enum, req_dt, paginate, req_present, rhu

bp = Blueprint("finance", __name__)

ACCOUNT_TYPES = ("CORPORATE", "INDIVIDUAL", "BROKER")
PAYMENT_METHODS = ("ACH", "CARD", "WIRE")


# ---------------------------------------------------------------- accounts
@bp.post("/api/accounts")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def create_account():
    data = body()
    legal_name = req_str(data, "legal_name")
    account_type = req_enum(data, "account_type", ACCOUNT_TYPES)
    tax_id = req_str(data, "tax_id")
    billing_email = req_str(data, "billing_email")
    for a in db.all_of("accounts"):
        if a["tax_id"] == tax_id:
            raise errors.err_invalid_request("tax_id must be unique across all accounts")
    acc = db.new_entity({
        "legal_name": legal_name,
        "account_type": account_type,
        "tax_id": tax_id,
        "billing_email": billing_email,
        "status": "PROSPECT",
    })
    db.insert("accounts", acc)
    return success(pub_account(acc), status=201)


@bp.get("/api/accounts/<aid>")
@require_roles(*ALL_ROLES)
def get_account(aid):
    acc = get_or_404("accounts", aid)
    check_scope(acc["id"])
    return success(pub_account(acc))


@bp.get("/api/accounts")
@require_roles(*ALL_ROLES)
def list_accounts():
    items = list(db.all_of("accounts"))
    if is_holder():
        items = [a for a in items if a["id"] == g.user_id]
    status = request.args.get("status")
    account_type = request.args.get("account_type")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if account_type is not None:
        items = [a for a in items if a["account_type"] == account_type]
    page, meta = paginate(items, pub_account)
    return success_list(page, meta)


@bp.patch("/api/accounts/<aid>")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def patch_account(aid):
    acc = get_or_404("accounts", aid)
    data = body()
    expected = data.get("expected_account_version")
    if expected is None:
        raise errors.err_invalid_request("expected_account_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_account_version must be an integer")
    new_tax = data.get("tax_id")
    if new_tax is not None:
        if not isinstance(new_tax, str) or new_tax == "":
            raise errors.err_invalid_request("tax_id must be a non-empty string")
        for a in db.all_of("accounts"):
            if a["id"] != aid and a["tax_id"] == new_tax:
                raise errors.err_invalid_request("tax_id must be unique across all accounts")
    if "legal_name" in data and data["legal_name"] is not None and not isinstance(data["legal_name"], str):
        raise errors.err_invalid_request("legal_name must be a string")
    if "billing_email" in data and data["billing_email"] is not None and not isinstance(data["billing_email"], str):
        raise errors.err_invalid_request("billing_email must be a string")
    if expected != acc["version"]:
        raise errors.err_stale_version()
    if new_tax is not None:
        acc["tax_id"] = new_tax
    if data.get("legal_name") is not None:
        acc["legal_name"] = data["legal_name"]
    if data.get("billing_email") is not None:
        acc["billing_email"] = data["billing_email"]
    db.touch(acc)
    return success(pub_account(acc))


@bp.post("/api/accounts/<aid>/set_status")
@require_roles("FinanceController", "PremiumSalesRep", "StadiumAdmin")
def account_set_status(aid):
    acc = get_or_404("accounts", aid)
    data = body()
    target = data.get("target_status")
    if target not in ("PROSPECT", "ACTIVE", "SUSPENDED"):
        raise errors.err_invalid_request("target_status must be an account status")
    cur = acc["status"]
    if g.role == "PremiumSalesRep" and not (cur == "PROSPECT" and target == "ACTIVE"):
        # reps may only activate prospects; suspend/reinstate are finance functions
        raise errors.err_forbidden("PremiumSalesRep may only drive PROSPECT -> ACTIVE")
    if cur == "PROSPECT" and target == "ACTIVE":
        acc["status"] = "ACTIVE"
        db.touch(acc)
    elif cur == "ACTIVE" and target == "SUSPENDED":
        domain.suspend_account(acc, "ADMINISTRATIVE")
    elif cur == "SUSPENDED" and target == "ACTIVE":
        if domain.account_credit_standing(aid) != "GOOD":
            raise errors.err_credit_hold("manual reinstate requires GOOD credit standing")
        domain.reinstate_account(acc)
    else:
        raise errors.err_invalid_state()
    return success(pub_account(acc))


# ---------------------------------------------------------------- agreements
@bp.post("/api/agreements")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def create_agreement():
    data = body()
    suite = resolve_fk("suites", data.get("suite_id"))
    acc = resolve_fk("accounts", data.get("account_id"))
    season = resolve_fk("seasons", data.get("start_season_id"))
    term = req_int(data, "term_seasons", minimum=1, maximum=10)
    base_fee = req_int(data, "base_annual_fee_cents", minimum=0)
    esc = req_int(data, "escalator_bp", minimum=0, maximum=2000)
    fb_min = req_int(data, "f_b_minimum_cents", minimum=0)
    agr = db.new_entity({
        "suite_id": suite["id"],
        "account_id": acc["id"],
        "start_season_id": season["id"],
        "term_seasons": term,
        "base_annual_fee_cents": base_fee,
        "escalator_bp": esc,
        "f_b_minimum_cents": fb_min,
        "executed_on": None,
        "fee_schedule_cents": [],
        "suspension_reason": None,
        "suspension_count": 0,
        "renewal_agreement_id": None,
        "active_sublease_account_id": None,
        "status": "DRAFT",
    })
    db.insert("agreements", agr)
    return success(pub_agreement(agr), status=201)


def _get_agreement_scoped(aid):
    agr = get_or_404("agreements", aid)
    check_scope(agr["account_id"])
    return agr


@bp.get("/api/agreements/<aid>")
@require_roles(*ALL_ROLES)
def get_agreement(aid):
    return success(pub_agreement(_get_agreement_scoped(aid)))


@bp.get("/api/agreements")
@require_roles(*ALL_ROLES)
def list_agreements():
    items = list(db.all_of("agreements"))
    if is_holder():
        items = [a for a in items if a["account_id"] == g.user_id]
    for param in ("suite_id", "account_id", "start_season_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    page, meta = paginate(items, pub_agreement)
    return success_list(page, meta)


@bp.post("/api/agreements/<aid>/submit")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def submit_agreement(aid):
    agr = get_or_404("agreements", aid)
    if agr["status"] != "DRAFT":
        raise errors.err_invalid_state()
    agr["status"] = "PENDING_EXECUTION"
    db.touch(agr)
    return success(pub_agreement(agr))


@bp.post("/api/agreements/<aid>/execute")
@require_roles("AccountHolder")
def execute_agreement(aid):
    agr = get_or_404("agreements", aid)
    check_scope(agr["account_id"])
    if agr["status"] != "PENDING_EXECUTION":
        raise errors.err_invalid_state()
    acc = db.get("accounts", agr["account_id"])
    suite = db.get("suites", agr["suite_id"])
    season = db.get("seasons", agr["start_season_id"])
    # gate 8(i): account guard
    if acc["status"] == "SUSPENDED":
        raise errors.err_account_suspended()
    if acc["status"] != "ACTIVE":
        raise errors.err_invalid_state("a PROSPECT account was never eligible to sign")
    # gate 9: season lock (start season must be PUBLISHED, not SETTLED/DRAFT)
    if season is None or season["status"] != "PUBLISHED":
        raise errors.err_season_locked()
    # gates 14/15: suite status then overlap exclusivity
    if suite["status"] == "OUT_OF_SERVICE":
        raise errors.err_suite_not_available()
    if suite["status"] == "LICENSED":
        raise errors.err_suite_already_licensed()
    my_coverage = set(domain.covered_season_ids(agr))
    for other in db.all_of("agreements"):
        if other["id"] == agr["id"] or other["suite_id"] != suite["id"]:
            continue
        if other["status"] in ("PENDING_EXECUTION", "ACTIVE", "SUSPENDED", "EXPIRING"):
            if set(domain.covered_season_ids(other)) & my_coverage:
                raise errors.err_suite_already_licensed()
    # gate 23: credit gate
    if domain.account_credit_standing(acc["id"]) == "HOLD":
        raise errors.err_credit_hold()
    clock = now()
    agr["executed_on"] = clock
    agr["fee_schedule_cents"] = domain.fee_schedule(
        agr["base_annual_fee_cents"], agr["escalator_bp"], agr["term_seasons"])
    agr["status"] = "ACTIVE"
    db.touch(agr)
    # season-1 LICENSE_FEE invoice, prorated when executing after season start
    first_fee = agr["fee_schedule_cents"][0]
    amount = first_fee
    if clock > season["starts_on"]:
        ratio = domain.proration_ratio(season["id"], clock)
        if ratio is not None:
            amount = rhu(Decimal(first_fee) * ratio)
    domain.create_auto_invoice(
        account_id=acc["id"], invoice_type="LICENSE_FEE", amount_cents=amount,
        description="Season 1 license fee", due_on=clock + timedelta(days=30),
        agreement_id=agr["id"], season_id=season["id"])
    suite["status"] = "LICENSED"
    suite["current_agreement_id"] = agr["id"]
    db.touch(suite)
    return success(pub_agreement(agr))


@bp.post("/api/agreements/<aid>/terminate")
@require_roles("PremiumSalesRep", "StadiumAdmin")
def terminate_agreement(aid):
    agr = get_or_404("agreements", aid)
    cur = agr["status"]
    if cur in ("DRAFT", "PENDING_EXECUTION"):
        agr["status"] = "WITHDRAWN"
        db.touch(agr)
        return success(pub_agreement(agr))
    if cur not in ("ACTIVE", "SUSPENDED"):
        raise errors.err_invalid_state()
    # gate 23: no open invoices on this agreement
    for inv in db.all_of("invoices"):
        if inv.get("agreement_id") == aid and inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
            raise errors.err_unsettled_balance("agreement has open invoices")
    idx = domain.current_season_index(agr)
    schedule = agr.get("fee_schedule_cents") or []
    cur_fee = schedule[idx - 1] if 0 < idx <= len(schedule) else 0
    remaining_after = sum(schedule[idx:]) if idx < len(schedule) else 0
    fee = max(2 * cur_fee, rhu(Decimal("0.5") * remaining_after))
    clock = now()
    domain.create_auto_invoice(
        account_id=agr["account_id"], invoice_type="TERMINATION_FEE", amount_cents=fee,
        description="Early termination fee", due_on=clock + timedelta(days=30),
        agreement_id=agr["id"])
    agr["status"] = "TERMINATED"
    agr["suspension_reason"] = None
    db.touch(agr)
    domain.release_suite(agr)
    return success(pub_agreement(agr))


@bp.post("/api/agreements/<aid>/cure")
@require_roles("FinanceController", "StadiumAdmin")
def cure_agreement(aid):
    agr = get_or_404("agreements", aid)
    if agr["status"] != "SUSPENDED":
        raise errors.err_invalid_state()
    acc = db.get("accounts", agr["account_id"])
    if acc is None or acc["status"] != "ACTIVE":
        raise errors.err_account_suspended()
    clock = now()
    for inv in db.all_of("invoices"):
        if inv.get("agreement_id") == aid and inv["status"] in ("ISSUED", "PARTIALLY_PAID") \
                and inv.get("due_on") is not None and inv["due_on"] < clock:
            raise errors.err_unsettled_balance("agreement has past-due invoices")
    agr["status"] = "ACTIVE"
    agr["suspension_reason"] = None
    db.touch(agr)
    return success(pub_agreement(agr))


# ---------------------------------------------------------------- invoices
def _validate_lines(lines):
    if not isinstance(lines, list):
        raise errors.err_invalid_request("lines must be a list")
    for ln in lines:
        if not isinstance(ln, dict):
            raise errors.err_invalid_request("each line must be an object")
        if "description" not in ln or not isinstance(ln["description"], str):
            raise errors.err_invalid_request("line description is required")
        q = ln.get("quantity")
        if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
            raise errors.err_invalid_request("line quantity must be a positive integer")
        p = ln.get("unit_price_cents")
        if not isinstance(p, int) or isinstance(p, bool) or p < 0:
            raise errors.err_invalid_request("line unit_price_cents must be a non-negative integer")


@bp.post("/api/invoices")
@require_roles("FinanceController", "StadiumAdmin")
def create_invoice():
    data = body()
    acc = resolve_fk("accounts", data.get("account_id"))
    agreement_id = data.get("agreement_id")
    if agreement_id is not None:
        resolve_fk("agreements", agreement_id)
    season_id = data.get("season_id")
    if season_id is not None:
        resolve_fk("seasons", season_id)
    lines = req_present(data, "lines")
    _validate_lines(lines)
    due_on = req_dt(data, "due_on")
    subtotal = sum(ln["quantity"] * ln["unit_price_cents"] for ln in lines)
    inv = db.new_entity({
        "account_id": acc["id"],
        "agreement_id": agreement_id,
        "rental_id": None,
        "assessment_id": None,
        "season_id": season_id,
        "invoice_type": "MANUAL",
        "lines": lines,
        "subtotal_cents": subtotal,
        "amount_paid_cents": 0,
        "due_on": due_on,
        "issued_at": None,
        "status": "DRAFT",
    })
    db.insert("invoices", inv)
    return success(pub_invoice(inv), status=201)


def _get_invoice_scoped(iid):
    inv = get_or_404("invoices", iid)
    check_scope(inv["account_id"])
    return inv


@bp.get("/api/invoices/<iid>")
@require_roles(*ALL_ROLES)
def get_invoice(iid):
    return success(pub_invoice(_get_invoice_scoped(iid)))


@bp.get("/api/invoices")
@require_roles(*ALL_ROLES)
def list_invoices():
    items = list(db.all_of("invoices"))
    if is_holder():
        items = [i for i in items if i["account_id"] == g.user_id]
    for param in ("account_id", "agreement_id", "rental_id", "assessment_id",
                  "season_id", "invoice_type", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    page, meta = paginate(items, pub_invoice)
    return success_list(page, meta)


@bp.post("/api/invoices/<iid>/issue")
@require_roles("FinanceController", "StadiumAdmin")
def issue_invoice(iid):
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise errors.err_invalid_state()
    if not inv["lines"]:
        raise errors.err_invalid_request("cannot issue an invoice with no lines")
    inv["issued_at"] = now()
    inv["status"] = "ISSUED"
    db.touch(inv)
    acc = db.get("accounts", inv["account_id"])
    if acc is not None:
        db.touch(acc)
    return success(pub_invoice(inv))


@bp.post("/api/invoices/<iid>/void")
@require_roles("FinanceController", "StadiumAdmin")
def void_invoice(iid):
    inv = get_or_404("invoices", iid)
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise errors.err_invalid_state()
    if inv["status"] == "ISSUED":
        # gate 9: season lock precedes gate 22 fiscal referential guard
        if inv.get("season_id"):
            season = db.get("seasons", inv["season_id"])
            if season is not None and season["status"] == "SETTLED":
                raise errors.err_season_locked()
        for p in db.all_of("payments"):
            if p["status"] in ("INITIATED", "CLEARED") and \
                    any(a["invoice_id"] == iid for a in p["allocations"]):
                raise errors.err_invoice_has_payments()
    inv["status"] = "VOID"
    db.touch(inv)
    acc = db.get("accounts", inv["account_id"])
    if acc is not None:
        db.touch(acc)
    domain.maybe_settle_assessment(inv)
    return success(pub_invoice(inv))


# ---------------------------------------------------------------- payments
@bp.post("/api/payments")
@require_roles("AccountHolder", "FinanceController", "StadiumAdmin")
def create_payment():
    data = body()
    acc = resolve_fk("accounts", data.get("account_id"))
    check_scope(acc["id"])
    amount = req_int(data, "amount_cents", minimum=1)
    method = req_enum(data, "method", PAYMENT_METHODS)
    allocations = req_present(data, "allocations")
    if not isinstance(allocations, list) or not allocations:
        raise errors.err_invalid_request("allocations must be a non-empty list")
    resolved = []
    for alloc in allocations:
        if not isinstance(alloc, dict):
            raise errors.err_invalid_request("each allocation must be an object")
        inv = resolve_fk("invoices", alloc.get("invoice_id"))
        amt = alloc.get("amount_cents")
        if not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
            raise errors.err_invalid_request("allocation amount_cents must be a positive integer")
        resolved.append((inv, amt))
    if sum(a for _, a in resolved) != amount:
        raise errors.err_invalid_request("amount_cents must equal the sum of allocations")
    for inv, amt in resolved:
        if inv["account_id"] != acc["id"]:
            raise errors.err_allocation_mismatch()
        if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            raise errors.err_invalid_request("allocated invoices must be ISSUED or PARTIALLY_PAID")
        if amt > domain.amount_due_cents(inv):
            raise errors.err_allocation_exceeds()
    payment = db.new_entity({
        "account_id": acc["id"],
        "amount_cents": amount,
        "method": method,
        "allocations": [{"invoice_id": inv["id"], "amount_cents": amt} for inv, amt in resolved],
        "status": "INITIATED",
    })
    db.insert("payments", payment)
    return success(pub_payment(payment), status=201)


def _get_payment_scoped(pid):
    p = get_or_404("payments", pid)
    check_scope(p["account_id"])
    return p


@bp.get("/api/payments/<pid>")
@require_roles(*ALL_ROLES)
def get_payment(pid):
    return success(pub_payment(_get_payment_scoped(pid)))


@bp.get("/api/payments")
@require_roles(*ALL_ROLES)
def list_payments():
    items = list(db.all_of("payments"))
    if is_holder():
        items = [p for p in items if p["account_id"] == g.user_id]
    for param in ("account_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p.get(param) == v]
    page, meta = paginate(items, pub_payment)
    return success_list(page, meta)


@bp.post("/api/payments/<pid>/set_status")
@require_roles("FinanceController", "StadiumAdmin")
def payment_set_status(pid):
    payment = get_or_404("payments", pid)
    target = body().get("target_status")
    if target not in ("INITIATED", "CLEARED", "FAILED", "REFUNDED"):
        raise errors.err_invalid_request("target_status must be a payment status")
    cur = payment["status"]
    if cur == "INITIATED" and target == "CLEARED":
        payment["status"] = "CLEARED"
        db.touch(payment)
        domain.payment_clear(payment)
    elif cur == "INITIATED" and target == "FAILED":
        payment["status"] = "FAILED"
        db.touch(payment)
    elif cur == "CLEARED" and target == "REFUNDED":
        payment["status"] = "REFUNDED"
        db.touch(payment)
        domain.payment_refund(payment)
    else:
        raise errors.err_invalid_state()
    return success(pub_payment(payment))

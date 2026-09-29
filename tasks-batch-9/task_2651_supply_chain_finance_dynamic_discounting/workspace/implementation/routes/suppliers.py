"""Supplier onboarding, identity verification and bank account endpoints
(PRD 3.2).  The supplier row carries two parallel axes -- identity and bank --
that join into ACTIVE.
"""

from flask import Blueprint

from db import base_row, clock, db, public, put_dt, sorted_rows, touch
from errors import ApiError
from middleware import (BUYER_ADMIN, BUYER_TREASURY, PLATFORM_OPS, SUPPLIER,
                        authenticate, get_bank_account, get_supplier,
                        scope_supplier)
from response import ok, ok_list
from services import calc, flows
from services import guards as g
from services import recompute as rc
from validation import (body, filter_arg, opt_int, opt_str, paginate,
                        pagination, req_bool, req_digits, req_enum, req_str)

bp = Blueprint("suppliers", __name__)

DISPLACEABLE = ("MICRO_DEPOSIT_SENT", "VERIFIED", "FAILED")


@bp.post("/suppliers")
def create_supplier():
    authenticate((PLATFORM_OPS,))
    b = body()
    legal_name = req_str(b, "legal_name", 1, 200)
    tax_id_last4 = req_digits(b, "tax_id_last4", 4)
    remittance_email = opt_str(b, "remittance_email", 1, 320)
    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "tax_id_last4": tax_id_last4,
            "remittance_email": remittance_email,
            "onboarding_status": "DRAFT",
            "idv_status": "NOT_STARTED",
            "bank_status": "NOT_STARTED",
            "identity_score": 0,
            "sanctions_hold": False,
            "verified_account_last4": None,
        }
    )
    put_dt(row, "idv_verified_at", None)
    put_dt(row, "payment_ready_at", None)
    db.suppliers[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/suppliers/<supplier_id>")
def read_supplier(supplier_id):
    ctx = authenticate((PLATFORM_OPS, SUPPLIER, BUYER_ADMIN, BUYER_TREASURY))
    supplier = get_supplier(supplier_id)
    scope_supplier(ctx, supplier["id"])
    return ok(public(supplier))


@bp.post("/suppliers/<supplier_id>/onboarding/submit")
def submit_onboarding(supplier_id):
    ctx = authenticate((SUPPLIER, PLATFORM_OPS))
    supplier = get_supplier(supplier_id)
    scope_supplier(ctx, supplier["id"])
    if supplier["onboarding_status"] != "DRAFT":
        g.invalid_state("Only a DRAFT supplier can submit onboarding.")
    g.require_no_sanctions_hold(supplier)
    supplier["onboarding_status"] = "VERIFYING"
    supplier["idv_status"] = "PENDING"
    touch(supplier)
    return ok(public(supplier))


@bp.post("/suppliers/<supplier_id>/idv/adjudicate")
def adjudicate_idv(supplier_id):
    authenticate((PLATFORM_OPS,))
    b = body()
    decision = req_enum(b, "decision", ("PASSED", "MANUAL_REVIEW", "FAILED"))
    identity_score = opt_int(b, "identity_score", 0, 100)
    supplier = get_supplier(supplier_id)
    if supplier["onboarding_status"] != "VERIFYING":
        g.invalid_state("The supplier is not VERIFYING.")
    if supplier["idv_status"] not in ("PENDING", "MANUAL_REVIEW"):
        g.invalid_state("Identity verification is not awaiting adjudication.")

    if identity_score is not None:
        supplier["identity_score"] = identity_score

    if decision == "PASSED":
        supplier["idv_status"] = "PASSED"
        put_dt(supplier, "idv_verified_at", clock())
        flows.supplier_join(supplier)
        touch(supplier)
    elif decision == "MANUAL_REVIEW":
        supplier["idv_status"] = "MANUAL_REVIEW"
        touch(supplier)
    else:
        supplier["idv_status"] = "FAILED"
        supplier["onboarding_status"] = "REJECTED"
        supplier["bank_status"] = "FAILED"
        touch(supplier)
        for account in rc.supplier_bank_accounts(supplier["id"]):
            if account["status"] != "REPLACED" and account["status"] != "FAILED":
                account["status"] = "FAILED"
                touch(account)
    return ok(public(supplier))


@bp.post("/suppliers/<supplier_id>/sanctions-hold")
def sanctions_hold(supplier_id):
    authenticate((PLATFORM_OPS,))
    b = body()
    hold = req_bool(b, "hold")
    supplier = get_supplier(supplier_id)
    if hold:
        if supplier["onboarding_status"] not in ("DRAFT", "VERIFYING", "ACTIVE"):
            g.invalid_state("A hold can only be applied from DRAFT, VERIFYING or ACTIVE.")
        supplier["sanctions_hold"] = True
        supplier["onboarding_status"] = "SUSPENDED"
    else:
        if supplier["onboarding_status"] != "SUSPENDED":
            g.invalid_state("Only a SUSPENDED supplier can be released.")
        supplier["sanctions_hold"] = False
        if supplier["idv_status"] == "PASSED" and supplier["bank_status"] == "VERIFIED":
            supplier["onboarding_status"] = "ACTIVE"
            if supplier.get("_payment_ready_at") is None:
                put_dt(supplier, "payment_ready_at", clock())
        else:
            supplier["onboarding_status"] = "VERIFYING"
    touch(supplier)
    return ok(public(supplier))


@bp.post("/suppliers/<supplier_id>/bank-accounts")
def create_bank_account(supplier_id):
    ctx = authenticate((SUPPLIER, PLATFORM_OPS))
    b = body()
    routing_number = req_digits(b, "routing_number", 9)
    account_last4 = req_digits(b, "account_last4", 4)
    supplier = get_supplier(supplier_id)
    scope_supplier(ctx, supplier["id"])
    g.require_no_sanctions_hold(supplier)

    for account in rc.supplier_bank_accounts(supplier["id"]):
        if account["status"] in DISPLACEABLE:
            account["status"] = "REPLACED"
            touch(account)

    row = base_row()
    row.update(
        {
            "supplier_id": supplier["id"],
            "routing_number": routing_number,
            "account_last4": account_last4,
            "micro_deposit_code": calc.micro_deposit_code(routing_number, account_last4),
            "micro_deposit_attempts": 0,
            "status": "MICRO_DEPOSIT_SENT",
        }
    )
    db.bank_accounts[row["id"]] = row

    supplier["bank_status"] = "MICRO_DEPOSIT_SENT"
    supplier["verified_account_last4"] = None
    if supplier["onboarding_status"] == "ACTIVE":
        supplier["onboarding_status"] = "VERIFYING"
        put_dt(supplier, "payment_ready_at", None)
    touch(supplier)
    return ok(public(row), 201)


@bp.get("/suppliers/<supplier_id>/bank-accounts")
def list_bank_accounts(supplier_id):
    ctx = authenticate((SUPPLIER, PLATFORM_OPS, BUYER_TREASURY))
    limit, offset = pagination()
    supplier = get_supplier(supplier_id)
    scope_supplier(ctx, supplier["id"])
    status = filter_arg("status")
    rows = rc.supplier_bank_accounts(supplier["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.post("/bank-accounts/<account_id>/micro-deposit/confirm")
def confirm_micro_deposit(account_id):
    ctx = authenticate((SUPPLIER, PLATFORM_OPS))
    b = body()
    code = req_str(b, "code", 1, 32)
    account = get_bank_account(account_id)
    scope_supplier(ctx, account["supplier_id"])
    supplier = db.suppliers.get(account["supplier_id"])
    if supplier is not None:
        g.require_no_sanctions_hold(supplier)
    if account["micro_deposit_attempts"] >= calc.MAX_MICRO_DEPOSIT_ATTEMPTS:
        raise ApiError("ERR_MICRO_DEPOSIT_ATTEMPTS_EXHAUSTED")
    g.require_bank_account_not_terminal(account)

    account["micro_deposit_attempts"] += 1
    if code == account["micro_deposit_code"]:
        account["status"] = "VERIFIED"
        touch(account)
        if supplier is not None:
            supplier["bank_status"] = "VERIFIED"
            supplier["verified_account_last4"] = account["account_last4"]
            flows.supplier_join(supplier)
            touch(supplier)
    elif account["micro_deposit_attempts"] >= calc.MAX_MICRO_DEPOSIT_ATTEMPTS:
        account["status"] = "FAILED"
        touch(account)
        if supplier is not None:
            supplier["bank_status"] = "FAILED"
            touch(supplier)
    else:
        # wrong code with attempts still remaining: only the bank account row
        # is mutated, so only its version advances.
        touch(account)
    return ok(public(account))

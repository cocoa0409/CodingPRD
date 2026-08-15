"""Clock, loans, escrow accounts, deposits, ledger, line items."""

from flask import Blueprint, request

from auth import any_role, check_borrower_owner, require_roles
from domain import (
    account_of_loan,
    advance_outstanding,
    advances_of_account,
    base_monthly_sum,
    close_account_for_loan,
    entries_of_account,
    line_items_of_account,
    post_ledger,
    recovery_waterfall,
    recompute_cushion,
    run_sweep,
)
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_DUP_LINE_ITEM,
    ERR_DUP_LOAN_NUMBER,
    ERR_ESCROW_EXISTS,
    ERR_ESCROW_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOAN_NOT_ACTIVE,
    ERR_PAYEE_NOT_VERIFIED,
    ERR_ADVANCE_OUTSTANDING,
    ERR_UNRESOLVED_CASE,
    not_found,
)
from serializers import account_out, ledger_out, line_item_out, loan_out
from store import store
from util import (
    add_months,
    bump,
    fmt_clock,
    fmt_date,
    new_record,
    now_ts,
    ok,
    ok_list,
    parse_date,
    parse_dt,
    today,
)
from validate import (
    body,
    fk_exists,
    opt_bool,
    opt_int,
    positive_amount,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("core", __name__)

EXPENSE_TYPES = ("PROPERTY_TAX", "HAZARD_INSURANCE", "FLOOD_INSURANCE", "PMI")
INSTALLMENT_CHOICES = (1, 2, 4, 12)

# ----------------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ComplianceOfficer")
    data = body()
    raw = data.get("to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 datetime")
    previous = store.clock
    store.clock = dt
    transitions = run_sweep()
    return ok({
        "previous_utc": fmt_clock(previous),
        "current_utc": fmt_clock(store.clock),
        "transitions_applied": transitions,
    })


@bp.get("/_clock/current_utc")
def get_clock():
    any_role()
    return ok({"current_utc": fmt_clock(store.clock)})

# ----------------------------------------------------------------------------
# Loans
# ----------------------------------------------------------------------------

@bp.post("/servicing/loans")
def create_loan():
    require_roles("ComplianceOfficer")
    data = body()
    loan_number = req_str(data, "loan_number")
    borrower_name = req_str(data, "borrower_name")
    principal = req_int(data, "principal_balance_cents", minimum=0)
    monthly_pi = req_int(data, "monthly_pi_cents", minimum=0)
    closing = req_date(data, "closing_date")
    escrow_required = opt_bool(data, "escrow_required", True)
    for l in store.loans.values():
        if l["loan_number"] == loan_number:
            raise ApiError(ERR_DUP_LOAN_NUMBER, 409, "loan_number already exists")
    loan = new_record({
        "loan_number": loan_number,
        "borrower_name": borrower_name,
        "principal_balance_cents": principal,
        "monthly_pi_cents": monthly_pi,
        "escrow_required": escrow_required,
        "closing_date": closing,
        "status": "ONBOARDING",
    })
    store.loans[loan["id"]] = loan
    return ok(loan_out(loan), 201)


def get_loan_or_404(loan_id):
    loan = store.loans.get(loan_id)
    if loan is None:
        raise not_found("Loan not found")
    return loan


def get_account_or_404(account_id):
    account = store.accounts.get(account_id)
    if account is None:
        raise not_found("EscrowAccount not found")
    return account


@bp.get("/servicing/loans")
def list_loans():
    any_role()
    rows = sorted(store.loans.values(), key=lambda r: r["_seq"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([loan_out(r) for r in rows])


@bp.get("/servicing/loans/<lid>")
def get_loan(lid):
    any_role()
    return ok(loan_out(get_loan_or_404(lid)))


@bp.post("/servicing/loans/<lid>/activate")
def activate_loan(lid):
    require_roles("ComplianceOfficer")
    loan = get_loan_or_404(lid)
    if loan["status"] in ("PAID_OFF", "TRANSFERRED_OUT"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Loan is terminal")
    if loan["status"] != "ONBOARDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Loan is not ONBOARDING")
    if loan["escrow_required"]:
        account = account_of_loan(loan["id"])
        if account is None or account["account_status"] != "ACTIVE":
            raise ApiError(ERR_ESCROW_NOT_ACTIVE, 409,
                           "Loan activation requires an ACTIVE escrow account")
    loan["status"] = "ACTIVE"
    bump(loan)
    return ok(loan_out(loan))


@bp.post("/servicing/loans/<lid>/payoff")
def payoff_loan(lid):
    require_roles("ComplianceOfficer")
    loan = get_loan_or_404(lid)
    if loan["status"] in ("PAID_OFF", "TRANSFERRED_OUT"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Loan is terminal")
    if loan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Loan is not ACTIVE")
    account = account_of_loan(loan["id"])
    if account:
        for a in advances_of_account(account["id"], open_only=True):
            if advance_outstanding(a) > 0:
                raise ApiError(ERR_ADVANCE_OUTSTANDING, 409,
                               "Outstanding advances block payoff")
    loan["status"] = "PAID_OFF"
    bump(loan)
    close_account_for_loan(loan)
    return ok(loan_out(loan))


@bp.post("/servicing/loans/<lid>/transfer-out")
def transfer_out_loan(lid):
    require_roles("ComplianceOfficer")
    loan = get_loan_or_404(lid)
    if loan["status"] in ("PAID_OFF", "TRANSFERRED_OUT"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Loan is terminal")
    if loan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Loan is not ACTIVE")
    for c in store.error_cases.values():
        if c["loan_id"] == loan["id"] and c["status"] in (
                "RECEIVED", "ACKNOWLEDGED", "INVESTIGATING", "EXTENDED"):
            raise ApiError(ERR_UNRESOLVED_CASE, 409, "Open error case blocks transfer")
    loan["status"] = "TRANSFERRED_OUT"
    bump(loan)
    close_account_for_loan(loan)
    return ok(loan_out(loan))

# ----------------------------------------------------------------------------
# Escrow accounts
# ----------------------------------------------------------------------------

@bp.post("/servicing/loans/<lid>/escrow-account")
def create_escrow_account(lid):
    require_roles("EscrowAnalyst")
    loan = get_loan_or_404(lid)
    if not loan["escrow_required"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Loan does not require an escrow account")
    if account_of_loan(loan["id"]) is not None:
        raise ApiError(ERR_ESCROW_EXISTS, 409, "Loan already has an escrow account")
    account = new_record({
        "loan_id": loan["id"],
        "account_status": "SETUP",
        "hold_status": "NONE",
        "balance_cents": 0,
        "target_cushion_cents": 0,
        "monthly_escrow_cents": None,
        "next_analysis_due_date": None,
        "last_analysis_year": None,
    })
    store.accounts[account["id"]] = account
    return ok(account_out(account), 201)


@bp.get("/servicing/escrow-accounts")
def list_accounts():
    any_role()
    rows = sorted(store.accounts.values(), key=lambda r: r["_seq"])
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    status = request.args.get("account_status")
    if status is not None:
        rows = [r for r in rows if r["account_status"] == status]
    return ok_list([account_out(r) for r in rows])


@bp.get("/servicing/escrow-accounts/<aid>")
def get_account(aid):
    any_role()
    return ok(account_out(get_account_or_404(aid)))


@bp.post("/servicing/escrow-accounts/<aid>/activate")
def activate_account(aid):
    require_roles("EscrowAnalyst")
    account = get_account_or_404(aid)
    if account["account_status"] == "CLOSED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Account is CLOSED")
    if account["account_status"] != "SETUP":
        raise ApiError(ERR_INVALID_STATE, 409, "Account is not SETUP")
    if not line_items_of_account(aid, active_only=True):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "At least one ACTIVE line item is required")
    account["monthly_escrow_cents"] = base_monthly_sum(aid)
    recompute_cushion(account)
    loan = store.loans.get(account["loan_id"])
    account["next_analysis_due_date"] = fmt_date(
        add_months(parse_date(loan["closing_date"]), 12))
    account["account_status"] = "ACTIVE"
    bump(account)
    return ok(account_out(account))


@bp.post("/servicing/escrow-accounts/<aid>/suspend")
def suspend_account(aid):
    require_roles("ComplianceOfficer")
    account = get_account_or_404(aid)
    if account["account_status"] == "CLOSED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Account is CLOSED")
    if account["account_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Account is not ACTIVE")
    account["account_status"] = "SUSPENDED"
    bump(account)
    return ok(account_out(account))


@bp.post("/servicing/escrow-accounts/<aid>/reinstate")
def reinstate_account(aid):
    require_roles("ComplianceOfficer")
    account = get_account_or_404(aid)
    if account["account_status"] == "CLOSED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Account is CLOSED")
    if account["account_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Account is not SUSPENDED")
    account["account_status"] = "ACTIVE"
    bump(account)
    return ok(account_out(account))


@bp.post("/servicing/escrow-accounts/<aid>/hold")
def hold_account(aid):
    require_roles("ComplianceOfficer")
    account = get_account_or_404(aid)
    if account["account_status"] == "CLOSED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Account is CLOSED")
    if account["hold_status"] != "NONE":
        raise ApiError(ERR_INVALID_STATE, 409, "Account is already on hold")
    account["hold_status"] = "COMPLIANCE_HOLD"
    bump(account)
    return ok(account_out(account))


@bp.post("/servicing/escrow-accounts/<aid>/release-hold")
def release_hold_account(aid):
    require_roles("ComplianceOfficer")
    account = get_account_or_404(aid)
    if account["hold_status"] != "COMPLIANCE_HOLD":
        raise ApiError(ERR_INVALID_STATE, 409, "Account is not on hold")
    account["hold_status"] = "NONE"
    bump(account)
    return ok(account_out(account))

# ----------------------------------------------------------------------------
# Deposits + ledger
# ----------------------------------------------------------------------------

@bp.post("/servicing/escrow-accounts/<aid>/deposits")
def create_deposit(aid):
    uid, role = require_roles("EscrowAnalyst", "Borrower")
    account = get_account_or_404(aid)
    if role == "Borrower":
        check_borrower_owner(uid, account["loan_id"])
    data = body()
    if not isinstance(data.get("amount_cents"), int) or isinstance(data.get("amount_cents"), bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents is required and must be an integer")
    eff = req_date(data, "effective_date")
    loan = store.loans.get(account["loan_id"])
    if loan is None or loan["status"] != "ACTIVE":
        raise ApiError(ERR_LOAN_NOT_ACTIVE, 409, "Loan is not ACTIVE")
    amount = positive_amount(data["amount_cents"])
    entry = post_ledger(account, "DEPOSIT", amount, eff, "Deposit", "deposit", "")
    entry["source_entity_id"] = entry["id"]
    recovery_waterfall(account, amount, eff)
    bump(account)
    return ok(ledger_out(entry), 201)


@bp.get("/servicing/escrow-accounts/<aid>/ledger")
def list_ledger(aid):
    any_role()
    account = get_account_or_404(aid)
    rows = entries_of_account(account["id"])
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    return ok_list([ledger_out(e) for e in rows])

# ----------------------------------------------------------------------------
# Line items
# ----------------------------------------------------------------------------

def get_line_item_or_404(liid):
    li = store.line_items.get(liid)
    if li is None:
        raise not_found("EscrowLineItem not found")
    return li


@bp.post("/servicing/escrow-accounts/<aid>/line-items")
def create_line_item(aid):
    require_roles("EscrowAnalyst")
    account = get_account_or_404(aid)
    data = body()
    payee = fk_exists(store.payees, data.get("payee_id"), "payee_id")
    expense_type = req_enum(data, "expense_type", EXPENSE_TYPES)
    amount = req_int(data, "expected_annual_amount_cents")
    ipy = req_int(data, "installments_per_year")
    if ipy not in INSTALLMENT_CHOICES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "installments_per_year must be one of 1, 2, 4, 12")
    first_due = req_date(data, "first_due_date")
    if payee is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "payee_id is required")
    for li in line_items_of_account(aid, active_only=True):
        if li["expense_type"] == expense_type:
            raise ApiError(ERR_DUP_LINE_ITEM, 409,
                           "An ACTIVE line item of this expense_type already exists")
    if payee["verification_status"] != "VERIFIED":
        raise ApiError(ERR_PAYEE_NOT_VERIFIED, 409, "Payee is not VERIFIED")
    positive_amount(amount, "expected_annual_amount_cents")
    li = new_record({
        "escrow_account_id": aid,
        "payee_id": payee["id"],
        "expense_type": expense_type,
        "expected_annual_amount_cents": amount,
        "installments_per_year": ipy,
        "first_due_date": first_due,
        "status": "ACTIVE",
    })
    store.line_items[li["id"]] = li
    recompute_cushion(account)
    bump(account)
    return ok(line_item_out(li), 201)


@bp.get("/servicing/escrow-accounts/<aid>/line-items")
def list_line_items(aid):
    any_role()
    get_account_or_404(aid)
    rows = line_items_of_account(aid)
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([line_item_out(r) for r in rows])


@bp.get("/servicing/escrow-line-items/<liid>")
def get_line_item(liid):
    any_role()
    return ok(line_item_out(get_line_item_or_404(liid)))


@bp.patch("/servicing/escrow-line-items/<liid>")
def patch_line_item(liid):
    require_roles("EscrowAnalyst")
    li = get_line_item_or_404(liid)
    data = body()
    # shape checks on provided fields
    if "expected_annual_amount_cents" in data and data["expected_annual_amount_cents"] is not None:
        v = data["expected_annual_amount_cents"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "expected_annual_amount_cents must be an integer")
    if "installments_per_year" in data and data["installments_per_year"] is not None:
        v = data["installments_per_year"]
        if not isinstance(v, int) or isinstance(v, bool) or v not in INSTALLMENT_CHOICES:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "installments_per_year must be one of 1, 2, 4, 12")
    if "first_due_date" in data and data["first_due_date"] is not None:
        if parse_date(data["first_due_date"]) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "first_due_date must be an ISO date")
    if li["status"] == "REMOVED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Line item is REMOVED")
    if li["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Line item is not ACTIVE")
    if data.get("expected_annual_amount_cents") is not None:
        positive_amount(data["expected_annual_amount_cents"], "expected_annual_amount_cents")
        li["expected_annual_amount_cents"] = data["expected_annual_amount_cents"]
    if data.get("installments_per_year") is not None:
        li["installments_per_year"] = data["installments_per_year"]
    if data.get("first_due_date") is not None:
        li["first_due_date"] = data["first_due_date"]
    bump(li)
    account = store.accounts.get(li["escrow_account_id"])
    if account:
        recompute_cushion(account)
        bump(account)
    return ok(line_item_out(li))


@bp.post("/servicing/escrow-line-items/<liid>/remove")
def remove_line_item(liid):
    require_roles("EscrowAnalyst")
    li = get_line_item_or_404(liid)
    if li["status"] == "REMOVED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Line item is REMOVED")
    li["status"] = "REMOVED"
    bump(li)
    account = store.accounts.get(li["escrow_account_id"])
    if account:
        recompute_cushion(account)
        bump(account)
    return ok(line_item_out(li))

"""Bookkeeping & Small-Business Accounting API (task_0299).

Single-file Flask app. In-memory store only; nothing seeded at startup.
Every behavior traces to PRD.md / SCAFFOLD.yaml.
"""
import os

from flask import Flask

import db
import errors
from middleware import get_user_context, require_role
from response import object_response, array_response, error_response
from serializers import serialize, serialize_list
import calculations as calc
import ledger
import util

app = Flask(__name__)
app.url_map.strict_slashes = False

# Role sets (PRD §2.1 / §4 endpoint table).
ALL_ROLES = ["Owner", "Accountant", "Bookkeeper", "Auditor"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(400)
def handle_400(e):
    return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    return error_response(errors.ERR_INVALID_REQUEST, "Internal error: %s" % e, 400)


def auth(allowed_roles):
    """Validate headers (priority 1) then role (priority 2). Returns (uid, role)."""
    uid, role = get_user_context()
    require_role(role, allowed_roles)
    return uid, role


# ---------------------------------------------------------------------------
# Period helpers (PRD §2.9)
# ---------------------------------------------------------------------------
def require_open_current_period(company, entity_date_str):
    """current_period_id set, that period OPEN, entity_date within it; else
    ERR_PERIOD_NOT_OPEN (PRD §2.9)."""
    pid = company.get("current_period_id")
    if not pid:
        raise errors.ApiError(errors.ERR_PERIOD_NOT_OPEN, 409, "No current period")
    period = db.accounting_periods.get(pid)
    if not period or period["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_PERIOD_NOT_OPEN, 409, "Current period not OPEN")
    if not util.within_period(entity_date_str, period):
        raise errors.ApiError(
            errors.ERR_PERIOD_NOT_OPEN, 409, "Date outside current open period"
        )
    return period


def require_period_open_for_void(period):
    """Void/reverse compensating ops require the period OPEN; else
    ERR_PERIOD_CLOSED (PRD §2.9)."""
    if not period or period["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_PERIOD_CLOSED, 409, "Period is not OPEN")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return object_response({"status": "ok"})


# ===========================================================================
# Company (PRD §3.1, §2.7)
# ===========================================================================
@app.route("/ledger/companies", methods=["POST"])
def create_company():
    auth(["Owner"])
    body = util.get_json_body()
    util.require_fields(body, ["legal_name"])
    accounting_basis = body.get("accounting_basis", "ACCRUAL")
    if accounting_basis not in ("ACCRUAL", "CASH"):
        raise errors.invalid_request("accounting_basis must be ACCRUAL or CASH")
    rec = db.make_record(
        {
            "legal_name": body["legal_name"],
            "base_currency": body.get("base_currency", "USD"),
            "accounting_basis": accounting_basis,
            "current_period_id": None,
            "retained_earnings_account_id": body.get("retained_earnings_account_id"),
            "retained_earnings_cents": 0,
            "trial_balance_status": "BALANCED",
        }
    )
    db.companies[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/companies/<company_id>", methods=["GET"])
def get_company(company_id):
    auth(ALL_ROLES)
    rec = util.get_company_or_404(company_id)
    return object_response(serialize(rec))


@app.route("/ledger/companies", methods=["GET"])
def list_companies():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.companies.values())
    cpid = request.args.get("current_period_id")
    reai = request.args.get("retained_earnings_account_id")
    if cpid is not None:
        items = [c for c in items if c.get("current_period_id") == cpid]
    if reai is not None:
        items = [c for c in items if c.get("retained_earnings_account_id") == reai]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/companies/<company_id>", methods=["PATCH"])
def configure_company(company_id):
    auth(["Owner"])
    company = util.get_company_or_404(company_id)
    body = util.get_json_body()
    # OCC: expected_company_version must match (PRD §2.7) when provided.
    expected = body.get("expected_company_version")
    if expected is not None and expected != company["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "Stale company version")
    if "retained_earnings_account_id" in body:
        company["retained_earnings_account_id"] = body["retained_earnings_account_id"]
    if "accounting_basis" in body:
        if body["accounting_basis"] not in ("ACCRUAL", "CASH"):
            raise errors.invalid_request("accounting_basis must be ACCRUAL or CASH")
        company["accounting_basis"] = body["accounting_basis"]
    db.touch(company)
    return object_response(serialize(company))


# ===========================================================================
# Account (PRD §3.1, §2.5)
# ===========================================================================
@app.route("/ledger/accounts", methods=["POST"])
def create_account():
    auth(["Owner", "Accountant"])
    body = util.get_json_body()
    util.require_fields(body, ["company_id", "code", "name", "account_type"])
    company = db.companies.get(body["company_id"])
    if company is None:
        raise errors.not_found("Company not found")
    account_type = body["account_type"]
    if account_type not in ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"):
        raise errors.invalid_request("Invalid account_type")
    is_cash = bool(body.get("is_cash", False))
    if is_cash and account_type != "ASSET":
        raise errors.invalid_request("is_cash accounts must be ASSET")

    parent_id = body.get("parent_account_id")
    if parent_id is not None:
        parent = util.get_account_or_404(parent_id)
        # priority 9: sub-account must share parent's account_type.
        if parent["account_type"] != account_type:
            raise errors.ApiError(
                errors.ERR_ACCOUNT_TYPE_MISMATCH, 409,
                "Sub-account type must match parent",
            )

    # priority 21: code unique per company among non-ARCHIVED accounts.
    for a in db.accounts.values():
        if (a["company_id"] == body["company_id"]
                and a["status"] != "ARCHIVED"
                and a["code"] == body["code"]):
            raise errors.ApiError(
                errors.ERR_DUPLICATE_ACCOUNT_CODE, 409, "Duplicate account code"
            )

    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "parent_account_id": parent_id,
            "code": body["code"],
            "name": body["name"],
            "account_type": account_type,
            "is_cash": is_cash,
            "status": "ACTIVE",
            "posted_balance_cents": 0,
        }
    )
    db.accounts[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    auth(ALL_ROLES)
    rec = util.get_account_or_404(account_id)
    return object_response(serialize(rec))


@app.route("/ledger/accounts", methods=["GET"])
def list_accounts():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.accounts.values())
    for key in ("company_id", "parent_account_id", "account_type", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/accounts/<account_id>/balance", methods=["GET"])
def get_account_balance(account_id):
    auth(ALL_ROLES)
    from flask import request
    util.get_account_or_404(account_id)
    posted = ledger.account_balance(account_id, include_drafts=False)
    include_drafts = request.args.get("include_drafts", "").lower() == "true"
    projected = (
        ledger.account_balance(account_id, include_drafts=True)
        if include_drafts else posted
    )
    return object_response({
        "account_id": account_id,
        "posted_balance_cents": posted,
        "projected_balance_cents": projected,
    })


@app.route("/ledger/accounts/<account_id>/archive", methods=["POST"])
def archive_account(account_id):
    auth(["Owner", "Accountant"])
    acct = util.get_account_or_404(account_id)
    if acct["status"] == "ARCHIVED":
        raise errors.invalid_state("Account already ARCHIVED")
    acct["status"] = "ARCHIVED"
    db.touch(acct)
    return object_response(serialize(acct))


# ===========================================================================
# AccountingPeriod (PRD §3.2, §2.7, §2.9)
# ===========================================================================
def _company_periods(company_id):
    return [p for p in db.accounting_periods.values() if p["company_id"] == company_id]


@app.route("/ledger/accounting-periods", methods=["POST"])
def create_period():
    auth(["Owner", "Accountant"])
    body = util.get_json_body()
    util.require_fields(
        body,
        ["company_id", "period_label", "start_date", "end_date",
         "expected_company_version"],
    )
    company = db.companies.get(body["company_id"])
    if company is None:
        raise errors.not_found("Company not found")
    # validate dates parseable
    util.parse_dt(body["start_date"])
    util.parse_dt(body["end_date"])

    # priority 9: contiguity — start_date must equal the prior closed period's
    # end_date. The prior period is the company's most recent CLOSED period.
    closed = [p for p in _company_periods(body["company_id"]) if p["status"] == "CLOSED"]
    if closed:
        closed.sort(key=lambda p: (util.parse_dt(p["end_date"]), p["_seq"]))
        prior = closed[-1]
        if util.parse_dt(body["start_date"]) != util.parse_dt(prior["end_date"]):
            raise errors.ApiError(
                errors.ERR_PERIOD_NOT_CONTIGUOUS, 409,
                "start_date must equal prior closed period end_date",
            )

    # priority 22: OCC on company version.
    if body["expected_company_version"] != company["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "Stale company version")

    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "period_label": body["period_label"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "status": "OPEN",
            "close_checklist": [
                {"item": "BANK_RECONCILED", "done": False},
                {"item": "AR_REVIEWED", "done": False},
                {"item": "AP_REVIEWED", "done": False},
                {"item": "SALES_TAX_REVIEWED", "done": False},
            ],
            "closing_journal_entry_id": None,
        }
    )
    db.accounting_periods[rec["id"]] = rec
    # advance company current_period_id and bump version (PRD §2.7).
    company["current_period_id"] = rec["id"]
    db.touch(company)
    return object_response(serialize(rec), 201)


@app.route("/ledger/accounting-periods/<period_id>", methods=["GET"])
def get_period(period_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.accounting_periods, period_id)
    return object_response(serialize(rec))


@app.route("/ledger/accounting-periods", methods=["GET"])
def list_periods():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.accounting_periods.values())
    for key in ("company_id", "status", "closing_journal_entry_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/accounting-periods/<period_id>/checklist", methods=["POST"])
def period_checklist(period_id):
    auth(["Owner", "Accountant", "Bookkeeper"])
    period = util.get_or_404(db.accounting_periods, period_id)
    body = util.get_json_body()
    util.require_fields(body, ["item", "done"])
    item = body["item"]
    done = bool(body["done"])
    found = False
    for entry in period["close_checklist"]:
        if entry["item"] == item:
            entry["done"] = done
            found = True
            break
    if not found:
        raise errors.invalid_request("Unknown checklist item: %s" % item)
    db.touch(period)
    return object_response(serialize(period))


@app.route("/ledger/accounting-periods/<period_id>/begin-close", methods=["POST"])
def begin_close(period_id):
    auth(["Accountant"])
    period = util.get_or_404(db.accounting_periods, period_id)
    if period["status"] != "OPEN":
        raise errors.invalid_state("Period not OPEN")
    # priority 19 preconditions, in PRD §3.2 order.
    if not all(c["done"] for c in period["close_checklist"]):
        raise errors.ApiError(errors.ERR_CHECKLIST_INCOMPLETE, 409,
                              "Close checklist incomplete")
    for e in db.journal_entries.values():
        if e["period_id"] == period_id and e["status"] == "DRAFT":
            raise errors.ApiError(errors.ERR_OPEN_DRAFT_ENTRIES, 409,
                                  "Draft journal entries exist in this period")
    for r in db.reconciliations.values():
        if r["company_id"] == period["company_id"] and r["status"] == "IN_PROGRESS":
            raise errors.ApiError(errors.ERR_RECONCILIATION_IN_PROGRESS, 409,
                                  "Reconciliation in progress")
    period["status"] = "CLOSING"
    db.touch(period)
    return object_response(serialize(period))


@app.route("/ledger/accounting-periods/<period_id>/post-close", methods=["POST"])
def post_close(period_id):
    auth(["Accountant"])
    period = util.get_or_404(db.accounting_periods, period_id)
    if period["status"] != "CLOSING":
        raise errors.invalid_state("Period not CLOSING")
    company = db.companies[period["company_id"]]
    # precondition: trial balance BALANCED.
    ledger.recompute_trial_balance(company["id"])
    if company["trial_balance_status"] != "BALANCED":
        raise errors.ApiError(errors.ERR_TRIAL_BALANCE_OUT_OF_BALANCE, 409,
                              "Trial balance out of balance")

    # CASCADE A hop1: closing entry debits each REVENUE account by its posted
    # balance and credits each EXPENSE account by its posted balance, with the
    # net carried to retained earnings (PRD §3.2). The closing entry must net to
    # zero (debits == credits) so the trial-balance invariant survives.
    #
    # posted_balance_cents is the account's signed normal-side balance:
    #   REVENUE/EXPENSE both expose a balance; to zero a REVENUE account we book
    #   the opposite of its normal (credit) side -> a debit of `bal`; to zero an
    #   EXPENSE account we book the opposite of its normal (debit) side -> a
    #   credit of `bal`. A negative `bal` flips the side (encoded via add_line's
    #   non-negative debit/credit fields).
    re_account_id = company["retained_earnings_account_id"]
    closing = ledger.create_system_entry(
        company_id=company["id"],
        period_id=period_id,
        entry_date=period["end_date"],
        source="CLOSING",
        memo="Closing entry for period %s" % period["period_label"],
    )

    def _book(account_id, signed_debit):
        """Add a line booking `signed_debit` cents on the debit side (negative =
        credit side). Returns the signed debit contribution to entry balance."""
        if signed_debit == 0:
            return 0
        if signed_debit > 0:
            ledger.add_line(closing["id"], account_id,
                            debit_cents=signed_debit, credit_cents=0)
        else:
            ledger.add_line(closing["id"], account_id,
                            debit_cents=0, credit_cents=-signed_debit)
        return signed_debit

    total_revenue = 0
    total_expense = 0
    debit_minus_credit = 0  # running (debits - credits) of the closing entry
    for acct in db.accounts.values():
        if acct["company_id"] != company["id"]:
            continue
        bal = acct["posted_balance_cents"]
        if acct["account_type"] == "REVENUE" and bal != 0:
            # Debit REVENUE by its (credit-positive) balance to zero it.
            debit_minus_credit += _book(acct["id"], bal)
            total_revenue += bal
        elif acct["account_type"] == "EXPENSE" and bal != 0:
            # Credit EXPENSE by its (debit-positive) balance to zero it.
            debit_minus_credit += _book(acct["id"], -bal)
            total_expense += bal

    net_income = total_revenue - total_expense
    # Retained earnings (EQUITY) absorbs the net: book the balancing amount so
    # the closing entry's debits equal its credits. The required RE line is the
    # negation of the running debit-minus-credit.
    if debit_minus_credit != 0:
        _book(re_account_id, -debit_minus_credit)

    # post it (CASCADE A hop2: REVENUE/EXPENSE balances -> 0, RE recomputed).
    if ledger._lines_for_entry(closing["id"]):
        ledger.post_entry(closing)
        period["closing_journal_entry_id"] = closing["id"]
    else:
        # No revenue/expense activity: discard the empty closing entry.
        del db.journal_entries[closing["id"]]

    # CASCADE A hop3: company retained_earnings_cents from RE account balance.
    re_acct = db.accounts.get(re_account_id)
    company["retained_earnings_cents"] = re_acct["posted_balance_cents"] if re_acct else 0
    db.touch(company)
    ledger.recompute_trial_balance(company["id"])

    period["status"] = "CLOSED"
    db.touch(period)
    return object_response(serialize(period))


@app.route("/ledger/accounting-periods/<period_id>/reopen", methods=["POST"])
def reopen_period(period_id):
    auth(["Owner"])
    period = util.get_or_404(db.accounting_periods, period_id)
    if period["status"] != "CLOSED":
        raise errors.invalid_state("Period not CLOSED")
    company = db.companies[period["company_id"]]
    # latest-closed check: this must be the most recently closed period. We
    # treat "latest closed" as the closed period with the greatest end_date.
    closed = [p for p in _company_periods(company["id"]) if p["status"] == "CLOSED"]
    closed.sort(key=lambda p: (util.parse_dt(p["end_date"]), p["_seq"]))
    if not closed or closed[-1]["id"] != period_id:
        raise errors.ApiError(errors.ERR_NOT_LATEST_CLOSED_PERIOD, 409,
                              "Not the latest closed period")

    # Void the closing entry via reversal path.
    ce_id = period.get("closing_journal_entry_id")
    if ce_id:
        ce = db.journal_entries.get(ce_id)
        if ce and ce["status"] == "POSTED":
            ledger.reverse_entry(ce)
            ce["status"] = "VOIDED"
            db.touch(ce)
        # recompute retained earnings from the RE account's new balance.
        re_acct = db.accounts.get(company["retained_earnings_account_id"])
        company["retained_earnings_cents"] = (
            re_acct["posted_balance_cents"] if re_acct else 0
        )
        db.touch(company)
        ledger.recompute_trial_balance(company["id"])
    period["closing_journal_entry_id"] = None
    period["status"] = "OPEN"
    db.touch(period)
    return object_response(serialize(period))


# ===========================================================================
# JournalEntry / JournalLine (PRD §3.3, §3.4)
# ===========================================================================
@app.route("/ledger/journal-entries", methods=["POST"])
def create_journal_entry():
    uid, role = auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(body, ["company_id", "period_id", "entry_date"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    if db.accounting_periods.get(body["period_id"]) is None:
        raise errors.not_found("Period not found")
    util.parse_dt(body["entry_date"])
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "period_id": body["period_id"],
            "entry_date": body["entry_date"],
            "memo": body.get("memo", ""),
            "source": "MANUAL",
            "created_by_user_id": uid,
            "reverses_journal_entry_id": None,
            "total_debit_cents": 0,
            "total_credit_cents": 0,
            "status": "DRAFT",
        }
    )
    db.journal_entries[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/journal-entries/<entry_id>", methods=["GET"])
def get_journal_entry(entry_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.journal_entries, entry_id)
    return object_response(serialize(rec))


@app.route("/ledger/journal-entries", methods=["GET"])
def list_journal_entries():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.journal_entries.values())
    for key in ("company_id", "period_id", "status", "reverses_journal_entry_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/journal-lines", methods=["POST"])
def create_journal_line():
    auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(body, ["journal_entry_id", "account_id"])
    entry = db.journal_entries.get(body["journal_entry_id"])
    if entry is None:
        raise errors.not_found("Journal entry not found")
    # account_id existence -> ERR_ACCOUNT_NOT_FOUND (priority 3).
    util.get_account_or_404(body["account_id"])
    # state: line may be added only while parent is DRAFT.
    if entry["status"] != "DRAFT":
        raise errors.invalid_state("Parent entry not DRAFT")
    debit = util.require_int(body, "debit_cents", required=False, default=0)
    credit = util.require_int(body, "credit_cents", required=False, default=0)
    # priority 13: exactly one of debit/credit > 0, both >= 0.
    if debit < 0 or credit < 0:
        raise errors.ApiError(errors.ERR_INVALID_LINE, 422, "Negative line amount")
    if (debit > 0) == (credit > 0):
        raise errors.ApiError(errors.ERR_INVALID_LINE, 422,
                              "Exactly one of debit/credit must be > 0")
    line = ledger.add_line(entry["id"], body["account_id"], debit, credit,
                           body.get("line_memo", ""))
    ledger.recompute_entry_totals(entry)
    db.touch(entry)
    return object_response(serialize(line), 201)


@app.route("/ledger/journal-lines/<line_id>", methods=["GET"])
def get_journal_line(line_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.journal_lines, line_id)
    return object_response(serialize(rec))


@app.route("/ledger/journal-lines", methods=["GET"])
def list_journal_lines():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.journal_lines.values())
    for key in ("journal_entry_id", "account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/journal-entries/<entry_id>/post", methods=["POST"])
def post_journal_entry(entry_id):
    uid, role = auth(["Accountant", "Owner"])
    entry = util.get_or_404(db.journal_entries, entry_id)
    if entry["status"] != "DRAFT":
        raise errors.invalid_state("Entry not DRAFT")
    # priority 6: segregation of duties (before referential rules).
    if uid == entry["created_by_user_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Maker cannot post own entry")
    lines = ledger._lines_for_entry(entry_id)
    # priority 7: every referenced account must be ACTIVE.
    for ln in lines:
        acct = db.accounts.get(ln["account_id"])
        if acct and acct["status"] == "ARCHIVED":
            raise errors.ApiError(errors.ERR_ACCOUNT_ARCHIVED, 409,
                                  "Referenced account is ARCHIVED")
    # priority 10: period must be OPEN.
    period = db.accounting_periods.get(entry["period_id"])
    if not period or period["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_PERIOD_NOT_OPEN, 409, "Period not OPEN")
    # priority 12: balanced, total > 0, >= 2 lines.
    ledger.recompute_entry_totals(entry)
    if (entry["total_debit_cents"] != entry["total_credit_cents"]
            or entry["total_debit_cents"] <= 0
            or len(lines) < 2):
        raise errors.ApiError(errors.ERR_ENTRY_NOT_BALANCED, 422,
                              "Entry not balanced")
    ledger.post_entry(entry)
    return object_response(serialize(entry))


@app.route("/ledger/journal-entries/<entry_id>/void", methods=["POST"])
def void_journal_entry(entry_id):
    auth(["Owner"])
    entry = util.get_or_404(db.journal_entries, entry_id)
    if entry["status"] != "POSTED":
        raise errors.invalid_state("Entry not POSTED")
    period = db.accounting_periods.get(entry["period_id"])
    # priority 11: closed period -> ERR_PERIOD_CLOSED.
    require_period_open_for_void(period)
    # priority 20: closing entries protected.
    if entry["source"] == "CLOSING":
        raise errors.ApiError(errors.ERR_CLOSING_ENTRY_PROTECTED, 409,
                              "Closing entry is protected")
    ledger.reverse_entry(entry)
    entry["status"] = "VOIDED"
    db.touch(entry)
    return object_response(serialize(entry))


# ===========================================================================
# BankAccount (PRD §3.5)
# ===========================================================================
@app.route("/ledger/bank-accounts", methods=["POST"])
def create_bank_account():
    auth(["Owner", "Accountant"])
    body = util.get_json_body()
    util.require_fields(body, ["company_id", "gl_account_id", "nickname"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    gl = util.get_account_or_404(body["gl_account_id"])
    # linked GL must be a cash ASSET account.
    if not (gl["is_cash"] and gl["account_type"] == "ASSET"):
        raise errors.ApiError(errors.ERR_INVALID_CATEGORIZATION_ACCOUNT, 409,
                              "GL account must be a cash ASSET account")
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "gl_account_id": body["gl_account_id"],
            "nickname": body["nickname"],
            "last_reconciled_statement_balance_cents": 0,
            "last_reconciled_through": None,
        }
    )
    db.bank_accounts[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/bank-accounts/<bank_account_id>", methods=["GET"])
def get_bank_account(bank_account_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.bank_accounts, bank_account_id)
    return object_response(serialize(rec))


@app.route("/ledger/bank-accounts", methods=["GET"])
def list_bank_accounts():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.bank_accounts.values())
    for key in ("company_id", "gl_account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


# ===========================================================================
# BankFeedTransaction (PRD §3.5)
# ===========================================================================
@app.route("/ledger/bank-feed-transactions", methods=["POST"])
def import_bank_feed_transaction():
    auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(
        body, ["company_id", "bank_account_id", "posted_date", "amount_cents",
               "bank_description"],
    )
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    if db.bank_accounts.get(body["bank_account_id"]) is None:
        raise errors.not_found("Bank account not found")
    amount = util.require_int(body, "amount_cents")
    util.parse_dt(body["posted_date"])
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "bank_account_id": body["bank_account_id"],
            "posted_date": body["posted_date"],
            "amount_cents": amount,
            "bank_description": body["bank_description"],
            "counter_account_id": None,
            "journal_entry_id": None,
            "cleared": False,
            "status": "UNMATCHED",
        }
    )
    db.bank_feed_transactions[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/bank-feed-transactions/<transaction_id>", methods=["GET"])
def get_bank_feed_transaction(transaction_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.bank_feed_transactions, transaction_id)
    return object_response(serialize(rec))


@app.route("/ledger/bank-feed-transactions", methods=["GET"])
def list_bank_feed_transactions():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.bank_feed_transactions.values())
    for key in ("company_id", "bank_account_id", "counter_account_id",
                "journal_entry_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/bank-feed-transactions/<transaction_id>/categorize",
           methods=["POST"])
def categorize_transaction(transaction_id):
    auth(["Bookkeeper", "Accountant"])
    txn = util.get_or_404(db.bank_feed_transactions, transaction_id)
    if txn["status"] != "UNMATCHED":
        raise errors.invalid_state("Transaction not UNMATCHED")
    body = util.get_json_body()
    util.require_fields(body, ["counter_account_id"])
    # priority 3/4: counter account existence (ERR_ACCOUNT_NOT_FOUND).
    counter = util.get_account_or_404(body["counter_account_id"])
    bank = db.bank_accounts[txn["bank_account_id"]]
    # priority 7: archived account checked before categorization-type rule.
    if counter["status"] == "ARCHIVED":
        raise errors.ApiError(errors.ERR_ACCOUNT_ARCHIVED, 409,
                              "Counter account is ARCHIVED")
    # same-company check.
    if counter["company_id"] != txn["company_id"]:
        raise errors.ApiError(errors.ERR_INVALID_CATEGORIZATION_ACCOUNT, 409,
                              "Counter account belongs to another company")
    # priority 8: not EQUITY, not the bank's own gl_account_id.
    if counter["account_type"] == "EQUITY" or counter["id"] == bank["gl_account_id"]:
        raise errors.ApiError(errors.ERR_INVALID_CATEGORIZATION_ACCOUNT, 409,
                              "Invalid categorization account")
    # priority 10: company current period OPEN and posted_date within it.
    company = db.companies[txn["company_id"]]
    period = require_open_current_period(company, txn["posted_date"])

    # create + post BANK_FEED entry (2 lines).
    gl_id = bank["gl_account_id"]
    counter_id = counter["id"]
    amount = txn["amount_cents"]
    entry = ledger.create_system_entry(
        company_id=company["id"],
        period_id=period["id"],
        entry_date=txn["posted_date"],
        source="BANK_FEED",
        memo=txn["bank_description"],
    )
    if amount >= 0:
        # deposit: debit bank gl, credit counter.
        ledger.add_line(entry["id"], gl_id, debit_cents=amount, credit_cents=0)
        ledger.add_line(entry["id"], counter_id, debit_cents=0, credit_cents=amount)
    else:
        amt = -amount
        # withdrawal: debit counter, credit bank gl.
        ledger.add_line(entry["id"], counter_id, debit_cents=amt, credit_cents=0)
        ledger.add_line(entry["id"], gl_id, debit_cents=0, credit_cents=amt)
    ledger.post_entry(entry)

    txn["journal_entry_id"] = entry["id"]
    txn["counter_account_id"] = counter_id
    txn["status"] = "CATEGORIZED"
    db.touch(txn)
    return object_response(serialize(txn))


@app.route("/ledger/bank-feed-transactions/<transaction_id>/recategorize",
           methods=["POST"])
def recategorize_transaction(transaction_id):
    auth(["Bookkeeper", "Accountant"])
    txn = util.get_or_404(db.bank_feed_transactions, transaction_id)
    if txn["status"] != "CATEGORIZED":
        raise errors.invalid_state("Transaction not CATEGORIZED")
    # priority 20: cleared txn cannot be recategorized.
    if txn["cleared"]:
        raise errors.ApiError(errors.ERR_TRANSACTION_CLEARED, 409,
                              "Cleared transaction cannot be recategorized")
    je_id = txn.get("journal_entry_id")
    if je_id:
        je = db.journal_entries.get(je_id)
        if je and je["status"] == "POSTED":
            ledger.reverse_entry(je)
            je["status"] = "VOIDED"
            db.touch(je)
    txn["journal_entry_id"] = None
    txn["counter_account_id"] = None
    txn["status"] = "UNMATCHED"
    db.touch(txn)
    return object_response(serialize(txn))


@app.route("/ledger/bank-feed-transactions/<transaction_id>/exclude",
           methods=["POST"])
def exclude_transaction(transaction_id):
    auth(["Bookkeeper", "Accountant"])
    txn = util.get_or_404(db.bank_feed_transactions, transaction_id)
    if txn["status"] != "UNMATCHED":
        raise errors.invalid_state("Transaction not UNMATCHED")
    txn["status"] = "EXCLUDED"
    db.touch(txn)
    return object_response(serialize(txn))


# ===========================================================================
# Reconciliation (PRD §3.9, §2.7)
# ===========================================================================
def _compute_reconciliation_difference(opening, ending, included_ids):
    movement = 0
    for tid in included_ids:
        t = db.bank_feed_transactions[tid]
        movement += t["amount_cents"]
    expected_ending = opening + movement
    return ending - expected_ending


@app.route("/ledger/reconciliations", methods=["POST"])
def create_reconciliation():
    auth(["Accountant", "Owner"])
    body = util.get_json_body()
    util.require_fields(
        body,
        ["company_id", "bank_account_id", "statement_start_date",
         "statement_end_date", "statement_opening_balance_cents",
         "statement_ending_balance_cents", "included_transaction_ids"],
    )
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    bank = db.bank_accounts.get(body["bank_account_id"])
    if bank is None:
        raise errors.not_found("Bank account not found")
    util.parse_dt(body["statement_start_date"])
    util.parse_dt(body["statement_end_date"])
    opening = util.require_int(body, "statement_opening_balance_cents")
    ending = util.require_int(body, "statement_ending_balance_cents")
    included = body["included_transaction_ids"]
    if not isinstance(included, list):
        raise errors.invalid_request("included_transaction_ids must be a list")

    # Every included transaction must be CATEGORIZED, same bank account, not
    # cleared (PRD §3.9) -> ERR_TRANSACTION_NOT_CATEGORIZED.
    for tid in included:
        t = db.bank_feed_transactions.get(tid)
        if t is None:
            raise errors.not_found("Included transaction not found")
        if (t["status"] != "CATEGORIZED"
                or t["bank_account_id"] != body["bank_account_id"]
                or t["cleared"]):
            raise errors.ApiError(errors.ERR_TRANSACTION_NOT_CATEGORIZED, 409,
                                  "Included transaction not categorized/uncleared")

    difference = _compute_reconciliation_difference(opening, ending, included)
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "bank_account_id": body["bank_account_id"],
            "statement_start_date": body["statement_start_date"],
            "statement_end_date": body["statement_end_date"],
            "statement_opening_balance_cents": opening,
            "statement_ending_balance_cents": ending,
            "included_transaction_ids": list(included),
            "difference_cents": difference,
            "status": "IN_PROGRESS",
        }
    )
    db.reconciliations[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/reconciliations/<reconciliation_id>", methods=["GET"])
def get_reconciliation(reconciliation_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.reconciliations, reconciliation_id)
    return object_response(serialize(rec))


@app.route("/ledger/reconciliations", methods=["GET"])
def list_reconciliations():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.reconciliations.values())
    for key in ("company_id", "bank_account_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/reconciliations/<reconciliation_id>/finalize",
           methods=["POST"])
def finalize_reconciliation(reconciliation_id):
    auth(["Accountant", "Owner"])
    rec = util.get_or_404(db.reconciliations, reconciliation_id)
    if rec["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Reconciliation not IN_PROGRESS")
    body = util.get_json_body()
    bank = db.bank_accounts[rec["bank_account_id"]]
    # recompute difference (PRD §3.9): re-check before finalizing.
    difference = _compute_reconciliation_difference(
        rec["statement_opening_balance_cents"],
        rec["statement_ending_balance_cents"],
        rec["included_transaction_ids"],
    )
    rec["difference_cents"] = difference
    # constraint order (priority 18): unbalanced first, then not-categorized.
    if difference != 0:
        raise errors.ApiError(errors.ERR_RECONCILIATION_UNBALANCED, 409,
                              "Reconciliation not balanced")
    for tid in rec["included_transaction_ids"]:
        t = db.bank_feed_transactions.get(tid)
        if t is None or t["status"] != "CATEGORIZED" or t["cleared"]:
            raise errors.ApiError(errors.ERR_TRANSACTION_NOT_CATEGORIZED, 409,
                                  "Included transaction not categorized/uncleared")
    # priority 22: OCC on bank account version.
    expected = body.get("expected_bank_account_version")
    if expected is not None and expected != bank["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "Stale bank account version")

    for tid in rec["included_transaction_ids"]:
        t = db.bank_feed_transactions[tid]
        t["cleared"] = True
        db.touch(t)
    bank["last_reconciled_statement_balance_cents"] = rec["statement_ending_balance_cents"]
    bank["last_reconciled_through"] = rec["statement_end_date"]
    db.touch(bank)  # bumps BankAccount.version
    rec["status"] = "RECONCILED"
    db.touch(rec)
    return object_response(serialize(rec))


@app.route("/ledger/reconciliations/<reconciliation_id>/abandon",
           methods=["POST"])
def abandon_reconciliation(reconciliation_id):
    auth(["Accountant", "Owner"])
    rec = util.get_or_404(db.reconciliations, reconciliation_id)
    if rec["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Reconciliation not IN_PROGRESS")
    rec["status"] = "ABANDONED"
    db.touch(rec)
    return object_response(serialize(rec))


# ===========================================================================
# Customer / Invoice / InvoicePayment (PRD §3.6, §3.7, §2.10)
# ===========================================================================
@app.route("/ledger/customers", methods=["POST"])
def create_customer():
    auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(
        body, ["company_id", "display_name", "tax_jurisdiction", "ar_account_id"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    util.get_account_or_404(body["ar_account_id"])
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "display_name": body["display_name"],
            "tax_jurisdiction": body["tax_jurisdiction"],
            "ar_account_id": body["ar_account_id"],
        }
    )
    db.customers[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.customers, customer_id)
    return object_response(serialize(rec))


@app.route("/ledger/customers", methods=["GET"])
def list_customers():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.customers.values())
    for key in ("company_id", "ar_account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


def _effective_tax_rate_bps(company_id, jurisdiction, on_date_str):
    """Rate effective on a date for a jurisdiction (PRD §2.10); 0 if none."""
    on_date = util.parse_dt(on_date_str)
    for tr in db.tax_rates.values():
        if tr["company_id"] != company_id or tr["jurisdiction"] != jurisdiction:
            continue
        if util.parse_dt(tr["effective_from"]) <= on_date < util.parse_dt(tr["effective_to"]):
            return tr["rate_bps"]
    return 0


@app.route("/ledger/invoices", methods=["POST"])
def create_invoice():
    auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(
        body,
        ["company_id", "customer_id", "revenue_account_id",
         "tax_liability_account_id", "issue_date", "lines"],
    )
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    if db.customers.get(body["customer_id"]) is None:
        raise errors.not_found("Customer not found")
    util.get_account_or_404(body["revenue_account_id"])
    util.get_account_or_404(body["tax_liability_account_id"])
    util.parse_dt(body["issue_date"])
    lines = body["lines"]
    if not isinstance(lines, list):
        raise errors.invalid_request("lines must be a list")
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "customer_id": body["customer_id"],
            "revenue_account_id": body["revenue_account_id"],
            "tax_liability_account_id": body["tax_liability_account_id"],
            "issue_date": body["issue_date"],
            "lines": lines,
            "applied_tax_rate_bps": 0,
            "taxable_subtotal_cents": 0,
            "nontaxable_subtotal_cents": 0,
            "discount_cents": 0,
            "tax_cents": 0,
            "total_cents": 0,
            "amount_paid_cents": 0,
            "balance_due_cents": 0,
            "delivery_status": "DRAFT",
            "payment_status": "UNPAID",
        }
    )
    db.invoices[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.invoices, invoice_id)
    return object_response(serialize(rec))


@app.route("/ledger/invoices", methods=["GET"])
def list_invoices():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.invoices.values())
    for key in ("company_id", "customer_id", "revenue_account_id",
                "tax_liability_account_id", "delivery_status", "payment_status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/invoices/<invoice_id>/send", methods=["POST"])
def send_invoice(invoice_id):
    auth(["Bookkeeper", "Accountant"])
    inv = util.get_or_404(db.invoices, invoice_id)
    if inv["delivery_status"] != "DRAFT":
        raise errors.invalid_state("Invoice not DRAFT")
    # priority 14: non-empty lines.
    if not inv["lines"]:
        raise errors.ApiError(errors.ERR_INVOICE_EMPTY, 422, "Invoice has no lines")
    company = db.companies[inv["company_id"]]
    # priority 10: current period OPEN, issue_date within it.
    period = require_open_current_period(company, inv["issue_date"])
    customer = db.customers[inv["customer_id"]]

    # capture applied_tax_rate_bps from rate effective on issue_date.
    rate_bps = _effective_tax_rate_bps(
        company["id"], customer["tax_jurisdiction"], inv["issue_date"])
    inv["applied_tax_rate_bps"] = rate_bps

    breakdown = calc.invoice_total_breakdown(inv["lines"], rate_bps)
    inv.update(breakdown)
    inv["amount_paid_cents"] = 0
    inv["balance_due_cents"] = breakdown["total_cents"]

    # post MANUAL entry: debit AR (total), credit revenue (discounted taxable +
    # nontaxable), credit tax-liability (tax). (PRD §3.6)
    discounted_taxable = breakdown["taxable_subtotal_cents"] - breakdown["discount_cents"]
    revenue_credit = discounted_taxable + breakdown["nontaxable_subtotal_cents"]
    entry = ledger.create_system_entry(
        company_id=company["id"],
        period_id=period["id"],
        entry_date=inv["issue_date"],
        source="MANUAL",
        memo="Invoice %s" % inv["id"],
    )
    ledger.add_line(entry["id"], customer["ar_account_id"],
                    debit_cents=breakdown["total_cents"], credit_cents=0)
    if revenue_credit != 0:
        ledger.add_line(entry["id"], inv["revenue_account_id"],
                        debit_cents=0, credit_cents=revenue_credit)
    if breakdown["tax_cents"] != 0:
        ledger.add_line(entry["id"], inv["tax_liability_account_id"],
                        debit_cents=0, credit_cents=breakdown["tax_cents"])
    ledger.post_entry(entry)
    inv["_posting_journal_entry_id"] = entry["id"]

    inv["delivery_status"] = "SENT"
    db.touch(inv)
    return object_response(serialize(inv))


@app.route("/ledger/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    auth(["Accountant", "Owner"])
    inv = util.get_or_404(db.invoices, invoice_id)
    if inv["delivery_status"] != "SENT":
        raise errors.invalid_state("Invoice not SENT")
    # priority 11: period closed -> ERR_PERIOD_CLOSED (after state check).
    company = db.companies[inv["company_id"]]
    period = db.accounting_periods.get(company.get("current_period_id"))
    # The invoice's issue-date period must be OPEN. We use the current period.
    require_period_open_for_void(period)
    # priority 17: cannot void if any CLEARED payment.
    if inv["payment_status"] != "UNPAID":
        raise errors.ApiError(errors.ERR_INVOICE_HAS_PAYMENTS, 409,
                              "Invoice has payments")
    je_id = inv.get("_posting_journal_entry_id")
    if je_id:
        je = db.journal_entries.get(je_id)
        if je and je["status"] == "POSTED":
            ledger.reverse_entry(je)
            je["status"] = "VOIDED"
            db.touch(je)
    inv["delivery_status"] = "VOID"
    db.touch(inv)
    return object_response(serialize(inv))


def _recompute_invoice_payment_state(inv):
    paid = sum(
        p["amount_cents"] for p in db.invoice_payments.values()
        if p["invoice_id"] == inv["id"] and p["status"] == "CLEARED"
    )
    inv["amount_paid_cents"] = paid
    inv["balance_due_cents"] = inv["total_cents"] - paid
    if paid == 0:
        inv["payment_status"] = "UNPAID"
    elif paid < inv["total_cents"]:
        inv["payment_status"] = "PARTIALLY_PAID"
    else:
        inv["payment_status"] = "PAID"
    db.touch(inv)


@app.route("/ledger/invoice-payments", methods=["POST"])
def create_invoice_payment():
    auth(["Bookkeeper", "Accountant"])
    body = util.get_json_body()
    util.require_fields(
        body, ["company_id", "invoice_id", "deposit_bank_account_id", "amount_cents"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    inv = db.invoices.get(body["invoice_id"])
    if inv is None:
        raise errors.not_found("Invoice not found")
    bank = db.bank_accounts.get(body["deposit_bank_account_id"])
    if bank is None:
        raise errors.not_found("Bank account not found")
    # state: invoice must be SENT.
    if inv["delivery_status"] != "SENT":
        raise errors.invalid_state("Invoice not SENT")
    amount = util.require_int(body, "amount_cents")
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be > 0")
    # priority 16: must not exceed balance_due_cents.
    if amount > inv["balance_due_cents"]:
        raise errors.ApiError(errors.ERR_PAYMENT_EXCEEDS_BALANCE, 409,
                              "Payment exceeds invoice balance")
    company = db.companies[inv["company_id"]]
    period = db.accounting_periods.get(company.get("current_period_id"))

    # post receipt entry: debit cash (bank gl), credit AR.
    customer = db.customers[inv["customer_id"]]
    entry = ledger.create_system_entry(
        company_id=company["id"],
        period_id=period["id"] if period else None,
        entry_date=inv["issue_date"],
        source="MANUAL",
        memo="Payment for invoice %s" % inv["id"],
    )
    ledger.add_line(entry["id"], bank["gl_account_id"],
                    debit_cents=amount, credit_cents=0)
    ledger.add_line(entry["id"], customer["ar_account_id"],
                    debit_cents=0, credit_cents=amount)
    ledger.post_entry(entry)

    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "invoice_id": body["invoice_id"],
            "deposit_bank_account_id": body["deposit_bank_account_id"],
            "amount_cents": amount,
            "status": "CLEARED",
            "journal_entry_id": entry["id"],
        }
    )
    db.invoice_payments[rec["id"]] = rec
    _recompute_invoice_payment_state(inv)
    return object_response(serialize(rec), 201)


@app.route("/ledger/invoice-payments/<payment_id>", methods=["GET"])
def get_invoice_payment(payment_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.invoice_payments, payment_id)
    return object_response(serialize(rec))


@app.route("/ledger/invoice-payments", methods=["GET"])
def list_invoice_payments():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.invoice_payments.values())
    for key in ("company_id", "invoice_id", "deposit_bank_account_id",
                "journal_entry_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/invoice-payments/<payment_id>/reverse", methods=["POST"])
def reverse_invoice_payment(payment_id):
    auth(["Accountant", "Owner"])
    pay = util.get_or_404(db.invoice_payments, payment_id)
    if pay["status"] != "CLEARED":
        raise errors.invalid_state("Payment not CLEARED")
    inv = db.invoices[pay["invoice_id"]]
    company = db.companies[inv["company_id"]]
    period = db.accounting_periods.get(company.get("current_period_id"))
    # priority 11: closed period -> ERR_PERIOD_CLOSED.
    require_period_open_for_void(period)
    je = db.journal_entries.get(pay["journal_entry_id"])
    if je and je["status"] == "POSTED":
        ledger.reverse_entry(je)
        je["status"] = "VOIDED"
        db.touch(je)
    pay["status"] = "REVERSED"
    db.touch(pay)
    _recompute_invoice_payment_state(inv)
    return object_response(serialize(pay))


# ===========================================================================
# Vendor / Bill (PRD §3.8, §2.10)
# ===========================================================================
@app.route("/ledger/vendors", methods=["POST"])
def create_vendor():
    auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(body, ["company_id", "display_name", "ap_account_id"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    util.get_account_or_404(body["ap_account_id"])
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "display_name": body["display_name"],
            "is_1099_eligible": bool(body.get("is_1099_eligible", False)),
            "ap_account_id": body["ap_account_id"],
            "ytd_1099_total_cents": 0,
        }
    )
    db.vendors[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.vendors, vendor_id)
    return object_response(serialize(rec))


@app.route("/ledger/vendors", methods=["GET"])
def list_vendors():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.vendors.values())
    for key in ("company_id", "ap_account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [v for v in items if v.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


def _company_tax_year(company):
    """Tax year = calendar year of the company's current open period start_date
    (PRD §3.8). Returns (year_int) or None when no current period."""
    pid = company.get("current_period_id")
    if not pid:
        return None
    period = db.accounting_periods.get(pid)
    if not period:
        return None
    return util.parse_dt(period["start_date"]).year


def _compute_vendor_1099(vendor):
    """vendor_1099_total (SCAFFOLD §1.3 / PRD §3.8)."""
    if not vendor["is_1099_eligible"]:
        return 0
    company = db.companies[vendor["company_id"]]
    year = _company_tax_year(company)
    vendor_bills = [b for b in db.bills.values() if b["vendor_id"] == vendor["id"]]
    if company["accounting_basis"] == "ACCRUAL":
        total = 0
        for b in vendor_bills:
            if b["status"] == "VOID":
                continue
            if year is not None and util.parse_dt(b["bill_date"]).year != year:
                continue
            total += b["total_cents"]
        return total
    else:  # CASH
        return sum(b["paid_in_tax_year"] for b in vendor_bills)


def _recompute_vendor_1099(vendor):
    vendor["ytd_1099_total_cents"] = _compute_vendor_1099(vendor)
    db.touch(vendor)


@app.route("/ledger/vendors/<vendor_id>/1099", methods=["GET"])
def get_vendor_1099(vendor_id):
    auth(["Owner", "Accountant", "Auditor"])
    vendor = util.get_or_404(db.vendors, vendor_id)
    company = db.companies[vendor["company_id"]]
    total = _compute_vendor_1099(vendor)
    return object_response({
        "vendor_id": vendor_id,
        "basis": company["accounting_basis"],
        "ytd_1099_total_cents": total,
        "is_1099_eligible": vendor["is_1099_eligible"],
    })


@app.route("/ledger/bills", methods=["POST"])
def create_bill():
    auth(["Owner", "Accountant", "Bookkeeper"])
    body = util.get_json_body()
    util.require_fields(
        body, ["company_id", "vendor_id", "expense_account_id", "bill_date", "lines"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    if db.vendors.get(body["vendor_id"]) is None:
        raise errors.not_found("Vendor not found")
    util.get_account_or_404(body["expense_account_id"])
    util.parse_dt(body["bill_date"])
    lines = body["lines"]
    if not isinstance(lines, list):
        raise errors.invalid_request("lines must be a list")
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "vendor_id": body["vendor_id"],
            "expense_account_id": body["expense_account_id"],
            "bill_date": body["bill_date"],
            "lines": lines,
            "applied_tax_rate_bps": 0,
            "subtotal_cents": 0,
            "use_tax_cents": 0,
            "total_cents": 0,
            "amount_paid_cents": 0,
            "paid_in_tax_year": 0,
            "status": "DRAFT",
        }
    )
    db.bills[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/bills/<bill_id>", methods=["GET"])
def get_bill(bill_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.bills, bill_id)
    return object_response(serialize(rec))


@app.route("/ledger/bills", methods=["GET"])
def list_bills():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.bills.values())
    for key in ("company_id", "vendor_id", "expense_account_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


@app.route("/ledger/bills/<bill_id>/approve", methods=["POST"])
def approve_bill(bill_id):
    auth(["Accountant", "Owner"])
    bill = util.get_or_404(db.bills, bill_id)
    if bill["status"] != "DRAFT":
        raise errors.invalid_state("Bill not DRAFT")
    # priority 15: non-empty lines.
    if not bill["lines"]:
        raise errors.ApiError(errors.ERR_BILL_EMPTY, 422, "Bill has no lines")
    company = db.companies[bill["company_id"]]
    # priority 10: current period OPEN, bill_date within it.
    period = require_open_current_period(company, bill["bill_date"])
    vendor = db.vendors[bill["vendor_id"]]

    # capture use-tax rate from company's default jurisdiction. The PRD calls it
    # "the company's default jurisdiction"; no explicit company field exists for
    # it, so the use-tax rate is captured from any TaxRate of the company
    # effective on bill_date (the company-level default). We pick the rate whose
    # window covers bill_date regardless of jurisdiction; if multiple, the most
    # recently created wins. 0 if none.
    rate_bps = 0
    on_date = util.parse_dt(bill["bill_date"])
    candidates = []
    for tr in db.tax_rates.values():
        if tr["company_id"] != company["id"]:
            continue
        if util.parse_dt(tr["effective_from"]) <= on_date < util.parse_dt(tr["effective_to"]):
            candidates.append(tr)
    if candidates:
        candidates.sort(key=lambda t: t["_seq"])
        rate_bps = candidates[-1]["rate_bps"]
    bill["applied_tax_rate_bps"] = rate_bps

    totals = calc.bill_use_tax_total(bill["lines"], rate_bps)
    bill.update(totals)

    # post MANUAL entry: debit expense (subtotal + use_tax), credit AP (total).
    entry = ledger.create_system_entry(
        company_id=company["id"],
        period_id=period["id"],
        entry_date=bill["bill_date"],
        source="MANUAL",
        memo="Bill %s" % bill["id"],
    )
    ledger.add_line(entry["id"], bill["expense_account_id"],
                    debit_cents=totals["subtotal_cents"] + totals["use_tax_cents"],
                    credit_cents=0)
    ledger.add_line(entry["id"], vendor["ap_account_id"],
                    debit_cents=0, credit_cents=totals["total_cents"])
    ledger.post_entry(entry)

    bill["status"] = "APPROVED"
    db.touch(bill)
    _recompute_vendor_1099(vendor)
    return object_response(serialize(bill))


@app.route("/ledger/bills/<bill_id>/record-payment", methods=["POST"])
def record_bill_payment(bill_id):
    auth(["Accountant", "Owner"])
    bill = util.get_or_404(db.bills, bill_id)
    if bill["status"] not in ("APPROVED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Bill not payable")
    body = util.get_json_body()
    util.require_fields(body, ["pay_from_bank_account_id", "amount_cents", "payment_date"])
    bank = db.bank_accounts.get(body["pay_from_bank_account_id"])
    if bank is None:
        raise errors.not_found("Bank account not found")
    amount = util.require_int(body, "amount_cents")
    util.parse_dt(body["payment_date"])
    company = db.companies[bill["company_id"]]
    # priority 10: current period OPEN, payment_date within it.
    period = require_open_current_period(company, body["payment_date"])
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be > 0")
    # priority 16: must not exceed remaining total.
    new_paid = bill["amount_paid_cents"] + amount
    if new_paid > bill["total_cents"]:
        raise errors.ApiError(errors.ERR_BILL_OVERPAY, 409, "Payment overpays bill")

    vendor = db.vendors[bill["vendor_id"]]
    # post MANUAL entry: debit AP, credit bank gl.
    entry = ledger.create_system_entry(
        company_id=company["id"],
        period_id=period["id"],
        entry_date=body["payment_date"],
        source="MANUAL",
        memo="Bill payment %s" % bill["id"],
    )
    ledger.add_line(entry["id"], vendor["ap_account_id"],
                    debit_cents=amount, credit_cents=0)
    ledger.add_line(entry["id"], bank["gl_account_id"],
                    debit_cents=0, credit_cents=amount)
    ledger.post_entry(entry)

    bill["amount_paid_cents"] = new_paid
    # paid_in_tax_year: sum of payments whose payment date falls in the company
    # tax year (PRD §3.8). Track via the company tax year of the payment date.
    pay_year = util.parse_dt(body["payment_date"]).year
    tax_year = _company_tax_year(company)
    if tax_year is None or pay_year == tax_year:
        bill["paid_in_tax_year"] = bill.get("paid_in_tax_year", 0) + amount

    if new_paid == bill["total_cents"]:
        bill["status"] = "PAID"
    else:
        bill["status"] = "PARTIALLY_PAID"
    db.touch(bill)
    _recompute_vendor_1099(vendor)
    return object_response(serialize(bill))


@app.route("/ledger/bills/<bill_id>/void", methods=["POST"])
def void_bill(bill_id):
    auth(["Accountant", "Owner"])
    bill = util.get_or_404(db.bills, bill_id)
    # void permitted only from DRAFT.
    if bill["status"] != "DRAFT":
        raise errors.invalid_state("Bill not DRAFT")
    bill["status"] = "VOID"
    db.touch(bill)
    return object_response(serialize(bill))


# ===========================================================================
# TaxRate (PRD §2.10)
# ===========================================================================
@app.route("/ledger/tax-rates", methods=["POST"])
def create_tax_rate():
    auth(["Owner", "Accountant"])
    body = util.get_json_body()
    util.require_fields(
        body, ["company_id", "jurisdiction", "rate_bps", "effective_from", "effective_to"])
    if db.companies.get(body["company_id"]) is None:
        raise errors.not_found("Company not found")
    rate_bps = util.require_int(body, "rate_bps", min_value=0)
    ef = util.parse_dt(body["effective_from"])
    et = util.parse_dt(body["effective_to"])
    # priority 9: no overlap with an existing rate for the same jurisdiction.
    for tr in db.tax_rates.values():
        if tr["company_id"] != body["company_id"]:
            continue
        if tr["jurisdiction"] != body["jurisdiction"]:
            continue
        ex_from = util.parse_dt(tr["effective_from"])
        ex_to = util.parse_dt(tr["effective_to"])
        # half-open [from, to) overlap test.
        if ef < ex_to and ex_from < et:
            raise errors.ApiError(errors.ERR_TAX_RATE_OVERLAP, 409,
                                  "Tax rate window overlaps an existing rate")
    rec = db.make_record(
        {
            "company_id": body["company_id"],
            "jurisdiction": body["jurisdiction"],
            "rate_bps": rate_bps,
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
        }
    )
    db.tax_rates[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@app.route("/ledger/tax-rates/<tax_rate_id>", methods=["GET"])
def get_tax_rate(tax_rate_id):
    auth(ALL_ROLES)
    rec = util.get_or_404(db.tax_rates, tax_rate_id)
    return object_response(serialize(rec))


@app.route("/ledger/tax-rates", methods=["GET"])
def list_tax_rates():
    auth(ALL_ROLES)
    from flask import request
    items = list(db.tax_rates.values())
    for key in ("company_id", "jurisdiction"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    page, limit, offset, total = util.paginate(items)
    return array_response(serialize_list(page), limit, offset, total)


# ===========================================================================
# Financial statements (PRD §3.10)
# ===========================================================================
@app.route("/ledger/companies/<company_id>/financial-statements", methods=["GET"])
def financial_statements(company_id):
    auth(["Owner", "Accountant", "Auditor"])
    company = util.get_company_or_404(company_id)
    ledger.recompute_trial_balance(company_id)
    total_revenue = 0
    total_expense = 0
    total_assets = 0
    total_liabilities = 0
    total_equity = 0
    for acct in db.accounts.values():
        if acct["company_id"] != company_id:
            continue
        bal = ledger.account_balance(acct["id"], include_drafts=False)
        t = acct["account_type"]
        if t == "REVENUE":
            total_revenue += bal
        elif t == "EXPENSE":
            total_expense += bal
        elif t == "ASSET":
            total_assets += bal
        elif t == "LIABILITY":
            total_liabilities += bal
        elif t == "EQUITY":
            total_equity += bal
    net_income = total_revenue - total_expense
    return object_response({
        "trial_balance_status": company["trial_balance_status"],
        "total_revenue_cents": total_revenue,
        "total_expense_cents": total_expense,
        "net_income_cents": net_income,
        "total_assets_cents": total_assets,
        "total_liabilities_cents": total_liabilities,
        "total_equity_cents": total_equity,
    })


if __name__ == "__main__":
    db.reset_all()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

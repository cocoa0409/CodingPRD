"""Fractional CFO & Outsourced Accounting API — Flask entry point.

In-memory only; no seeding at startup. Boots clean on every process start.
"""
import os

from flask import Flask, request, g

from errors import (ApiError, err,
                    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ONBOARDING_INCOMPLETE, ERR_OPEN_CLOSES_EXIST,
                    ERR_DECEMBER_CLOSE_NOT_FINAL, ERR_CLOSE_FINALIZED,
                    ERR_NO_LEDGER_ACCOUNTS, ERR_CROSS_CLIENT_PARENT,
                    ERR_DUPLICATE_ACCOUNT_CODE, ERR_DUPLICATE_PERIOD,
                    ERR_PAY_PERIOD_OVERLAP, ERR_COVENANT_BREACH,
                    ERR_UNDERPAYMENT, ERR_MISSING_SCHEDULE_DATE,
                    ERR_STALE_VERSION, ERR_INVALID_PERIOD,
                    ERR_INVALID_TASK_STATUS, ERR_NEGATIVE_AMOUNT)
from response import success, list_success, error_response
from store import store, parse_iso, clock_now
from helpers import (get_body, require_str, require_int, opt_int,
                     require_field_present, base_record, touch, public,
                     paginate, get_or_404, client_contact_guard)
from auth import require_roles
import calc

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = get_body()
    to_iso = require_field_present(body, "to_iso8601")
    if not isinstance(to_iso, str):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a string.")
    try:
        parse_iso(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant.")
    store.clock_iso = to_iso
    return success({}, status=200)


# ===========================================================================
# Client CRUD + onboarding/engagement
# ===========================================================================
def client_view(c):
    return public(c)


@app.route("/clients", methods=["POST"])
@require_roles("CFO", "PlatformAdmin")
def create_client():
    body = get_body()
    legal_name = require_str(body, "legal_name")
    state_code = require_str(body, "state_code")
    retainer_tier = require_str(body, "retainer_tier")
    if retainer_tier not in calc.TIER_TABLE:
        raise err(ERR_INVALID_REQUEST, "Invalid retainer_tier.")
    covenant_floor = opt_int(body, "covenant_floor_cents", 0)
    included = calc.TIER_TABLE[retainer_tier]["included_txns"]
    rec = base_record({
        "legal_name": legal_name,
        "state_code": state_code,
        "retainer_tier": retainer_tier,
        "onboarding_status": "LEAD",
        "engagement_status": "PROSPECT",
        "included_txn_count": included,
        "catchup_active": False,
        "covenant_floor_cents": covenant_floor,
        "open_close_count": 0,
    })
    store.clients[rec["id"]] = rec
    return success(client_view(rec), status=201)


@app.route("/clients", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "PlatformAdmin")
def list_clients():
    rows = list(store.clients.values())
    eng = request.args.get("engagement_status")
    if eng is not None:
        rows = [c for c in rows if c["engagement_status"] == eng]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/clients/<cid>", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def get_client(cid):
    c = get_or_404(store.clients, cid)
    client_contact_guard(c["id"])
    return success(client_view(c))


@app.route("/clients/<cid>/schedule-kickoff", methods=["POST"])
@require_roles("CFO")
def schedule_kickoff(cid):
    c = get_or_404(store.clients, cid)
    if c["onboarding_status"] != "LEAD":
        raise err(ERR_INVALID_STATE, "Client is not in LEAD.")
    c["onboarding_status"] = "KICKOFF_SCHEDULED"
    touch(c)
    return success(client_view(c))


@app.route("/clients/<cid>/start-ledger-setup", methods=["POST"])
@require_roles("Bookkeeper")
def start_ledger_setup(cid):
    c = get_or_404(store.clients, cid)
    if c["onboarding_status"] != "KICKOFF_SCHEDULED":
        raise err(ERR_INVALID_STATE, "Client is not in KICKOFF_SCHEDULED.")
    c["onboarding_status"] = "LEDGER_SETUP"
    touch(c)
    return success(client_view(c))


@app.route("/clients/<cid>/complete-onboarding", methods=["POST"])
@require_roles("CFO")
def complete_onboarding(cid):
    c = get_or_404(store.clients, cid)
    if c["onboarding_status"] != "LEDGER_SETUP":
        raise err(ERR_INVALID_STATE, "Client is not in LEDGER_SETUP.")
    has_active = any(a["client_id"] == cid and a["status"] == "ACTIVE"
                     for a in store.ledger_accounts.values())
    if not has_active:
        raise err(ERR_NO_LEDGER_ACCOUNTS, "No ACTIVE ledger account exists.")
    c["onboarding_status"] = "ONBOARDED"
    touch(c)
    return success(client_view(c))


@app.route("/clients/<cid>/activate-engagement", methods=["POST"])
@require_roles("CFO")
def activate_engagement(cid):
    c = get_or_404(store.clients, cid)
    if c["engagement_status"] not in ("PROSPECT", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Engagement is not in PROSPECT or PAUSED.")
    if c["onboarding_status"] != "ONBOARDED":
        raise err(ERR_ONBOARDING_INCOMPLETE, "Onboarding is not complete.")
    c["engagement_status"] = "ACTIVE"
    touch(c)
    return success(client_view(c))


@app.route("/clients/<cid>/pause-engagement", methods=["POST"])
@require_roles("CFO")
def pause_engagement(cid):
    c = get_or_404(store.clients, cid)
    if c["engagement_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Engagement is not ACTIVE.")
    c["engagement_status"] = "PAUSED"
    touch(c)
    return success(client_view(c))


@app.route("/clients/<cid>/offboard", methods=["POST"])
@require_roles("CFO")
def offboard(cid):
    c = get_or_404(store.clients, cid)
    if c["engagement_status"] not in ("ACTIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Engagement is not ACTIVE or PAUSED.")
    if c["open_close_count"] != 0:
        raise err(ERR_OPEN_CLOSES_EXIST, "Client has non-finalized closes.")
    c["engagement_status"] = "OFFBOARDED"
    touch(c)
    # cascade: non-terminal catch-up projects -> CANCELLED
    non_terminal = {"DRAFT", "SCOPED", "IN_PROGRESS", "CLIENT_REVIEW", "REVISION"}
    for p in store.catchup_projects.values():
        if p["client_id"] == cid and p["status"] in non_terminal:
            p["status"] = "CANCELLED"
            touch(p)
    calc.reconcile_catchup_active(c)
    return success(client_view(c))


# ===========================================================================
# LedgerAccount
# ===========================================================================
@app.route("/clients/<cid>/ledger-accounts", methods=["POST"])
@require_roles("Bookkeeper", "CFO")
def create_ledger_account(cid):
    c = get_or_404(store.clients, cid)
    body = get_body()
    account_code = require_str(body, "account_code")
    account_type = require_str(body, "account_type")
    name = require_str(body, "name")
    if account_type not in ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"):
        raise err(ERR_INVALID_REQUEST, "Invalid account_type.")
    parent_id = body.get("parent_account_id")
    if parent_id is not None:
        parent = store.ledger_accounts.get(parent_id)
        if (parent is None or parent["client_id"] != cid
                or parent["status"] != "ACTIVE"):
            raise err(ERR_CROSS_CLIENT_PARENT, "Invalid parent account.")
    # uniqueness across non-ARCHIVED accounts of this client
    for a in store.ledger_accounts.values():
        if (a["client_id"] == cid and a["status"] != "ARCHIVED"
                and a["account_code"] == account_code):
            raise err(ERR_DUPLICATE_ACCOUNT_CODE, "Duplicate account_code.")
    rec = base_record({
        "client_id": cid,
        "parent_account_id": parent_id,
        "account_code": account_code,
        "account_type": account_type,
        "name": name,
        "status": "ACTIVE",
    })
    store.ledger_accounts[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/ledger-accounts", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def list_ledger_accounts(cid):
    get_or_404(store.clients, cid)
    rows = [a for a in store.ledger_accounts.values() if a["client_id"] == cid]
    parent = request.args.get("parent_account_id")
    if parent is not None:
        rows = [a for a in rows if a["parent_account_id"] == parent]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/ledger-accounts/<aid>", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def get_ledger_account(aid):
    a = get_or_404(store.ledger_accounts, aid)
    return success(public(a))


@app.route("/ledger-accounts/<aid>/children", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def list_ledger_children(aid):
    get_or_404(store.ledger_accounts, aid)
    rows = [a for a in store.ledger_accounts.values()
            if a["parent_account_id"] == aid]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/ledger-accounts/<aid>/archive", methods=["POST"])
@require_roles("CFO")
def archive_ledger_account(aid):
    a = get_or_404(store.ledger_accounts, aid)
    if a["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Account is not ACTIVE.")
    a["status"] = "ARCHIVED"
    touch(a)
    return success(public(a))


# ===========================================================================
# CatchupProject
# ===========================================================================
@app.route("/clients/<cid>/catchup-projects", methods=["POST"])
@require_roles("CFO")
def create_catchup(cid):
    c = get_or_404(store.clients, cid)
    body = get_body()
    months_behind = require_int(body, "months_behind")
    quoted_fee = require_int(body, "quoted_fee_cents")
    if months_behind < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "months_behind must be >= 1.")
    if quoted_fee < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "quoted_fee_cents must be >= 1.")
    rec = base_record({
        "client_id": cid,
        "months_behind": months_behind,
        "status": "DRAFT",
        "revision_rounds": 0,
        "quoted_fee_cents": quoted_fee,
    })
    store.catchup_projects[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/catchup-projects", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def list_catchup(cid):
    get_or_404(store.clients, cid)
    client_contact_guard(cid)
    rows = [p for p in store.catchup_projects.values() if p["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/catchup-projects/<pid>", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def get_catchup(pid):
    p = get_or_404(store.catchup_projects, pid)
    client_contact_guard(p["client_id"])
    return success(public(p))


def _catchup_transition(pid, allowed_from, new_status, role_check_done=True):
    p = get_or_404(store.catchup_projects, pid)
    if p["status"] not in allowed_from:
        raise err(ERR_INVALID_STATE, "Invalid catch-up project state.")
    return p


@app.route("/catchup-projects/<pid>/scope", methods=["POST"])
@require_roles("CFO")
def scope_catchup(pid):
    p = _catchup_transition(pid, {"DRAFT"}, "SCOPED")
    p["status"] = "SCOPED"
    touch(p)
    c = store.clients[p["client_id"]]
    calc.reconcile_catchup_active(c)
    return success(public(p))


@app.route("/catchup-projects/<pid>/start", methods=["POST"])
@require_roles("Bookkeeper")
def start_catchup(pid):
    p = _catchup_transition(pid, {"SCOPED"}, "IN_PROGRESS")
    p["status"] = "IN_PROGRESS"
    touch(p)
    calc.reconcile_catchup_active(store.clients[p["client_id"]])
    return success(public(p))


@app.route("/catchup-projects/<pid>/submit-for-review", methods=["POST"])
@require_roles("Bookkeeper")
def submit_catchup(pid):
    p = _catchup_transition(pid, {"IN_PROGRESS", "REVISION"}, "CLIENT_REVIEW")
    p["status"] = "CLIENT_REVIEW"
    touch(p)
    calc.reconcile_catchup_active(store.clients[p["client_id"]])
    return success(public(p))


@app.route("/catchup-projects/<pid>/reject", methods=["POST"])
@require_roles("ClientContact")
def reject_catchup(pid):
    p = get_or_404(store.catchup_projects, pid)
    client_contact_guard(p["client_id"])
    if p["status"] != "CLIENT_REVIEW":
        raise err(ERR_INVALID_STATE, "Project is not in CLIENT_REVIEW.")
    p["status"] = "REVISION"
    p["revision_rounds"] += 1
    touch(p)
    calc.reconcile_catchup_active(store.clients[p["client_id"]])
    return success(public(p))


@app.route("/catchup-projects/<pid>/approve", methods=["POST"])
@require_roles("ClientContact")
def approve_catchup(pid):
    p = get_or_404(store.catchup_projects, pid)
    client_contact_guard(p["client_id"])
    if p["status"] != "CLIENT_REVIEW":
        raise err(ERR_INVALID_STATE, "Project is not in CLIENT_REVIEW.")
    p["status"] = "COMPLETED"
    touch(p)
    calc.reconcile_catchup_active(store.clients[p["client_id"]])
    return success(public(p))


@app.route("/catchup-projects/<pid>/cancel", methods=["POST"])
@require_roles("CFO")
def cancel_catchup(pid):
    p = get_or_404(store.catchup_projects, pid)
    non_terminal = {"DRAFT", "SCOPED", "IN_PROGRESS", "CLIENT_REVIEW", "REVISION"}
    if p["status"] not in non_terminal:
        raise err(ERR_INVALID_STATE, "Project is terminal.")
    p["status"] = "CANCELLED"
    touch(p)
    calc.reconcile_catchup_active(store.clients[p["client_id"]])
    return success(public(p))


# ===========================================================================
# MonthlyClose + CloseTask
# ===========================================================================
@app.route("/clients/<cid>/monthly-closes", methods=["POST"])
@require_roles("Bookkeeper", "CFO")
def create_close(cid):
    c = get_or_404(store.clients, cid)
    body = get_body()
    period_year = require_int(body, "period_year")
    period_month = require_int(body, "period_month")
    txn_count = opt_int(body, "txn_count", 0)
    if period_month < 1 or period_month > 12:
        raise err(ERR_INVALID_PERIOD, "period_month must be 1..12.")
    # duplicate non-finalized period for same client
    for mc in store.monthly_closes.values():
        if (mc["client_id"] == cid and mc["status"] != "FINALIZED"
                and mc["period_year"] == period_year
                and mc["period_month"] == period_month):
            raise err(ERR_DUPLICATE_PERIOD, "Duplicate open period.")
    rec = base_record({
        "client_id": cid,
        "period_year": period_year,
        "period_month": period_month,
        "status": "OPEN",
        "review_status": "NOT_STARTED",
        "txn_count": txn_count,
        "completion_pct": 0,
        "provisional_completion_pct": 0,
    })
    store.monthly_closes[rec["id"]] = rec
    calc.reconcile_open_close_count(c)
    return success(public(rec), status=201)


@app.route("/clients/<cid>/monthly-closes", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "ClientContact", "PlatformAdmin")
def list_closes(cid):
    get_or_404(store.clients, cid)
    client_contact_guard(cid)
    rows = [m for m in store.monthly_closes.values() if m["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    py = request.args.get("period_year")
    if py is not None:
        try:
            py_i = int(py)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "period_year must be an integer.")
        rows = [m for m in rows if m["period_year"] == py_i]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/monthly-closes/<mid>", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "ClientContact", "PlatformAdmin")
def get_close(mid):
    m = get_or_404(store.monthly_closes, mid)
    client_contact_guard(m["client_id"])
    return success(public(m))


@app.route("/monthly-closes/<mid>/close-tasks", methods=["POST"])
@require_roles("Bookkeeper", "CFO")
def create_close_task(mid):
    m = get_or_404(store.monthly_closes, mid)
    body = get_body()
    name = require_str(body, "name")
    weight = require_int(body, "weight")
    if weight < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "weight must be >= 1.")
    rec = base_record({
        "monthly_close_id": mid,
        "name": name,
        "weight": weight,
        "status": "PENDING",
        "blocking_reason": None,
    })
    store.close_tasks[rec["id"]] = rec
    # creating a PENDING task does not move it out of PENDING; recompute pcts
    calc.recompute_close_completion(m)
    touch(m)
    return success(public(rec), status=201)


@app.route("/monthly-closes/<mid>/close-tasks", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "ClientContact", "PlatformAdmin")
def list_close_tasks(mid):
    m = get_or_404(store.monthly_closes, mid)
    client_contact_guard(m["client_id"])
    rows = [t for t in store.close_tasks.values() if t["monthly_close_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/monthly-closes/<mid>/payroll-runs", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def list_close_payroll_runs(mid):
    get_or_404(store.monthly_closes, mid)
    rows = [r for r in store.payroll_runs.values() if r["monthly_close_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/monthly-closes/<mid>/retainer-invoices", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "PlatformAdmin")
def list_close_retainers(mid):
    get_or_404(store.monthly_closes, mid)
    rows = [r for r in store.retainer_invoices.values()
            if r["monthly_close_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


CLOSE_TASK_STATUSES = {"PENDING", "IN_REVIEW", "DONE", "WAIVED", "BLOCKED"}


@app.route("/close-tasks/<tid>/transition", methods=["POST"])
@require_roles("Bookkeeper", "CFO")
def transition_close_task(tid):
    t = get_or_404(store.close_tasks, tid)
    body = get_body()
    to_status = require_field_present(body, "to_status")
    if not isinstance(to_status, str) or to_status not in CLOSE_TASK_STATUSES:
        raise err(ERR_INVALID_TASK_STATUS, "Invalid to_status.")
    m = store.monthly_closes[t["monthly_close_id"]]
    was_pending = (t["status"] == "PENDING")
    t["status"] = to_status
    if to_status == "BLOCKED":
        t["blocking_reason"] = body.get("blocking_reason")
    touch(t)

    # bubble-up: OPEN/REOPENED -> IN_PROGRESS when a task leaves PENDING
    if was_pending and to_status != "PENDING" and m["status"] in ("OPEN", "REOPENED"):
        if m["status"] == "REOPENED":
            m["review_status"] = "NOT_STARTED"
        m["status"] = "IN_PROGRESS"

    completion, _prov = calc.recompute_close_completion(m)

    # bubble-up: IN_PROGRESS -> READY_FOR_REVIEW when final completion == 100
    if m["status"] == "IN_PROGRESS" and completion == 100:
        m["status"] = "READY_FOR_REVIEW"
        m["review_status"] = "UNDER_REVIEW"

    touch(m)
    return success(public(t))


@app.route("/monthly-closes/<mid>/approve-review", methods=["POST"])
@require_roles("CFO")
def approve_review(mid):
    m = get_or_404(store.monthly_closes, mid)
    if m["status"] != "READY_FOR_REVIEW" or m["review_status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Close is not under review.")
    m["review_status"] = "APPROVED"
    touch(m)
    return success(public(m))


@app.route("/monthly-closes/<mid>/request-changes", methods=["POST"])
@require_roles("CFO")
def request_changes(mid):
    m = get_or_404(store.monthly_closes, mid)
    if m["status"] != "READY_FOR_REVIEW" or m["review_status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Close is not under review.")
    body = get_body()
    changed = require_field_present(body, "changed_task_names")
    if not isinstance(changed, list):
        raise err(ERR_INVALID_REQUEST, "changed_task_names must be a list.")
    m["status"] = "REOPENED"
    m["review_status"] = "CHANGES_REQUESTED"
    changed_set = set(changed)
    for t in store.close_tasks.values():
        if (t["monthly_close_id"] == mid and t["status"] == "DONE"
                and t["name"] in changed_set):
            t["status"] = "PENDING"
            touch(t)
    calc.recompute_close_completion(m)
    touch(m)
    return success(public(m))


@app.route("/monthly-closes/<mid>/finalize", methods=["POST"])
@require_roles("CFO")
def finalize_close(mid):
    m = get_or_404(store.monthly_closes, mid)
    if m["status"] != "READY_FOR_REVIEW" or m["review_status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Close is not READY_FOR_REVIEW/APPROVED.")
    m["status"] = "FINALIZED"
    touch(m)
    calc.reconcile_open_close_count(store.clients[m["client_id"]])
    return success(public(m))


# ===========================================================================
# ARInvoice
# ===========================================================================
@app.route("/clients/<cid>/ar-invoices", methods=["POST"])
@require_roles("Bookkeeper", "CFO")
def create_ar_invoice(cid):
    get_or_404(store.clients, cid)
    body = get_body()
    counterparty = require_str(body, "counterparty_name")
    amount = require_int(body, "amount_cents")
    issue_date = require_str(body, "issue_date")
    due_date = require_str(body, "due_date")
    if amount < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "amount_cents must be >= 1.")
    rec = base_record({
        "client_id": cid,
        "counterparty_name": counterparty,
        "amount_cents": amount,
        "issue_date": issue_date,
        "due_date": due_date,
        "status": "OPEN",
        "paid_amount_cents": 0,
    })
    store.ar_invoices[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/ar-invoices", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "ClientContact", "PlatformAdmin")
def list_ar_invoices(cid):
    get_or_404(store.clients, cid)
    client_contact_guard(cid)
    rows = [i for i in store.ar_invoices.values() if i["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/ar-invoices/<iid>", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "ClientContact", "PlatformAdmin")
def get_ar_invoice(iid):
    i = get_or_404(store.ar_invoices, iid)
    client_contact_guard(i["client_id"])
    return success(public(i))


@app.route("/ar-invoices/<iid>/dispute", methods=["POST"])
@require_roles("ClientContact")
def dispute_ar(iid):
    i = get_or_404(store.ar_invoices, iid)
    client_contact_guard(i["client_id"])
    if i["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Invoice is not OPEN.")
    i["status"] = "DISPUTED"
    touch(i)
    return success(public(i))


@app.route("/ar-invoices/<iid>/resolve-dispute", methods=["POST"])
@require_roles("Bookkeeper")
def resolve_dispute(iid):
    i = get_or_404(store.ar_invoices, iid)
    if i["status"] != "DISPUTED":
        raise err(ERR_INVALID_STATE, "Invoice is not DISPUTED.")
    i["status"] = "OPEN"
    touch(i)
    return success(public(i))


@app.route("/ar-invoices/<iid>/record-payment", methods=["POST"])
@require_roles("Bookkeeper")
def record_payment(iid):
    i = get_or_404(store.ar_invoices, iid)
    if i["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Invoice is not OPEN.")
    body = get_body()
    payment = require_int(body, "payment_cents")
    if i["paid_amount_cents"] + payment < i["amount_cents"]:
        raise err(ERR_UNDERPAYMENT, "Payment does not cover the invoice total.")
    i["paid_amount_cents"] += payment
    i["status"] = "PAID"
    touch(i)
    return success(public(i))


@app.route("/ar-invoices/<iid>/write-off", methods=["POST"])
@require_roles("CFO")
def write_off(iid):
    i = get_or_404(store.ar_invoices, iid)
    if i["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Invoice is not OPEN.")
    i["status"] = "WRITTEN_OFF"
    touch(i)
    return success(public(i))


@app.route("/clients/<cid>/ar-summary", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "PlatformAdmin")
def get_ar_summary(cid):
    c = get_or_404(store.clients, cid)
    cs_raw = request.args.get("credit_sales_cents")
    if cs_raw is None:
        raise err(ERR_INVALID_REQUEST, "credit_sales_cents is required.")
    try:
        credit_sales = int(cs_raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "credit_sales_cents must be an integer.")
    summary = calc.ar_summary(c, credit_sales, clock_now())
    return success(summary)


# ===========================================================================
# APBill
# ===========================================================================
@app.route("/clients/<cid>/ap-bills", methods=["POST"])
@require_roles("Bookkeeper")
def create_ap_bill(cid):
    get_or_404(store.clients, cid)
    body = get_body()
    vendor = require_str(body, "vendor_name")
    amount = require_int(body, "amount_cents")
    due_date = require_str(body, "due_date")
    if amount < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "amount_cents must be >= 1.")
    rec = base_record({
        "client_id": cid,
        "vendor_name": vendor,
        "amount_cents": amount,
        "due_date": due_date,
        "status": "ENTERED",
        "scheduled_pay_date": None,
    })
    store.ap_bills[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/ap-bills", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def list_ap_bills(cid):
    get_or_404(store.clients, cid)
    rows = [b for b in store.ap_bills.values() if b["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/ap-bills/<bid>", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def get_ap_bill(bid):
    b = get_or_404(store.ap_bills, bid)
    return success(public(b))


@app.route("/ap-bills/<bid>/approve", methods=["POST"])
@require_roles("CFO")
def approve_ap(bid):
    b = get_or_404(store.ap_bills, bid)
    if b["status"] != "ENTERED":
        raise err(ERR_INVALID_STATE, "Bill is not ENTERED.")
    b["status"] = "APPROVED"
    touch(b)
    return success(public(b))


@app.route("/ap-bills/<bid>/schedule", methods=["POST"])
@require_roles("Bookkeeper")
def schedule_ap(bid):
    b = get_or_404(store.ap_bills, bid)
    if b["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Bill is not APPROVED.")
    body = get_body()
    spd = body.get("scheduled_pay_date")
    if spd is None or not isinstance(spd, str) or spd == "":
        raise err(ERR_MISSING_SCHEDULE_DATE, "scheduled_pay_date is required.")
    b["scheduled_pay_date"] = spd
    b["status"] = "SCHEDULED"
    touch(b)
    return success(public(b))


@app.route("/ap-bills/<bid>/mark-paid", methods=["POST"])
@require_roles("Bookkeeper")
def mark_paid_ap(bid):
    b = get_or_404(store.ap_bills, bid)
    if b["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Bill is not SCHEDULED.")
    b["status"] = "PAID"
    touch(b)
    return success(public(b))


@app.route("/ap-bills/<bid>/void", methods=["POST"])
@require_roles("CFO")
def void_ap(bid):
    b = get_or_404(store.ap_bills, bid)
    if b["status"] not in ("ENTERED", "APPROVED"):
        raise err(ERR_INVALID_STATE, "Bill is not ENTERED or APPROVED.")
    b["status"] = "VOID"
    touch(b)
    return success(public(b))


# ===========================================================================
# PayrollRun + PayrollAllocation
# ===========================================================================
@app.route("/clients/<cid>/payroll-runs", methods=["POST"])
@require_roles("Bookkeeper")
def create_payroll_run(cid):
    get_or_404(store.clients, cid)
    body = get_body()
    mc_id = require_str(body, "monthly_close_id")
    pay_date = require_str(body, "pay_date")
    pp_start = require_str(body, "pay_period_start")
    pp_end = require_str(body, "pay_period_end")
    total = require_int(body, "total_employer_cost_cents")
    # FK existence
    get_or_404(store.monthly_closes, mc_id)
    if total < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "total_employer_cost_cents must be >= 1.")
    new_start = parse_iso(pp_start)
    new_end = parse_iso(pp_end)
    # half-open overlap against non-REVERSED runs of same client
    for r in store.payroll_runs.values():
        if r["client_id"] != cid or r["status"] == "REVERSED":
            continue
        ex_start = parse_iso(r["pay_period_start"])
        ex_end = parse_iso(r["pay_period_end"])
        if new_start < ex_end and ex_start < new_end:
            raise err(ERR_PAY_PERIOD_OVERLAP, "Pay period overlaps an existing run.")
    rec = base_record({
        "client_id": cid,
        "monthly_close_id": mc_id,
        "pay_date": pay_date,
        "pay_period_start": pp_start,
        "pay_period_end": pp_end,
        "total_employer_cost_cents": total,
        "status": "DRAFT",
    })
    store.payroll_runs[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/payroll-runs", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def list_payroll_runs(cid):
    get_or_404(store.clients, cid)
    rows = [r for r in store.payroll_runs.values() if r["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    mc = request.args.get("monthly_close_id")
    if mc is not None:
        rows = [r for r in rows if r["monthly_close_id"] == mc]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/payroll-runs/<rid>", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def get_payroll_run(rid):
    r = get_or_404(store.payroll_runs, rid)
    return success(public(r))


@app.route("/payroll-runs/<rid>/allocations", methods=["POST"])
@require_roles("Bookkeeper")
def add_allocation(rid):
    r = get_or_404(store.payroll_runs, rid)
    body = get_body()
    dept = require_str(body, "department_name")
    gross = require_int(body, "dept_gross_cents")
    if gross < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "dept_gross_cents must be >= 1.")
    rec = base_record({
        "payroll_run_id": rid,
        "department_name": dept,
        "dept_gross_cents": gross,
        "allocated_cents": 0,
    })
    store.payroll_allocations[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/payroll-runs/<rid>/allocations", methods=["GET"])
@require_roles("Bookkeeper", "CFO", "PlatformAdmin")
def list_allocations(rid):
    get_or_404(store.payroll_runs, rid)
    rows = [a for a in store.payroll_allocations.values()
            if a["payroll_run_id"] == rid]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/payroll-runs/<rid>/allocate", methods=["POST"])
@require_roles("Bookkeeper")
def allocate_run(rid):
    r = get_or_404(store.payroll_runs, rid)
    if r["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Run is not DRAFT.")
    has_alloc = any(a["payroll_run_id"] == rid
                    for a in store.payroll_allocations.values())
    if not has_alloc:
        raise err(ERR_INVALID_STATE, "Run has no allocation lines.")
    calc.allocate_payroll(r)
    r["status"] = "ALLOCATED"
    touch(r)
    return success(public(r))


@app.route("/payroll-runs/<rid>/post", methods=["POST"])
@require_roles("CFO")
def post_run(rid):
    r = get_or_404(store.payroll_runs, rid)
    if r["status"] != "ALLOCATED":
        raise err(ERR_INVALID_STATE, "Run is not ALLOCATED.")
    mc = store.monthly_closes[r["monthly_close_id"]]
    if mc["status"] == "FINALIZED":
        raise err(ERR_CLOSE_FINALIZED, "Linked close is FINALIZED.")
    r["status"] = "POSTED"
    touch(r)
    return success(public(r))


@app.route("/payroll-runs/<rid>/reverse", methods=["POST"])
@require_roles("CFO")
def reverse_run(rid):
    r = get_or_404(store.payroll_runs, rid)
    if r["status"] != "POSTED":
        raise err(ERR_INVALID_STATE, "Run is not POSTED.")
    mc = store.monthly_closes[r["monthly_close_id"]]
    if mc["status"] == "FINALIZED":
        raise err(ERR_CLOSE_FINALIZED, "Linked close is FINALIZED.")
    r["status"] = "REVERSED"
    touch(r)
    calc.zero_payroll_allocations(r)
    return success(public(r))


# ===========================================================================
# CashFlowForecast + ForecastLine
# ===========================================================================
@app.route("/clients/<cid>/forecasts", methods=["POST"])
@require_roles("CFO")
def create_forecast(cid):
    get_or_404(store.clients, cid)
    body = get_body()
    opening = require_int(body, "opening_balance_cents")
    rec = base_record({
        "client_id": cid,
        "opening_balance_cents": opening,
        "status": "DRAFT",
        "ending_balance_cents": opening,
        "min_projected_balance_cents": opening,
    })
    store.forecasts[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/forecasts", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "PlatformAdmin")
def list_forecasts(cid):
    get_or_404(store.clients, cid)
    rows = [f for f in store.forecasts.values() if f["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/forecasts/<fid>", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "PlatformAdmin")
def get_forecast(fid):
    f = get_or_404(store.forecasts, fid)
    return success(public(f))


@app.route("/forecasts/<fid>/lines", methods=["POST"])
@require_roles("CFO")
def add_forecast_line(fid):
    f = get_or_404(store.forecasts, fid)
    body = get_body()
    effective_date = require_str(body, "effective_date")
    direction = require_str(body, "direction")
    amount = require_int(body, "amount_cents")
    if direction not in ("INFLOW", "OUTFLOW"):
        raise err(ERR_INVALID_REQUEST, "direction must be INFLOW or OUTFLOW.")
    if amount < 1:
        raise err(ERR_NEGATIVE_AMOUNT, "amount_cents must be >= 1.")
    rec = base_record({
        "forecast_id": fid,
        "effective_date": effective_date,
        "direction": direction,
        "amount_cents": amount,
    })
    store.forecast_lines[rec["id"]] = rec
    calc.recompute_forecast(f)
    touch(f)
    return success(public(rec), status=201)


@app.route("/forecasts/<fid>/lines", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "PlatformAdmin")
def list_forecast_lines(fid):
    get_or_404(store.forecasts, fid)
    rows = [ln for ln in store.forecast_lines.values() if ln["forecast_id"] == fid]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/forecasts/<fid>/approve", methods=["POST"])
@require_roles("CFO")
def approve_forecast(fid):
    f = get_or_404(store.forecasts, fid)
    if f["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Forecast is not DRAFT.")
    c = store.clients[f["client_id"]]
    body = get_body()
    expected = require_int(body, "expected_client_version")
    # business-constraint stage: covenant before OCC? Per validations priority,
    # covenant (14) precedes stale-version (17). Both follow state (4).
    if f["min_projected_balance_cents"] < c["covenant_floor_cents"]:
        raise err(ERR_COVENANT_BREACH, "Minimum projected balance below covenant floor.")
    if expected != c["version"]:
        raise err(ERR_STALE_VERSION, "Stale client version.")
    f["status"] = "APPROVED"
    touch(f)
    for other in store.forecasts.values():
        if (other["client_id"] == c["id"] and other["id"] != f["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(c)
    return success(public(f))


# ===========================================================================
# TaxHandoff
# ===========================================================================
@app.route("/clients/<cid>/tax-handoffs", methods=["POST"])
@require_roles("CFO")
def create_tax_handoff(cid):
    get_or_404(store.clients, cid)
    body = get_body()
    tax_year = require_int(body, "tax_year")
    rec = base_record({
        "client_id": cid,
        "tax_year": tax_year,
        "status": "PREPARING",
        "books_signoff": False,
        "advisory_signoff": False,
    })
    store.tax_handoffs[rec["id"]] = rec
    return success(public(rec), status=201)


@app.route("/clients/<cid>/tax-handoffs", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def list_tax_handoffs(cid):
    get_or_404(store.clients, cid)
    client_contact_guard(cid)
    rows = [h for h in store.tax_handoffs.values() if h["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/tax-handoffs/<hid>", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def get_tax_handoff(hid):
    h = get_or_404(store.tax_handoffs, hid)
    client_contact_guard(h["client_id"])
    return success(public(h))


@app.route("/tax-handoffs/<hid>/start-reviews", methods=["POST"])
@require_roles("CFO")
def start_reviews(hid):
    h = get_or_404(store.tax_handoffs, hid)
    if h["status"] != "PREPARING":
        raise err(ERR_INVALID_STATE, "Handoff is not PREPARING.")
    # December close of tax_year must be FINALIZED for this client
    dec_final = any(
        m["client_id"] == h["client_id"]
        and m["period_year"] == h["tax_year"]
        and m["period_month"] == 12
        and m["status"] == "FINALIZED"
        for m in store.monthly_closes.values()
    )
    if not dec_final:
        raise err(ERR_DECEMBER_CLOSE_NOT_FINAL, "December close not finalized.")
    h["status"] = "BOOKS_REVIEW"
    touch(h)
    return success(public(h))


@app.route("/tax-handoffs/<hid>/books-signoff", methods=["POST"])
@require_roles("Bookkeeper")
def books_signoff(hid):
    h = get_or_404(store.tax_handoffs, hid)
    if h["status"] not in ("BOOKS_REVIEW", "ADVISORY_REVIEW") or h["books_signoff"]:
        raise err(ERR_INVALID_STATE, "Books sign-off not available.")
    h["books_signoff"] = True
    if h["advisory_signoff"]:
        h["status"] = "READY"
    else:
        h["status"] = "ADVISORY_REVIEW"
    touch(h)
    return success(public(h))


@app.route("/tax-handoffs/<hid>/advisory-signoff", methods=["POST"])
@require_roles("CFO")
def advisory_signoff(hid):
    h = get_or_404(store.tax_handoffs, hid)
    if h["status"] not in ("BOOKS_REVIEW", "ADVISORY_REVIEW") or h["advisory_signoff"]:
        raise err(ERR_INVALID_STATE, "Advisory sign-off not available.")
    h["advisory_signoff"] = True
    if h["books_signoff"]:
        h["status"] = "READY"
    else:
        h["status"] = "BOOKS_REVIEW"
    touch(h)
    return success(public(h))


@app.route("/tax-handoffs/<hid>/deliver", methods=["POST"])
@require_roles("CFO")
def deliver_handoff(hid):
    h = get_or_404(store.tax_handoffs, hid)
    if h["status"] != "READY":
        raise err(ERR_INVALID_STATE, "Handoff is not READY.")
    h["status"] = "DELIVERED"
    touch(h)
    return success(public(h))


@app.route("/tax-handoffs/<hid>/mark-returned", methods=["POST"])
@require_roles("CFO")
def mark_returned(hid):
    h = get_or_404(store.tax_handoffs, hid)
    if h["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, "Handoff is not DELIVERED.")
    h["status"] = "RETURNED"
    touch(h)
    return success(public(h))


# ===========================================================================
# RetainerInvoice
# ===========================================================================
@app.route("/clients/<cid>/retainer-invoices", methods=["POST"])
@require_roles("CFO")
def issue_retainer(cid):
    c = get_or_404(store.clients, cid)
    body = get_body()
    mc_id = require_str(body, "monthly_close_id")
    expected = require_int(body, "expected_client_version")
    close = get_or_404(store.monthly_closes, mc_id)
    if expected != c["version"]:
        raise err(ERR_STALE_VERSION, "Stale client version.")
    base_fee, overage, surcharge, total = calc.compute_retainer(c, close)
    rec = base_record({
        "client_id": cid,
        "monthly_close_id": mc_id,
        "base_fee_cents": base_fee,
        "overage_cents": overage,
        "surcharge_cents": surcharge,
        "total_cents": total,
        "status": "ISSUED",
    })
    store.retainer_invoices[rec["id"]] = rec
    touch(c)
    return success(public(rec), status=201)


@app.route("/clients/<cid>/retainer-invoices", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def list_retainers(cid):
    get_or_404(store.clients, cid)
    client_contact_guard(cid)
    rows = [r for r in store.retainer_invoices.values() if r["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    mc = request.args.get("monthly_close_id")
    if mc is not None:
        rows = [r for r in rows if r["monthly_close_id"] == mc]
    items, limit, offset, total = paginate(rows)
    return list_success(items, limit, offset, total)


@app.route("/retainer-invoices/<rid>", methods=["GET"])
@require_roles("CFO", "Bookkeeper", "ClientContact", "PlatformAdmin")
def get_retainer(rid):
    r = get_or_404(store.retainer_invoices, rid)
    client_contact_guard(r["client_id"])
    return success(public(r))


@app.route("/retainer-invoices/<rid>/pay", methods=["POST"])
@require_roles("ClientContact", "CFO")
def pay_retainer(rid):
    r = get_or_404(store.retainer_invoices, rid)
    client_contact_guard(r["client_id"])
    if r["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Invoice is not ISSUED.")
    r["status"] = "PAID"
    touch(r)
    return success(public(r))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

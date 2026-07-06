import os

from flask import Flask, request

import calc
from db import db, stamp_new, touch
from errors import ApiError, err
from middleware import get_user_context, require_role
from response import success, list_response, error_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Enum / constant tables
# ---------------------------------------------------------------------------
ENTITY_TYPES = {"SOLE_PROP", "PARTNERSHIP", "S_CORP", "C_CORP", "LLC"}
ACCOUNTING_BASIS = {"CASH", "ACCRUAL"}
COMPLEXITY_TIERS = {"LOW", "MEDIUM", "HIGH"}
ACCOUNT_TYPES = {"ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"}
SIDES = {"DEBIT", "CREDIT"}
MATCH_KINDS = {"EXACT", "TOLERANCE"}
EXCEPTION_KINDS = {"MISSING_DOC", "UNCATEGORIZED", "UNRECONCILED_DIFF", "DUPLICATE"}
SEVERITIES = {"NORMAL", "BLOCKING"}

ALL_ROLES = ["EngagementManager", "Bookkeeper", "Reviewer", "TaxPreparer"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length and request.content_length > 0:
            try:
                data = request.get_json(force=True, silent=True)
            except Exception:
                data = None
            if data is None:
                raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
            if not isinstance(data, dict):
                raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
            return data
        return {}
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(value, valid, field):
    if value not in valid:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % field)


def require_positive_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a positive integer" % field)


def require_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)


def get_pagination():
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """items already sorted by created_at asc."""
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_client_or_404(cid):
    c = db.clients.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Client not found")
    return c


def get_engagement_or_404(eid):
    e = db.engagements.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Engagement not found")
    return e


def get_account_or_404(aid, engagement_id=None):
    a = db.accounts.get(aid)
    if a is None or (engagement_id is not None and a["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Account not found")
    return a


def get_entry_or_404(eid, engagement_id=None):
    e = db.entries.get(eid)
    if e is None or (engagement_id is not None and e["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Entry not found")
    return e


def get_statement_or_404(sid, engagement_id=None):
    s = db.statements.get(sid)
    if s is None or (engagement_id is not None and s["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Statement not found")
    return s


def get_scope_estimate_or_404(seid, engagement_id=None):
    s = db.scope_estimates.get(seid)
    if s is None or (engagement_id is not None and s["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Scope estimate not found")
    return s


def get_phase_or_404(pid, engagement_id=None):
    p = db.phases.get(pid)
    if p is None or (engagement_id is not None and p["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Phase not found")
    return p


def get_invoice_or_404(iid, engagement_id=None):
    i = db.invoices.get(iid)
    if i is None or (engagement_id is not None and i["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Invoice not found")
    return i


def get_tax_package_or_404(tid, engagement_id=None):
    t = db.tax_packages.get(tid)
    if t is None or (engagement_id is not None and t["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Tax package not found")
    return t


def get_service_plan_or_404(spid, engagement_id=None):
    s = db.service_plans.get(spid)
    if s is None or (engagement_id is not None and s["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Service plan not found")
    return s


def get_exception_or_404(xid, engagement_id=None):
    x = db.exceptions.get(xid)
    if x is None or (engagement_id is not None and x["engagement_id"] != engagement_id):
        raise err("ERR_NOT_FOUND", "Exception not found")
    return x


def get_recon_item_or_404(rid, statement_id=None):
    r = db.recon_items.get(rid)
    if r is None or (statement_id is not None and r["statement_id"] != statement_id):
        raise err("ERR_NOT_FOUND", "Reconciliation item not found")
    return r


# ---------------------------------------------------------------------------
# Children accessors
# ---------------------------------------------------------------------------
def accounts_of(engagement_id):
    return [a for a in db.accounts.values() if a["engagement_id"] == engagement_id]


def entries_of(engagement_id):
    return [e for e in db.entries.values() if e["engagement_id"] == engagement_id]


def entries_of_account(account_id):
    return [e for e in db.entries.values() if e["account_id"] == account_id]


def statements_of(engagement_id):
    return [s for s in db.statements.values() if s["engagement_id"] == engagement_id]


def statements_of_account(account_id):
    return [s for s in db.statements.values() if s["account_id"] == account_id]


def phases_of(engagement_id):
    return [p for p in db.phases.values() if p["engagement_id"] == engagement_id]


def invoices_of(engagement_id):
    return [i for i in db.invoices.values() if i["engagement_id"] == engagement_id]


def exceptions_of(engagement_id):
    return [x for x in db.exceptions.values() if x["engagement_id"] == engagement_id]


def exceptions_of_account(account_id):
    return [x for x in db.exceptions.values() if x.get("account_id") == account_id]


def recon_items_of_statement(statement_id):
    return [r for r in db.recon_items.values() if r["statement_id"] == statement_id]


def tax_packages_of(engagement_id):
    return [t for t in db.tax_packages.values() if t["engagement_id"] == engagement_id]


# ---------------------------------------------------------------------------
# Derived field computation
# ---------------------------------------------------------------------------
def account_book_balance(account_id):
    """Signed running balance from POSTED entries on this account.
    DEBIT and CREDIT relative to normal_side. Use signed by side relative
    to the account's normal side: DEBIT positive for debit-normal accounts."""
    acct = db.accounts.get(account_id)
    normal = acct["normal_side"] if acct else "DEBIT"
    total = 0
    for e in entries_of_account(account_id):
        if e["status"] != "POSTED":
            continue
        signed = e["amount_cents"] if e["side"] == normal else -e["amount_cents"]
        total += signed
    return total


def recompute_account_balance(account):
    account["book_balance_cents"] = account_book_balance(account["id"])


def engagement_reconciled_count(engagement_id):
    return sum(1 for a in accounts_of(engagement_id) if a["status"] == "RECONCILED")


def engagement_total_account_count(engagement_id):
    return sum(1 for a in accounts_of(engagement_id) if a["status"] != "EXCLUDED")


def engagement_open_blocking_count(engagement_id):
    return sum(
        1 for x in exceptions_of(engagement_id)
        if x["severity"] == "BLOCKING" and x["status"] not in ("RESOLVED", "WAIVED")
    )


def compute_recon_status(engagement_id):
    """OUT_OF_BALANCE if any BankStatement is RECONCILING with an OPEN
    out-of-balance UNRECONCILED_DIFF exception; PENDING if any non-EXCLUDED
    is_bank_account account has no RECONCILED statement; otherwise IN_BALANCE."""
    accts = accounts_of(engagement_id)
    bank_accts = [a for a in accts if a.get("is_bank_account") and a["status"] != "EXCLUDED"]

    # OUT_OF_BALANCE check
    open_diff_exists = any(
        x["kind"] == "UNRECONCILED_DIFF" and x["status"] not in ("RESOLVED", "WAIVED")
        for x in exceptions_of(engagement_id)
    )
    reconciling_exists = any(
        s["status"] == "RECONCILING" for s in statements_of(engagement_id)
    )
    if open_diff_exists and reconciling_exists:
        return "OUT_OF_BALANCE"

    # PENDING check
    for a in bank_accts:
        stmts = statements_of_account(a["id"])
        if not any(s["status"] == "RECONCILED" for s in stmts):
            return "PENDING"

    return "IN_BALANCE"


def compute_readiness(engagement):
    return calc.readiness_score(
        engagement_reconciled_count(engagement["id"]),
        engagement_total_account_count(engagement["id"]),
        engagement_open_blocking_count(engagement["id"]),
    )


def recompute_engagement_derived(engagement, bump=True):
    """Recompute engagement derived fields. Per §2.4/§2.7 a derived recompute
    is a mutation that refreshes updated_at and bumps version."""
    engagement["reconciled_account_count"] = engagement_reconciled_count(engagement["id"])
    engagement["total_account_count"] = engagement_total_account_count(engagement["id"])
    engagement["open_blocking_exception_count"] = engagement_open_blocking_count(engagement["id"])
    engagement["recon_status"] = compute_recon_status(engagement["id"])
    engagement["readiness_score"] = compute_readiness(engagement)
    if bump:
        touch(engagement)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def ser_client(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "entity_type": c["entity_type"],
        "accounting_basis": c["accounting_basis"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_engagement(e):
    return {
        "id": e["id"],
        "client_id": e["client_id"],
        "title": e["title"],
        "period_start": e["period_start"],
        "period_end": e["period_end"],
        "complexity_tier": e["complexity_tier"],
        "workflow_status": e["workflow_status"],
        "billing_status": e["billing_status"],
        "scope_locked": e["scope_locked"],
        "estimated_txn_volume": e["estimated_txn_volume"],
        "reconciled_account_count": e["reconciled_account_count"],
        "total_account_count": e["total_account_count"],
        "open_blocking_exception_count": e["open_blocking_exception_count"],
        "readiness_score": e["readiness_score"],
        "recon_status": e["recon_status"],
        "fixed_price_cents": e.get("fixed_price_cents"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_scope_estimate(s):
    return {
        "id": s["id"],
        "engagement_id": s["engagement_id"],
        "monthly_txn_rate": s["monthly_txn_rate"],
        "period_month_count": s["period_month_count"],
        "txn_volume_estimate": s["txn_volume_estimate"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_account(a):
    return {
        "id": a["id"],
        "engagement_id": a["engagement_id"],
        "account_code": a["account_code"],
        "name": a["name"],
        "account_type": a["account_type"],
        "normal_side": a["normal_side"],
        "is_bank_account": a["is_bank_account"],
        "book_balance_cents": a["book_balance_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_entry(e):
    return {
        "id": e["id"],
        "engagement_id": e["engagement_id"],
        "account_id": e["account_id"],
        "txn_date": e["txn_date"],
        "side": e["side"],
        "amount_cents": e["amount_cents"],
        "memo": e["memo"],
        "cash_settled": e["cash_settled"],
        "reconciliation_item_id": e["reconciliation_item_id"],
        "reversed_entry_id": e["reversed_entry_id"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_statement(s):
    return {
        "id": s["id"],
        "engagement_id": s["engagement_id"],
        "account_id": s["account_id"],
        "statement_start": s["statement_start"],
        "statement_end": s["statement_end"],
        "ending_balance_cents": s["ending_balance_cents"],
        "deposits_in_transit_cents": s["deposits_in_transit_cents"],
        "outstanding_checks_cents": s["outstanding_checks_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_recon_item(r):
    return {
        "id": r["id"],
        "statement_id": r["statement_id"],
        "engagement_id": r["engagement_id"],
        "ledger_entry_id": r["ledger_entry_id"],
        "statement_line_amount_cents": r["statement_line_amount_cents"],
        "match_kind": r["match_kind"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_phase(p):
    return {
        "id": p["id"],
        "engagement_id": p["engagement_id"],
        "phase_index": p["phase_index"],
        "label": p["label"],
        "weight_bp": p["weight_bp"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_invoice(i):
    return {
        "id": i["id"],
        "engagement_id": i["engagement_id"],
        "phase_id": i["phase_id"],
        "amount_cents": i["amount_cents"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_tax_package(t):
    return {
        "id": t["id"],
        "engagement_id": t["engagement_id"],
        "basis": t["basis"],
        "net_book_income_cents": t["net_book_income_cents"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_service_plan(s):
    return {
        "id": s["id"],
        "engagement_id": s["engagement_id"],
        "monthly_fee_cents": s["monthly_fee_cents"],
        "conversion_date": s["conversion_date"],
        "first_month_prorated_cents": s["first_month_prorated_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_exception(x):
    return {
        "id": x["id"],
        "engagement_id": x["engagement_id"],
        "account_id": x["account_id"],
        "kind": x["kind"],
        "severity": x["severity"],
        "doc_due_date": x["doc_due_date"],
        "status": x["status"],
        "created_at": x["created_at"],
        "updated_at": x["updated_at"],
        "version": x["version"],
    }


def ser_completion_report(c):
    return {
        "id": c["id"],
        "engagement_id": c["engagement_id"],
        "final_readiness_score": c["final_readiness_score"],
        "reconciled_account_count": c["reconciled_account_count"],
        "total_billed_cents": c["total_billed_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ===========================================================================
# CLIENT
# ===========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    body = get_body()
    require_fields(body, ["legal_name", "entity_type"])
    if not isinstance(body["legal_name"], str) or body["legal_name"] == "":
        raise err("ERR_INVALID_REQUEST", "legal_name must be a non-empty string")
    require_enum(body["entity_type"], ENTITY_TYPES, "entity_type")
    basis = body.get("accounting_basis", "ACCRUAL")
    if basis is None:
        basis = "ACCRUAL"
    require_enum(basis, ACCOUNTING_BASIS, "accounting_basis")
    with db.lock:
        c = stamp_new({
            "legal_name": body["legal_name"],
            "entity_type": body["entity_type"],
            "accounting_basis": basis,
            "status": "ACTIVE",
        })
        db.clients[c["id"]] = c
    return success(ser_client(c), status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    c = get_client_or_404(cid)
    return success(ser_client(c), status=200)


# ===========================================================================
# ENGAGEMENT
# ===========================================================================
@app.route("/engagements", methods=["POST"])
def create_engagement():
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    body = get_body()
    require_fields(body, ["client_id", "title", "period_start", "period_end"])
    tier = body.get("complexity_tier", "MEDIUM")
    if tier is None:
        tier = "MEDIUM"
    require_enum(tier, COMPLEXITY_TIERS, "complexity_tier")
    if not isinstance(body["title"], str) or body["title"] == "":
        raise err("ERR_INVALID_REQUEST", "title required")
    for f in ("period_start", "period_end"):
        if not isinstance(body[f], str):
            raise err("ERR_INVALID_REQUEST", "%s must be an ISO date string" % f)
        try:
            calc.parse_iso_date(body[f])
        except Exception:
            raise err("ERR_INVALID_REQUEST", "%s must be a valid YYYY-MM-DD date" % f)
    with db.lock:
        get_client_or_404(body["client_id"])
        e = stamp_new({
            "client_id": body["client_id"],
            "title": body["title"],
            "period_start": body["period_start"],
            "period_end": body["period_end"],
            "complexity_tier": tier,
            "workflow_status": "DRAFT",
            "billing_status": "UNBILLED",
            "scope_locked": False,
            "estimated_txn_volume": 0,
            "reconciled_account_count": 0,
            "total_account_count": 0,
            "open_blocking_exception_count": 0,
            "readiness_score": 0,
            "recon_status": "IN_BALANCE",
            "fixed_price_cents": None,
        })
        db.engagements[e["id"]] = e
    return success(ser_engagement(e), status=201)


@app.route("/engagements", methods=["GET"])
def list_engagements():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.engagements.values())
    client_id = request.args.get("client_id")
    if client_id:
        items = [e for e in items if e["client_id"] == client_id]
    wf = request.args.get("workflow_status")
    if wf:
        items = [e for e in items if e["workflow_status"] == wf]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_engagement(e) for e in page], limit, offset, total)


@app.route("/engagements/<eid>", methods=["GET"])
def get_engagement(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    e = get_engagement_or_404(eid)
    return success(ser_engagement(e), status=200)


@app.route("/engagements/<eid>/volume-actuals", methods=["GET"])
def volume_actuals(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    e = get_engagement_or_404(eid)
    ps = calc.parse_iso_date(e["period_start"])
    pe = calc.parse_iso_date(e["period_end"])
    count = 0
    for entry in entries_of(eid):
        if entry["status"] != "POSTED":
            continue
        td = calc.parse_iso_date(entry["txn_date"])
        if ps <= td <= pe:
            count += 1
    est = e["estimated_txn_volume"]
    return success({
        "actual_txn_volume": count,
        "estimated_txn_volume": est,
        "variance": count - est,
    }, status=200)


@app.route("/engagements/<eid>/start-scoping", methods=["POST"])
def start_scoping(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["workflow_status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Engagement not in DRAFT")
        e["workflow_status"] = "SCOPING"
        touch(e)
    return success(ser_engagement(e), status=200)


@app.route("/engagements/<eid>/advance-to-reconciliation", methods=["POST"])
def advance_to_reconciliation(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["workflow_status"] != "RECONSTRUCTION":
            raise err("ERR_INVALID_STATE", "Engagement not in RECONSTRUCTION")
        accts = accounts_of(eid)
        if not any(a["status"] in ("CATEGORIZED", "RECONCILED") for a in accts):
            raise err("ERR_NO_CATEGORIZED_ACCOUNTS", "No CATEGORIZED/RECONCILED accounts")
        if any(en["status"] == "DRAFT" for en in entries_of(eid)):
            raise err("ERR_UNPOSTED_ENTRIES", "DRAFT entries remain")
        e["workflow_status"] = "RECONCILIATION"
        touch(e)
    return success(ser_engagement(e), status=200)


@app.route("/engagements/<eid>/quote", methods=["POST"])
def quote(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["billing_status"] != "UNBILLED":
            raise err("ERR_INVALID_STATE", "Billing not in UNBILLED")
        if not e["scope_locked"]:
            raise err("ERR_SCOPE_NOT_LOCKED", "Scope not locked")
        e["fixed_price_cents"] = calc.fixed_price_quote(e["estimated_txn_volume"])
        e["billing_status"] = "QUOTED"
        touch(e)
    return success(ser_engagement(e), status=200)


@app.route("/engagements/<eid>/complete", methods=["POST"])
def complete_engagement(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["workflow_status"] != "TAX_HANDOFF":
            raise err("ERR_INVALID_STATE", "Engagement not in TAX_HANDOFF")
        if e["billing_status"] != "SETTLED":
            raise err("ERR_BILLING_NOT_SETTLED", "Billing not SETTLED")
        if not any(t["status"] == "HANDED_OFF" for t in tax_packages_of(eid)):
            raise err("ERR_TAX_NOT_HANDED_OFF", "No HANDED_OFF tax package")
        total_billed = sum(
            i["amount_cents"] for i in invoices_of(eid) if i["status"] != "VOID"
        )
        report = stamp_new({
            "engagement_id": eid,
            "final_readiness_score": e["readiness_score"],
            "reconciled_account_count": e["reconciled_account_count"],
            "total_billed_cents": total_billed,
            "status": "FINAL",
        })
        db.completion_reports[report["id"]] = report
        e["workflow_status"] = "COMPLETED"
        touch(e)
    return success(ser_engagement(e), status=200)


@app.route("/engagements/<eid>/cancel", methods=["POST"])
def cancel_engagement(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["workflow_status"] not in ("DRAFT", "SCOPING", "RECONSTRUCTION"):
            raise err("ERR_INVALID_STATE", "Engagement cannot be cancelled from this state")
        if e["workflow_status"] == "RECONSTRUCTION":
            if any(i["status"] == "PAID" for i in invoices_of(eid)):
                raise err("ERR_PAID_INVOICES_EXIST", "Paid invoices exist")
        e["workflow_status"] = "CANCELLED"
        touch(e)
    return success(ser_engagement(e), status=200)


# ===========================================================================
# SCOPE ESTIMATE
# ===========================================================================
@app.route("/engagements/<eid>/scope-estimates", methods=["POST"])
def create_scope_estimate(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    body = get_body()
    with db.lock:
        e = get_engagement_or_404(eid)
        require_fields(body, ["monthly_txn_rate"])
        require_positive_int(body["monthly_txn_rate"], "monthly_txn_rate")
        mc = calc.period_month_count(e["period_start"], e["period_end"])
        vol = calc.scope_volume_estimate(mc, body["monthly_txn_rate"], e["complexity_tier"])
        s = stamp_new({
            "engagement_id": eid,
            "monthly_txn_rate": body["monthly_txn_rate"],
            "period_month_count": mc,
            "txn_volume_estimate": vol,
            "status": "PROPOSED",
        })
        db.scope_estimates[s["id"]] = s
    return success(ser_scope_estimate(s), status=201)


@app.route("/engagements/<eid>/scope-estimates", methods=["GET"])
def list_scope_estimates(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = [s for s in db.scope_estimates.values() if s["engagement_id"] == eid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_scope_estimate(s) for s in page], limit, offset, total)


@app.route("/engagements/<eid>/scope-estimates/<seid>/accept", methods=["POST"])
def accept_scope_estimate(eid, seid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    body = get_body()
    with db.lock:
        e = get_engagement_or_404(eid)
        s = get_scope_estimate_or_404(seid, eid)
        require_fields(body, ["expected_engagement_version"])
        require_int(body["expected_engagement_version"], "expected_engagement_version")
        if s["status"] != "PROPOSED":
            raise err("ERR_INVALID_STATE", "Scope estimate not PROPOSED")
        if body["expected_engagement_version"] != e["version"]:
            raise err("ERR_STALE_ENGAGEMENT_VERSION", "Engagement version is stale")
        if e["workflow_status"] != "SCOPING":
            raise err("ERR_INVALID_STATE", "Engagement not in SCOPING")
        # supersede any previously ACCEPTED estimate on this engagement
        for other in db.scope_estimates.values():
            if other["engagement_id"] == eid and other["id"] != seid and other["status"] == "ACCEPTED":
                other["status"] = "SUPERSEDED"
                touch(other)
        s["status"] = "ACCEPTED"
        touch(s)
        e["scope_locked"] = True
        e["estimated_txn_volume"] = s["txn_volume_estimate"]
        e["workflow_status"] = "RECONSTRUCTION"
        touch(e)
    return success(ser_scope_estimate(s), status=200)


# ===========================================================================
# LEDGER ACCOUNT
# ===========================================================================
@app.route("/engagements/<eid>/accounts", methods=["POST"])
def create_account(eid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper", "EngagementManager"])
    body = get_body()
    with db.lock:
        get_engagement_or_404(eid)
        require_fields(body, ["account_code", "name", "account_type"])
        require_enum(body["account_type"], ACCOUNT_TYPES, "account_type")
        if not isinstance(body["account_code"], str) or body["account_code"] == "":
            raise err("ERR_INVALID_REQUEST", "account_code required")
        if not isinstance(body["name"], str) or body["name"] == "":
            raise err("ERR_INVALID_REQUEST", "name required")
        is_bank = body.get("is_bank_account", False)
        if is_bank is None:
            is_bank = False
        if not isinstance(is_bank, bool):
            raise err("ERR_INVALID_REQUEST", "is_bank_account must be boolean")
        # uniqueness among non-EXCLUDED accounts in engagement
        for a in accounts_of(eid):
            if a["status"] != "EXCLUDED" and a["account_code"] == body["account_code"]:
                raise err("ERR_DUPLICATE_ACCOUNT_CODE", "account_code already used")
        normal_side = "DEBIT" if body["account_type"] in ("ASSET", "EXPENSE") else "CREDIT"
        a = stamp_new({
            "engagement_id": eid,
            "account_code": body["account_code"],
            "name": body["name"],
            "account_type": body["account_type"],
            "normal_side": normal_side,
            "is_bank_account": is_bank,
            "book_balance_cents": 0,
            "status": "DRAFT",
            "categorized_by": None,
        })
        db.accounts[a["id"]] = a
    return success(ser_account(a), status=201)


@app.route("/engagements/<eid>/accounts", methods=["GET"])
def list_accounts(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = accounts_of(eid)
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    at = request.args.get("account_type")
    if at:
        items = [a for a in items if a["account_type"] == at]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_account(a) for a in page], limit, offset, total)


@app.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    a = get_account_or_404(aid)
    return success(ser_account(a), status=200)


@app.route("/engagements/<eid>/accounts/<aid>/categorize", methods=["POST"])
def categorize_account(eid, aid):
    uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        e = get_engagement_or_404(eid)
        a = get_account_or_404(aid, eid)
        if a["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Account not in DRAFT")
        if e["workflow_status"] != "RECONSTRUCTION":
            raise err("ERR_INVALID_STATE", "Engagement not in RECONSTRUCTION")
        if not any(en["status"] == "POSTED" for en in entries_of_account(aid)):
            raise err("ERR_NO_POSTED_ENTRIES", "No POSTED entries")
        recompute_account_balance(a)
        a["status"] = "CATEGORIZED"
        a["categorized_by"] = uid
        touch(a)
    return success(ser_account(a), status=200)


@app.route("/engagements/<eid>/accounts/<aid>/mark-reconciled", methods=["POST"])
def mark_reconciled(eid, aid):
    uid, role = get_user_context()
    require_role(role, ["Reviewer"])
    with db.lock:
        # segregation of duties is priority 3, BEFORE existence (priority 4).
        a = db.accounts.get(aid)
        if a is not None and a["engagement_id"] == eid and a.get("categorized_by") == uid:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Reviewer cannot be the categorizing Bookkeeper")
        e = get_engagement_or_404(eid)
        a = get_account_or_404(aid, eid)
        if a["status"] != "CATEGORIZED":
            raise err("ERR_INVALID_STATE", "Account not in CATEGORIZED")
        if a["is_bank_account"]:
            if not any(s["status"] == "RECONCILED" for s in statements_of_account(aid)):
                raise err("ERR_BANK_NOT_RECONCILED", "No RECONCILED statement")
        for x in exceptions_of_account(aid):
            if x["kind"] == "UNRECONCILED_DIFF" and x["status"] not in ("RESOLVED", "WAIVED"):
                raise err("ERR_OPEN_DIFF_EXCEPTION", "Open UNRECONCILED_DIFF exception")
        a["status"] = "RECONCILED"
        touch(a)
        recompute_engagement_derived(e)
    return success(ser_account(a), status=200)


@app.route("/engagements/<eid>/accounts/<aid>/exclude", methods=["POST"])
def exclude_account(eid, aid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        e = get_engagement_or_404(eid)
        a = get_account_or_404(aid, eid)
        if a["status"] not in ("DRAFT", "CATEGORIZED"):
            raise err("ERR_INVALID_STATE", "Account cannot be excluded from this state")
        if a["status"] == "CATEGORIZED" and a["is_bank_account"]:
            if any(s["status"] in ("RECONCILING", "RECONCILED") for s in statements_of_account(aid)):
                raise err("ERR_BANK_NOT_RECONCILED",
                          "Cannot exclude bank account with reconciling/reconciled statement")
        a["status"] = "EXCLUDED"
        touch(a)
        recompute_engagement_derived(e)
    return success(ser_account(a), status=200)


# ===========================================================================
# LEDGER ENTRY
# ===========================================================================
@app.route("/engagements/<eid>/entries", methods=["POST"])
def create_entry(eid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    body = get_body()
    with db.lock:
        get_engagement_or_404(eid)
        require_fields(body, ["account_id", "txn_date", "side", "amount_cents"])
        require_enum(body["side"], SIDES, "side")
        require_positive_int(body["amount_cents"], "amount_cents")
        if not isinstance(body["txn_date"], str):
            raise err("ERR_INVALID_REQUEST", "txn_date must be an ISO date string")
        try:
            calc.parse_iso_date(body["txn_date"])
        except Exception:
            raise err("ERR_INVALID_REQUEST", "txn_date must be a valid YYYY-MM-DD date")
        memo = body.get("memo", "")
        if memo is None:
            memo = ""
        if not isinstance(memo, str):
            raise err("ERR_INVALID_REQUEST", "memo must be a string")
        rev_id = body.get("reversed_entry_id")
        get_account_or_404(body["account_id"], eid)
        e = stamp_new({
            "engagement_id": eid,
            "account_id": body["account_id"],
            "txn_date": body["txn_date"],
            "side": body["side"],
            "amount_cents": body["amount_cents"],
            "memo": memo,
            "cash_settled": False,
            "reconciliation_item_id": None,
            "reversed_entry_id": rev_id,
            "status": "DRAFT",
        })
        db.entries[e["id"]] = e
    return success(ser_entry(e), status=201)


@app.route("/engagements/<eid>/entries", methods=["GET"])
def list_entries(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = entries_of(eid)
    items = _filter_entries(items)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_entry(e) for e in page], limit, offset, total)


def _filter_entries(items):
    aid = request.args.get("account_id")
    if aid:
        items = [e for e in items if e["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    rev = request.args.get("reversed_entry_id")
    if rev:
        items = [e for e in items if e["reversed_entry_id"] == rev]
    ri = request.args.get("reconciliation_item_id")
    if ri:
        items = [e for e in items if e["reconciliation_item_id"] == ri]
    return items


@app.route("/entries/<entry_id>", methods=["GET"])
def get_entry_flat(entry_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    e = get_entry_or_404(entry_id)
    return success(ser_entry(e), status=200)


@app.route("/entries", methods=["GET"])
def list_entries_flat():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = _filter_entries(list(db.entries.values()))
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_entry(e) for e in page], limit, offset, total)


@app.route("/engagements/<eid>/entries/<entry_id>/post", methods=["POST"])
def post_entry(eid, entry_id):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        e = get_engagement_or_404(eid)
        entry = get_entry_or_404(entry_id, eid)
        if entry["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Entry not in DRAFT")
        td = calc.parse_iso_date(entry["txn_date"])
        ps = calc.parse_iso_date(e["period_start"])
        pe = calc.parse_iso_date(e["period_end"])
        if not (ps <= td <= pe):
            raise err("ERR_ENTRY_OUT_OF_PERIOD", "txn_date out of engagement period")
        acct = get_account_or_404(entry["account_id"], eid)
        if acct["status"] == "EXCLUDED":
            raise err("ERR_ACCOUNT_EXCLUDED", "Account is EXCLUDED")
        entry["status"] = "POSTED"
        touch(entry)
        recompute_account_balance(acct)
        touch(acct)
    return success(ser_entry(entry), status=200)


@app.route("/engagements/<eid>/entries/<entry_id>/reverse", methods=["POST"])
def reverse_entry(eid, entry_id):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        get_engagement_or_404(eid)
        entry = get_entry_or_404(entry_id, eid)
        if entry["status"] != "POSTED":
            raise err("ERR_INVALID_STATE", "Entry not in POSTED")
        if entry["cash_settled"]:
            raise err("ERR_ENTRY_SETTLED", "Entry is cash settled")
        acct = get_account_or_404(entry["account_id"], eid)
        if acct["status"] == "RECONCILED":
            raise err("ERR_ACCOUNT_RECONCILED", "Account is RECONCILED")
        opposite = "CREDIT" if entry["side"] == "DEBIT" else "DEBIT"
        reversing = stamp_new({
            "engagement_id": eid,
            "account_id": entry["account_id"],
            "txn_date": entry["txn_date"],
            "side": opposite,
            "amount_cents": entry["amount_cents"],
            "memo": entry["memo"],
            "cash_settled": False,
            "reconciliation_item_id": None,
            "reversed_entry_id": entry["id"],
            "status": "POSTED",
        })
        db.entries[reversing["id"]] = reversing
        entry["status"] = "REVERSED"
        touch(entry)
        recompute_account_balance(acct)
        touch(acct)
    return success(ser_entry(entry), status=200)


# ===========================================================================
# BANK STATEMENT
# ===========================================================================
@app.route("/engagements/<eid>/statements", methods=["POST"])
def create_statement(eid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper", "Reviewer"])
    body = get_body()
    with db.lock:
        get_engagement_or_404(eid)
        require_fields(body, ["account_id", "statement_start", "statement_end", "ending_balance_cents"])
        require_int(body["ending_balance_cents"], "ending_balance_cents")
        for f in ("statement_start", "statement_end"):
            if not isinstance(body[f], str):
                raise err("ERR_INVALID_REQUEST", "%s must be an ISO date string" % f)
            try:
                calc.parse_iso_date(body[f])
            except Exception:
                raise err("ERR_INVALID_REQUEST", "%s must be a valid date" % f)
        if calc.parse_iso_date(body["statement_end"]) < calc.parse_iso_date(body["statement_start"]):
            raise err("ERR_INVALID_REQUEST", "statement_end before statement_start")
        dit = body.get("deposits_in_transit_cents", 0)
        if dit is None:
            dit = 0
        require_int(dit, "deposits_in_transit_cents")
        oc = body.get("outstanding_checks_cents", 0)
        if oc is None:
            oc = 0
        require_int(oc, "outstanding_checks_cents")
        get_account_or_404(body["account_id"], eid)
        s = stamp_new({
            "engagement_id": eid,
            "account_id": body["account_id"],
            "statement_start": body["statement_start"],
            "statement_end": body["statement_end"],
            "ending_balance_cents": body["ending_balance_cents"],
            "deposits_in_transit_cents": dit,
            "outstanding_checks_cents": oc,
            "status": "IMPORTED",
        })
        db.statements[s["id"]] = s
    return success(ser_statement(s), status=201)


@app.route("/engagements/<eid>/statements", methods=["GET"])
def list_statements(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = statements_of(eid)
    items = _filter_statements(items)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_statement(s) for s in page], limit, offset, total)


def _filter_statements(items):
    aid = request.args.get("account_id")
    if aid:
        items = [s for s in items if s["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return items


@app.route("/statements/<statement_id>", methods=["GET"])
def get_statement_flat(statement_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    s = get_statement_or_404(statement_id)
    return success(ser_statement(s), status=200)


@app.route("/statements", methods=["GET"])
def list_statements_flat():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = _filter_statements(list(db.statements.values()))
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_statement(s) for s in page], limit, offset, total)


@app.route("/engagements/<eid>/statements/<sid>/finalize", methods=["POST"])
def finalize_statement(eid, sid):
    _uid, role = get_user_context()
    require_role(role, ["Reviewer"])
    with db.lock:
        e = get_engagement_or_404(eid)
        s = get_statement_or_404(sid, eid)
        if s["status"] != "RECONCILING":
            raise err("ERR_INVALID_STATE", "Statement not in RECONCILING")
        items = recon_items_of_statement(sid)
        if any(it["status"] in ("UNMATCHED", "DISPUTED") for it in items):
            raise err("ERR_OPEN_RECON_ITEMS", "Open reconciliation items remain")
        acct = db.accounts.get(s["account_id"])
        book_balance = acct["book_balance_cents"] if acct else 0
        diff = calc.recon_difference(s, book_balance)
        if abs(diff) > calc.MATCH_TOLERANCE_CENTS:
            # create BLOCKING UNRECONCILED_DIFF exception, reject
            x = stamp_new({
                "engagement_id": eid,
                "account_id": s["account_id"],
                "kind": "UNRECONCILED_DIFF",
                "severity": "BLOCKING",
                "doc_due_date": None,
                "status": "OPEN",
            })
            db.exceptions[x["id"]] = x
            recompute_engagement_derived(e)
            raise err("ERR_RECON_OUT_OF_BALANCE", "Reconciliation out of balance")
        s["status"] = "RECONCILED"
        touch(s)
        # mark linked ledger entries cash_settled
        for it in items:
            if it["status"] == "MATCHED" and it.get("ledger_entry_id"):
                le = db.entries.get(it["ledger_entry_id"])
                if le is not None:
                    le["cash_settled"] = True
                    touch(le)
        recompute_engagement_derived(e)
    return success(ser_statement(s), status=200)


# ===========================================================================
# RECONCILIATION ITEM
# ===========================================================================
@app.route("/engagements/<eid>/statements/<sid>/reconciliation-items", methods=["POST"])
def create_recon_item(eid, sid):
    _uid, role = get_user_context()
    require_role(role, ["Reviewer"])
    body = get_body()
    with db.lock:
        get_engagement_or_404(eid)
        s = get_statement_or_404(sid, eid)
        require_fields(body, ["ledger_entry_id", "statement_line_amount_cents"])
        require_int(body["statement_line_amount_cents"], "statement_line_amount_cents")
        match_kind = body.get("match_kind", "EXACT")
        if match_kind is None:
            match_kind = "EXACT"
        require_enum(match_kind, MATCH_KINDS, "match_kind")
        # statement's account must be a bank account (gates IMPORTED -> RECONCILING)
        acct = db.accounts.get(s["account_id"])
        if acct is None or not acct.get("is_bank_account"):
            raise err("ERR_NOT_BANK_ACCOUNT", "Statement account is not a bank account")
        entry = get_entry_or_404(body["ledger_entry_id"], eid)
        # determine match status
        book_mag = abs(entry["amount_cents"])
        line_mag = abs(body["statement_line_amount_cents"])
        delta = abs(book_mag - line_mag)
        if match_kind == "EXACT":
            status = "MATCHED" if delta == 0 else "UNMATCHED"
        else:  # TOLERANCE
            status = "MATCHED" if delta <= calc.MATCH_TOLERANCE_CENTS else "UNMATCHED"
        r = stamp_new({
            "statement_id": sid,
            "engagement_id": eid,
            "ledger_entry_id": body["ledger_entry_id"],
            "statement_line_amount_cents": body["statement_line_amount_cents"],
            "match_kind": match_kind,
            "status": status,
        })
        db.recon_items[r["id"]] = r
        if status == "MATCHED":
            entry["reconciliation_item_id"] = r["id"]
            touch(entry)
        # first item: IMPORTED -> RECONCILING
        if s["status"] == "IMPORTED":
            s["status"] = "RECONCILING"
            touch(s)
    return success(ser_recon_item(r), status=201)


@app.route("/engagements/<eid>/statements/<sid>/reconciliation-items", methods=["GET"])
def list_recon_items(eid, sid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    get_statement_or_404(sid, eid)
    items = recon_items_of_statement(sid)
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_recon_item(r) for r in page], limit, offset, total)


@app.route("/reconciliation-items", methods=["GET"])
def list_recon_items_flat():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.recon_items.values())
    le = request.args.get("ledger_entry_id")
    if le:
        items = [r for r in items if r["ledger_entry_id"] == le]
    sid = request.args.get("statement_id")
    if sid:
        items = [r for r in items if r["statement_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_recon_item(r) for r in page], limit, offset, total)


@app.route("/reconciliation-items/<item_id>", methods=["GET"])
def get_recon_item_flat(item_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    r = get_recon_item_or_404(item_id)
    return success(ser_recon_item(r), status=200)


# ===========================================================================
# PHASE / BILLING
# ===========================================================================
@app.route("/engagements/<eid>/phases", methods=["POST"])
def create_phase(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    body = get_body()
    with db.lock:
        get_engagement_or_404(eid)
        require_fields(body, ["phase_index", "label", "weight_bp"])
        require_positive_int(body["phase_index"], "phase_index")
        require_positive_int(body["weight_bp"], "weight_bp")
        if not isinstance(body["label"], str) or body["label"] == "":
            raise err("ERR_INVALID_REQUEST", "label required")
        p = stamp_new({
            "engagement_id": eid,
            "phase_index": body["phase_index"],
            "label": body["label"],
            "weight_bp": body["weight_bp"],
            "amount_cents": None,
            "status": "PLANNED",
        })
        db.phases[p["id"]] = p
    return success(ser_phase(p), status=201)


@app.route("/engagements/<eid>/phases", methods=["GET"])
def list_phases(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = phases_of(eid)
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_phase(p) for p in page], limit, offset, total)


@app.route("/phases/<phase_id>", methods=["GET"])
def get_phase_flat(phase_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    p = get_phase_or_404(phase_id)
    return success(ser_phase(p), status=200)


@app.route("/engagements/<eid>/phases/generate", methods=["POST"])
def generate_phases(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["billing_status"] != "QUOTED":
            raise err("ERR_INVALID_STATE", "Billing not in QUOTED")
        ph = phases_of(eid)
        if sum(p["weight_bp"] for p in ph) != 10000:
            raise err("ERR_PHASE_WEIGHTS_INVALID", "Phase weights must sum to 10000")
        ph_sorted = sorted(ph, key=lambda p: p["phase_index"])
        amounts = calc.phase_billing_split(e["fixed_price_cents"], ph_sorted)
        for p in ph_sorted:
            p["amount_cents"] = amounts[p["id"]]
            p["status"] = "BILLABLE"
            touch(p)
        e["billing_status"] = "PHASED"
        touch(e)
    return success(ser_engagement(e), status=200)


@app.route("/engagements/<eid>/phases/<pid>/invoice", methods=["POST"])
def invoice_phase(eid, pid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        get_engagement_or_404(eid)
        p = get_phase_or_404(pid, eid)
        if p["status"] != "BILLABLE":
            raise err("ERR_INVALID_STATE", "Phase not BILLABLE")
        for other in phases_of(eid):
            if other["phase_index"] < p["phase_index"] and other["status"] not in ("INVOICED", "PAID"):
                raise err("ERR_PHASE_ORDER", "Lower-index phases not invoiced/paid")
        inv = stamp_new({
            "engagement_id": eid,
            "phase_id": pid,
            "amount_cents": p["amount_cents"],
            "status": "ISSUED",
        })
        db.invoices[inv["id"]] = inv
        p["status"] = "INVOICED"
        touch(p)
    return success(ser_invoice(inv), status=201)


@app.route("/engagements/<eid>/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(eid, iid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        inv = get_invoice_or_404(iid, eid)
        if inv["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Invoice not ISSUED")
        p = db.phases.get(inv["phase_id"])
        if p is None or p["status"] != "INVOICED":
            raise err("ERR_INVALID_STATE", "Phase not INVOICED")
        inv["status"] = "PAID"
        touch(inv)
        p["status"] = "PAID"
        touch(p)
        all_phases = phases_of(eid)
        if all_phases and all(ph["status"] == "PAID" for ph in all_phases):
            if e["billing_status"] == "PHASED":
                e["billing_status"] = "SETTLED"
                touch(e)
    return success(ser_invoice(inv), status=200)


@app.route("/engagements/<eid>/invoices", methods=["GET"])
def list_invoices(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = invoices_of(eid)
    items = _filter_invoices(items)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_invoice(i) for i in page], limit, offset, total)


def _filter_invoices(items):
    pid = request.args.get("phase_id")
    if pid:
        items = [i for i in items if i["phase_id"] == pid]
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    return items


@app.route("/phase-invoices/<invoice_id>", methods=["GET"])
def get_invoice_flat(invoice_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    i = get_invoice_or_404(invoice_id)
    return success(ser_invoice(i), status=200)


@app.route("/phase-invoices", methods=["GET"])
def list_invoices_flat():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.invoices.values())
    eng = request.args.get("engagement_id")
    if eng:
        items = [i for i in items if i["engagement_id"] == eng]
    items = _filter_invoices(items)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_invoice(i) for i in page], limit, offset, total)


# ===========================================================================
# TAX PACKAGE
# ===========================================================================
def compute_taxable_income(engagement, basis):
    eid = engagement["id"]
    ps = calc.parse_iso_date(engagement["period_start"])
    pe = calc.parse_iso_date(engagement["period_end"])
    income = 0
    expense = 0
    for entry in entries_of(eid):
        if entry["status"] != "POSTED":
            continue
        td = calc.parse_iso_date(entry["txn_date"])
        if not (ps <= td <= pe):
            continue
        acct = db.accounts.get(entry["account_id"])
        if acct is None or acct["status"] == "EXCLUDED":
            continue
        if basis == "CASH" and not entry["cash_settled"]:
            continue
        if acct["account_type"] == "INCOME" and entry["side"] == "CREDIT":
            income += entry["amount_cents"]
        elif acct["account_type"] == "EXPENSE" and entry["side"] == "DEBIT":
            expense += entry["amount_cents"]
    return income - expense


@app.route("/engagements/<eid>/tax-packages", methods=["POST"])
def build_tax_package(eid):
    _uid, role = get_user_context()
    require_role(role, ["TaxPreparer"])
    with db.lock:
        e = get_engagement_or_404(eid)
        if e["workflow_status"] != "RECONCILIATION":
            raise err("ERR_INVALID_STATE", "Engagement not in RECONCILIATION")
        # blocking-exception check precedes balance check (priority 9 before 10)
        if e["open_blocking_exception_count"] != 0:
            raise err("ERR_BLOCKING_EXCEPTIONS_OPEN", "Open blocking exceptions")
        if e["recon_status"] != "IN_BALANCE":
            raise err("ERR_RECON_NOT_IN_BALANCE", "Reconciliation not IN_BALANCE")
        client = db.clients.get(e["client_id"])
        basis = client["accounting_basis"] if client else "ACCRUAL"
        net = compute_taxable_income(e, basis)
        t = stamp_new({
            "engagement_id": eid,
            "basis": basis,
            "net_book_income_cents": net,
            "status": "BUILT",
        })
        db.tax_packages[t["id"]] = t
        e["workflow_status"] = "TAX_HANDOFF"
        touch(e)
    return success(ser_tax_package(t), status=201)


@app.route("/engagements/<eid>/tax-packages", methods=["GET"])
def list_tax_packages(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = tax_packages_of(eid)
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_tax_package(t) for t in page], limit, offset, total)


@app.route("/engagements/<eid>/tax-packages/<tid>/handoff", methods=["POST"])
def handoff_tax_package(eid, tid):
    _uid, role = get_user_context()
    require_role(role, ["TaxPreparer"])
    with db.lock:
        e = get_engagement_or_404(eid)
        t = get_tax_package_or_404(tid, eid)
        if t["status"] != "BUILT":
            raise err("ERR_INVALID_STATE", "Tax package not BUILT")
        if e["open_blocking_exception_count"] != 0:
            raise err("ERR_BLOCKING_EXCEPTIONS_OPEN", "Open blocking exceptions")
        t["status"] = "HANDED_OFF"
        touch(t)
    return success(ser_tax_package(t), status=200)


@app.route("/engagements/<eid>/tax-packages/<tid>/amend", methods=["POST"])
def amend_tax_package(eid, tid):
    _uid, role = get_user_context()
    require_role(role, ["TaxPreparer"])
    with db.lock:
        e = get_engagement_or_404(eid)
        t = get_tax_package_or_404(tid, eid)
        if t["status"] != "HANDED_OFF":
            raise err("ERR_INVALID_STATE", "Tax package not HANDED_OFF")
        t["net_book_income_cents"] = compute_taxable_income(e, t["basis"])
        t["status"] = "AMENDED"
        touch(t)
    return success(ser_tax_package(t), status=200)


# ===========================================================================
# SERVICE PLAN
# ===========================================================================
@app.route("/engagements/<eid>/service-plans", methods=["POST"])
def create_service_plan(eid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    body = get_body()
    with db.lock:
        get_engagement_or_404(eid)
        require_fields(body, ["monthly_fee_cents", "conversion_date"])
        require_positive_int(body["monthly_fee_cents"], "monthly_fee_cents")
        if not isinstance(body["conversion_date"], str):
            raise err("ERR_INVALID_REQUEST", "conversion_date must be an ISO date string")
        try:
            calc.parse_iso_date(body["conversion_date"])
        except Exception:
            raise err("ERR_INVALID_REQUEST", "conversion_date must be a valid date")
        sp = stamp_new({
            "engagement_id": eid,
            "monthly_fee_cents": body["monthly_fee_cents"],
            "conversion_date": body["conversion_date"],
            "first_month_prorated_cents": None,
            "status": "PENDING",
        })
        db.service_plans[sp["id"]] = sp
    return success(ser_service_plan(sp), status=201)


@app.route("/engagements/<eid>/service-plans", methods=["GET"])
def list_service_plans(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = [s for s in db.service_plans.values() if s["engagement_id"] == eid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_service_plan(s) for s in page], limit, offset, total)


@app.route("/engagements/<eid>/service-plans/<spid>/activate", methods=["POST"])
def activate_service_plan(eid, spid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        e = get_engagement_or_404(eid)
        sp = get_service_plan_or_404(spid, eid)
        if sp["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Service plan not PENDING")
        if e["workflow_status"] not in ("TAX_HANDOFF", "COMPLETED"):
            raise err("ERR_INVALID_STATE", "Engagement not in TAX_HANDOFF/COMPLETED")
        sp["first_month_prorated_cents"] = calc.service_proration(
            sp["monthly_fee_cents"], sp["conversion_date"]
        )
        sp["status"] = "ACTIVE"
        touch(sp)
    return success(ser_service_plan(sp), status=200)


@app.route("/engagements/<eid>/service-plans/<spid>/cancel", methods=["POST"])
def cancel_service_plan(eid, spid):
    _uid, role = get_user_context()
    require_role(role, ["EngagementManager"])
    with db.lock:
        get_engagement_or_404(eid)
        sp = get_service_plan_or_404(spid, eid)
        if sp["status"] not in ("PENDING", "ACTIVE"):
            raise err("ERR_INVALID_STATE", "Service plan cannot be cancelled")
        sp["status"] = "CANCELLED"
        touch(sp)
    return success(ser_service_plan(sp), status=200)


# ===========================================================================
# EXCEPTION
# ===========================================================================
@app.route("/engagements/<eid>/exceptions", methods=["POST"])
def create_exception(eid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper", "Reviewer"])
    body = get_body()
    with db.lock:
        e = get_engagement_or_404(eid)
        require_fields(body, ["account_id", "kind"])
        require_enum(body["kind"], EXCEPTION_KINDS, "kind")
        severity = body.get("severity", "NORMAL")
        if severity is None:
            severity = "NORMAL"
        require_enum(severity, SEVERITIES, "severity")
        doc_due = body.get("doc_due_date")
        if body["kind"] == "MISSING_DOC":
            if not doc_due:
                raise err("ERR_INVALID_REQUEST", "doc_due_date required for MISSING_DOC")
            if not isinstance(doc_due, str):
                raise err("ERR_INVALID_REQUEST", "doc_due_date must be an ISO date string")
            try:
                calc.parse_iso_date(doc_due)
            except Exception:
                raise err("ERR_INVALID_REQUEST", "doc_due_date must be a valid date")
        get_account_or_404(body["account_id"], eid)
        x = stamp_new({
            "engagement_id": eid,
            "account_id": body["account_id"],
            "kind": body["kind"],
            "severity": severity,
            "doc_due_date": doc_due,
            "status": "OPEN",
        })
        db.exceptions[x["id"]] = x
        if severity == "BLOCKING":
            recompute_engagement_derived(e)
    return success(ser_exception(x), status=201)


@app.route("/engagements/<eid>/exceptions", methods=["GET"])
def list_exceptions(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = exceptions_of(eid)
    items = _filter_exceptions(items)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_exception(x) for x in page], limit, offset, total)


def _filter_exceptions(items):
    aid = request.args.get("account_id")
    if aid:
        items = [x for x in items if x.get("account_id") == aid]
    kind = request.args.get("kind")
    if kind:
        items = [x for x in items if x["kind"] == kind]
    status = request.args.get("status")
    if status:
        items = [x for x in items if x["status"] == status]
    severity = request.args.get("severity")
    if severity:
        items = [x for x in items if x["severity"] == severity]
    return items


@app.route("/exceptions/<exception_id>", methods=["GET"])
def get_exception_flat(exception_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    x = get_exception_or_404(exception_id)
    return success(ser_exception(x), status=200)


@app.route("/exceptions", methods=["GET"])
def list_exceptions_flat():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.exceptions.values())
    eng = request.args.get("engagement_id")
    if eng:
        items = [x for x in items if x["engagement_id"] == eng]
    items = _filter_exceptions(items)
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_exception(x) for x in page], limit, offset, total)


@app.route("/engagements/<eid>/exceptions/<xid>/request-docs", methods=["POST"])
def request_docs(eid, xid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        get_engagement_or_404(eid)
        x = get_exception_or_404(xid, eid)
        if x["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Exception not OPEN")
        if x["kind"] != "MISSING_DOC":
            raise err("ERR_INVALID_STATE", "Only MISSING_DOC can request docs")
        x["status"] = "WAITING_DOCS"
        touch(x)
    return success(ser_exception(x), status=200)


@app.route("/engagements/<eid>/exceptions/<xid>/docs-received", methods=["POST"])
def docs_received(eid, xid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        get_engagement_or_404(eid)
        x = get_exception_or_404(xid, eid)
        if x["status"] != "WAITING_DOCS":
            raise err("ERR_INVALID_STATE", "Exception not WAITING_DOCS")
        x["status"] = "OPEN"
        touch(x)
    return success(ser_exception(x), status=200)


@app.route("/engagements/<eid>/exceptions/<xid>/resolve", methods=["POST"])
def resolve_exception(eid, xid):
    _uid, role = get_user_context()
    require_role(role, ["Bookkeeper"])
    with db.lock:
        e = get_engagement_or_404(eid)
        x = get_exception_or_404(xid, eid)
        if x["status"] not in ("OPEN", "WAITING_DOCS"):
            raise err("ERR_INVALID_STATE", "Exception not OPEN/WAITING_DOCS")
        was_blocking = x["severity"] == "BLOCKING"
        x["status"] = "RESOLVED"
        touch(x)
        if was_blocking:
            recompute_engagement_derived(e)
    return success(ser_exception(x), status=200)


@app.route("/engagements/<eid>/exceptions/<xid>/waive", methods=["POST"])
def waive_exception(eid, xid):
    _uid, role = get_user_context()
    require_role(role, ["Reviewer"])
    with db.lock:
        e = get_engagement_or_404(eid)
        x = get_exception_or_404(xid, eid)
        if x["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Exception not OPEN")
        if x["kind"] == "UNRECONCILED_DIFF":
            raise err("ERR_CANNOT_WAIVE_DIFF", "Cannot waive UNRECONCILED_DIFF")
        was_blocking = x["severity"] == "BLOCKING"
        x["status"] = "WAIVED"
        touch(x)
        if was_blocking:
            recompute_engagement_derived(e)
    return success(ser_exception(x), status=200)


# ===========================================================================
# COMPLETION REPORT
# ===========================================================================
@app.route("/engagements/<eid>/completion-report", methods=["GET"])
def get_completion_report(eid):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    get_engagement_or_404(eid)
    items = [c for c in db.completion_reports.values() if c["engagement_id"] == eid]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return list_response([ser_completion_report(c) for c in page], limit, offset, total)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

"""StorageStatement, billing-run, and CarrierInvoice endpoints."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import (
    validation,
    invalid_transition,
    stale_job_version,
    statement_period_open,
    payment_exceeds_balance,
    invoice_balance_outstanding,
)
from helpers import (
    get_body,
    require_string,
    require_enum,
    require_int,
    require_date,
    optional_int,
    optional_string,
    make_common_fields,
    get_job,
    get_statement,
    get_invoice,
    touch,
    parse_date_str,
    items_of_job,
)
from middleware import require_roles, parse_pagination, paginate
from response import success_object, success_list, success
from services.recompute import (
    compute_provisional_total,
    compute_final_total,
    recompute_job_accrued,
    recompute_job_billing_status,
    recompute_invoice_balance,
)

bp = Blueprint("billing", __name__)

FEE_TIER1_MAX = 100000
FEE_TIER2_MAX = 500000
FEE_TIER1_PCT = 5
FEE_TIER2_PCT = 7
FEE_TIER3_PCT = 9

INVOICE_ACTIONS = {"SUBMIT", "RECORD_PAYMENT", "DISPUTE", "RECONCILE"}


def serialize_statement(s):
    return dict(s)


def serialize_invoice(inv):
    return dict(inv)


@bp.route("/api/pack-out-jobs/<job_id>/storage-statements", methods=["POST"])
def create_statement(job_id):
    user_id, role = require_roles("BillingClerk")
    body = get_body()
    period_start = require_date(body, "period_start")
    period_end = require_date(body, "period_end")
    expected_job_version = require_int(body, "expected_job_version")
    supersedes_id = body.get("supersedes_statement_id")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        raise validation("supersedes_statement_id must be a string")

    job = get_job(job_id)

    # period validity (priority 9 — ERR_VALIDATION)
    ps = parse_date_str(period_start)
    pe = parse_date_str(period_end)
    if pe <= ps:
        raise validation("period_end must be strictly after period_start")

    # supersedes target must exist (existence, priority 5) — checked before OCC per priority order
    superseded = None
    if supersedes_id is not None:
        superseded = store.statements.get(supersedes_id)
        if superseded is None:
            from errors import not_found
            raise not_found("supersedes_statement_id does not reference an existing statement")
        if superseded["job_id"] != job["id"]:
            raise validation("supersedes_statement_id belongs to a different job")
        if superseded["status"] != "PROVISIONAL":
            raise validation("supersedes_statement_id must name the current PROVISIONAL statement")

    # OCC check (priority 6)
    if expected_job_version != job["version"]:
        raise stale_job_version()

    # Business constraints: disjoint periods among non-VOIDED; at most one PROVISIONAL unless supersede names it
    for s in store.statements.values():
        if s["job_id"] != job["id"]:
            continue
        if s["status"] == "VOIDED":
            continue
        if superseded is not None and s["id"] == superseded["id"]:
            continue
        s_ps = parse_date_str(s["period_start"])
        s_pe = parse_date_str(s["period_end"])
        # overlap iff ps < s_pe and s_ps < pe
        if ps < s_pe and s_ps < pe:
            raise validation("Statement period overlaps an existing non-VOIDED statement")
    if superseded is None:
        for s in store.statements.values():
            if s["job_id"] == job["id"] and s["status"] == "PROVISIONAL":
                raise validation("Job already has a PROVISIONAL statement; use supersedes_statement_id")

    stmt = make_common_fields()
    stmt.update({
        "job_id": job["id"],
        "period_start": period_start,
        "period_end": period_end,
        "supersedes_statement_id": supersedes_id,
        "status": "PROVISIONAL",
        "provisional_total_cents": 0,
        "final_total_cents": None,
    })
    store.statements[stmt["id"]] = stmt
    if superseded is not None:
        superseded["status"] = "VOIDED"
        touch(superseded)
    stmt["provisional_total_cents"] = compute_provisional_total(stmt)
    touch(job)  # increments version by 1
    recompute_job_accrued(job)
    return success_object(serialize_statement(stmt), status=201)


@bp.route("/api/storage-statements", methods=["GET"])
def list_statements():
    user_id, role = require_roles("BillingClerk", "ProjectManager")
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")
    supersedes_id = request.args.get("supersedes_statement_id")
    stmts = list(store.statements.values())
    if job_id is not None:
        stmts = [s for s in stmts if s["job_id"] == job_id]
    if supersedes_id is not None:
        stmts = [s for s in stmts if s.get("supersedes_statement_id") == supersedes_id]
    page, total = paginate([serialize_statement(s) for s in stmts], limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/storage-statements/<stmt_id>", methods=["GET"])
def read_statement(stmt_id):
    user_id, role = require_roles("BillingClerk", "ProjectManager")
    stmt = get_statement(stmt_id)
    return success_object(serialize_statement(stmt))


@bp.route("/api/billing-runs", methods=["POST"])
def billing_run():
    user_id, role = require_roles("BillingClerk")
    today = store.now().date()
    finalized_ids = []
    affected_jobs = set()
    for s in list(store.statements.values()):
        if s["status"] != "PROVISIONAL":
            continue
        pe = parse_date_str(s["period_end"])
        if pe <= today:
            s["final_total_cents"] = compute_final_total(s)
            s["status"] = "FINALIZED"
            touch(s)
            finalized_ids.append(s["id"])
            affected_jobs.add(s["job_id"])
    for job_id in affected_jobs:
        job = store.jobs.get(job_id)
        if job is not None:
            recompute_job_accrued(job)
    finalized_ids.sort()
    return success_object({
        "finalized_count": len(finalized_ids),
        "finalized_statement_ids": finalized_ids,
    })


# ---- CarrierInvoice ----

def _compute_invoice_totals(storage_cents, adjustment_cents):
    subtotal = storage_cents + adjustment_cents
    if subtotal < FEE_TIER1_MAX:
        fee_pct = FEE_TIER1_PCT
    elif subtotal < FEE_TIER2_MAX:
        fee_pct = FEE_TIER2_PCT
    else:
        fee_pct = FEE_TIER3_PCT
    fee = (Decimal(subtotal) * fee_pct / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    admin_fee = int(fee)
    total = subtotal + admin_fee
    return admin_fee, total


@bp.route("/api/pack-out-jobs/<job_id>/carrier-invoices", methods=["POST"])
def create_invoice(job_id):
    user_id, role = require_roles("BillingClerk")
    body = get_body()
    adjustment_cents = optional_int(body, "adjustment_cents", default=0)

    job = get_job(job_id)
    if job["status"] == "CLOSED":
        raise invalid_transition("Job is CLOSED")
    # gates
    for s in store.statements.values():
        if s["job_id"] == job["id"] and s["status"] == "PROVISIONAL":
            raise statement_period_open("Job has a PROVISIONAL statement")
    finalized = [s for s in store.statements.values()
                 if s["job_id"] == job["id"] and s["status"] == "FINALIZED"]
    if len(finalized) == 0:
        raise statement_period_open("No FINALIZED statements to sweep")

    storage_cents = sum(s["final_total_cents"] or 0 for s in finalized)
    admin_fee, total = _compute_invoice_totals(storage_cents, adjustment_cents)

    inv = make_common_fields()
    inv.update({
        "job_id": job["id"],
        "adjustment_cents": adjustment_cents,
        "storage_cents": storage_cents,
        "admin_fee_cents": admin_fee,
        "total_cents": total,
        "claim_credit_cents": 0,
        "amount_paid_cents": 0,
        "balance_cents": total,
        "dispute_reason": None,
        "status": "DRAFT",
    })
    store.invoices[inv["id"]] = inv
    for s in finalized:
        s["status"] = "INVOICED"
        touch(s)
    recompute_job_accrued(job)
    recompute_job_billing_status(job)
    return success_object(serialize_invoice(inv), status=201)


@bp.route("/api/pack-out-jobs/<job_id>/carrier-invoices", methods=["GET"])
def list_invoices_of_job(job_id):
    user_id, role = require_roles("BillingClerk", "ProjectManager", "CarrierRepresentative")
    job = get_job(job_id)
    invs = [i for i in store.invoices.values() if i["job_id"] == job["id"]]
    invs.sort(key=lambda i: i["created_at"])
    return success([serialize_invoice(i) for i in invs], status=200, response_type="array")


@bp.route("/api/carrier-invoices/<inv_id>", methods=["GET"])
def read_invoice(inv_id):
    user_id, role = require_roles("BillingClerk", "ProjectManager", "CarrierRepresentative")
    inv = get_invoice(inv_id)
    return success_object(serialize_invoice(inv))


@bp.route("/api/carrier-invoices/<inv_id>/transition", methods=["POST"])
def transition_invoice(inv_id):
    user_id, role = require_roles("BillingClerk", "CarrierRepresentative")
    body = get_body()
    action = require_enum(body, "action", INVOICE_ACTIONS)
    inv = get_invoice(inv_id)
    job = store.jobs.get(inv["job_id"])

    # role gating per action
    if action in ("SUBMIT", "RECORD_PAYMENT"):
        if role != "BillingClerk":
            from errors import forbidden_role
            raise forbidden_role(f"{action} requires BillingClerk")
    else:  # DISPUTE, RECONCILE
        if role != "CarrierRepresentative":
            from errors import forbidden_role
            raise forbidden_role(f"{action} requires CarrierRepresentative")

    if action == "SUBMIT":
        if inv["status"] not in ("DRAFT", "DISPUTED"):
            raise invalid_transition("Invoice cannot be SUBMITTED from current status")
        # sweep APPROVED claims of the job
        if job is not None:
            approved = []
            for item in items_of_job(job["id"]):
                for c in store.claims.values():
                    if c["item_id"] == item["id"] and c["status"] == "APPROVED":
                        approved.append(c)
            from routes.claims import _settle_claim
            credit_add = 0
            for c in approved:
                credit_add += c["settlement_amount_cents"] or 0
                item = store.items.get(c["item_id"])
                _settle_claim(c, item, job, invoice_id=inv["id"])
            inv["claim_credit_cents"] = inv.get("claim_credit_cents", 0) + credit_add
        inv["status"] = "SUBMITTED"
        recompute_invoice_balance(inv)
        touch(inv)
        if job is not None:
            recompute_job_billing_status(job)
    elif action == "RECORD_PAYMENT":
        if inv["status"] not in ("SUBMITTED", "DISPUTED"):
            raise invalid_transition("Invoice must be SUBMITTED or DISPUTED to record payment")
        amount = body.get("amount_cents")
        if amount is None:
            raise validation("amount_cents is required")
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise validation("amount_cents must be an integer")
        if amount < 1:
            raise validation("amount_cents must be >= 1")
        if amount > inv["balance_cents"]:
            raise payment_exceeds_balance()
        inv["amount_paid_cents"] += amount
        recompute_invoice_balance(inv)
        touch(inv)
    elif action == "DISPUTE":
        if inv["status"] != "SUBMITTED":
            raise invalid_transition("Invoice is not SUBMITTED")
        reason = body.get("dispute_reason")
        if reason is None or not isinstance(reason, str) or reason == "":
            raise validation("dispute_reason is required")
        inv["dispute_reason"] = reason
        inv["status"] = "DISPUTED"
        touch(inv)
        if job is not None:
            recompute_job_billing_status(job)
    elif action == "RECONCILE":
        if inv["status"] != "SUBMITTED":
            raise invalid_transition("Invoice is not SUBMITTED")
        if inv["balance_cents"] != 0:
            raise invoice_balance_outstanding()
        inv["status"] = "RECONCILED"
        touch(inv)
        if job is not None:
            recompute_job_billing_status(job)
    return success_object(serialize_invoice(inv))

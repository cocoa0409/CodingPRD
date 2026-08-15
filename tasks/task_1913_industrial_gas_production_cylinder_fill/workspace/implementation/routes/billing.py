"""BillingRun endpoints (PRD §3.6)."""
from flask import Blueprint

from db import store
from errors import ERR_BILLING_RUN_INVALID_STATE, ApiError, bad_request, not_found
from middleware import ANY_ROLE, get_body, locked, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import base_record, billing_run_out, credit_evaluate
from util import clock_date, parse_date, touch

bp = Blueprint("billing", __name__)


def _get_run(billingRunId):
    r = store.billing_runs.get(billingRunId)
    if r is None:
        not_found("billing run not found")
    return r


@bp.post("/api/billing-runs")
@locked
def create_billing_run():
    require_roles("BillingClerk")
    body = get_body()
    period_start = parse_date(body.get("period_start"))
    period_end = parse_date(body.get("period_end"))
    if period_start is None or period_end is None:
        bad_request("period_start and period_end must be ISO dates")
    if period_start > period_end:
        bad_request("period_start must not be after period_end")
    r = base_record()
    r.update(
        {
            "period_start_d": period_start,
            "period_end_d": period_end,
            "charge_lines": [],
            "total_charges_cents": 0,
            "status": "DRAFT",
        }
    )
    store.billing_runs[r["id"]] = r
    return success(billing_run_out(r), status=201)


@bp.get("/api/billing-runs")
@locked
def list_billing_runs():
    require_roles(*ANY_ROLE)
    return list_response(store.billing_runs.values(), billing_run_out, [("status", "status")])


@bp.get("/api/billing-runs/<billingRunId>")
@locked
def get_billing_run(billingRunId):
    require_roles(*ANY_ROLE)
    return success(billing_run_out(_get_run(billingRunId)))


@bp.post("/api/billing-runs/<billingRunId>/finalize")
@locked
def finalize_billing_run(billingRunId):
    require_roles("BillingClerk")
    get_body()
    run = _get_run(billingRunId)
    if run["status"] != "DRAFT":
        raise ApiError(ERR_BILLING_RUN_INVALID_STATE, 409, "run must be DRAFT to finalize")
    today = clock_date()
    touched = set()
    # Overdue checkpoint: ACTIVE rentals with due_date strictly before today -> OVERDUE.
    for r in store.rentals.values():
        if r["status"] == "ACTIVE" and r["due_date_d"] < today:
            r["status"] = "OVERDUE"
            touch(r)
            touched.add(r["id"])
    # Charge computation over the accrual windows.
    lines = []
    rentals = sorted(store.rentals.values(), key=lambda r: r["_seq"])
    for r in rentals:
        if r["status"] not in ("ACTIVE", "OVERDUE"):
            continue
        if not (r["due_date_d"] < run["period_end_d"]):
            continue
        first = (r["billed_through_date_d"] - r["due_date_d"]).days + 1
        last = (run["period_end_d"] - r["due_date_d"]).days
        if last < first or last <= 0:
            continue
        line_cents = calc.demurrage_cents(r["daily_rate_cents"], first, last)
        lines.append(
            {
                "rental_id": r["id"],
                "customer_id": r["customer_id"],
                "overdue_days": last,
                "demurrage_cents": line_cents,
            }
        )
        r["billed_through_date_d"] = run["period_end_d"]
        r["demurrage_billed_cents"] += line_cents
        if r["id"] not in touched:
            touch(r)
            touched.add(r["id"])
    run["charge_lines"] = lines
    run["total_charges_cents"] = sum(l["demurrage_cents"] for l in lines)
    run["status"] = "FINALIZED"
    touch(run)
    return success(billing_run_out(run))


@bp.post("/api/billing-runs/<billingRunId>/post")
@locked
def post_billing_run(billingRunId):
    require_roles("BillingClerk")
    get_body()
    run = _get_run(billingRunId)
    if run["status"] != "FINALIZED":
        raise ApiError(ERR_BILLING_RUN_INVALID_STATE, 409, "run must be FINALIZED to post")
    touched = set()
    per_customer = {}
    for line in run["charge_lines"]:
        per_customer[line["customer_id"]] = per_customer.get(line["customer_id"], 0) + line["demurrage_cents"]
    for cid, amount in per_customer.items():
        customer = store.customers.get(cid)
        if customer is None:
            continue
        customer["outstanding_balance_cents"] += amount
        if cid not in touched:
            touch(customer)
            touched.add(cid)
        credit_evaluate(customer, touched)
    # recall_flag is cleared here and nowhere else, for customers with no
    # remaining RECALL_HOLD rentals.
    held = {r["customer_id"] for r in store.rentals.values() if r["status"] == "RECALL_HOLD"}
    for customer in store.customers.values():
        if customer["recall_flag"] and customer["id"] not in held:
            customer["recall_flag"] = False
            if customer["id"] not in touched:
                touch(customer)
                touched.add(customer["id"])
    run["status"] = "POSTED"
    touch(run)
    return success(billing_run_out(run))

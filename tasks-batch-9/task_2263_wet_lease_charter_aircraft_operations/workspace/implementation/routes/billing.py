"""Utilization periods, settlement invoicing and disputes (PRD 3.8 / 3.9)."""

from flask import Blueprint, request

from db import db, new_row, touch, public
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, BILLING_ADMIN,
)
from response import object_response, pagination, paged
from routes.common import find_period, find_invoice, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("billing", __name__)

CLOSEABLE_PERIOD_STATUSES = ("OPEN", "REOPENED")
VOIDABLE_INVOICE_STATUSES = ("PREPARED", "APPROVED", "ISSUED")


# ---------------------------------------------------------------- utilization periods

@bp.get("/wetlease/utilization-periods/<period_id>")
def get_period(period_id):
    actor = require((BILLING_ADMIN, LESSOR_OPS, LESSEE))
    period = find_period(period_id)
    check_ownership(actor, "period", period)
    return object_response(public(period))


@bp.get("/wetlease/utilization-periods")
def list_periods():
    actor = require((BILLING_ADMIN, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.utilization_periods.values()), request.args, {
        "lease_id": "lease_id",
        "period_month": "period_month",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "period", rows)
    return paged(rows, limit, offset)


@bp.get("/wetlease/utilization-periods/<period_id>/settlement-preview")
def settlement_preview(period_id):
    actor = require((BILLING_ADMIN, LESSOR_OPS, LESSEE))
    period = find_period(period_id)
    check_ownership(actor, "period", period)

    provisional = W.compute_period(period, "PROVISIONAL")
    final = W.compute_period(period, "FINAL")
    return object_response({
        "period_id": period["id"],
        "period_month": period["period_month"],
        "mgh_effective_hours": final["mgh_effective_hours"],
        "provisional_credited_hours": provisional["credited_hours"],
        "provisional_gross_charge_cents": provisional["gross_charge_cents"],
        "final_credited_hours": final["credited_hours"],
        "final_shortfall_hours": final["shortfall_hours"],
        "final_overrun_hours": final["overrun_hours"],
        "final_gross_charge_cents": final["gross_charge_cents"],
        "reliability_penalty_cents": final["reliability_penalty_cents"],
        "projected_final_charge_cents": final["net_charge_cents"],
    })


@bp.post("/wetlease/utilization-periods/<period_id>/close")
def close_period_endpoint(period_id):
    require((BILLING_ADMIN,))
    V.json_body()
    period = find_period(period_id)

    if period["status"] not in CLOSEABLE_PERIOD_STATUSES:
        raise ApiError("ERR_PERIOD_INVALID_STATE")
    for leg in W.month_legs_of_lease(period["lease_id"], period["period_month"]):
        if leg["status"] in ("SCHEDULED", "DISPATCHED"):
            raise ApiError("ERR_PERIOD_INVALID_STATE")

    # A first close rolls the programme forward; a close out of REOPENED does not.
    W.close_period(period, open_next_month=(period["status"] == "OPEN"))
    return object_response(public(period))


@bp.post("/wetlease/utilization-periods/<period_id>/dispute")
def dispute_period(period_id):
    actor = require((LESSEE,))
    body = V.json_body()
    dispute_reason = V.req_str(body, "dispute_reason")
    disputed_amount = V.req_int(body, "disputed_amount_cents")
    period = find_period(period_id)
    check_ownership(actor, "period", period)

    if period["status"] != "SETTLED":
        raise ApiError("ERR_PERIOD_INVALID_STATE")
    if disputed_amount <= 0 or disputed_amount > period["final_charge_cents"]:
        raise bad_request(
            "disputed_amount_cents must be greater than 0 and at most final_charge_cents")

    period["status"] = "DISPUTED"
    period["dispute_reason"] = dispute_reason
    period["disputed_amount_cents"] = disputed_amount
    touch(period)
    return object_response(public(period))


@bp.post("/wetlease/utilization-periods/<period_id>/resolve-dispute")
def resolve_dispute(period_id):
    require((BILLING_ADMIN,))
    body = V.json_body()
    resolution = V.req_enum(body, "resolution", ("REOPEN", "UPHOLD_SETTLEMENT"))
    period = find_period(period_id)

    if period["status"] != "DISPUTED":
        raise ApiError("ERR_PERIOD_INVALID_STATE")

    if resolution == "UPHOLD_SETTLEMENT":
        # dispute_reason deliberately survives on the row for audit.
        period["status"] = "SETTLED"
        period["disputed_amount_cents"] = 0
        touch(period)
        return object_response(public(period))

    # REOPEN — unwind every issued invoice, then rest in REOPENED.
    for invoice in W.invoices_of_period(period["id"]):
        if invoice["status"] == "ISSUED":
            _void_invoice(invoice, "PERIOD_DISPUTE_REOPENED",
                          period_target="REOPENED",
                          revert_statuses=("SETTLED", "DISPUTED"))
    if period["status"] != "REOPENED":
        period["status"] = "REOPENED"
        touch(period)
    return object_response(public(period))


# ---------------------------------------------------------------- invoices

def _line_items(period):
    lease = db.leases[period["lease_id"]]
    rate = C.D(lease["block_hour_rate_usd_cents"])
    mgh = C.D(period["mgh_effective_hours"])
    t1, t2, t3 = C.overrun_tiers(mgh, C.D(period["overrun_hours"]))
    tier_cents = (
        C.cents(t1 * rate * C.OVERRUN_TIER1_MULTIPLIER),
        C.cents(t2 * rate * C.OVERRUN_TIER2_MULTIPLIER),
        C.cents(t3 * rate * C.OVERRUN_TIER3_MULTIPLIER),
    )
    return [
        {"code": "BASE_GUARANTEE",
         "hours": period["mgh_effective_hours"],
         "cents": period["base_charge_cents"]},
        {"code": "SHORTFALL_CREDIT",
         "hours": period["lessor_attributable_shortfall_hours"],
         "cents": period["shortfall_credit_cents"]},
        {"code": "OVERRUN_TIER1", "hours": float(t1), "cents": tier_cents[0]},
        {"code": "OVERRUN_TIER2", "hours": float(t2), "cents": tier_cents[1]},
        {"code": "OVERRUN_TIER3", "hours": float(t3), "cents": tier_cents[2]},
        {"code": "RELIABILITY_PENALTY",
         "hours": 0.0,
         "cents": period["reliability_penalty_cents"]},
    ]


def _credit_limit_guard(lease, amount_cents):
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None:
        raise ApiError("ERR_LESSEE_NOT_FOUND")
    if lessee["outstanding_balance_usd_cents"] + amount_cents > \
            lessee["credit_limit_usd_cents"]:
        raise ApiError("ERR_LESSEE_CREDIT_LIMIT_EXCEEDED")
    return lessee


@bp.post("/wetlease/settlement-invoices")
def create_invoice():
    actor = require((BILLING_ADMIN,))
    body = V.json_body()
    period_id = V.req_str(body, "period_id")
    expected_period_version = V.req_int(body, "expected_period_version")
    due_on_raw, _due_on = V.req_date(body, "due_on")
    variant = V.opt_enum(body, "variant", ("PROVISIONAL", "FINAL"), default="FINAL")

    period = find_period(period_id)
    if expected_period_version != period["version"]:
        raise ApiError("ERR_STALE_PERIOD_VERSION")
    if period["status"] != "PENDING_SETTLEMENT":
        raise ApiError("ERR_PERIOD_NOT_READY_FOR_SETTLEMENT")

    lease = db.leases[period["lease_id"]]
    amount_cents = period["provisional_charge_cents"] if variant == "PROVISIONAL" \
        else period["final_charge_cents"]
    _credit_limit_guard(lease, amount_cents)

    row = new_row()
    row.update({
        "period_id": period["id"],
        "lease_id": period["lease_id"],
        "variant": variant,
        "amount_cents": amount_cents,
        "line_items": _line_items(period),
        "due_on": due_on_raw,
        "prepared_by_user_id": actor.user_id,
        "approved_by_user_id": None,
        "status": "PREPARED",
        "void_reason": None,
    })
    db.settlement_invoices[row["id"]] = row

    if variant == "PROVISIONAL":
        W.mark_provisionally_billed(period)
    touch(period)
    return object_response(public(row), 201)


@bp.get("/wetlease/settlement-invoices/<invoice_id>")
def get_invoice(invoice_id):
    actor = require((BILLING_ADMIN, LESSOR_OPS, LESSEE))
    invoice = find_invoice(invoice_id)
    check_ownership(actor, "invoice", invoice)
    return object_response(public(invoice))


@bp.get("/wetlease/settlement-invoices")
def list_invoices():
    actor = require((BILLING_ADMIN, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.settlement_invoices.values()), request.args, {
        "period_id": "period_id",
        "lease_id": "lease_id",
        "status": "status",
        "variant": "variant",
    })
    rows = scope_for_lessee(actor, "invoice", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/settlement-invoices/<invoice_id>/approve")
def approve_invoice(invoice_id):
    actor = require((BILLING_ADMIN,))
    V.json_body()
    invoice = find_invoice(invoice_id)

    if invoice["status"] != "PREPARED":
        raise ApiError("ERR_INVOICE_INVALID_STATE")

    period = db.utilization_periods.get(invoice["period_id"])
    period_month = period["period_month"] if period is not None else None
    if W.accepted_report_for(invoice["lease_id"], period_month) is None:
        raise ApiError("ERR_RELIABILITY_REPORT_NOT_ACCEPTED")
    if actor.user_id == invoice["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    invoice["status"] = "APPROVED"
    invoice["approved_by_user_id"] = actor.user_id
    touch(invoice)
    return object_response(public(invoice))


@bp.post("/wetlease/settlement-invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    require((BILLING_ADMIN,))
    body = V.json_body()
    due_on_raw, _due_on = V.opt_date(body, "due_on")
    invoice = find_invoice(invoice_id)

    if invoice["status"] != "APPROVED":
        raise ApiError("ERR_INVOICE_INVALID_STATE")

    lease = db.leases[invoice["lease_id"]]
    lessee = _credit_limit_guard(lease, invoice["amount_cents"])

    invoice["status"] = "ISSUED"
    if due_on_raw is not None:
        invoice["due_on"] = due_on_raw
    touch(invoice)

    lessee["outstanding_balance_usd_cents"] = (
        lessee["outstanding_balance_usd_cents"] + invoice["amount_cents"])
    touch(lessee)

    period = db.utilization_periods.get(invoice["period_id"])
    if invoice["variant"] == "FINAL" and period is not None \
            and period["status"] == "PENDING_SETTLEMENT":
        W.settle_period(period)

    return object_response(public(invoice))


def _void_invoice(invoice, reason, period_target="PENDING_SETTLEMENT",
                  revert_statuses=("SETTLED",)):
    was_issued = invoice["status"] == "ISSUED"
    invoice["status"] = "VOID"
    invoice["void_reason"] = reason
    touch(invoice)

    if not was_issued:
        return

    lease = db.leases.get(invoice["lease_id"])
    lessee = db.lessees.get(lease["lessee_id"]) if lease is not None else None
    if lessee is not None:
        lessee["outstanding_balance_usd_cents"] = (
            lessee["outstanding_balance_usd_cents"] - invoice["amount_cents"])
        touch(lessee)

    period = db.utilization_periods.get(invoice["period_id"])
    if invoice["variant"] == "FINAL" and period is not None \
            and period["status"] in revert_statuses:
        W.unsettle_period(period, period_target)


@bp.post("/wetlease/settlement-invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    require((BILLING_ADMIN,))
    body = V.json_body()
    reason = V.req_str(body, "void_reason")
    invoice = find_invoice(invoice_id)

    if invoice["status"] not in VOIDABLE_INVOICE_STATUSES:
        raise ApiError("ERR_INVOICE_INVALID_STATE")

    _void_invoice(invoice, reason)
    return object_response(public(invoice))

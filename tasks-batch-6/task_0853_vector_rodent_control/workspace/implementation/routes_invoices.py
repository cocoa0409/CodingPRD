"""Cost-recovery invoices: preparation, approval, payments, liens, voids (PRD 3.7)."""

import datetime

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import flows
import lclock
import lookups
import serialize
import store
import valid
from errors import ApiError

bp = Blueprint("invoices", __name__)
P = "/vector-control"

PAYMENT_METHODS = ("CHECK", "ACH", "CARD", "CASH")


def _owner_of(order):
    prop = store.properties.get(order["property_id"])
    if prop is None:
        return None, None
    return prop, store.owners.get(prop["owner_id"])


def _estimate(order, owner):
    tier = order["infestation_tier_at_issue"] or "LOW"
    return calc.cost_recovery_invoice_total(
        calc.ESTIMATED_LABOR_HOURS[tier],
        calc.MATERIALS_ESTIMATE_CENTS[tier],
        order["escalation_level"],
        order["education_advisory_served"],
        owner["hardship_certified"] if owner is not None else False,
    )


def _final(order, owner):
    return calc.cost_recovery_invoice_total(
        order["actual_labor_hours"] if order["actual_labor_hours"] is not None else 0,
        order["actual_materials_cents"] if order["actual_materials_cents"] is not None else 0,
        order["escalation_level"],
        order["education_advisory_served"],
        owner["hardship_certified"] if owner is not None else False,
    )


@bp.post(P + "/cost-recovery-invoices")
def create_invoice():
    caller = auth.guard("FinanceOfficer")
    data = valid.body()
    raw_order_id = data.get("abatement_order_id")
    order = None
    if isinstance(raw_order_id, str) and raw_order_id:
        order = lookups.order(raw_order_id)
    order_id = valid.req_id(data, "abatement_order_id")
    expected_version = valid.req_int(data, "expected_abatement_order_version")
    if order is None:
        order = lookups.order(order_id)
    # step 6: optimistic concurrency on the order
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")
    # step 8: related-entity state
    if order["status"] != "CITY_ABATED":
        raise ApiError("ERR_ORDER_NOT_ABATED")
    # step 10: only one live invoice per order
    for existing in store.invoices.values():
        if existing["abatement_order_id"] == order["id"] and existing["billing_status"] != "VOID":
            raise ApiError("ERR_INVOICE_ALREADY_EXISTS")

    prop, owner = _owner_of(order)
    estimate = _estimate(order, owner)
    invoice = store.stamp_new(
        {
            "abatement_order_id": order["id"],
            "property_id": order["property_id"],
            "owner_id": prop["owner_id"] if prop is not None else None,
            "prepared_by_user_id": caller.user_id,
            "approved_by_user_id": None,
            "billing_status": "DRAFT",
            "lien_status": "NONE",
            "estimated_total_cents": estimate["total_cents"],
            "final_total_cents": None,
            "labor_line_cents": None,
            "materials_line_cents": None,
            "penalty_line_cents": None,
            "education_credit_cents": None,
            "admin_fee_cents": None,
            "hardship_discount_cents": None,
            "amount_paid_cents": 0,
            "balance_due_cents": 0,
            "due_at": None,
            "paid_at": None,
            "lien_filed_at": None,
            "voided_at": None,
            "void_reason": None,
        }
    )
    store.invoices[invoice["id"]] = invoice
    store.bump(order)
    return envelope.obj(serialize.invoice(invoice), 201)


@bp.get(P + "/cost-recovery-invoices/<invoice_id>")
def read_invoice(invoice_id):
    caller = auth.guard("ProgramAdmin", "Supervisor", "FinanceOfficer", "PropertyOwner")
    invoice = lookups.invoice(invoice_id)
    auth.require_owner(caller, invoice["owner_id"])
    return envelope.obj(serialize.invoice(invoice))


@bp.get(P + "/cost-recovery-invoices")
def list_invoices():
    auth.guard("ProgramAdmin", "Supervisor", "FinanceOfficer")
    limit, offset = valid.pagination()
    filters = {
        "abatement_order_id": valid.query_str("abatement_order_id"),
        "property_id": valid.query_str("property_id"),
        "owner_id": valid.query_str("owner_id"),
        "billing_status": valid.query_str("billing_status"),
        "lien_status": valid.query_str("lien_status"),
    }

    def keep(v):
        for field, expected in filters.items():
            if expected is not None and v[field] != expected:
                return False
        return True

    rows = store.ordered(store.invoices, keep)
    return lookups.page(rows, limit, offset, serialize.invoice)


@bp.post(P + "/cost-recovery-invoices/<invoice_id>/approve")
def approve_invoice(invoice_id):
    caller = auth.guard("ProgramAdmin")
    invoice = lookups.invoice(invoice_id)
    data = valid.body()
    escalated_approval = valid.opt_bool(data, "escalated_approval", False)
    if invoice["billing_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT invoice may be approved.")
    if caller.user_id == invoice["prepared_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN")
    order = store.orders.get(invoice["abatement_order_id"])
    owner = store.owners.get(invoice["owner_id"])
    final = _final(order, owner)
    if final["total_cents"] > calc.APPROVAL_LIMIT_CENTS and not escalated_approval:
        raise ApiError("ERR_APPROVAL_LIMIT_EXCEEDED")

    now = lclock.now()
    invoice["billing_status"] = "APPROVED"
    invoice["approved_by_user_id"] = caller.user_id
    invoice["final_total_cents"] = final["total_cents"]
    invoice["labor_line_cents"] = final["labor_line_cents"]
    invoice["materials_line_cents"] = final["materials_line_cents"]
    invoice["penalty_line_cents"] = final["penalty_line_cents"]
    invoice["education_credit_cents"] = final["education_credit_cents"]
    invoice["admin_fee_cents"] = final["admin_fee_cents"]
    invoice["hardship_discount_cents"] = final["hardship_discount_cents"]
    invoice["balance_due_cents"] = final["total_cents"]
    invoice["due_at"] = now + datetime.timedelta(days=calc.INVOICE_DUE_DAYS)
    store.touch(invoice)
    flows.owner_recompute(invoice["owner_id"])
    return envelope.obj(serialize.invoice(invoice))


@bp.post(P + "/cost-recovery-invoices/<invoice_id>/payments")
def post_payment(invoice_id):
    caller = auth.guard("FinanceOfficer", "PropertyOwner")
    invoice = lookups.invoice(invoice_id)
    auth.require_owner(caller, invoice["owner_id"])
    data = valid.body()
    amount_cents = valid.req_int(data, "amount_cents", minimum=1)
    valid.req_enum(data, "method", PAYMENT_METHODS)
    if invoice["billing_status"] not in ("APPROVED", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVOICE_NOT_APPROVED")
    if amount_cents > invoice["balance_due_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    now = lclock.now()
    invoice["amount_paid_cents"] += amount_cents
    invoice["balance_due_cents"] -= amount_cents
    if invoice["balance_due_cents"] == 0:
        invoice["billing_status"] = "PAID"
        invoice["paid_at"] = now
        store.touch(invoice)
        flows.release_lien(invoice)
        flows.owner_recompute(invoice["owner_id"])
        order = store.orders.get(invoice["abatement_order_id"])
        if order is not None and order["status"] == "CITY_ABATED":
            flows.order_reaches_terminal(order, "CLOSED")
    else:
        invoice["billing_status"] = "PARTIALLY_PAID"
        store.touch(invoice)
        flows.owner_recompute(invoice["owner_id"])
    return envelope.obj(serialize.invoice(invoice))


@bp.post(P + "/cost-recovery-invoices/<invoice_id>/lien")
def file_lien(invoice_id):
    auth.guard("FinanceOfficer")
    invoice = lookups.invoice(invoice_id)
    if invoice["lien_status"] != "NONE":
        raise ApiError("ERR_INVALID_STATE", "A lien has already been filed on this invoice.")
    if invoice["billing_status"] not in ("APPROVED", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVOICE_NOT_APPROVED")
    now = lclock.now()
    due_at = invoice["due_at"]
    past_due_mark = (
        due_at + datetime.timedelta(days=calc.LIEN_MIN_DAYS_PAST_DUE) if due_at else None
    )
    if invoice["balance_due_cents"] < calc.LIEN_MIN_BALANCE_CENTS:
        raise ApiError("ERR_LIEN_THRESHOLD_NOT_MET")
    if past_due_mark is None or now < past_due_mark:
        raise ApiError("ERR_LIEN_THRESHOLD_NOT_MET")
    invoice["lien_status"] = "FILED"
    invoice["lien_filed_at"] = now
    store.touch(invoice)
    prop = store.properties.get(invoice["property_id"])
    if prop is not None:
        aggregates.property_counters(prop)
        store.bump(prop)
    return envelope.obj(serialize.invoice(invoice))


@bp.post(P + "/cost-recovery-invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    auth.guard("FinanceOfficer")
    invoice = lookups.invoice(invoice_id)
    data = valid.body()
    void_reason = valid.req_str(data, "void_reason", min_len=1)
    if invoice["billing_status"] in ("PAID", "VOID"):
        raise ApiError("ERR_INVALID_STATE", "A PAID or VOID invoice cannot be voided.")
    invoice["billing_status"] = "VOID"
    invoice["void_reason"] = void_reason
    invoice["voided_at"] = lclock.now()
    invoice["balance_due_cents"] = 0
    store.touch(invoice)
    flows.release_lien(invoice)
    flows.owner_recompute(invoice["owner_id"])
    return envelope.obj(serialize.invoice(invoice))

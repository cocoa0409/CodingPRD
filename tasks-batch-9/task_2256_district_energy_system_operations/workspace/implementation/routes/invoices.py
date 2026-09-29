"""Invoice endpoints, the billing ledger and the arrears cascade (PRD 3.7)."""

from flask import Blueprint, g

import enums
import services as svc
from calc import D
from db import base_record, store, touch
from errors import fail
from middleware import endpoint, paginate
from validators import (bad, get_dt, get_enum, get_int, get_num, get_str,
                        json_body, present, query_enum, query_str)

bp = Blueprint("invoices", __name__, url_prefix="/district-energy")

LIST_READERS = ("SystemController", "BillingAnalyst")
GET_READERS = ("SystemController", "BillingAnalyst", "CustomerAccount")

BILLABLE_CONTRACT_STATES = ("ACTIVE", "SUSPENDED")
LEDGER_STATES = ("DRAFT", "ISSUED", "ADJUSTED", "PAID")

DETERMINANT_FIELDS = ("billed_energy_mwh", "billed_demand_kw", "load_factor_pct",
                      "energy_charge", "demand_charge", "fixed_charge",
                      "total_amount", "minimum_bill_applied", "variant_applied")


def require_ownership(invoice):
    if g.role == "CustomerAccount" and g.user_id != invoice["agreement_id"]:
        fail("ERR_FORBIDDEN_AGREEMENT",
             "a CustomerAccount may only act on its own invoices")


@endpoint(bp, "/invoices", ["POST"], ["BillingAnalyst"], status=201)
def create_invoice():
    body = json_body()
    agreement_id = get_str(body, "agreement_id")
    start_raw, start_dt = get_dt(body, "period_start")
    end_raw, end_dt = get_dt(body, "period_end")
    variant = get_enum(body, "variant", enums.INVOICE_VARIANT)
    expected_version = get_int(body, "expected_agreement_version", ge=0)
    if not end_dt > start_dt:
        bad("period_end must be after period_start")

    agreement = svc.fk_get("agreements", agreement_id)

    if agreement["version"] != expected_version:
        fail("ERR_STALE_AGREEMENT_VERSION",
             "the agreement is at version %d, not %d"
             % (agreement["version"], expected_version))

    if agreement["contract_state"] not in BILLABLE_CONTRACT_STATES:
        fail("ERR_INVOICE_STATE_INVALID",
             "the agreement is '%s' and cannot be billed"
             % agreement["contract_state"])

    for peer in svc.rows("invoices"):
        if peer["agreement_id"] != agreement["id"]:
            continue
        if peer["invoice_state"] not in LEDGER_STATES:
            continue
        if start_dt < peer["_period_end"] and peer["_period_start"] < end_dt:
            fail("ERR_INVOICE_PERIOD_OVERLAP",
                 "the billing period overlaps invoice '%s'" % peer["id"])

    determinants = svc.run_determinants(agreement, start_dt, end_dt, variant)

    invoice = base_record()
    invoice.update({
        "agreement_id": agreement["id"],
        "period_start": start_raw,
        "_period_start": start_dt,
        "period_end": end_raw,
        "_period_end": end_dt,
        "paid_amount": 0.0,
        "invoice_state": "DRAFT",
    })
    invoice.update(determinants)
    store.invoices[invoice["id"]] = invoice

    touch(agreement)
    return invoice


@endpoint(bp, "/invoices", ["GET"], LIST_READERS)
def list_invoices():
    filters = {}
    agreement_id = query_str("agreement_id")
    invoice_state = query_enum("invoice_state", enums.INVOICE_STATE)
    variant_applied = query_enum("variant_applied", enums.INVOICE_VARIANT)
    if agreement_id is not None:
        filters["agreement_id"] = agreement_id
    if invoice_state is not None:
        filters["invoice_state"] = invoice_state
    if variant_applied is not None:
        filters["variant_applied"] = variant_applied
    return paginate(svc.where("invoices", **filters))


@endpoint(bp, "/invoices/<invoice_id>", ["GET"], GET_READERS)
def get_invoice(invoice_id):
    invoice = svc.path_get("invoices", invoice_id)
    require_ownership(invoice)
    return invoice


@endpoint(bp, "/invoices/<invoice_id>/issue", ["POST"], ["BillingAnalyst"])
def issue_invoice(invoice_id):
    invoice = svc.path_get("invoices", invoice_id)
    agreement = store.agreements[invoice["agreement_id"]]
    if invoice["invoice_state"] != "DRAFT":
        fail("ERR_INVOICE_STATE_INVALID", "only a DRAFT invoice can be issued")
    if agreement["contract_state"] not in BILLABLE_CONTRACT_STATES:
        fail("ERR_INVOICE_STATE_INVALID",
             "the agreement is '%s' and cannot be billed"
             % agreement["contract_state"])

    invoice["invoice_state"] = "ISSUED"
    touch(invoice)

    if D(invoice["billed_demand_kw"]) > D(agreement["billed_demand_ratchet_kw"]):
        agreement["billed_demand_ratchet_kw"] = invoice["billed_demand_kw"]
    balance = svc.recompute_balance(agreement)
    svc.enter_arrears_if_needed(agreement, balance)
    touch(agreement)
    return invoice


@endpoint(bp, "/invoices/<invoice_id>/adjust", ["POST"], ["BillingAnalyst"])
def adjust_invoice(invoice_id):
    body = json_body()
    variant = get_enum(body, "variant", enums.INVOICE_VARIANT)
    if present(body, "adjustment_note"):
        get_str(body, "adjustment_note", min_len=0)

    invoice = svc.path_get("invoices", invoice_id)
    agreement = store.agreements[invoice["agreement_id"]]
    if invoice["invoice_state"] not in ("ISSUED", "ADJUSTED"):
        fail("ERR_INVOICE_STATE_INVALID",
             "only an ISSUED or ADJUSTED invoice can be adjusted")
    if agreement["contract_state"] not in BILLABLE_CONTRACT_STATES:
        fail("ERR_INVOICE_STATE_INVALID",
             "the agreement is '%s' and cannot be billed"
             % agreement["contract_state"])

    determinants = svc.run_determinants(
        agreement, invoice["_period_start"], invoice["_period_end"], variant)
    for field in DETERMINANT_FIELDS:
        invoice[field] = determinants[field]
    invoice["invoice_state"] = "ADJUSTED"
    touch(invoice)

    svc.recompute_balance(agreement)
    touch(agreement)
    return invoice


@endpoint(bp, "/invoices/<invoice_id>/payments", ["POST"], ["CustomerAccount"])
def pay_invoice(invoice_id):
    body = json_body()
    amount = get_num(body, "amount", ge=0)

    invoice = svc.path_get("invoices", invoice_id)
    require_ownership(invoice)
    if invoice["invoice_state"] not in ("ISSUED", "ADJUSTED"):
        fail("ERR_INVOICE_STATE_INVALID",
             "only an ISSUED or ADJUSTED invoice can be paid")
    if D(amount) != D(invoice["total_amount"]):
        fail("ERR_PAYMENT_AMOUNT_MISMATCH",
             "the payment must equal the invoice total of %s"
             % invoice["total_amount"])

    invoice["paid_amount"] = amount
    invoice["invoice_state"] = "PAID"
    touch(invoice)

    agreement = store.agreements[invoice["agreement_id"]]
    balance = svc.recompute_balance(agreement)
    svc.exit_arrears_if_needed(agreement, balance)
    touch(agreement)
    return invoice


@endpoint(bp, "/invoices/<invoice_id>/void", ["POST"], ["BillingAnalyst"])
def void_invoice(invoice_id):
    body = json_body()
    if present(body, "reason"):
        get_str(body, "reason", min_len=0)

    invoice = svc.path_get("invoices", invoice_id)
    previous = invoice["invoice_state"]
    if previous not in ("DRAFT", "ISSUED", "ADJUSTED"):
        fail("ERR_INVOICE_STATE_INVALID",
             "a '%s' invoice cannot be voided" % previous)

    invoice["invoice_state"] = "VOID"
    touch(invoice)

    if previous == "DRAFT":
        return invoice

    agreement = store.agreements[invoice["agreement_id"]]
    balance = svc.recompute_balance(agreement)
    svc.exit_arrears_if_needed(agreement, balance)
    touch(agreement)
    return invoice

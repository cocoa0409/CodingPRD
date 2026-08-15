"""Fee invoice endpoints: create (tiered/flat fee math), get, list, approve, pay."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services import navmath
from services.navmath import D, round2
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("fee_invoices", __name__)

INVOICE_SCHEMA = {
    "fund_id": ("string", True, None),
    "fee_type": ("enum", True, ["ADVISER", "ADMINISTRATOR"]),
    "period_start": ("date", True, None),
    "period_end": ("date", True, None),
}

FEE_YEAR_DAYS = Decimal(365)


def _daterange(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


@bp.post("/fee-invoices")
def create_fee_invoice():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(INVOICE_SCHEMA)
    fund = require_fk(store.funds, body["fund_id"], "fund_id")
    if body["period_end"] < body["period_start"]:
        raise ApiError("ERR_VALIDATION", 400, "period_end must not precede period_start")

    # Constraint (priority 9): periods for one fund+fee_type tile contiguously.
    priors = [i for i in store.fee_invoices.values()
              if i["fund_id"] == fund["id"] and i["fee_type"] == body["fee_type"]
              and i["status"] in ("DRAFT", "APPROVED", "PAID")]
    if priors:
        previous_end = max(i["period_end"] for i in priors)
        expected_start = (navmath.date_of(previous_end) + timedelta(days=1)).isoformat()
        if body["period_start"] != expected_start:
            raise ApiError("ERR_FEE_PERIOD_NOT_CONTIGUOUS", 409,
                           "period_start must be exactly one day after the previous period_end")

    # adviser_fee_tiered: inclusive day count; per-date fund TNA over FINAL
    # records of all the fund's classes; dates without any FINAL are excluded
    # from both numerator and denominator.
    start = navmath.date_of(body["period_start"])
    end = navmath.date_of(body["period_end"])
    days = (end - start).days + 1
    class_ids = {c["id"] for c in store.share_classes.values()
                 if c["fund_id"] == fund["id"]}
    daily_sum = Decimal("0")
    contributing = 0
    for day in _daterange(start, end):
        iso = day.isoformat()
        day_tna = sum((D(n["total_net_assets"]) for n in store.nav_records.values()
                       if n["share_class_id"] in class_ids and n["status"] == "FINAL"
                       and n["accounting_date"] == iso), Decimal("0"))
        has_final = any(n["share_class_id"] in class_ids and n["status"] == "FINAL"
                        and n["accounting_date"] == iso
                        for n in store.nav_records.values())
        if has_final:
            daily_sum += day_tna
            contributing += 1
    if contributing == 0:
        raise ApiError("ERR_NO_FINAL_NAV_IN_PERIOD", 422,
                       "No FINAL NavRecord of the fund inside the fee period")

    # Average daily net assets stays unrounded until the final multiplication.
    adna = daily_sum / Decimal(contributing)
    if body["fee_type"] == "ADVISER":
        units = Decimal("0")
        prev = Decimal("0")
        for tier in fund["adviser_fee_tiers"]:
            ceiling = tier["up_to_net_assets"]
            top = adna if ceiling is None else min(adna, D(ceiling))
            chunk = top - prev
            if chunk > 0:
                units += chunk * D(tier["rate_bps"])
            if ceiling is None:
                break
            prev = D(ceiling)
    else:
        units = adna * D(fund["admin_fee_bps"])
    gross_fee = round2(units / Decimal(10000) * Decimal(days) / FEE_YEAR_DAYS)

    # Waiver offset: WAIVER ledger amounts dated inside the period across all
    # agreements of the fund's classes.
    agreement_ids = {a["id"] for a in store.waiver_agreements.values()
                     if a["share_class_id"] in class_ids}
    waiver_offset = sum((D(e["amount"]) for e in store.waiver_ledger_entries.values()
                         if e["waiver_agreement_id"] in agreement_ids
                         and e["entry_type"] == "WAIVER"
                         and body["period_start"] <= e["entry_date"] <= body["period_end"]),
                        Decimal("0"))
    net_fee = round2(max(Decimal("0"), gross_fee - waiver_offset))

    invoice = {
        "id": db.new_id(),
        "fund_id": fund["id"],
        "fee_type": body["fee_type"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "average_daily_net_assets": adna,
        "gross_fee": gross_fee,
        "waiver_offset": waiver_offset,
        "net_fee": net_fee,
        "status": "DRAFT",
        "created_by_user_id": g.user_id,
        "approved_by_user_id": None,
    }
    db.new_common(invoice)
    store.fee_invoices[invoice["id"]] = invoice
    return created(invoice)


@bp.get("/fee-invoices/<fee_invoice_id>")
def get_fee_invoice(fee_invoice_id):
    get_context()
    invoice = require_path_entity(store.fee_invoices, fee_invoice_id)
    require_roles(ALL_ROLES)
    return ok(invoice)


@bp.get("/fee-invoices")
def list_fee_invoices():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.fee_invoices.values())
    rows = filter_arg(rows, "fund_id")
    rows = filter_arg(rows, "fee_type")
    rows = filter_arg(rows, "status")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/fee-invoices/<fee_invoice_id>/approve")
def approve_fee_invoice(fee_invoice_id):
    get_context()
    invoice = require_path_entity(store.fee_invoices, fee_invoice_id)
    require_roles(["FundController"])
    parse_body({})
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT invoice can be approved")
    if g.user_id == invoice["created_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "The invoice's preparer cannot approve it")
    invoice["status"] = "APPROVED"
    invoice["approved_by_user_id"] = g.user_id
    db.touch(invoice)
    return ok(invoice)


@bp.post("/fee-invoices/<fee_invoice_id>/pay")
def pay_fee_invoice(fee_invoice_id):
    get_context()
    invoice = require_path_entity(store.fee_invoices, fee_invoice_id)
    require_roles(["FundController"])
    parse_body({})
    if invoice["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an APPROVED invoice can be paid")
    invoice["status"] = "PAID"
    db.touch(invoice)
    return ok(invoice)

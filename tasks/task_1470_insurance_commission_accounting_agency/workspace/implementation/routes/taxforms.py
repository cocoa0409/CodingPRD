"""TaxForm1099 endpoints: generate, list, get, finalize."""
from flask import Blueprint

from db import DB, now_iso
from errors import ApiError
from middleware import auth, ADMIN, ALL_ROLES
from response import ok
from services import (
    FORM_1099_THRESHOLD_CENTS,
    accrual_basis_total_cents,
    by_seq,
    cash_basis_total_cents,
    new_resource,
    ser_taxform,
    touch,
)
from util import apply_filters, as_int, get_body, req, respond_list

bp = Blueprint("taxforms", __name__)


@bp.post("/agency/tax-forms/generate")
def generate_tax_forms():
    auth(ADMIN)
    data = get_body()
    tax_year = as_int(req(data, "tax_year"), "tax_year")
    created = []
    for producer in by_seq(DB["producers"].values()):
        cash = cash_basis_total_cents(producer["id"], tax_year)
        if cash < FORM_1099_THRESHOLD_CENTS:
            continue
        exists = any(
            f["producer_id"] == producer["id"] and f["tax_year"] == tax_year
            for f in DB["taxforms"].values()
        )
        if exists:
            continue
        form = new_resource({
            "producer_id": producer["id"],
            "tax_year": tax_year,
            "status": "DRAFT",
            "finalized_at": None,
        })
        DB["taxforms"][form["id"]] = form
        created.append(form)
    return ok({
        "generated_count": len(created),
        "tax_form_ids": [f["id"] for f in created],
    })


@bp.get("/agency/tax-forms")
def list_tax_forms():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["taxforms"].values(),
        {"producer_id": "producer_id", "tax_year": "tax_year", "status": "status"},
    )
    return respond_list(items, ser_taxform)


@bp.get("/agency/tax-forms/<formId>")
def get_tax_form(formId):
    auth(ALL_ROLES)
    f = DB["taxforms"].get(formId)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TaxForm1099 not found")
    return ok(ser_taxform(f))


@bp.post("/agency/tax-forms/<formId>/finalize")
def finalize_tax_form(formId):
    auth(ADMIN)
    f = DB["taxforms"].get(formId)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TaxForm1099 not found")
    if f["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "TaxForm1099 is not DRAFT")
    # Totals recomputed as of now and locked against further drift.
    f["cash_basis_total_cents"] = cash_basis_total_cents(f["producer_id"], f["tax_year"])
    f["accrual_basis_total_cents"] = accrual_basis_total_cents(f["producer_id"], f["tax_year"])
    f["status"] = "FINALIZED"
    f["finalized_at"] = now_iso()
    touch(f)
    return ok(ser_taxform(f))

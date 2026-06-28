"""TaxForm: generate, list, get (PRD §3.10). Immutable snapshot — id + created_at
only (no updated_at / version).

FORM_1099_SA: gross = sum amount over CLEARED-and-not-later-REVERSED distributions
in plan_year; nonqualified = sum over those whose substantiation_status ==
NONQUALIFIED (UNSUBSTANTIATED treated as NONQUALIFIED for tax reporting); fmv = 0.
FORM_5498_SA: gross = sum amount over POSTED contributions in tax_year;
fmv = cash_balance + invested_balance snapshot; nonqualified = 0.
"""
from flask import Blueprint

import serializers
from db import db, stamp_create
from helpers import get_json_body, paginate, qarg, require_enum, require_int
from lookups import get_account, get_tax_form
from middleware import caller, require_role
from response import success

bp = Blueprint("tax_forms", __name__)


@bp.route("/hsa/accounts/<account_id>/tax-forms", methods=["POST"])
def generate_tax_form(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    body = get_json_body()
    form_type = require_enum(body, "form_type", {"FORM_1099_SA", "FORM_5498_SA"})
    tax_year = require_int(body, "tax_year")

    if form_type == "FORM_1099_SA":
        included = [
            d for d in db.distributions.values()
            if d["account_id"] == account_id and d["status"] == "CLEARED"
        ]
        gross = sum(d["amount_cents"] for d in included)
        nonqualified = sum(
            d["amount_cents"] for d in included
            if d["substantiation_status"] in ("NONQUALIFIED", "UNSUBSTANTIATED")
        )
        fmv = 0
    else:  # FORM_5498_SA
        posted = [
            c for c in db.contributions.values()
            if c["account_id"] == account_id and c["status"] == "POSTED"
        ]
        gross = sum(c["amount_cents"] for c in posted)
        nonqualified = 0
        fmv = account["cash_balance_cents"] + account["invested_balance_cents"]

    o = {
        "account_id": account_id,
        "form_type": form_type,
        "tax_year": tax_year,
        "gross_amount_cents": gross,
        "nonqualified_amount_cents": nonqualified,
        "fair_market_value_cents": fmv,
    }
    stamp_create(o, versioned=False)  # immutable: only id + created_at
    db.tax_forms[o["id"]] = o
    return success(serializers.tax_form(o), status=201)


@bp.route("/hsa/accounts/<account_id>/tax-forms", methods=["GET"])
def list_tax_forms(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    form_type = qarg("form_type")
    tax_year = qarg("tax_year")
    tax_year_int = None
    if tax_year is not None:
        try:
            tax_year_int = int(tax_year)
        except (ValueError, TypeError):
            tax_year_int = None
    items = [
        t for t in db.tax_forms.values()
        if t["account_id"] == account_id
        and (form_type is None or t["form_type"] == form_type)
        and (tax_year is None or t["tax_year"] == tax_year_int)
    ]
    page, meta = paginate(items)
    return success([serializers.tax_form(t) for t in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/tax-forms/<tax_form_id>", methods=["GET"])
def get_tax_form_route(account_id, tax_form_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    o = get_tax_form(account_id, tax_form_id)
    return success(serializers.tax_form(o), status=200)

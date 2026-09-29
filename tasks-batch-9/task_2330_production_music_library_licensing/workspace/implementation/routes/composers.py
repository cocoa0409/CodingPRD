"""Composer create/read plus the royalty preview."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import (
    ALL_STAFF,
    body,
    opt_enum,
    opt_number,
    opt_string,
    req_string,
    require_role,
)
from response import object_response
from routes.common import PREFIX, PRO_AFFILIATIONS, guard_composer
from services import calc
from services.cascade import sweep_set
from services.derive import lookup, outstanding_advance_cents, serialize_composer

bp = Blueprint("composers", __name__)


@bp.post(PREFIX + "/composers")
def create_composer():
    data = body()
    display_name = req_string(data, "display_name", allow_empty=False)
    pro = opt_enum(data, "pro_affiliation", PRO_AFFILIATIONS, "NONE")
    country = opt_string(data, "payee_country", "US", allow_empty=False)
    withholding = opt_number(data, "tax_withholding_pct", 0, Decimal("0.50"), "0.30")
    require_role("CatalogAdmin", "RightsManager")

    row = DB.new_row()
    row.update(
        {
            "display_name": display_name,
            "pro_affiliation": pro,
            "payee_country": country,
            "_tax_withholding_pct": calc.dp2(withholding),
        }
    )
    DB.composers[row["id"]] = row
    return object_response(serialize_composer(row), 201)


@bp.get(PREFIX + "/composers/<composer_id>")
def get_composer(composer_id):
    row = lookup("composers", composer_id)
    require_role(*(ALL_STAFF + ("Composer",)))
    guard_composer(row["id"])
    return object_response(serialize_composer(row))


@bp.get(PREFIX + "/composers/<composer_id>/royalty-preview")
def royalty_preview(composer_id):
    args = request.args
    start = _query_dt(args, "period_start")
    end = _query_dt(args, "period_end")
    basis = args.get("basis")
    if basis in (None, ""):
        basis = "ACCRUAL"
    if basis not in ("ACCRUAL", "CASH"):
        fail("ERR_VALIDATION", "basis must be ACCRUAL or CASH.")

    composer = lookup("composers", composer_id)
    require_role("RoyaltyAccountant", "Composer")
    guard_composer(composer["id"])

    accrual = sweep_set(composer["id"], start, end, "ACCRUAL")
    cash = sweep_set(composer["id"], start, end, "CASH")
    accrual_gross = sum(e["amount_cents"] for e in accrual)
    cash_gross = sum(e["amount_cents"] for e in cash)
    selected = accrual if basis == "ACCRUAL" else cash
    gross = accrual_gross if basis == "ACCRUAL" else cash_gross
    advance = outstanding_advance_cents(composer["id"])
    recouped, withholding, net, status = calc.statement_figures(
        gross, advance, composer["_tax_withholding_pct"]
    )
    return object_response(
        {
            "basis": basis,
            "accrual_gross_cents": accrual_gross,
            "cash_gross_cents": cash_gross,
            "gross_cents": gross,
            "included_entry_count": len(selected),
            "outstanding_advance_cents": advance,
            "projected_recoup_cents": recouped,
            "projected_withholding_cents": withholding,
            "projected_net_cents": net,
            "projected_payout_status": status,
        }
    )


def _query_dt(args, name):
    from db import parse_ts

    raw = args.get(name)
    if raw in (None, ""):
        fail("ERR_VALIDATION", "%s is required." % name)
    parsed = parse_ts(raw)
    if parsed is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 timestamp." % name)
    return parsed

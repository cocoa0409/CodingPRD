"""1099-K tax form endpoints (PRD §3.11)."""
from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_int, err,
)
from errors import ERR_INVALID_STATE, ERR_BELOW_1099K_THRESHOLD
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch
from services.entity import stamp_create, touch

bp = Blueprint("tax_forms", __name__)

FEDERAL_THRESHOLD_CENTS = 500000
LEGACY_THRESHOLD_CENTS = 2000000
LEGACY_TXN_THRESHOLD = 200


@bp.post("/tax-forms")
def create_tax_form():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    body = get_json_body()
    require_fields(body, ["seller_id", "tax_year"])
    require_int(body["tax_year"], "tax_year", 2020, 2030)
    seller = fetch(db.sellers, body["seller_id"])

    form = {
        "seller_id": seller["id"],
        "tax_year": body["tax_year"],
        "gross_reported_cents": 0,
        "transaction_count": 0,
        "threshold_basis": "NONE",
        "form_status": "DRAFT",
    }
    stamp_create(form)
    db.tax_forms[form["id"]] = form
    return success(form, status=201)


def _compute_figures(seller_id, tax_year):
    """Gross & count of AVAILABLE/PAID orders whose settled_at year == tax_year
    (PRD §3.11). Refunds/chargebacks do not reduce gross (IRS gross-volume)."""
    orders = [
        o for o in db.orders.values()
        if o["seller_id"] == seller_id
        and o["settlement_status"] in ("AVAILABLE", "PAID")
        and o.get("settled_at")
        and o["settled_at"][:4] == str(tax_year)
    ]
    gross = sum(o["gross_amount_cents"] for o in orders)
    count = len(orders)
    return gross, count


def _threshold_basis(gross, count):
    if gross >= FEDERAL_THRESHOLD_CENTS:
        return "FEDERAL_5000"
    if gross >= LEGACY_THRESHOLD_CENTS and count >= LEGACY_TXN_THRESHOLD:
        return "LEGACY_20K_200"
    return "NONE"


@bp.get("/tax-forms/<form_id>")
def get_tax_form(form_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    form = fetch(db.tax_forms, form_id)
    from routes.helpers import ensure_seller_owns
    ensure_seller_owns(role, user_id, form["seller_id"])
    return success(form)


@bp.get("/tax-forms")
def list_tax_forms():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.tax_forms.values())
    if role == ROLE_SELLER:
        items = [f for f in items if f["seller_id"] == user_id]
    seller_id = request.args.get("seller_id")
    if seller_id is not None:
        items = [f for f in items if f["seller_id"] == seller_id]
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        items = [f for f in items if str(f["tax_year"]) == tax_year]
    form_status = request.args.get("form_status")
    if form_status is not None:
        items = [f for f in items if f["form_status"] == form_status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)


@bp.post("/tax-forms/<form_id>/issue")
def issue(form_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    form = fetch(db.tax_forms, form_id)
    if form["form_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Only a DRAFT form can be issued.")
    body = get_json_body()
    force = bool(body.get("force", False))

    gross, count = _compute_figures(form["seller_id"], form["tax_year"])
    basis = _threshold_basis(gross, count)

    # Below-threshold (basis NONE) blocked unless force=true (PRD §3.11).
    if basis == "NONE" and not force:
        raise err(ERR_BELOW_1099K_THRESHOLD,
                  "1099-K below threshold; supply force=true to issue.")

    form["gross_reported_cents"] = gross
    form["transaction_count"] = count
    form["threshold_basis"] = basis
    form["form_status"] = "ISSUED"
    touch(form)
    return success(form)


@bp.post("/tax-forms/<form_id>/correct")
def correct(form_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    form = fetch(db.tax_forms, form_id)
    if form["form_status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Only an ISSUED form can be corrected.")
    gross, count = _compute_figures(form["seller_id"], form["tax_year"])
    form["gross_reported_cents"] = gross
    form["transaction_count"] = count
    form["threshold_basis"] = _threshold_basis(gross, count)
    form["form_status"] = "CORRECTED"
    touch(form)
    return success(form)

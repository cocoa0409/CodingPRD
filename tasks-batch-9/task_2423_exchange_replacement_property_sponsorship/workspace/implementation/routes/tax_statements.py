"""Tax statement endpoints (PRD 3.8, exempt from posture gating)."""
from datetime import datetime, timezone
from fractions import Fraction

from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("tax_statements", __name__)


def _year_window(tax_year):
    return (
        datetime(tax_year, 1, 1, tzinfo=timezone.utc),
        datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc),
    )


def _trust_totals(trust, tax_year):
    """The three trust-level totals of PRD 3.8, over unreversed entries only."""
    start, end = _year_window(tax_year)
    rental = 0
    interest = 0
    for entry in domain.unreversed_entries(trust["id"]):
        if not (start <= entry["occurred_at"] < end):
            continue
        if entry["entry_type"] == "RENT_RECEIPT":
            rental += entry["amount_cents"]
        elif entry["entry_type"] == "DEBT_SERVICE":
            interest += entry["amount_cents"]
    prop = db.properties[trust["property_id"]]
    depreciation = calc.trust_depreciation(
        prop.get("depreciable_basis_cents") or 0,
        trust.get("property_acquired_at"),
        tax_year,
    )
    return rental, -interest, depreciation


def _share(trust, sub, tax_year, variant):
    if variant == "UNITS_AT_YEAR_END":
        denominator = trust["units_issued"]
        if not denominator:
            return Fraction(0)
        return Fraction(sub["units_requested"], denominator)
    mine = calc.unit_days(sub["units_requested"], sub.get("closed_at"), tax_year)
    total = 0
    for other in domain.closed_subscriptions_of_trust(trust):
        total += calc.unit_days(other["units_requested"], other.get("closed_at"), tax_year)
    if not total:
        return Fraction(0)
    return Fraction(mine, total)


@bp.post("/tax-statements")
def prepare_tax_statement():
    middleware.actor([C.SPONSOR])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    subscription_id = middleware.req_str(payload, "subscription_id")
    tax_year = middleware.req_int(payload, "tax_year", 2026)
    allocation_variant = middleware.req_enum(payload, "allocation_variant",
                                             C.ALLOCATION_VARIANTS)

    trust = domain.require("trust", trust_id)
    sub = domain.require("subscription", subscription_id)

    if sub["status"] != "CLOSED":
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE")

    for other in db.sorted_rows(db.tax_statements):
        if other["trust_id"] == trust["id"] \
                and other["subscription_id"] == sub["id"] \
                and other["tax_year"] == tax_year \
                and other["allocation_variant"] == allocation_variant:
            raise ApiError("ERR_DUPLICATE_TAX_STATEMENT")

    rental_total, interest_total, depreciation_total = _trust_totals(trust, tax_year)
    share = _share(trust, sub, tax_year, allocation_variant)
    amounts = calc.tax_allocation(rental_total, interest_total, depreciation_total, share)

    row = db.new_row(db.tax_statements, {
        "trust_id": trust["id"],
        "subscription_id": sub["id"],
        "tax_year": tax_year,
        "allocation_variant": allocation_variant,
        "rental_income_cents": amounts["rental_income_cents"],
        "interest_expense_cents": amounts["interest_expense_cents"],
        "depreciation_cents": amounts["depreciation_cents"],
        "net_taxable_income_cents": amounts["net_taxable_income_cents"],
        "issued_at": None,
        "status": "DRAFT",
    })
    return created_response(db.serialize(row))


@bp.get("/tax-statements/<tax_statement_id>")
def get_tax_statement(tax_statement_id):
    return read_one("tax_statement", C.READ_TRUST_SIDE, tax_statement_id)


@bp.get("/tax-statements")
def list_tax_statements():
    return listing(db.tax_statements, C.READ_TRUST_SIDE,
                   str_filters=("trust_id", "subscription_id", "status",
                                "allocation_variant"),
                   int_filters=("tax_year",))


@bp.post("/tax-statements/<tax_statement_id>/issue")
def issue_tax_statement(tax_statement_id):
    middleware.actor([C.SPONSOR])
    statement = domain.require("tax_statement", tax_statement_id)
    sub = db.subscriptions.get(statement["subscription_id"])

    if sub is None or sub["status"] != "CLOSED":
        raise ApiError("ERR_SUBSCRIPTION_INVALID_STATE")
    if statement["status"] != "DRAFT":
        raise ApiError("ERR_TAX_STATEMENT_INVALID_STATE")

    statement["status"] = "ISSUED"
    statement["issued_at"] = clock.now()
    db.touch(statement)
    return object_response(db.serialize(statement))

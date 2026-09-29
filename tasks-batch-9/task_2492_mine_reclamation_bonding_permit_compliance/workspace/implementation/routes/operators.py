"""Operator registry and the self-bonding financial test (PRD 3.1)."""

from flask import Blueprint

import calculations as calc
import constants as C
import serialization as ser
from db import ZERO, base_row, db
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import apply_filters, collection_filtered, paged
from validation import authorize, enum_field, get_body, lookup, number_field, str_field

bp = Blueprint("operators", __name__)

LIST_FILTERS = [
    ("registry_status", "registry_status", C.REGISTRY_STATUSES),
    ("self_bond_status", "self_bond_status", C.SELF_BOND_STATUSES),
]


@bp.post("/mining/operators")
def create_operator():
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    legal_name = str_field(body, "legal_name")
    tangible_net_worth = number_field(body, "tangible_net_worth", ge=0)
    fixed_assets_in_state = number_field(body, "fixed_assets_in_state", ge=0)
    total_liabilities = number_field(body, "total_liabilities", ge=0)
    net_income_prior_year = number_field(body, "net_income_prior_year")
    elected = enum_field(body, "elected_financial_test", C.ELECTED_FINANCIAL_TESTS)

    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "tangible_net_worth": tangible_net_worth,
            "fixed_assets_in_state": fixed_assets_in_state,
            "total_liabilities": total_liabilities,
            "net_income_prior_year": net_income_prior_year,
            "elected_financial_test": elected,
            "registry_status": "ACTIVE",
            "self_bond_status": "UNTESTED",
            "self_bond_capacity_amount": ZERO,
            "forfeiture_count": 0,
            "refund_due_amount": ZERO,
        }
    )
    db.operators[row["id"]] = row
    return created_response(ser.operator_out(row))


@bp.get("/mining/operators/<operator_id>")
def get_operator(operator_id):
    authorize(C.ALL_ROLES)
    row = lookup(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
    return object_response(ser.operator_out(row))


@bp.get("/mining/operators")
def list_operators():
    authorize(C.ROLES_STAFF_AND_PUBLIC)
    return collection_filtered(db.operators.values(), LIST_FILTERS, ser.operator_out)


@bp.patch("/mining/operators/<operator_id>/financials")
def update_financials(operator_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    tangible_net_worth = number_field(body, "tangible_net_worth", required=False, ge=0)
    fixed_assets_in_state = number_field(body, "fixed_assets_in_state", required=False, ge=0)
    total_liabilities = number_field(body, "total_liabilities", required=False, ge=0)
    net_income_prior_year = number_field(body, "net_income_prior_year", required=False)
    elected = enum_field(
        body, "elected_financial_test", C.ELECTED_FINANCIAL_TESTS, required=False
    )

    row = lookup(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
    if row["registry_status"] == "DISQUALIFIED":
        raise ApiError(
            "ERR_OPERATOR_DISQUALIFIED",
            "A disqualified operator's financial statements can no longer be restated.",
        )

    if tangible_net_worth is not None:
        row["tangible_net_worth"] = tangible_net_worth
    if fixed_assets_in_state is not None:
        row["fixed_assets_in_state"] = fixed_assets_in_state
    if total_liabilities is not None:
        row["total_liabilities"] = total_liabilities
    if net_income_prior_year is not None:
        row["net_income_prior_year"] = net_income_prior_year
    if elected is not None:
        row["elected_financial_test"] = elected

    # Restated figures invalidate any prior determination.
    if row["self_bond_status"] in ("QUALIFIED", "FAILED"):
        row["self_bond_status"] = "UNTESTED"
    row["self_bond_capacity_amount"] = ZERO
    bump(row)
    return object_response(ser.operator_out(row))


@bp.post("/mining/operators/<operator_id>/financial-test")
def run_financial_test(operator_id):
    authorize([C.ROLE_BOND_SPECIALIST])
    get_body()
    row = lookup(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
    if row["self_bond_status"] == "DISQUALIFIED":
        raise ApiError(
            "ERR_OPERATOR_DISQUALIFIED",
            "A disqualified operator can never be re-tested for self-bonding.",
        )
    passes, capacity = calc.operator_self_bond_capacity(row)
    row["self_bond_status"] = "QUALIFIED" if passes else "FAILED"
    row["self_bond_capacity_amount"] = capacity
    bump(row)
    return object_response(ser.operator_out(row))


@bp.get("/mining/operators/<operator_id>/permits")
def operator_permits(operator_id):
    authorize(C.ROLES_OP_STAFF_PUBLIC)
    lookup(db.operators, operator_id, "ERR_OPERATOR_NOT_FOUND")
    rows = [p for p in db.permits.values() if p["operator_id"] == operator_id]
    rows = apply_filters(rows, [("status", "status", C.PERMIT_STATUSES)])
    return paged(rows, ser.permit_out)

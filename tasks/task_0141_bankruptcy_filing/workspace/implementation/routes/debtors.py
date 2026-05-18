"""Debtor endpoints."""

from flask import Blueprint, g

from middleware import require_auth, parse_json_body
from response import success
from services.case_engine import create_debtor
from services.serializers import serialize_debtor
from db import store
from errors import make_error


debtors_bp = Blueprint("debtors", __name__)


@debtors_bp.post("/debtors")
@require_auth(allowed_roles=["Debtor"])
def create_debtor_route():
    body = parse_json_body(required_fields=["full_name", "household_size", "state_code"])
    with store.lock:
        debtor = create_debtor(
            full_name=body["full_name"],
            household_size=body["household_size"],
            state_code=body["state_code"],
        )
    return success(serialize_debtor(debtor), status=201)


@debtors_bp.get("/debtors/<debtor_id>")
@require_auth(allowed_roles=["Debtor", "Trustee", "Judge"])
def get_debtor_route(debtor_id: str):
    debtor = store.debtors.get(debtor_id)
    if debtor is None:
        raise make_error("ERR_NOT_FOUND", f"Debtor {debtor_id} not found.")
    return success(serialize_debtor(debtor))

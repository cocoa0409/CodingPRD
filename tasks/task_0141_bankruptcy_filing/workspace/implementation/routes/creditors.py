"""Creditor endpoints."""

from flask import Blueprint

from middleware import require_auth, parse_json_body
from response import success
from services.case_engine import create_creditor
from services.serializers import serialize_creditor
from db import store
from errors import make_error


creditors_bp = Blueprint("creditors", __name__)


@creditors_bp.post("/creditors")
@require_auth(allowed_roles=["Creditor"])
def create_creditor_route():
    body = parse_json_body(required_fields=["name", "creditor_type"])
    with store.lock:
        creditor = create_creditor(name=body["name"], creditor_type=body["creditor_type"])
    return success(serialize_creditor(creditor), status=201)


@creditors_bp.get("/creditors/<creditor_id>")
@require_auth(allowed_roles=["Creditor", "Trustee", "Judge"])
def get_creditor_route(creditor_id: str):
    creditor = store.creditors.get(creditor_id)
    if creditor is None:
        raise make_error("ERR_NOT_FOUND", f"Creditor {creditor_id} not found.")
    return success(serialize_creditor(creditor))

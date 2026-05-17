"""Self-pay invoice routes."""
from flask import Blueprint, jsonify

from app.auth import require_roles
from app.errors import err_invalid_state, err_not_found
from app.responses import success_object
from app.store import store
from app.utils import bump_version_and_timestamp, check_version_if_supplied, parse_json_body


bp = Blueprint("invoices", __name__)


@bp.get("/telemed/invoices/<iid>")
@require_roles(["ComplianceOfficer"])
def get_invoice(iid: str):
    inv = store.invoices.get(iid)
    if not inv:
        raise err_not_found()
    return jsonify(success_object(inv)), 200


@bp.post("/telemed/invoices/<iid>/mark-paid")
@require_roles(["ComplianceOfficer"])
def mark_invoice_paid(iid: str):
    inv = store.invoices.get(iid)
    if not inv:
        raise err_not_found()
    body = parse_json_body()
    if inv["status"] != "ISSUED":
        raise err_invalid_state("Only ISSUED invoices can be marked paid")
    check_version_if_supplied(inv, body)
    with store.lock:
        if inv["status"] != "ISSUED":
            raise err_invalid_state("Only ISSUED invoices can be marked paid")
        inv["status"] = "PAID"
        bump_version_and_timestamp(inv, store.now_iso())
    return jsonify(success_object(inv)), 200

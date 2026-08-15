"""Spend records: import, list, get, void (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import make_record, touch, pub_spend_record
from validate import get_body, req_str, req_int, req_date, opt_str, get_resource

bp = Blueprint("spend", __name__)

ANALYST = ["DiversityAnalyst"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "Auditor"]


@bp.route("/api/v1/spend-records", methods=["POST"])
def create_spend_record():
    authorized(ANALYST)
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    business_unit_id = req_str(body, "business_unit_id")
    # Existence (ladder rung 3) precedes structural range checks (rung 8).
    get_resource("suppliers", supplier_id)
    bu = get_resource("business_units", business_unit_id)
    amount_cents = req_int(body, "amount_cents", minimum=1)
    transaction_date = req_date(body, "transaction_date")
    payment_date = req_date(body, "payment_date")
    po_number = opt_str(body, "po_number")
    rec = make_record({
        "supplier_id": supplier_id,
        "business_unit_id": business_unit_id,
        "amount_cents": amount_cents,
        "transaction_date": transaction_date,
        "payment_date": payment_date,
        "po_number": po_number,
        "status": "POSTED",
    })
    db["spend_records"][rec["id"]] = rec
    # Monotonic lifetime counter; never decremented (PRD 3.3).
    bu["lifetime_imported_spend_cents"] += amount_cents
    touch(bu)
    return success_object(pub_spend_record(rec), status=201)


@bp.route("/api/v1/spend-records", methods=["GET"])
def list_spend_records():
    authorized(READERS)
    filters = {
        "supplier_id": request.args.get("supplier_id"),
        "business_unit_id": request.args.get("business_unit_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(db["spend_records"].values()), filters, pub_spend_record)


@bp.route("/api/v1/spend-records/<rid>", methods=["GET"])
def get_spend_record(rid):
    authorized(READERS)
    rec = get_resource("spend_records", rid)
    return success_object(pub_spend_record(rec))


@bp.route("/api/v1/spend-records/<rid>/void", methods=["POST"])
def void_spend_record(rid):
    authorized(ANALYST)
    rec = get_resource("spend_records", rid)
    if rec["status"] != "POSTED":
        raise_error(ERR_INVALID_STATE, "only a POSTED spend record can be voided")
    rec["status"] = "VOIDED"
    touch(rec)
    bu = db["business_units"].get(rec["business_unit_id"])
    if bu is not None:
        bu["lifetime_voided_spend_cents"] += rec["amount_cents"]
        touch(bu)
    # GENERATED scorecards are snapshots and are NOT mutated by the void.
    return success_object(pub_spend_record(rec))

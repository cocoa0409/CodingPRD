"""Payment routes (PRD §3.5) — record (waterfall), get, list."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, require_iso_date,
    parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("payments", __name__)


@bp.route("/payments", methods=["POST"])
def create_payment():
    require_role({"PropertyManager", "Tenant"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    amount = require_int(body, "amount_cents", minimum=1)
    received_date = require_iso_date(body, "received_date")
    with db.LOCK:
        lease = db.leases.get(lease_id)
        if lease is None:
            raise err(errors.ERR_FK_NOT_FOUND, "lease_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "lease_id": lease_id,
            "amount_cents": amount,
            "received_date": received_date,
            "applied_breakdown": [],
            "applied_to_rent_cents": 0,
            "unapplied_cents": 0,
        }
        db.payments[record["id"]] = record
        domain.apply_payment_waterfall(record, lease)
        return object_response(serialize(record), 201)


@bp.route("/payments/<id>", methods=["GET"])
def get_payment(id):
    require_role({"PropertyManager", "Owner", "Tenant"})
    with db.LOCK:
        record = db.payments.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Payment not found")
        return object_response(serialize(record), 200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    require_role({"PropertyManager", "Owner", "Tenant"})
    lease_id = filter_param(request.args, "lease_id")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.payments.values())
        if lease_id is not None:
            records = [r for r in records if r["lease_id"] == lease_id]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)

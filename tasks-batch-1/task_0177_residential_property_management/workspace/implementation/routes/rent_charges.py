"""RentCharge routes (PRD §3.5) — post, get, list, waive."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, optional_string, require_int, require_enum,
    require_iso_date, parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("rent_charges", __name__)

CHARGE_TYPES = {"RENT", "LATE_FEE"}


@bp.route("/rent-charges", methods=["POST"])
def create_rent_charge():
    require_role({"PropertyManager"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    charge_type = require_enum(body, "charge_type", CHARGE_TYPES, default="RENT")
    period_label = optional_string(body, "period_label")
    due_date = require_iso_date(body, "due_date")
    amount = require_int(body, "amount_cents", minimum=1)
    with db.LOCK:
        lease = db.leases.get(lease_id)
        if lease is None:
            raise err(errors.ERR_FK_NOT_FOUND, "lease_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "lease_id": lease_id,
            "charge_type": charge_type,
            "period_label": period_label,
            "due_date": due_date,
            "amount_cents": amount,
            "amount_paid_cents": 0,
            "amount_outstanding_cents": amount,
            "late_fee_assessed": False,
            "status": "OPEN",
        }
        db.rent_charges[record["id"]] = record
        domain.recompute_lease_balance(lease)
        return object_response(serialize(record), 201)


@bp.route("/rent-charges/<id>", methods=["GET"])
def get_rent_charge(id):
    require_role({"PropertyManager", "Owner", "Tenant"})
    with db.LOCK:
        record = db.rent_charges.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Rent charge not found")
        return object_response(serialize(record), 200)


@bp.route("/rent-charges", methods=["GET"])
def list_rent_charges():
    require_role({"PropertyManager", "Owner", "Tenant"})
    lease_id = filter_param(request.args, "lease_id")
    status = filter_param(request.args, "status")
    charge_type = filter_param(request.args, "charge_type")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.rent_charges.values())
        if lease_id is not None:
            records = [r for r in records if r["lease_id"] == lease_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        if charge_type is not None:
            records = [r for r in records if r["charge_type"] == charge_type]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/rent-charges/<id>/waive", methods=["POST"])
def waive_rent_charge(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        charge = db.rent_charges.get(id)
        if charge is None:
            raise err(errors.ERR_NOT_FOUND, "Rent charge not found")
        # State-admissibility (priority 7) precedes waiver-target (priority 12).
        if charge["status"] not in ("OPEN", "PARTIAL"):
            raise err(errors.ERR_INVALID_STATE, "Charge is not OPEN or PARTIAL")
        if charge["charge_type"] != "LATE_FEE":
            raise err(errors.ERR_CANNOT_WAIVE_RENT, "Only LATE_FEE charges may be waived")
        charge["status"] = "WAIVED"
        charge["amount_outstanding_cents"] = 0
        db.touch(charge)
        lease = db.leases.get(charge["lease_id"])
        if lease is not None:
            domain.recompute_lease_balance(lease)
        return object_response(serialize(charge), 200)

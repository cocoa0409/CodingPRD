"""SecurityDeposit routes (PRD §3.6) — collect, get, list, settle."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, optional_int, require_iso_date,
    parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("security_deposits", __name__)


@bp.route("/security-deposits", methods=["POST"])
def create_deposit():
    require_role({"PropertyManager"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    collected = require_int(body, "collected_cents", minimum=0)
    collected_date = require_iso_date(body, "collected_date")
    with db.LOCK:
        lease = db.leases.get(lease_id)
        if lease is None:
            raise err(errors.ERR_FK_NOT_FOUND, "lease_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "lease_id": lease_id,
            "collected_cents": collected,
            "collected_date": collected_date,
            "interest_accrued_cents": 0,
            "deductions_cents": 0,
            "refund_cents": 0,
            "settlement_date": None,
            "status": "HELD",
        }
        db.security_deposits[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/security-deposits/<id>", methods=["GET"])
def get_deposit(id):
    require_role({"PropertyManager", "Owner", "Tenant"})
    with db.LOCK:
        record = db.security_deposits.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Security deposit not found")
        return object_response(serialize(record), 200)


@bp.route("/security-deposits", methods=["GET"])
def list_deposits():
    require_role({"PropertyManager", "Owner", "Tenant"})
    lease_id = filter_param(request.args, "lease_id")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.security_deposits.values())
        if lease_id is not None:
            records = [r for r in records if r["lease_id"] == lease_id]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/security-deposits/<id>/settle", methods=["POST"])
def settle_deposit(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    settlement_date = require_iso_date(body, "settlement_date")
    damage = optional_int(body, "damage_deductions_cents", 0, minimum=0)
    with db.LOCK:
        deposit = db.security_deposits.get(id)
        if deposit is None:
            raise err(errors.ERR_NOT_FOUND, "Security deposit not found")
        # State-admissibility (priority 7) precedes lease-state business guard.
        if deposit["status"] != "HELD":
            raise err(errors.ERR_INVALID_STATE, "Deposit is not HELD")
        lease = db.leases.get(deposit["lease_id"])
        if lease is None or lease["status"] not in ("EXPIRED", "TERMINATED"):
            raise err(errors.ERR_LEASE_STILL_ACTIVE,
                      "Lease must be EXPIRED or TERMINATED to settle the deposit")
        prop = domain.property_of_lease(lease)
        deposit["settlement_date"] = settlement_date
        # settle_deposit raises ERR_TRUST_INSUFFICIENT (priority 14) before any
        # deposit field mutation, so nothing is committed on failure.
        domain.settle_deposit(deposit, lease, prop, damage)
        db.touch(deposit)
        return object_response(serialize(deposit), 200)

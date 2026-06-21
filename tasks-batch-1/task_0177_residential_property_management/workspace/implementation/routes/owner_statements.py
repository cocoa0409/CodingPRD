"""OwnerStatement routes (PRD §3.10) — create, get, list, finalize, distribute."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_enum, require_int,
    parse_pagination, paginate, filter_param,
)
from services import domain

bp = Blueprint("owner_statements", __name__)

BASES = {"CASH", "ACCRUAL"}


@bp.route("/owner-statements", methods=["POST"])
def create_statement():
    require_role({"PropertyManager"})
    body = get_json_body()
    property_id = require_string(body, "property_id")
    period_label = require_string(body, "period_label")
    basis = require_enum(body, "basis", BASES, default="CASH")
    with db.LOCK:
        if property_id not in db.properties:
            raise err(errors.ERR_FK_NOT_FOUND, "property_id does not resolve")
        common = db.new_common()
        record = {
            **{k: common[k] for k in ("id", "created_at", "updated_at", "version", "_seq")},
            "property_id": property_id,
            "period_label": period_label,
            "basis": basis,
            "gross_cents": 0,
            "management_fee_cents": 0,
            "maintenance_cents": 0,
            "net_to_owner_cents": 0,
            "distribution_cents": 0,
            "status": "DRAFT",
        }
        db.owner_statements[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/owner-statements/<id>", methods=["GET"])
def get_statement(id):
    require_role({"PropertyManager", "Owner"})
    with db.LOCK:
        record = db.owner_statements.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Owner statement not found")
        return object_response(serialize(record), 200)


@bp.route("/owner-statements", methods=["GET"])
def list_statements():
    require_role({"PropertyManager", "Owner"})
    property_id = filter_param(request.args, "property_id")
    status = filter_param(request.args, "status")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.owner_statements.values())
        if property_id is not None:
            records = [r for r in records if r["property_id"] == property_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/owner-statements/<id>/finalize", methods=["POST"])
def finalize_statement(id):
    require_role({"PropertyManager"})
    with db.LOCK:
        stmt = db.owner_statements.get(id)
        if stmt is None:
            raise err(errors.ERR_NOT_FOUND, "Owner statement not found")
        if stmt["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Statement is not DRAFT")
        prop = db.properties.get(stmt["property_id"])
        owner = db.owners.get(prop["owner_id"])
        domain.compute_owner_statement(stmt, prop, owner)
        stmt["status"] = "FINALIZED"
        db.touch(stmt)
        return object_response(serialize(stmt), 200)


@bp.route("/owner-statements/<id>/distribute", methods=["POST"])
def distribute_statement(id):
    require_role({"PropertyManager"})
    body = get_json_body()
    with db.LOCK:
        stmt = db.owner_statements.get(id)
        if stmt is None:
            raise err(errors.ERR_NOT_FOUND, "Owner statement not found")
        expected = require_int(body, "expected_property_version")
        prop = db.properties.get(stmt["property_id"])
        # OCC (priority 6) precedes state-admissibility (priority 7) precedes
        # the nothing-to-distribute business guard.
        if prop["version"] != expected:
            raise err(errors.ERR_STALE_VERSION, "property version is stale")
        if stmt["status"] != "FINALIZED":
            raise err(errors.ERR_INVALID_STATE, "Statement is not FINALIZED")
        if prop["distributable_cents"] < 1:
            raise err(errors.ERR_NOTHING_TO_DISTRIBUTE, "Nothing to distribute")
        amount = min(stmt["net_to_owner_cents"], prop["distributable_cents"])
        # Debit trust (bumps Property.version when amount > 0); recompute
        # distributable. PRD §3.10/§2.9: a successful distribution always
        # increments the property's version, even when the debited amount is 0
        # (debit_trust is a no-op for a 0 amount), so bump it explicitly here.
        before_version = prop["version"]
        domain.debit_trust(prop, amount)
        if prop["version"] == before_version:
            db.touch(prop)
        stmt["distribution_cents"] = amount
        stmt["status"] = "DISTRIBUTED"
        db.touch(stmt)
        return object_response(serialize(stmt), 200)

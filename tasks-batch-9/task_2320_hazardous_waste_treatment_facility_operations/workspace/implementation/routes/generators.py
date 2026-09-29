"""Generators and their reliability scores."""

from flask import Blueprint

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import by_created_at, check_generator_scope, load, respond_list
from services import calc, derive
from services.tracking import touch
from util import new_id

bp = Blueprint("generators", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "WasteApprovalChemist", "RegulatoryInspector"]
SCORE_READERS = ["PlatformAdmin", "ComplianceManager", "WasteApprovalChemist", "RegulatoryInspector", "Generator"]

CREATE_SPEC = {
    "epa_id": {"type": "string", "required": True, "non_empty": True},
    "name": {"type": "string", "required": True, "non_empty": True},
    "generator_category": {"type": "string", "required": True, "enum": calc.GENERATOR_CATEGORIES},
    "state_code": {"type": "string", "required": True, "non_empty": True},
}


@bp.post("/tsdf/generators")
@endpoint(roles=["PlatformAdmin", "ComplianceManager"], mutating=True)
def create_generator():
    body = schema.body(CREATE_SPEC)
    if any(row["epa_id"] == body["epa_id"] for row in db.generators.values()):
        fail("ERR_DUPLICATE_MANIFEST_NUMBER", "A generator with this epa_id already exists")
    stamp = now()
    row = {
        "id": new_id(),
        "epa_id": body["epa_id"],
        "name": body["name"],
        "generator_category": body["generator_category"],
        "state_code": body["state_code"],
        "status": "ACTIVE",
        "suspension_reason_code": None,
        "open_charge_cents": 0,
        "settled_charge_cents": 0,
        "voided_charge_cents": 0,
        "charge_adjustment_cents": 0,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("generators", row)
    return created(derive.project_generator(row))


@bp.get("/tsdf/generators/<gid>")
@endpoint(roles=READERS + ["Generator"])
def get_generator(gid):
    check_generator_scope(gid)
    return ok(derive.project_generator(load("generators", gid)))


@bp.get("/tsdf/generators")
@endpoint(roles=READERS)
def list_generators():
    filters, limit, offset = schema.listing(
        filters=["status", "epa_id", "generator_category"],
        enums={"status": calc.GENERATOR_STATUSES, "generator_category": calc.GENERATOR_CATEGORIES})
    rows = by_created_at(list(db.generators.values()))
    for key in ("status", "epa_id", "generator_category"):
        if key in filters:
            rows = [row for row in rows if row[key] == filters[key]]
    return respond_list(rows, derive.project_generator, limit, offset)


@bp.post("/tsdf/generators/<gid>/status")
@endpoint(roles=["ComplianceManager"], mutating=True)
def set_generator_status(gid):
    body = schema.body({
        "to_status": {"type": "string", "required": True, "enum": calc.GENERATOR_STATUSES},
        "reason_code": {"type": "string"},
    })
    row = load("generators", gid)
    current = row["status"]
    target = body["to_status"]

    if (current, target) == ("ACTIVE", "SUSPENDED"):
        row["status"] = "SUSPENDED"
        row["suspension_reason_code"] = body["reason_code"]
    elif (current, target) == ("SUSPENDED", "ACTIVE"):
        row["status"] = "ACTIVE"
        row["suspension_reason_code"] = None
    elif current in ("ACTIVE", "SUSPENDED") and target == "TERMINATED":
        for m in derive.manifests_of_generator(gid):
            if m["status"] in ("EN_ROUTE", "DISCREPANT", "VERIFIED"):
                fail("ERR_INVALID_STATE", "The generator still has manifests in flight")
        row["status"] = "TERMINATED"
    else:
        fail("ERR_INVALID_STATE", "Unsupported generator status transition")

    touch("generators", row)
    return ok(derive.project_generator(row))


@bp.get("/tsdf/generators/<gid>/reliability-score")
@endpoint(roles=SCORE_READERS)
def get_reliability_score(gid):
    check_generator_scope(gid)
    return ok(derive.project_generator(load("generators", gid)))

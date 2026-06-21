"""StorageLot routes (PRD §3.8).

Release accrues SIT charge to the job ledger gross. Waive is an OCC write on
MoveJob.version that credits waived_cents (conservation: gross unchanged,
balance drops by exactly the waived charge) and bumps the job version by one.
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common
from services import calculations

bp = Blueprint("storage_lots", __name__)


@bp.route("/storage-lots", methods=["POST"])
def create_storage_lot():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin"})
    body = common.get_json_body()
    common.require_fields(body, ["move_job_id", "intake_date"])

    common.lookup_fk(db.move_jobs, body["move_job_id"])
    intake_dt = common.parse_datetime(body["intake_date"], "ERR_INVALID_FIELD", "intake_date")

    record = db.new_common({
        "move_job_id": body["move_job_id"],
        "intake_date": body["intake_date"],
        "release_date": None,
        "billable_days": 0,
        "sit_charge_cents": 0,
        "status": "IN_STORAGE",
        "_intake_dt": intake_dt,
    })
    db.storage_lots[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/storage-lots/<lid>", methods=["GET"])
def get_storage_lot(lid):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin", "Customer"})
    record = common.lookup(db.storage_lots, lid)
    return object_response(public(record), 200)


@bp.route("/storage-lots", methods=["GET"])
def list_storage_lots():
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher", "PlatformAdmin", "Customer"})
    limit, offset = common.parse_pagination()
    move_job_id = request.args.get("move_job_id")
    status = request.args.get("status")
    records = list(db.storage_lots.values())
    if move_job_id is not None:
        records = [r for r in records if r["move_job_id"] == move_job_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


@bp.route("/storage-lots/<lid>/release", methods=["POST"])
def release_storage_lot(lid):
    user_id, role = authenticate()
    require_roles(role, {"Dispatcher"})
    lot = common.lookup(db.storage_lots, lid)
    job = common.lookup(db.move_jobs, lot["move_job_id"])

    # State (priority 6): release only from IN_STORAGE.
    if lot["status"] != "IN_STORAGE":
        raise err("ERR_INVALID_STATE", "Only an IN_STORAGE lot may be released.")
    # Dependent state: job must be DELIVERED or IN_TRANSIT.
    if job["job_status"] not in {"DELIVERED", "IN_TRANSIT"}:
        raise err("ERR_INVALID_STATE", "Job must be IN_TRANSIT or DELIVERED to release storage.")

    body = common.get_json_body()
    common.require_fields(body, ["release_date"])
    release_dt = common.parse_datetime(body["release_date"], "ERR_INVALID_FIELD", "release_date")

    # Temporal (priority 23): release_date >= intake_date.
    if release_dt < lot["_intake_dt"]:
        raise err("ERR_RELEASE_BEFORE_INTAKE", "release_date must be on or after intake_date.")

    billable_days, charge = calculations.sit_accrual(lot["_intake_dt"], release_dt)
    lot["release_date"] = body["release_date"]
    lot["billable_days"] = billable_days
    lot["sit_charge_cents"] = charge
    lot["status"] = "RELEASED"
    db.touch(lot)

    # Add to job gross; recompute balance (PRD §3.8).
    job["gross_charges_cents"] += charge
    common.recompute_balance(job)
    db.touch_updated_only(job)

    return object_response(public(lot), 200)


@bp.route("/storage-lots/<lid>/waive", methods=["POST"])
def waive_storage_lot(lid):
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin"})
    lot = common.lookup(db.storage_lots, lid)
    job = common.lookup(db.move_jobs, lot["move_job_id"])

    # State (priority 6): waive only from RELEASED.
    if lot["status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "Only a RELEASED lot may be waived.")

    body = common.get_json_body()
    common.require_fields(body, ["expected_move_job_version"])
    expected = body["expected_move_job_version"]
    if not common.is_int(expected):
        raise err("ERR_INVALID_FIELD", "expected_move_job_version must be an integer.")
    # OCC (priority 17).
    if expected != job["version"]:
        raise err("ERR_STALE_VERSION", "MoveJob version has advanced; refresh and retry.")

    lot["status"] = "WAIVED"
    db.touch(lot)

    # Compensating credit: waived += sit_charge; gross unchanged; bump version.
    job["waived_cents"] += lot["sit_charge_cents"]
    common.recompute_balance(job)
    db.touch(job)  # increments MoveJob.version by 1

    return object_response(public(lot), 200)

"""ManagementAgreement endpoints, including termination and records handover."""
from flask import Blueprint, request

import clock
from db import db
from errors import (
    validation, ApiError,
    ERR_AGREEMENT_INVALID_STATE, ERR_AGREEMENT_CONFLICT_EXISTS,
    ERR_STALE_AGREEMENT_VERSION, ERR_RECORD_NOT_IN_SCOPE,
    ERR_RECORD_ALREADY_RELEASED, ERR_HANDOVER_INCOMPLETE,
    ERR_OPEN_OBLIGATIONS,
)
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import agreement_view
from services.core import (
    make_record, touch, require_exists, filter_value_exists,
    get_pagination, paginate, live_agreement_for_aircraft,
)
from services.trips import cancel_trip
from util import fmt_ts

bp = Blueprint("agreements", __name__)

TAX_METHODS = {"FLIGHT_HOURS", "TRIP_LEGS"}


def _validate_pct(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation(f"{field} must be a number")
    if value < 0:
        raise validation(f"{field} must be non-negative")


@bp.route("/agreements", methods=["POST"])
def create_agreement():
    require_roles("AccountExecutive")
    body = request.get_json(silent=True) or {}

    owner_id = body.get("owner_id")
    aircraft_id = body.get("aircraft_id")
    # FK existence
    if owner_id is not None:
        require_exists(db.owners, owner_id, "owner_id does not resolve")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")

    if not isinstance(owner_id, str) or not owner_id:
        raise validation("owner_id is required")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    fee = body.get("monthly_management_fee_cents")
    if isinstance(fee, bool) or not isinstance(fee, int) or fee < 0:
        raise validation("monthly_management_fee_cents must be a non-negative integer")

    variable_fee_pct = body.get("variable_fee_pct")
    _validate_pct(variable_fee_pct, "variable_fee_pct")
    charter_owner_share_pct = body.get("charter_owner_share_pct")
    _validate_pct(charter_owner_share_pct, "charter_owner_share_pct")

    tax_method = body.get("tax_allocation_method")
    if tax_method not in TAX_METHODS:
        raise validation("tax_allocation_method must be FLIGHT_HOURS or TRIP_LEGS")

    if live_agreement_for_aircraft(aircraft_id) is not None:
        raise ApiError(ERR_AGREEMENT_CONFLICT_EXISTS,
                       "A live (non-TERMINATED) agreement already exists for the aircraft", 409)

    rec = make_record({
        "owner_id": owner_id,
        "aircraft_id": aircraft_id,
        "monthly_management_fee_cents": fee,
        "variable_fee_pct": variable_fee_pct,
        "charter_owner_share_pct": charter_owner_share_pct,
        "tax_allocation_method": tax_method,
        "status": "PENDING",
        "notice_given_at": None,
        "records_total": 0,
        "records_released": 0,
    })
    db.agreements[rec["id"]] = rec
    return success_object(agreement_view(rec), 201)


@bp.route("/agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    require_read()
    rec = require_exists(db.agreements, agreement_id)
    return success_object(agreement_view(rec))


@bp.route("/agreements", methods=["GET"])
def list_agreements():
    require_read()
    owner_id = request.args.get("owner_id")
    aircraft_id = request.args.get("aircraft_id")
    filter_value_exists(db.owners, owner_id)
    filter_value_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = list(db.agreements.values())
    if owner_id is not None:
        records = [r for r in records if r["owner_id"] == owner_id]
    if aircraft_id is not None:
        records = [r for r in records if r["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([agreement_view(r) for r in page], limit, offset, total)


@bp.route("/agreements/<agreement_id>/terms", methods=["PATCH"])
def amend_terms(agreement_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.agreements, agreement_id)
    body = request.get_json(silent=True) or {}

    if "expected_agreement_version" not in body:
        raise validation("expected_agreement_version is required")
    expected = body.get("expected_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("expected_agreement_version must be an integer")

    for f in ("variable_fee_pct", "charter_owner_share_pct"):
        if f in body and body[f] is not None:
            _validate_pct(body[f], f)
    if "monthly_management_fee_cents" in body and body["monthly_management_fee_cents"] is not None:
        v = body["monthly_management_fee_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise validation("monthly_management_fee_cents must be a non-negative integer")
    if "tax_allocation_method" in body and body["tax_allocation_method"] is not None:
        if body["tax_allocation_method"] not in TAX_METHODS:
            raise validation("tax_allocation_method must be FLIGHT_HOURS or TRIP_LEGS")

    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE,
                       "Terms may only be amended while the agreement is ACTIVE", 409)

    if expected != rec["version"]:
        raise ApiError(ERR_STALE_AGREEMENT_VERSION,
                       "expected_agreement_version does not equal the agreement's current version", 412)

    for f in ("monthly_management_fee_cents", "variable_fee_pct",
              "charter_owner_share_pct", "tax_allocation_method"):
        if f in body and body[f] is not None:
            rec[f] = body[f]
    touch(rec, bump_version=True)
    return success_object(agreement_view(rec))


@bp.route("/agreements/<agreement_id>/activate", methods=["POST"])
def activate(agreement_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.agreements, agreement_id)
    if rec["status"] != "PENDING":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement must be in PENDING", 409)
    rec["status"] = "ACTIVE"
    touch(rec, bump_version=True)
    return success_object(agreement_view(rec))


@bp.route("/agreements/<agreement_id>/give-termination-notice", methods=["POST"])
def give_termination_notice(agreement_id):
    require_roles("AccountExecutive", "Owner")
    rec = require_exists(db.agreements, agreement_id)
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement must be in ACTIVE", 409)

    now_str = fmt_ts(clock.now())
    rec["notice_given_at"] = now_str

    # snapshot records_total
    count = 0
    for e in db.events.values():
        if e["aircraft_id"] == rec["aircraft_id"]:
            count += 1
    for f in db.filings.values():
        if f["aircraft_id"] == rec["aircraft_id"]:
            count += 1
    rec["records_total"] = count

    # cascade-cancel open trips (each cancellation releases its ASSIGNED assignments)
    for t in list(db.trips.values()):
        if t["aircraft_id"] == rec["aircraft_id"] and t["status"] in ("REQUESTED", "APPROVED", "SCHEDULED"):
            cancel_trip(t)

    rec["status"] = "TERMINATION_PENDING"
    touch(rec, bump_version=True)
    return success_object(agreement_view(rec))


@bp.route("/agreements/<agreement_id>/release-records", methods=["POST"])
def release_records(agreement_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.agreements, agreement_id)
    body = request.get_json(silent=True) or {}

    record_ids = body.get("record_ids")
    if record_ids is None or not isinstance(record_ids, list):
        raise validation("record_ids must be a list")

    # existence of each named record (as a record of the agreement's aircraft)
    targets = []
    for rid in record_ids:
        if not isinstance(rid, str):
            raise validation("record_ids entries must be strings")
        target = db.events.get(rid) or db.filings.get(rid)
        if target is not None and target["aircraft_id"] != rec["aircraft_id"]:
            target = None
        targets.append((rid, target))

    if rec["status"] not in ("TERMINATION_PENDING", "HANDOVER_IN_PROGRESS"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE,
                       "Agreement must be in TERMINATION_PENDING or HANDOVER_IN_PROGRESS", 409)

    for rid, target in targets:
        if target is None:
            raise ApiError(ERR_RECORD_NOT_IN_SCOPE,
                           "record_id does not identify a MaintenanceEvent or ComplianceFiling of the agreement's aircraft", 422)
    for rid, target in targets:
        if target["handed_over_at"] is not None:
            raise ApiError(ERR_RECORD_ALREADY_RELEASED,
                           "record already released", 409)

    now_str = fmt_ts(clock.now())
    for rid, target in targets:
        target["handed_over_at"] = now_str
        touch(target)
    rec["records_released"] += len(targets)
    if rec["status"] == "TERMINATION_PENDING":
        rec["status"] = "HANDOVER_IN_PROGRESS"
    touch(rec, bump_version=True)
    return success_object(agreement_view(rec))


@bp.route("/agreements/<agreement_id>/complete-termination", methods=["POST"])
def complete_termination(agreement_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.agreements, agreement_id)
    if rec["status"] != "HANDOVER_IN_PROGRESS":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE,
                       "Agreement must be in HANDOVER_IN_PROGRESS", 409)
    if rec["records_released"] != rec["records_total"]:
        raise ApiError(ERR_HANDOVER_INCOMPLETE,
                       "records_released must equal records_total", 409)

    for t in db.trips.values():
        if t["aircraft_id"] == rec["aircraft_id"] and t["status"] in ("REQUESTED", "APPROVED", "SCHEDULED"):
            raise ApiError(ERR_OPEN_OBLIGATIONS,
                           "Aircraft holds a non-terminal trip", 409)
    for p in db.programs.values():
        if p["aircraft_id"] == rec["aircraft_id"] and p["status"] == "ENROLLED":
            raise ApiError(ERR_OPEN_OBLIGATIONS,
                           "Aircraft holds an ENROLLED maintenance program", 409)

    for p in db.programs.values():
        if p["aircraft_id"] == rec["aircraft_id"] and p["status"] == "SUSPENDED":
            p["status"] = "CANCELLED"
            touch(p)

    rec["status"] = "TERMINATED"
    touch(rec, bump_version=True)
    return success_object(agreement_view(rec))

"""Sales periods and sales records (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_principal, require_publisher, serialize
from response import object_response, array_response
from services import validate
from services.access import can_read_contract
from services.listing import paginate

bp = Blueprint("periods", __name__)


def _read_contract_or_403(cid):
    role, user_id = get_principal()
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    if not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return contract


def _read_period_or_403(pid):
    role, user_id = get_principal()
    period = db.sales_periods.get(pid)
    if period is None:
        raise errors.not_found("Sales period not found.")
    contract = db.contracts.get(period["contract_id"])
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return period


# ---- Sales periods ----

@bp.route("/contracts/<cid>/sales-periods", methods=["POST"])
def create_period(cid):
    role, _ = get_principal()
    require_publisher(role)
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    body = validate.get_body()
    label = validate.req_string(body, "label")
    sequence = validate.req_int(body, "sequence")
    validate.range_ge(sequence, "sequence", 1)
    # sequence uniqueness within contract (priority 7, ERR_DUPLICATE_PERIOD_SEQUENCE).
    for p in db.sales_periods.values():
        if p["contract_id"] == cid and p["sequence"] == sequence:
            raise errors.duplicate_period_sequence()
    rec = db.make_common({
        "contract_id": cid,
        "label": label,
        "sequence": sequence,
        "status": "OPEN",
    })
    db.sales_periods[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/contracts/<cid>/sales-periods", methods=["GET"])
def list_periods(cid):
    contract = _read_contract_or_403(cid)
    records = [p for p in db.sales_periods.values() if p["contract_id"] == contract["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/sales-periods/<pid>", methods=["GET"])
def get_period(pid):
    period = _read_period_or_403(pid)
    return object_response(serialize(period))


@bp.route("/sales-periods/<pid>/close", methods=["POST"])
def close_period(pid):
    role, _ = get_principal()
    require_publisher(role)
    period = db.sales_periods.get(pid)
    if period is None:
        raise errors.not_found("Sales period not found.")
    contract = db.contracts.get(period["contract_id"])
    if period["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN period may be closed.")
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.invalid_state("Owning contract must be ACTIVE to close a period.")
    # ascending-sequence: every lower-sequence period must be STATEMENTED.
    for p in db.sales_periods.values():
        if (p["contract_id"] == period["contract_id"]
                and p["sequence"] < period["sequence"]
                and p["status"] != "STATEMENTED"):
            raise errors.period_sequence_violation()
    period["status"] = "CLOSED"
    db.touch(period)
    return object_response(serialize(period))


# ---- Sales records ----

@bp.route("/sales-periods/<pid>/sales-records", methods=["POST"])
def create_sales_record(pid):
    role, _ = get_principal()
    require_publisher(role)
    period = db.sales_periods.get(pid)
    if period is None:
        raise errors.not_found("Sales period not found.")
    body = validate.get_body()
    format_id = validate.req_string(body, "format_id")
    units_sold = validate.opt_int(body, "units_sold", 0)
    units_returned = validate.opt_int(body, "units_returned", 0)
    validate.range_ge(units_sold, "units_sold", 0)
    validate.range_ge(units_returned, "units_returned", 0)

    fmt = db.formats.get(format_id)
    if fmt is None:
        raise errors.not_found("format_id does not resolve.")

    # Cross-contract referential coherence (priority 9).
    title = db.titles.get(fmt["title_id"])
    if title is None or title["contract_id"] != period["contract_id"]:
        raise errors.cross_contract_reference()

    # Period-open / contract-active / format-active (priority 10).
    contract = db.contracts.get(period["contract_id"])
    if period["status"] != "OPEN":
        raise errors.period_not_open("Period is not OPEN.")
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.period_not_open("Owning contract is not ACTIVE.")
    if not fmt["active"]:
        raise errors.period_not_open("Target format is not active.")

    rec = db.make_common({
        "period_id": pid,
        "format_id": format_id,
        "units_sold": units_sold,
        "units_returned": units_returned,
    })
    db.sales_records[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/sales-periods/<pid>/sales-records", methods=["GET"])
def list_period_records(pid):
    period = _read_period_or_403(pid)
    format_id = request.args.get("format_id")
    records = [r for r in db.sales_records.values() if r["period_id"] == period["id"]]
    if format_id is not None:
        records = [r for r in records if r["format_id"] == format_id]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/sales-records", methods=["GET"])
def list_sales_records():
    role, user_id = get_principal()
    format_id = request.args.get("format_id")
    limit, offset = validate.pagination()
    records = []
    for r in db.sales_records.values():
        if format_id is not None and r["format_id"] != format_id:
            continue
        # Scope by ownership through period -> contract.
        period = db.sales_periods.get(r["period_id"])
        if period is None:
            continue
        contract = db.contracts.get(period["contract_id"])
        if contract is None or not can_read_contract(role, user_id, contract):
            continue
        records.append(r)
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/sales-records/<rid>", methods=["GET"])
def get_sales_record(rid):
    role, user_id = get_principal()
    rec = db.sales_records.get(rid)
    if rec is None:
        raise errors.not_found("Sales record not found.")
    period = db.sales_periods.get(rec["period_id"])
    contract = db.contracts.get(period["contract_id"]) if period else None
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return object_response(serialize(rec))

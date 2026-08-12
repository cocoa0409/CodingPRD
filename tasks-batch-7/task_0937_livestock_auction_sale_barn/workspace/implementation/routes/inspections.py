"""Health papers, brand inspection and their results (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, check_min, enum_field, fields, path_row, reference
from clock import parse_date, render_date
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from store import db, get, insert_versioned, touch

bp = Blueprint("inspections", __name__)
ALL = config.ALL_ROLES


def _context(lot):
    consignment = get("consignments", lot["consignment_id"])
    sale_day = get("sale_days", lot["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"]) if consignment else None
    return consignment, sale_day, party


@bp.post("/sale-barn/inspection-records")
def create_record():
    actor(["Inspector"])
    data = body()
    v = fields(data, required=[
        ("lot_id", "string"),
        ("inspection_type", "string"),
        ("document_number", "string"),
        ("issue_date", "string"),
        ("inspected_head", "integer"),
    ], optional=[("destination_state_code", "string")])
    inspection_type = enum_field(data, "inspection_type", config.INSPECTION_TYPES)
    check_min(v["inspected_head"], 1, "inspected_head")
    issued = parse_date(v["issue_date"])
    if issued is None:
        fail("ERR_INVALID_REQUEST", "Field 'issue_date' must be a YYYY-MM-DD date.")

    lot = reference("lots", v["lot_id"], "Lot")
    consignment, sale_day, party = _context(lot)
    # Exempt from G2: a quarantined lot's papers stay workable, which is what
    # makes the hold liftable in practice.
    run_gates("inspection_records.create", sale_day=sale_day, lot=lot, party=party)

    valid_through = issued + timedelta(days=config.INSPECTION_VALIDITY_DAYS[inspection_type])
    row = insert_versioned("inspection_records", {
        "lot_id": lot["id"],
        "inspection_type": inspection_type,
        "document_number": v["document_number"],
        "issue_date": v["issue_date"],
        "valid_through": render_date(valid_through),
        "inspected_head": v["inspected_head"],
        "destination_state_code": v["destination_state_code"],
        "retest_count": 0,
        "status": "PENDING",
    })
    return ok(serialize.inspection_record(row), 201)


@bp.get("/sale-barn/inspection-records/<record_id>")
def read_record(record_id):
    actor(ALL)
    return ok(serialize.inspection_record(
        path_row("inspection_records", record_id, "InspectionRecord")))


@bp.get("/sale-barn/inspection-records")
def list_records():
    actor(ALL)
    rows = list(db["inspection_records"].values())
    for key in ("lot_id", "inspection_type", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.inspection_record)


@bp.post("/sale-barn/inspection-records/<record_id>/result")
def record_result(record_id):
    actor(["Inspector"])
    record = path_row("inspection_records", record_id, "InspectionRecord")
    data = body()
    result = enum_field(data, "result", config.INSPECTION_RESULTS)
    lot = get("lots", record["lot_id"])
    consignment, sale_day, party = _context(lot) if lot else (None, None, None)
    run_gates("inspection_records.result", sale_day=sale_day, lot=lot, party=party)

    if result in ("CLEARED", "FAILED"):
        if record["status"] != "PENDING":
            fail("ERR_INVALID_STATE")
        record["status"] = result
    else:  # RETEST
        if record["status"] != "FAILED":
            fail("ERR_INVALID_STATE")
        if record["retest_count"] >= config.MAX_RETEST_COUNT:
            fail("ERR_RETEST_LIMIT_EXCEEDED")
        record["retest_count"] += 1
        record["status"] = "PENDING"
    touch(record)
    return ok(serialize.inspection_record(record))

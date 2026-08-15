"""Rental lines: create (OCC-guarded), list, read, off-rent, re-rent."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, forbid
from response import ok, created, paginate
from services import calc, domain
from validation import validate_body

bp = Blueprint("lines", __name__)


def _load_line(lid):
    line = store.lines.get(lid)
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Rental line not found")
    return line


def _check_line_actor(line, uid, role):
    """Customer callers must own the line's contract (off-rent / re-rent)."""
    if role == "Customer":
        contract = store.contracts[line["contract_id"]]
        if contract["customer_id"] != uid:
            forbid("A Customer may act only on lines of its own contracts")


@bp.post("/rental-lines")
def create_line():
    uid, role = get_context()
    require_roles(["RentalCoordinator"])
    body = validate_body({
        "contract_id": ("string", True),
        "unit_id": ("string", True),
        "requested_start_date": ("date", True),
        "requested_end_date": ("date", True),
        "required_working_height_ft": ("integer", True, {"min_exclusive": 0}),
        "expected_contract_version": ("integer", True),
        "engineering_plan_ref": ("string", False),
    })
    start = db.parse_date(body["requested_start_date"])
    end = db.parse_date(body["requested_end_date"])
    if end < start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "requested_end_date must not be earlier than requested_start_date")
    contract = store.contracts.get(body["contract_id"])
    if contract is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Rental contract not found")
    unit = store.units.get(body["unit_id"])
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Equipment unit not found")
    if body["expected_contract_version"] != contract["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_contract_version does not match the contract version")
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Lines may be added only to DRAFT or ACTIVE contracts")
    cls = store.classes[unit["class_id"]]
    if cls["requires_familiarization"] and not domain.has_valid_training(
            contract["customer_id"], cls["id"]):
        raise ApiError("ERR_FAMILIARIZATION_REQUIRED", 422,
                       "No valid familiarization training record for this class")
    if cls["requires_engineering"] and not body["engineering_plan_ref"]:
        raise ApiError("ERR_ENGINEERING_PLAN_REQUIRED", 422,
                       "An engineering plan reference is required for this class")
    if body["required_working_height_ft"] > cls["max_working_height_ft"]:
        raise ApiError("ERR_REACH_EXCEEDED", 422,
                       "required_working_height_ft exceeds the class maximum")
    from datetime import timedelta
    if domain.unit_window_conflict(unit["id"], start, end + timedelta(days=1)):
        raise ApiError("ERR_UNIT_WINDOW_CONFLICT", 409,
                       "The unit is already committed to an overlapping rental window")
    customer = store.customers[contract["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 402,
                       "Suspended customers cannot add rental lines")
    line = db.new_common({
        "id": db.new_id(),
        "contract_id": contract["id"],
        "unit_id": unit["id"],
        "class_id": unit["class_id"],
        "status": "RESERVED",
        "requested_start_date": body["requested_start_date"],
        "requested_end_date": body["requested_end_date"],
        "required_working_height_ft": body["required_working_height_ft"],
        "engineering_plan_ref": body["engineering_plan_ref"],
        "on_rent_at": None,
        "off_rent_at": None,
        "segment_count": 0,
        "accrued_charge_cents": 0,
        "final_charge_cents": None,
    })
    store.lines[line["id"]] = line
    db.touch(contract)  # adding a line mutates the contract
    # Balance recomputes (derived on read); line creation does not trigger the
    # suspension cascade per the recompute trigger list.
    return created(domain.view_line(line))


@bp.get("/rental-lines")
def list_lines():
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    rows = list(store.lines.values())
    for f in ("contract_id", "unit_id", "class_id", "status"):
        rows = paginate.filter(rows, f)
    rows = [domain.view_line(l) for l in rows]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/rental-lines/<lid>")
def get_line(lid):
    uid, role = get_context()
    require_roles(["BranchManager", "RentalCoordinator", "Customer"])
    line = _load_line(lid)
    return ok(domain.view_line(line))


@bp.post("/rental-lines/<lid>/off-rent")
def off_rent(lid):
    uid, role = get_context()
    require_roles(["RentalCoordinator", "Customer"])
    line = _load_line(lid)
    _check_line_actor(line, uid, role)
    if line["status"] != "OUT_ON_RENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Line is not OUT_ON_RENT")
    contract = store.contracts[line["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
    cls = store.classes[line["class_id"]]
    off_rent_at = db.LOGICAL_CLOCK
    on_rent_at = db.parse_datetime(line["on_rent_at"])
    # Finalize the billable segment over the actual on-rent -> off-rent interval.
    line["accrued_charge_cents"] += calc.segment_charge_cents(cls, on_rent_at, off_rent_at)
    line["segment_count"] += 1
    line["off_rent_at"] = db.logical_stamp()
    line["status"] = "OFF_RENT"
    db.touch(line)
    db.touch(contract)  # rental_subtotal_cents recomputed (derived view)
    customer = store.customers.get(contract["customer_id"])
    if customer is not None:
        calc.maybe_suspend(customer)
    return ok(domain.view_line(line))


@bp.post("/rental-lines/<lid>/re-rent")
def re_rent(lid):
    uid, role = get_context()
    require_roles(["RentalCoordinator", "Customer"])
    line = _load_line(lid)
    _check_line_actor(line, uid, role)
    if line["status"] != "OFF_RENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Line is not OFF_RENT")
    contract = store.contracts[line["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
    # Any SCHEDULED pickup for this line becomes pointless — cancel by cascade.
    for trip in store.trips.values():
        if (trip["line_id"] == line["id"] and trip["trip_type"] == "PICKUP"
                and trip["status"] == "SCHEDULED"):
            trip["status"] = "CANCELLED"
            db.touch(trip)
    line["status"] = "OUT_ON_RENT"
    line["on_rent_at"] = db.logical_stamp()
    line["off_rent_at"] = None
    db.touch(line)
    customer = store.customers.get(contract["customer_id"])
    if customer is not None:
        calc.maybe_suspend(customer)
    return ok(domain.view_line(line))

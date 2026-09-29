"""Load sheets, captain decision, last-minute changes and amendment (PRD §3.7, §3.8)."""
from flask import Blueprint

import calc
import clock
import db
import middleware
import resolve
import response
import validate
from calc import D
from errors import (
    ERR_COMPARTMENT_KIND_MISMATCH,
    ERR_COMPARTMENT_NOT_ON_AIRCRAFT,
    ERR_DG_NOT_ACCEPTED,
    ERR_FLIGHT_INVALID_STATE,
    ERR_LMC_ALLOWANCE_EXCEEDED,
    ERR_LOAD_NOT_RELEASED,
    ERR_PLAN_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SHEET_INVALID_STATE,
    ERR_STALE_LOAD_PLAN_VERSION,
    fail,
)
from middleware import ANY_ROLE, authorize
from services import balance

bp = Blueprint("sheets", __name__)

SHEET_STATUSES = ("ISSUED", "ACCEPTED", "REJECTED_BY_CAPTAIN", "AMENDED", "SUPERSEDED")
CHANGE_KINDS = ("PAX_ADD", "PAX_REMOVE", "BAG_ADD", "BAG_REMOVE", "CARGO_OFFLOAD")
CHANGE_STATUSES = ("APPLIED", "REVERSED")
PAX_KINDS = ("PAX_ADD", "PAX_REMOVE")
LMC_OPEN_SHEET_STATUSES = ("ISSUED", "ACCEPTED")
DG_BLOCKING_CARGO_STATUSES = ("BOOKED", "ACCEPTED", "LOADED")


# ------------------------------------------------------------------- issue
@bp.post("/load-sheets")
@authorize("LoadController")
def issue_load_sheet():
    payload = validate.body()
    plan_id = validate.req_str(payload, "load_plan_id")
    expected = validate.req_int(payload, "expected_load_plan_version")

    plan = resolve.load_plan(plan_id)
    flight, _aircraft, program = balance.plan_context(plan)

    if plan["status"] != "COMPUTED" or not plan["envelope_ok"]:
        fail(ERR_PLAN_INVALID_STATE)
    if expected != int(plan["version"]):
        fail(ERR_STALE_LOAD_PLAN_VERSION)

    for item in db.flight_cargo(flight["id"]):
        if not item["is_dangerous_goods"]:
            continue
        if item["status"] not in DG_BLOCKING_CARGO_STATUSES:
            continue
        if not any(d["status"] == "ACCEPTED" for d in db.cargo_declarations(item["id"])):
            fail(ERR_DG_NOT_ACCEPTED)

    existing = db.plan_sheets(plan_id)
    sheet_no = max((int(s["sheet_no"]) for s in existing), default=0) + 1
    dg_accepted = any(
        d["status"] == "ACCEPTED" for d in db.flight_declarations(flight["id"])
    )

    row = {
        "load_plan_id": plan_id,
        "sheet_no": sheet_no,
        "status": "ISSUED",
        "issued_by_user_id": middleware.current_user_id(),
        "accepted_by_user_id": None,
        "notoc_reference": (
            "NOTOC-%s-%d" % (flight["flight_number"], sheet_no) if dg_accepted else None
        ),
        "weight_program_documentation_ref": program["documentation_ref"],
        "issued_takeoff_weight_kg": plan["takeoff_weight_kg"],
        "issued_index_tow": plan["index_tow"],
        "issued_payload_kg": plan["planned_payload_kg"],
        "lmc_allowance_kg": float(calc.lmc_allowance(plan["underload_kg"])),
        "lmc_net_weight_delta_kg": 0,
        "lmc_absolute_weight_delta_kg": 0,
        "final_takeoff_weight_kg": plan["takeoff_weight_kg"],
        "final_index_tow": plan["index_tow"],
        "final_mac_tow_pct": plan["mac_tow_pct"],
        "final_payload_kg": plan["planned_payload_kg"],
    }

    for sheet in existing:
        if sheet["status"] in ("ISSUED", "REJECTED_BY_CAPTAIN"):
            sheet["status"] = "SUPERSEDED"
            db.touch(sheet)

    created = db.insert(db.load_sheets, row)
    plan["status"] = "SHEET_ISSUED"
    db.touch(plan)
    return response.object_response(db.public(created), 201)


@bp.get("/load-sheets/<row_id>")
@authorize(*ANY_ROLE)
def read_load_sheet(row_id):
    return response.object_response(db.public(resolve.load_sheet(row_id)))


@bp.get("/load-plans/<row_id>/load-sheets")
@authorize(*ANY_ROLE)
def list_plan_load_sheets(row_id):
    validate.pagination()
    status = validate.query_enum("status", SHEET_STATUSES)
    resolve.load_plan(row_id)
    rows = [s for s in db.plan_sheets(row_id) if status is None or s["status"] == status]
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)


# ------------------------------------------------------------------ accept
@bp.post("/load-sheets/<row_id>/accept")
@authorize("Captain")
def accept_load_sheet(row_id):
    sheet = resolve.load_sheet(row_id)
    plan = db.load_plans[sheet["load_plan_id"]]
    flight, _aircraft, _program = balance.plan_context(plan)

    if int(flight["dg_hold_count"]) != 0:
        fail(ERR_LOAD_NOT_RELEASED)
    if sheet["status"] != "ISSUED":
        fail(ERR_SHEET_INVALID_STATE)
    if middleware.current_user_id() == sheet["issued_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES)

    sheet["status"] = "ACCEPTED"
    sheet["accepted_by_user_id"] = middleware.current_user_id()
    db.touch(sheet)

    flight["load_release_state"] = "RELEASED"
    db.touch(flight)

    for item in db.flight_cargo(flight["id"]):
        if item["status"] != "ACCEPTED" or not item.get("assigned_compartment_id"):
            continue
        item["status"] = "LOADED"
        db.touch(item)
        for declaration in db.cargo_declarations(item["id"]):
            if declaration["status"] == "ACCEPTED":
                declaration["notoc_issued"] = True
                declaration["updated_at"] = clock.now_iso()
    return response.object_response(db.public(sheet))


# ------------------------------------------------------------------ reject
@bp.post("/load-sheets/<row_id>/reject")
@authorize("Captain")
def reject_load_sheet(row_id):
    sheet = resolve.load_sheet(row_id)
    plan = db.load_plans[sheet["load_plan_id"]]

    if sheet["status"] != "ISSUED":
        fail(ERR_SHEET_INVALID_STATE)
    if middleware.current_user_id() == sheet["issued_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES)

    sheet["status"] = "REJECTED_BY_CAPTAIN"
    db.touch(sheet)
    if plan["status"] == "SHEET_ISSUED":
        plan["status"] = "COMPUTED"
        db.touch(plan)
    return response.object_response(db.public(sheet))


# ------------------------------------------------------------------- amend
@bp.post("/load-sheets/<row_id>/amend")
@authorize("LoadController")
def amend_load_sheet(row_id):
    sheet = resolve.load_sheet(row_id)
    plan = db.load_plans[sheet["load_plan_id"]]
    flight, _aircraft, _program = balance.plan_context(plan)

    if flight["status"] != "DEPARTED":
        fail(ERR_FLIGHT_INVALID_STATE)
    if sheet["status"] != "ACCEPTED":
        fail(ERR_SHEET_INVALID_STATE)

    balance.refresh_sheet_totals(sheet)
    sheet["status"] = "AMENDED"
    db.touch(sheet)
    return response.object_response(db.public(sheet))


# ------------------------------------------------------- last-minute changes
@bp.post("/last-minute-changes")
@authorize("LoadController")
def create_last_minute_change():
    payload = validate.body()
    row = {
        "load_sheet_id": validate.req_str(payload, "load_sheet_id"),
        "change_kind": validate.req_enum(payload, "change_kind", CHANGE_KINDS),
        "compartment_id": validate.req_str(payload, "compartment_id"),
        "male_count": validate.opt_int(payload, "male_count", default=0, ge=0),
        "female_count": validate.opt_int(payload, "female_count", default=0, ge=0),
        "mass_kg": validate.opt_num(payload, "mass_kg", default=0, ge=0),
        "status": "APPLIED",
    }

    sheet = resolve.load_sheet(row["load_sheet_id"])
    compartment = resolve.compartment(row["compartment_id"])
    plan = db.load_plans[sheet["load_plan_id"]]
    flight, aircraft, program = balance.plan_context(plan)

    if sheet["status"] not in LMC_OPEN_SHEET_STATUSES:
        fail(ERR_SHEET_INVALID_STATE)
    if compartment["aircraft_id"] != flight["aircraft_id"]:
        fail(ERR_COMPARTMENT_NOT_ON_AIRCRAFT)
    expected_kind = "CABIN_ZONE" if row["change_kind"] in PAX_KINDS else "HOLD"
    if compartment["kind"] != expected_kind:
        fail(ERR_COMPARTMENT_KIND_MISMATCH)

    signed = calc.r2(
        calc.lmc_signed_mass(
            row["change_kind"], row["male_count"], row["female_count"], row["mass_kg"], program
        )
    )
    consumed = D(sheet["lmc_absolute_weight_delta_kg"]) + abs(signed)
    if consumed > D(sheet["lmc_allowance_kg"]):
        fail(ERR_LMC_ALLOWANCE_EXCEEDED)

    row["weight_delta_kg"] = float(signed)
    row["index_delta"] = float(
        calc.index_delta(signed, compartment["arm_m"], aircraft["ref_arm_m"], aircraft["index_c"])
    )
    change = db.insert(db.last_minute_changes, row)
    balance.refresh_sheet_totals(sheet)
    db.touch(sheet)
    return response.object_response(db.public(change), 201)


@bp.get("/last-minute-changes/<row_id>")
@authorize(*ANY_ROLE)
def read_last_minute_change(row_id):
    return response.object_response(db.public(resolve.last_minute_change(row_id)))


@bp.get("/last-minute-changes")
@authorize(*ANY_ROLE)
def list_last_minute_changes():
    validate.pagination()
    sheet_id = validate.query_str("load_sheet_id")
    compartment_id = validate.query_str("compartment_id")
    status = validate.query_enum("status", CHANGE_STATUSES)
    rows = []
    for change in db.last_minute_changes.values():
        if sheet_id is not None and change["load_sheet_id"] != sheet_id:
            continue
        if compartment_id is not None and change["compartment_id"] != compartment_id:
            continue
        if status is not None and change["status"] != status:
            continue
        rows.append(change)
    items, meta = validate.paginate(db.ordered(rows))
    return response.list_response(items, meta)


@bp.post("/last-minute-changes/<row_id>/reverse")
@authorize("LoadController")
def reverse_last_minute_change(row_id):
    change = resolve.last_minute_change(row_id)
    sheet = db.load_sheets[change["load_sheet_id"]]

    if change["status"] != "APPLIED" or sheet["status"] not in LMC_OPEN_SHEET_STATUSES:
        fail(ERR_SHEET_INVALID_STATE)

    change["status"] = "REVERSED"
    db.touch(change)
    balance.refresh_sheet_totals(sheet)
    db.touch(sheet)
    return response.object_response(db.public(change))

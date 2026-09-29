"""Field records: cleaning cycles, gas balance proposals and component inspections."""
from flask import Blueprint, g

import calc
import projections
import serializers
import settlement
import store
from common import (API_PREFIX, APPLIED_PSI_TOLERANCE, CO2_PCT_TOLERANCE, D,
                    MIN_USABLE_LITERS, ROLE_AUDITOR, ROLE_DISPATCH, ROLE_TECH,
                    ROLE_VENUE, rhu)
from envelope import object_response
from errors import raise_error
from helpers import listing, match, resolve_body, resolve_path
from security import guard, require_self_technician
from shape import F, bad, parse_body, query_enum, query_str

bp = Blueprint("work", __name__)

CHEMICAL_TYPES = ["CAUSTIC", "ACID"]
CYCLE_RESULTS = ["PASS", "FAIL_CONCENTRATION", "FAIL_CONTACT_TIME", "FAIL_TEMPERATURE"]
RECORD_STATUSES = ["POSTED", "VOIDED"]
BALANCE_STATUSES = ["PROPOSED", "APPLIED", "REJECTED", "SUPERSEDED"]
BALANCE_STATES = ["BALANCED", "RESTRICTION_HIGH", "PRESSURE_HIGH"]
COMPONENT_TYPES = ["FAUCET", "COUPLER", "FOB"]
CONDITION_GRADES = ["GOOD", "WORN", "FAILED"]
ACTIONS = ["NONE", "CLEANED", "REPLACED"]


def line_out_of_service_cascade(line, drop_compliance_flag):
    """Shared hop: line out of service, applied blends superseded, account re-scored."""
    if drop_compliance_flag:
        line["compliance_grade_flag"] = "NON_COMPLIANT"
    projections.take_line_out_of_service(line)
    store.touch(line)
    account = store.accounts.get(line["account_id"])
    if account is not None:
        projections.recompute_account_counters(account)
        projections.evaluate_suspension_threshold(account)


# ---------------------------------------------------------------- cleaning cycles

@bp.post(API_PREFIX + "/cleaning-cycles")
@guard(ROLE_TECH)
def create_cycle():
    body = parse_body([
        F("visit_id", "id", required=True),
        F("line_id", "id", required=True),
        F("chemical_lot_id", "id", required=True),
        F("chemical_type", "enum", required=True, values=CHEMICAL_TYPES),
        F("contact_minutes", "int", required=True, min_value=0),
        F("recirculation_temp_f", "num", required=True),
        F("concentrate_liters_used", "num", required=True, gt=0),
    ])
    visit = resolve_body("visit_id", body["visit_id"])
    line = resolve_body("line_id", body["line_id"])
    lot = resolve_body("chemical_lot_id", body["chemical_lot_id"])
    require_self_technician(visit["technician_id"])
    if visit["work_status"] != "IN_PROGRESS":
        raise_error("ERR_VISIT_NOT_IN_PROGRESS")
    if line["status"] != "IN_SERVICE":
        raise_error("ERR_LINE_OUT_OF_SERVICE")
    if lot["status"] != "AVAILABLE":
        raise_error("ERR_CHEMICAL_LOT_UNAVAILABLE")
    if line["account_id"] != visit["account_id"]:
        raise_error("ERR_LINE_ACCOUNT_MISMATCH")
    if body["chemical_type"] != lot["chemical_type"]:
        raise_error("ERR_CHEMICAL_TYPE_MISMATCH")
    if store.today() > lot["expires_on"]:
        raise_error("ERR_CHEMICAL_LOT_EXPIRED")
    technician = store.technicians.get(visit["technician_id"])
    if body["chemical_type"] == "CAUSTIC":
        if technician is None or not technician["caustic_certified"]:
            raise_error("ERR_TECHNICIAN_NOT_CAUSTIC_CERTIFIED")
    loop = store.account_loop(visit["account_id"])
    if loop is not None and projections.loop_status(loop) == "ALARM":
        raise_error("ERR_GLYCOL_ALARM_BLOCK")
    last = line["last_chemical_type"]
    if last == "NONE":
        if body["chemical_type"] != "CAUSTIC":
            raise_error("ERR_CHEMICAL_PARITY_VIOLATION")
    elif body["chemical_type"] == last:
        raise_error("ERR_CHEMICAL_PARITY_VIOLATION")
    floor_date = projections.early_cleaning_floor(line)
    if floor_date is not None and store.today() < floor_date:
        raise_error("ERR_CLEANING_TOO_EARLY")
    if D(lot["liters_remaining"]) < D(body["concentrate_liters_used"]):
        raise_error("ERR_CHEMICAL_INSUFFICIENT_VOLUME")
    figures = calc.dosing(line, lot, body["chemical_type"], body["contact_minutes"],
                          body["recirculation_temp_f"], body["concentrate_liters_used"])
    row = store.new_row(dict(figures, **{
        "visit_id": visit["id"],
        "line_id": line["id"],
        "chemical_lot_id": lot["id"],
        "chemical_type": body["chemical_type"],
        "logged_at": store.now(),
        "logged_by_technician_id": g.user_id,
        "contact_minutes": body["contact_minutes"],
        "recirculation_temp_f": body["recirculation_temp_f"],
        "concentrate_liters_used": body["concentrate_liters_used"],
        "record_status": "POSTED",
        "void_reason": None,
    }))
    store.cycles[row["id"]] = row
    lot["liters_remaining"] = rhu(D(lot["liters_remaining"])
                                 - D(body["concentrate_liters_used"]), 3)
    if lot["liters_remaining"] < D(0):
        lot["liters_remaining"] = D("0.000")
    if lot["status"] == "AVAILABLE" and lot["liters_remaining"] < MIN_USABLE_LITERS:
        lot["status"] = "DEPLETED"
    store.touch(lot)
    changed = projections.refresh_line_history(line)
    if row["compliance_result"] != "PASS":
        line_out_of_service_cascade(line, True)
    elif changed:
        store.touch(line)
    return object_response(serializers.cleaning_cycle(row), 201)


@bp.get(API_PREFIX + "/cleaning-cycles/<cycle_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_cycle(cycle_id):
    return object_response(serializers.cleaning_cycle(resolve_path("cycle_id", cycle_id)))


@bp.get(API_PREFIX + "/cleaning-cycles")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_cycles():
    visit_id = query_str("visit_id")
    line_id = query_str("line_id")
    lot_id = query_str("chemical_lot_id")
    record_status = query_enum("record_status", RECORD_STATUSES)
    result = query_enum("compliance_result", CYCLE_RESULTS)
    rows = [r for r in store.cycles.values()
            if match(r, "visit_id", visit_id)
            and match(r, "line_id", line_id)
            and match(r, "chemical_lot_id", lot_id)
            and match(r, "record_status", record_status)
            and match(r, "compliance_result", result)]
    return listing(rows, serializers.cleaning_cycle)


@bp.post(API_PREFIX + "/cleaning-cycles/<cycle_id>/void")
@guard(ROLE_AUDITOR)
def void_cycle(cycle_id):
    cycle = resolve_path("cycle_id", cycle_id)
    body = parse_body([F("void_reason", "str", required=True)])
    if cycle["record_status"] != "POSTED":
        raise_error("ERR_CYCLE_ALREADY_VOIDED")
    visit = store.visits.get(cycle["visit_id"])
    if visit is not None and visit["settlement_state"] == "SETTLED":
        raise_error("ERR_VISIT_ALREADY_SETTLED")
    cycle["record_status"] = "VOIDED"
    cycle["void_reason"] = body["void_reason"]
    store.touch(cycle)
    lot = store.chemical_lots.get(cycle["chemical_lot_id"])
    if lot is not None:
        lot["liters_remaining"] = rhu(D(lot["liters_remaining"])
                                     + D(cycle["concentrate_liters_used"]), 3)
        if lot["status"] == "DEPLETED" and lot["liters_remaining"] >= MIN_USABLE_LITERS:
            lot["status"] = "AVAILABLE"
        store.touch(lot)
    line = store.lines.get(cycle["line_id"])
    if line is not None:
        changed = projections.refresh_line_history(line)
        changed = projections.replay_line_grade(line) or changed
        if changed:
            store.touch(line)
    if visit is not None and settlement.recount_visit(visit):
        store.touch(visit)
    return object_response(serializers.cleaning_cycle(cycle))


# ---------------------------------------------------------------- balance records

@bp.post(API_PREFIX + "/balance-records")
@guard(ROLE_TECH)
def create_balance_record():
    body = parse_body([
        F("visit_id", "id", required=True),
        F("line_id", "id", required=True),
        F("measured_temp_f", "num", required=True),
        F("proposed_applied_psi", "num", required=True, gt=0),
        F("proposed_co2_pct", "num", required=True, min_value="0.0", max_value="100.0"),
        F("expected_line_version", "int", required=True, min_value=0),
    ])
    visit = resolve_body("visit_id", body["visit_id"])
    line = resolve_body("line_id", body["line_id"])
    require_self_technician(visit["technician_id"])
    if body["expected_line_version"] != line["version"]:
        raise_error("ERR_STALE_LINE_VERSION")
    if visit["work_status"] != "IN_PROGRESS":
        raise_error("ERR_VISIT_NOT_IN_PROGRESS")
    if line["account_id"] != visit["account_id"]:
        raise_error("ERR_LINE_ACCOUNT_MISMATCH")
    figures = calc.gas_balance(line, body["measured_temp_f"])
    if abs(D(body["proposed_applied_psi"])
           - D(figures["required_applied_psi"])) > APPLIED_PSI_TOLERANCE:
        raise_error("ERR_PRESSURE_OUT_OF_BALANCE")
    if abs(D(body["proposed_co2_pct"])
           - D(figures["required_co2_pct"])) > CO2_PCT_TOLERANCE:
        raise_error("ERR_GAS_BLEND_MISMATCH")
    row = store.new_row(dict(figures, **{
        "line_id": line["id"],
        "visit_id": visit["id"],
        "measured_temp_f": body["measured_temp_f"],
        "proposed_applied_psi": body["proposed_applied_psi"],
        "proposed_co2_pct": body["proposed_co2_pct"],
        "proposed_by_technician_id": g.user_id,
        "status": "PROPOSED",
        "decision_note": None,
    }))
    store.balance_records[row["id"]] = row
    store.touch(line)
    return object_response(serializers.balance_record(row), 201)


@bp.get(API_PREFIX + "/balance-records/<record_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_balance_record(record_id):
    return object_response(serializers.balance_record(
        resolve_path("record_id", record_id)))


@bp.get(API_PREFIX + "/balance-records")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_balance_records():
    line_id = query_str("line_id")
    visit_id = query_str("visit_id")
    status = query_enum("status", BALANCE_STATUSES)
    balance_state = query_enum("balance_state", BALANCE_STATES)
    rows = [r for r in store.balance_records.values()
            if match(r, "line_id", line_id)
            and match(r, "visit_id", visit_id)
            and match(r, "status", status)
            and match(r, "balance_state", balance_state)]
    return listing(rows, serializers.balance_record)


@bp.post(API_PREFIX + "/balance-records/<record_id>/decision")
@guard(ROLE_TECH, ROLE_AUDITOR)
def decide_balance_record(record_id):
    record = resolve_path("record_id", record_id)
    body = parse_body([
        F("decision", "enum", required=True, values=["APPLY", "REJECT"]),
        F("decision_note", "str"),
    ])
    decision = body["decision"]
    if decision == "APPLY":
        require_self_technician(record["proposed_by_technician_id"])
    elif g.user_role != ROLE_AUDITOR:
        # Only the compliance office may kill a proposal outright.
        raise_error("ERR_UNAUTHORIZED")
    if record["status"] != "PROPOSED":
        raise_error("ERR_BALANCE_RECORD_NOT_PROPOSED")
    line = store.lines.get(record["line_id"])
    if decision == "APPLY":
        if line is None or line["status"] != "IN_SERVICE":
            raise_error("ERR_LINE_OUT_OF_SERVICE")
        for other in store.sort_created(store.line_balance_records(line["id"])):
            if other["id"] != record["id"] and other["status"] == "APPLIED":
                other["status"] = "SUPERSEDED"
                store.touch(other)
        record["status"] = "APPLIED"
        record["decision_note"] = body["decision_note"]
        store.touch(record)
        store.touch(line)
    else:
        record["status"] = "REJECTED"
        record["decision_note"] = body["decision_note"]
        store.touch(record)
    return object_response(serializers.balance_record(record))


# ----------------------------------------------------------- component inspections

@bp.post(API_PREFIX + "/component-inspections")
@guard(ROLE_TECH)
def create_inspection():
    body = parse_body([
        F("visit_id", "id", required=True),
        F("line_id", "id", required=True),
        F("component_type", "enum", required=True, values=COMPONENT_TYPES),
        F("condition_grade", "enum", required=True, values=CONDITION_GRADES),
        F("action_taken", "enum", required=True, values=ACTIONS),
        F("part_sku_id", "id"),
    ])
    replaced = body["action_taken"] == "REPLACED"
    if replaced and body["part_sku_id"] is None:
        bad("part_sku_id is required when action_taken is REPLACED.")
    if not replaced and body["part_sku_id"] is not None:
        bad("part_sku_id is only permitted when action_taken is REPLACED.")
    visit = resolve_body("visit_id", body["visit_id"])
    line = resolve_body("line_id", body["line_id"])
    part = resolve_body("part_sku_id", body["part_sku_id"], optional=True)
    require_self_technician(visit["technician_id"])
    if visit["work_status"] != "IN_PROGRESS":
        raise_error("ERR_VISIT_NOT_IN_PROGRESS")
    if line["account_id"] != visit["account_id"]:
        raise_error("ERR_LINE_ACCOUNT_MISMATCH")
    charge = 0
    if replaced:
        if part["component_type"] != body["component_type"]:
            raise_error("ERR_PART_TYPE_MISMATCH")
        if int(part["stock_on_hand"]) < 1:
            raise_error("ERR_PART_OUT_OF_STOCK")
        charge = int(part["unit_price_cents"])
    row = store.new_row({
        "visit_id": visit["id"],
        "line_id": line["id"],
        "part_sku_id": part["id"] if part is not None else None,
        "component_type": body["component_type"],
        "condition_grade": body["condition_grade"],
        "action_taken": body["action_taken"],
        "part_charge_cents": charge,
        "inspected_by_technician_id": g.user_id,
    }, mutable=False)
    store.inspections[row["id"]] = row
    if replaced:
        part["stock_on_hand"] = int(part["stock_on_hand"]) - 1
        store.touch(part)
    # A failed component nobody replaced pulls the line, but leaves the cleaning
    # compliance flag untouched (PRD 3.6).
    if body["condition_grade"] == "FAILED" and not replaced:
        line_out_of_service_cascade(line, False)
    return object_response(serializers.inspection(row), 201)


@bp.get(API_PREFIX + "/component-inspections/<inspection_id>")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def read_inspection(inspection_id):
    return object_response(serializers.inspection(
        resolve_path("inspection_id", inspection_id)))


@bp.get(API_PREFIX + "/component-inspections")
@guard(ROLE_DISPATCH, ROLE_AUDITOR, ROLE_TECH, ROLE_VENUE)
def list_inspections():
    visit_id = query_str("visit_id")
    line_id = query_str("line_id")
    part_sku_id = query_str("part_sku_id")
    component_type = query_enum("component_type", COMPONENT_TYPES)
    condition_grade = query_enum("condition_grade", CONDITION_GRADES)
    rows = [r for r in store.inspections.values()
            if match(r, "visit_id", visit_id)
            and match(r, "line_id", line_id)
            and match(r, "part_sku_id", part_sku_id)
            and match(r, "component_type", component_type)
            and match(r, "condition_grade", condition_grade)]
    return listing(rows, serializers.inspection)

"""Heat lots: the traceability root (PRD 3.2)."""

from flask import Blueprint

import calcs
import domain
from auth import ANY, require_action_role, require_roles
from calcs import dec
from db import db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    MATERIAL_GRADES,
    PROCESSES,
    filter_value,
    get_body,
    get_enum,
    get_number,
    get_string,
    paginate,
    parse_pagination,
)

bp = Blueprint("heat_lots", __name__)

ACTION_ROLES = {
    "VERIFY": ["QualityManager"],
    "RELEASE": ["QualityManager"],
    "QUARANTINE": ["QualityManager"],
    "REJECT": ["QualityManager"],
}
ACTIONS = list(ACTION_ROLES.keys())


@bp.post("/valve-mfg/heat-lots")
def create_heat_lot():
    user_id, role = require_roles(["SupplierRep", "ProcurementSpecialist"])
    body = get_body()

    if role == "SupplierRep":
        claimed = body.get("foundry_id")
        if isinstance(claimed, str) and claimed.strip() != "" and claimed != user_id:
            raise api_error(
                "ERR_FOUNDRY_SCOPE_VIOLATION",
                "a SupplierRep may only declare heat lots for its own foundry",
            )

    foundry_id = get_string(body, "foundry_id")
    heat_number = get_string(body, "heat_number")
    material_grade = get_enum(body, "material_grade", MATERIAL_GRADES)
    process = get_enum(body, "process", PROCESSES)
    qty_received_kg = get_number(body, "qty_received_kg", exclusive_minimum=0)
    mtr_document_ref = get_string(body, "mtr_document_ref")
    carbon_equivalent_pct = get_number(body, "carbon_equivalent_pct", minimum=0)
    impact_energy_j = get_number(body, "impact_energy_j", minimum=0)

    if role == "SupplierRep" and foundry_id != user_id:
        raise api_error(
            "ERR_FOUNDRY_SCOPE_VIOLATION",
            "a SupplierRep may only declare heat lots for its own foundry",
        )

    foundry = domain.find_foundry(foundry_id)

    for row in db.heat_lots.values():
        if row["foundry_id"] == foundry_id and row["heat_number"] == heat_number:
            raise api_error(
                "ERR_DUPLICATE_CODE",
                "heat_number '%s' already exists for this foundry" % heat_number,
            )

    row = new_row(
        {
            "foundry_id": foundry_id,
            "heat_number": heat_number,
            "material_grade": material_grade,
            "process": process,
            "qty_received_kg": qty_received_kg,
            "mtr_document_ref": mtr_document_ref,
            "carbon_equivalent_pct": carbon_equivalent_pct,
            "impact_energy_j": impact_energy_j,
            "status": "RECEIVED",
            "verified_by_user_id": None,
            "quarantine_reason": None,
        }
    )
    db.heat_lots[row["id"]] = row
    touch(foundry)
    return object_response(domain.serialize_heat_lot(row), 201)


@bp.get("/valve-mfg/heat-lots")
def list_heat_lots():
    user_id, role = require_roles(ANY)
    limit, offset = parse_pagination()
    foundry_id = filter_value("foundry_id")
    if role == "SupplierRep":
        if foundry_id is not None and foundry_id != user_id:
            raise api_error(
                "ERR_FOUNDRY_SCOPE_VIOLATION",
                "a SupplierRep may only list heat lots of its own foundry",
            )
        foundry_id = user_id
    rows = sort_rows(list(db.heat_lots.values()))
    status = filter_value("status")
    material_grade = filter_value("material_grade")
    if foundry_id is not None:
        rows = [r for r in rows if r["foundry_id"] == foundry_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if material_grade is not None:
        rows = [r for r in rows if r["material_grade"] == material_grade]
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_heat_lot(r) for r in page], limit, offset, total
    )


@bp.get("/valve-mfg/heat-lots/<lot_id>")
def get_heat_lot(lot_id):
    user_id, role = require_roles(ANY)
    lot = domain.find_heat_lot(lot_id)
    if role == "SupplierRep" and lot["foundry_id"] != user_id:
        raise api_error(
            "ERR_FOUNDRY_SCOPE_VIOLATION",
            "a SupplierRep may only read heat lots of its own foundry",
        )
    return object_response(domain.serialize_heat_lot(lot))


def _quarantine_cascade(lot):
    for component in sort_rows(domain.components_of_lot(lot["id"])):
        if component["status"] in ("CREATED", "ISSUED_TO_MACHINING", "CONSUMED"):
            component["pre_hold_status"] = component["status"]
            component["status"] = "HOLD"
            touch(component)
            for unit in sort_rows(list(db.valve_units.values())):
                if unit.get("body_component_id") != component["id"]:
                    continue
                domain.refresh_unit(unit)
                if unit["cert_status"] in ("TESTS_PASSED", "CERTIFIED"):
                    domain.decertify_unit(unit, "LOT_QUARANTINE")


@bp.post("/valve-mfg/heat-lots/<lot_id>/dispositions")
def heat_lot_dispositions(lot_id):
    user_id, role = require_roles(["QualityManager"])
    body = get_body()
    action = get_enum(body, "action", ACTIONS)
    require_action_role(role, action, ACTION_ROLES)
    quarantine_reason = get_string(body, "quarantine_reason", required=False, default=None)

    lot = domain.find_heat_lot(lot_id)
    foundry = db.foundries.get(lot["foundry_id"])
    before = domain.foundry_derived(foundry) if foundry is not None else None

    if action == "VERIFY":
        if lot["status"] != "RECEIVED":
            raise api_error(
                "ERR_STATE_INVALID",
                "VERIFY requires status RECEIVED (current: %s)" % lot["status"],
            )
        grade = lot["material_grade"]
        if dec(lot["carbon_equivalent_pct"]) > calcs.MAX_CARBON_EQUIVALENT_PCT[grade]:
            raise api_error(
                "ERR_MTR_CHEMISTRY_OUT_OF_SPEC",
                "carbon_equivalent_pct exceeds the ceiling for grade %s" % grade,
            )
        if dec(lot["impact_energy_j"]) < calcs.MIN_IMPACT_ENERGY_J[grade]:
            raise api_error(
                "ERR_MTR_CHEMISTRY_OUT_OF_SPEC",
                "impact_energy_j is below the floor for grade %s" % grade,
            )
        lot["status"] = "VERIFIED"
        lot["verified_by_user_id"] = user_id
        touch(lot)

    elif action == "RELEASE":
        if lot["status"] == "VERIFIED":
            lot["status"] = "RELEASED"
            touch(lot)
        elif lot["status"] == "QUARANTINED":
            for component in sort_rows(domain.components_of_lot(lot["id"])):
                if component["status"] == "HOLD":
                    component["status"] = component.get("pre_hold_status") or "CREATED"
                    component["pre_hold_status"] = None
                    touch(component)
            lot["status"] = "RELEASED"
            lot["quarantine_reason"] = None
            touch(lot)
        else:
            raise api_error(
                "ERR_STATE_INVALID",
                "RELEASE requires status VERIFIED or QUARANTINED (current: %s)"
                % lot["status"],
            )

    elif action == "QUARANTINE":
        if lot["status"] not in ("VERIFIED", "RELEASED"):
            raise api_error(
                "ERR_STATE_INVALID",
                "QUARANTINE requires status VERIFIED or RELEASED (current: %s)"
                % lot["status"],
            )
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = quarantine_reason
        touch(lot)
        _quarantine_cascade(lot)

    else:  # REJECT
        if lot["status"] == "RECEIVED":
            lot["status"] = "REJECTED"
            touch(lot)
        elif lot["status"] == "QUARANTINED":
            for component in sort_rows(domain.components_of_lot(lot["id"])):
                if component["status"] == "HOLD":
                    component["status"] = "SCRAPPED"
                    component["pre_hold_status"] = None
                    touch(component)
            lot["status"] = "REJECTED"
            touch(lot)
        else:
            raise api_error(
                "ERR_STATE_INVALID",
                "REJECT requires status RECEIVED or QUARANTINED (current: %s)"
                % lot["status"],
            )

    if foundry is not None:
        after = domain.foundry_derived(foundry)
        if after != before:
            touch(foundry)

    return object_response(domain.serialize_heat_lot(lot))

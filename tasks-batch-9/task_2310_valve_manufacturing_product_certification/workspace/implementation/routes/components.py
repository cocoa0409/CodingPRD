"""Traceable rough components drawn from a heat lot (PRD 3.2)."""

from flask import Blueprint

import domain
from auth import ANY, require_action_role, require_roles
from calcs import dec
from db import db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    COMPONENT_TYPES,
    filter_value,
    get_body,
    get_enum,
    get_number,
    get_string,
    paginate,
    parse_pagination,
)

bp = Blueprint("components", __name__)

ACTION_ROLES = {
    "ISSUE_TO_MACHINING": ["ProcurementSpecialist"],
    "SCRAP": ["ProcurementSpecialist"],
    "VOID": ["ProcurementSpecialist"],
}
ACTIONS = list(ACTION_ROLES.keys())


@bp.post("/valve-mfg/components")
def create_component():
    require_roles(["ProcurementSpecialist"])
    body = get_body()
    heat_lot_id = get_string(body, "heat_lot_id")
    target_model_id = get_string(body, "target_model_id")
    component_type = get_enum(body, "component_type", COMPONENT_TYPES)
    net_weight_kg = get_number(body, "net_weight_kg", exclusive_minimum=0)

    model = domain.find_model(target_model_id)
    lot = domain.find_heat_lot(heat_lot_id)

    if lot["status"] != "RELEASED":
        raise api_error(
            "ERR_HEAT_LOT_NOT_RELEASED",
            "heat lot status is %s, not RELEASED" % lot["status"],
        )

    covered = False
    for qual in domain.qualifications_of_foundry(lot["foundry_id"]):
        domain.refresh_qualification(qual)
        if domain.qualification_covers(
            qual, lot["process"], lot["material_grade"], model["pressure_class"]
        ):
            covered = True
            break
    if not covered:
        raise api_error(
            "ERR_FOUNDRY_NOT_QUALIFIED",
            "no in-window qualification covers this process, grade and pressure class",
        )

    _committed, _scrapped, available = domain.lot_mass_balance(lot)
    if dec(net_weight_kg) > dec(available):
        raise api_error(
            "ERR_LOT_INSUFFICIENT_MASS",
            "net_weight_kg exceeds the lot's available mass (%s kg)" % available,
        )

    row = new_row(
        {
            "heat_lot_id": heat_lot_id,
            "target_model_id": target_model_id,
            "component_type": component_type,
            "net_weight_kg": net_weight_kg,
            "status": "CREATED",
            "pre_hold_status": None,
        }
    )
    db.components[row["id"]] = row
    touch(lot)
    return object_response(domain.serialize_component(row), 201)


@bp.get("/valve-mfg/components")
def list_components():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.components.values()))
    heat_lot_id = filter_value("heat_lot_id")
    target_model_id = filter_value("target_model_id")
    status = filter_value("status")
    component_type = filter_value("component_type")
    if heat_lot_id is not None:
        rows = [r for r in rows if r["heat_lot_id"] == heat_lot_id]
    if target_model_id is not None:
        rows = [r for r in rows if r["target_model_id"] == target_model_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if component_type is not None:
        rows = [r for r in rows if r["component_type"] == component_type]
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_component(r) for r in page], limit, offset, total
    )


@bp.get("/valve-mfg/components/<component_id>")
def get_component(component_id):
    require_roles(ANY)
    row = domain.find_component(component_id)
    return object_response(domain.serialize_component(row))


@bp.post("/valve-mfg/components/<component_id>/dispositions")
def component_dispositions(component_id):
    _user_id, role = require_roles(["ProcurementSpecialist"])
    body = get_body()
    action = get_enum(body, "action", ACTIONS)
    require_action_role(role, action, ACTION_ROLES)

    component = domain.find_component(component_id)
    lot = db.heat_lots.get(component["heat_lot_id"])

    if action == "ISSUE_TO_MACHINING":
        if component["status"] != "CREATED":
            raise api_error(
                "ERR_STATE_INVALID",
                "ISSUE_TO_MACHINING requires status CREATED (current: %s)"
                % component["status"],
            )
        if lot is None or lot["status"] != "RELEASED":
            raise api_error(
                "ERR_HEAT_LOT_NOT_RELEASED", "the parent heat lot is not RELEASED"
            )
        component["status"] = "ISSUED_TO_MACHINING"
        touch(component)

    elif action == "SCRAP":
        if component["status"] not in ("CREATED", "ISSUED_TO_MACHINING", "HOLD"):
            raise api_error(
                "ERR_STATE_INVALID",
                "SCRAP is not a transition out of %s" % component["status"],
            )
        component["status"] = "SCRAPPED"
        component["pre_hold_status"] = None
        touch(component)
        if lot is not None:
            touch(lot)

    else:  # VOID
        if component["status"] not in ("CREATED", "ISSUED_TO_MACHINING"):
            raise api_error(
                "ERR_STATE_INVALID",
                "VOID is not a transition out of %s" % component["status"],
            )
        for unit in db.valve_units.values():
            if unit.get("body_component_id") == component["id"]:
                raise api_error(
                    "ERR_COMPONENT_NOT_AVAILABLE",
                    "the component is referenced by a valve unit",
                )
        component["status"] = "VOIDED"
        touch(component)
        if lot is not None:
            touch(lot)

    return object_response(domain.serialize_component(component))

"""Pilots: the hiring pipeline, training steps and attrition (PRD 3.2)."""

from flask import Blueprint

import derive
import enums
import lookup
import validate
from auth import (ROLE_BASE_CHIEF_PILOT, ROLE_REGIONAL_OPS_CONTROLLER, any_role,
                  current_user_id, require)
from db import new_entity, public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("pilots", __name__)

LIST_FILTERS = (
    ("base_id", "base_id", None),
    ("status", "status", enums.PILOT_STATUS),
    ("seat", "seat", enums.SEAT),
)

ADVANCE_SOURCE = {"IN_TRAINING": "PIPELINE", "LINE_QUALIFIED": "IN_TRAINING"}


def _base_of(pilot):
    return store.crew_bases[pilot["base_id"]]


def _require_ownership(pilot):
    if current_user_id() != pilot["base_id"]:
        fail("ERR_BASE_NOT_OWNED")


@bp.route("/pilots", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def hire_pilot():
    data = validate.body()
    base_id = validate.string_field(data, "base_id")
    base = lookup.reference("crew_bases", base_id)

    employee_ref = validate.string_field(data, "employee_ref")
    seat = validate.enum_field(data, "seat", enums.SEAT)
    hire_class_date, _ = validate.date_field(data, "hire_class_date")

    for pilot in store.pilots.values():
        if pilot["base_id"] == base["id"] and pilot["employee_ref"] == employee_ref:
            fail("ERR_DUPLICATE_RESOURCE")

    pilot = new_entity({
        "base_id": base["id"],
        "employee_ref": employee_ref,
        "seat": seat,
        "hire_class_date": hire_class_date,
        "status": "PIPELINE",
        "attrition_destination": None,
    })
    store.pilots[pilot["id"]] = pilot
    derive.apply_base_staffing(base)
    return object_response(public(pilot), 201)


@bp.route("/pilots", methods=["GET"])
@any_role()
def list_pilots():
    return collection_listing("pilots", LIST_FILTERS)


@bp.route("/pilots/<pilot_id>", methods=["GET"])
@any_role()
def read_pilot(pilot_id):
    return object_response(public(lookup.pilot(pilot_id)))


@bp.route("/pilots/<pilot_id>/advance", methods=["POST"])
@require(ROLE_BASE_CHIEF_PILOT)
def advance_pilot(pilot_id):
    pilot = lookup.pilot(pilot_id)
    data = validate.body()
    to_status = validate.enum_field(data, "to_status", enums.PILOT_STATUS)

    _require_ownership(pilot)

    base = _base_of(pilot)
    agreement = store.agreements[base["agreement_id"]]
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    guard_terminal(pilot, enums.PILOT_TERMINAL)
    guard_state(pilot["status"] == ADVANCE_SOURCE.get(to_status),
                "The pilot cannot reach %s from %s" % (to_status, pilot["status"]))
    if to_status == "IN_TRAINING":
        guard_state(base["lifecycle_status"] == "ACTIVE",
                    "The crew base is CLOSED")

    pilot["status"] = to_status
    touch(pilot)
    derive.apply_base_staffing(base)

    return object_response(public(pilot))


@bp.route("/pilots/<pilot_id>/attrite", methods=["POST"])
@require(ROLE_BASE_CHIEF_PILOT)
def attrite_pilot(pilot_id):
    pilot = lookup.pilot(pilot_id)
    data = validate.body()
    destination = validate.enum_field(data, "destination",
                                      enums.ATTRITION_DESTINATION)

    _require_ownership(pilot)

    guard_terminal(pilot, enums.PILOT_TERMINAL)
    if destination == "MAINLINE":
        guard_state(pilot["status"] == "LINE_QUALIFIED",
                    "Only a LINE_QUALIFIED pilot may attrite to the mainline")
        pilot["status"] = "ATTRITED_TO_MAINLINE"
    else:
        guard_state(pilot["status"] in ("PIPELINE", "IN_TRAINING", "LINE_QUALIFIED"))
        pilot["status"] = "RESIGNED"
    pilot["attrition_destination"] = destination
    touch(pilot)

    derive.apply_base_staffing(_base_of(pilot))

    return object_response(public(pilot))

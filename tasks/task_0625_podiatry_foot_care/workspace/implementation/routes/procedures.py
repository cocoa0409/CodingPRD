"""Procedure lines (PRD §3.4)."""

from flask import Blueprint, request

import calculations as calc
import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("procedures", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}

PROCEDURE_KINDS = {
    "ROUTINE_NAIL_DEBRIDEMENT",
    "ROUTINE_CALLUS_PARING",
    "WOUND_DEBRIDEMENT",
    "NAIL_AVULSION",
}


@bp.route("/podiatry/procedures", methods=["POST"])
def create_procedure():
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    body = mw.get_body()
    with db.lock():
        encounter_id = v.as_str(body, "encounter_id", required=True)
        encounter = db.encounters.get(encounter_id)
        if encounter is None:
            raise errors.fk_not_found("encounter_id references a non-existent encounter.")
        procedure_kind = v.as_enum(body, "procedure_kind", PROCEDURE_KINDS, required=True)
        service_date = v.as_date(body, "service_date", required=True)
        billed = v.as_int(body, "billed_cents", required=True, minimum=0)
        fee_cap = v.as_int(body, "fee_cap_cents", required=True, minimum=0)
        entity = {
            "encounter_id": encounter_id,
            "patient_id": encounter["patient_id"],
            "procedure_kind": procedure_kind,
            "service_date": service_date,
            "billed_cents": billed,
            "fee_cap_cents": fee_cap,
            "coverage_decision": "PENDING",
            "medicare_pays_cents": 0,
            "patient_resp_cents": 0,
            "is_routine": calc.is_routine(procedure_kind),
        }
        db.stamp_common(entity)
        db.procedures[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/procedures", methods=["GET"])
def list_procedures():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    encounter_id = request.args.get("encounter_id")
    items = [p for p in db.procedures.values()
             if encounter_id is None or p["encounter_id"] == encounter_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/procedures/<procedure_id>", methods=["GET"])
def get_procedure(procedure_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.procedures.get(procedure_id)
    if entity is None:
        raise errors.not_found("Procedure not found.")
    return resp.success(entity, 200)

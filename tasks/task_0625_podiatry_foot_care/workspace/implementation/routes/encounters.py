"""Encounter lifecycle: scheduling through adjudication (PRD §3.3)."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
import services
import validate as v

bp = Blueprint("encounters", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


def _bad_state(msg="Encounter not in a legal state for the requested transition."):
    return errors.ApiError(errors.ERR_ENCOUNTER_BAD_STATE, 409, msg)


@bp.route("/podiatry/encounters", methods=["POST"])
def create_encounter():
    _, role = mw.authenticate()
    mw.require_role(role, {"FrontDesk"})
    body = mw.get_body()
    with db.lock():
        patient_id = v.as_str(body, "patient_id", required=True)
        provider_id = v.as_str(body, "provider_id", required=True)
        if patient_id not in db.patients:
            raise errors.fk_not_found("patient_id references a non-existent patient.")
        if provider_id not in db.providers:
            raise errors.fk_not_found("provider_id references a non-existent provider.")
        start = v.as_datetime(body, "scheduled_start", required=True)
        end = v.as_datetime(body, "scheduled_end", required=True)
        if end <= start:
            raise errors.invalid_request("scheduled_end must be after scheduled_start.")
        exam_billed = v.as_int(body, "exam_billed_cents", required=True, minimum=0)
        exam_cap = v.as_int(body, "exam_fee_cap_cents", required=True, minimum=0)

        # Provider double-booking (PRD §3.3): half-open overlap with non-VOIDED
        # encounters on the same provider; touching at the boundary is allowed.
        from validate import parse_datetime
        for e in db.encounters.values():
            if e["provider_id"] != provider_id:
                continue
            if e["status"] == "VOIDED":
                continue
            e_start = parse_datetime(e["scheduled_start"])
            e_end = parse_datetime(e["scheduled_end"])
            if start < e_end and e_start < end:
                raise errors.ApiError(errors.ERR_PROVIDER_DOUBLE_BOOKED, 409,
                                      "New encounter overlaps an existing encounter "
                                      "on this provider.")

        entity = {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "exam_billed_cents": exam_billed,
            "exam_fee_cap_cents": exam_cap,
            "exam_coverage_decision": "PENDING",
            "total_medicare_pays_cents": 0,
            "total_patient_resp_cents": 0,
            "status": "OPEN",
        }
        db.stamp_common(entity)
        db.encounters[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/encounters", methods=["GET"])
def list_encounters():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    patient_id = request.args.get("patient_id")
    provider_id = request.args.get("provider_id")
    items = []
    for e in db.encounters.values():
        if patient_id is not None and e["patient_id"] != patient_id:
            continue
        if provider_id is not None and e["provider_id"] != provider_id:
            continue
        items.append(e)
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/encounters/<encounter_id>", methods=["GET"])
def get_encounter(encounter_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.encounters.get(encounter_id)
    if entity is None:
        raise errors.not_found("Encounter not found.")
    return resp.success(entity, 200)


def _load(encounter_id):
    entity = db.encounters.get(encounter_id)
    if entity is None:
        raise errors.not_found("Encounter not found.")
    return entity


@bp.route("/podiatry/encounters/<encounter_id>/complete-exam", methods=["POST"])
def complete_exam(encounter_id):
    user_id, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    with db.lock():
        e = _load(encounter_id)
        # State legality (priority 7) is checked before the rendering-provider
        # ownership check (priority 8) per PRD §2.11.
        if e["status"] != "OPEN":
            raise _bad_state("complete-exam requires status OPEN.")
        if user_id != e["provider_id"]:
            raise errors.ApiError(errors.ERR_NOT_RENDERING_PROVIDER, 403,
                                  "Only the rendering provider may complete this exam.")
        e["status"] = "EXAM_DONE"
        db.touch(e)
        return resp.success(e, 200)


@bp.route("/podiatry/encounters/<encounter_id>/code", methods=["POST"])
def code_encounter(encounter_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    with db.lock():
        e = _load(encounter_id)
        if e["status"] != "EXAM_DONE":
            raise _bad_state("code requires status EXAM_DONE.")
        services.code_encounter(e)
        e["status"] = "CODED"
        db.touch(e)
        return resp.success(e, 200)


@bp.route("/podiatry/encounters/<encounter_id>/recode", methods=["POST"])
def recode_encounter(encounter_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    with db.lock():
        e = _load(encounter_id)
        if e["status"] != "CODED":
            raise _bad_state("recode requires status CODED.")
        services.reset_encounter_charges(e)
        e["status"] = "EXAM_DONE"
        db.touch(e)
        return resp.success(e, 200)


@bp.route("/podiatry/encounters/<encounter_id>/submit", methods=["POST"])
def submit_encounter(encounter_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    with db.lock():
        e = _load(encounter_id)
        if e["status"] != "CODED":
            raise _bad_state("submit requires status CODED.")
        e["status"] = "SUBMITTED"
        db.touch(e)
        return resp.success(e, 200)


@bp.route("/podiatry/encounters/<encounter_id>/adjudicate", methods=["POST"])
def adjudicate_encounter(encounter_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"PayerAgent"})
    with db.lock():
        e = _load(encounter_id)
        if e["status"] != "SUBMITTED":
            raise _bad_state("adjudicate requires status SUBMITTED.")
        e["status"] = "ADJUDICATED"
        db.touch(e)
        # Cascade A (PRD §3.3): for each child procedure that is routine and was
        # decided COVERED, set patient.last_covered_routine_care_date to the later
        # of its existing value and that procedure's service_date. This patient
        # mutation increments the patient's version.
        patient = db.patients[e["patient_id"]]
        new_last = patient.get("last_covered_routine_care_date")
        mutated = False
        for proc in db.procedures.values():
            if proc["encounter_id"] != e["id"]:
                continue
            if proc["is_routine"] and proc["coverage_decision"] == "COVERED":
                mutated = True
                sd = proc["service_date"]
                if new_last is None or sd > new_last:
                    new_last = sd
        if mutated:
            patient["last_covered_routine_care_date"] = new_last
            db.touch(patient)
        return resp.success(e, 200)


@bp.route("/podiatry/encounters/<encounter_id>/void", methods=["POST"])
def void_encounter(encounter_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    with db.lock():
        e = _load(encounter_id)
        if e["status"] not in ("OPEN", "EXAM_DONE", "CODED"):
            raise _bad_state("void requires status OPEN, EXAM_DONE, or CODED.")
        services.reset_encounter_charges(e)
        e["status"] = "VOIDED"
        db.touch(e)
        # Cascade: cancel any SCHEDULED child imaging order, freeing the modality.
        for io in db.imaging_orders.values():
            if io["encounter_id"] == e["id"] and io["status"] == "SCHEDULED":
                io["status"] = "CANCELLED"
                db.touch(io)
        return resp.success(e, 200)

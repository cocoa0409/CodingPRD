"""Logical clock, workers, patients and screening instruments (PRD §2.4, §3.1, §3.2)."""

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, parse_iso
from envelope import created, ok
from errors import ApiError, ERR_INVALID_STATE, ERR_VALIDATION
from ladder import (
    ALL_ROLES, BILLING, CHW, Endpoint, PARTNER, PROGRAM_ADMIN, SUPERVISOR, run,
)
from serial import dump

bp = Blueprint("config", __name__)

EP_CLOCK_SET = Endpoint("clock.set", [PROGRAM_ADMIN])
EP_WORKER_CREATE = Endpoint("worker.create", [PROGRAM_ADMIN])
EP_WORKER_READ = Endpoint("worker.read", ALL_ROLES, path=[("worker_id", "worker")])
EP_PATIENT_CREATE = Endpoint("patient.create", [CHW, SUPERVISOR, PROGRAM_ADMIN])
EP_PATIENT_READ = Endpoint("patient.read", ALL_ROLES, path=[("patient_id", "patient")])
EP_PATIENT_UPDATE = Endpoint("patient.update", [SUPERVISOR, PROGRAM_ADMIN],
                             path=[("patient_id", "patient")], gated=True)
EP_RECORDS_HOLD = Endpoint("patient.records_hold", [SUPERVISOR],
                           path=[("patient_id", "patient")])
EP_INSTRUMENT_CREATE = Endpoint("instrument.create", [PROGRAM_ADMIN])
EP_INSTRUMENT_READ = Endpoint("instrument.read", ALL_ROLES,
                              path=[("instrument_id", "instrument")])
EP_INSTRUMENT_PUBLISH = Endpoint("instrument.publish", [PROGRAM_ADMIN],
                                 path=[("instrument_id", "instrument")])
EP_INSTRUMENT_RETIRE = Endpoint("instrument.retire", [PROGRAM_ADMIN],
                                path=[("instrument_id", "instrument")])

CREDENTIAL_LEVELS = ("CHW_BASIC", "CHW_SENIOR", "CHW_SUPERVISOR")
ENROLLMENT_ACTIONS = ("ENROLL", "DISENROLL", "REENROLL")
HOLD_ACTIONS = ("PLACE", "RELEASE")


# ------------------------------------------------------------------ clock
@bp.post("/chw/_clock/set_current_utc")
def set_clock():
    def payload(ctx):
        value = v.req_str(ctx.body, "to_iso8601")
        if parse_iso(value) is None:
            v.bad("to_iso8601 must be an ISO 8601 instant")
        ctx.state["to_iso8601"] = value

    ctx = run(EP_CLOCK_SET, steps={5: [payload]})
    clock.set(ctx.state["to_iso8601"])
    return ok({"current_utc": clock.now_raw()})


# ------------------------------------------------------------------ workers
@bp.post("/chw/workers")
def create_worker():
    def payload(ctx):
        ctx.state["full_name"] = v.req_str(ctx.body, "full_name")
        code = v.req_str(ctx.body, "employee_code")
        ctx.state["employee_code"] = code
        ctx.state["credential_level"] = v.opt_enum(
            ctx.body, "credential_level", CREDENTIAL_LEVELS, "CHW_BASIC")
        for existing in store.all_rows("worker"):
            if existing.get("employee_code") == code:
                v.bad("employee_code must be unique")

    ctx = run(EP_WORKER_CREATE, steps={5: [payload]})
    row = store.insert("worker", {
        "full_name": ctx.state["full_name"],
        "employee_code": ctx.state["employee_code"],
        "credential_level": ctx.state["credential_level"],
        "employment_status": "ACTIVE",
    })
    return created(dump(row))


@bp.get("/chw/workers/<worker_id>")
def read_worker(worker_id):
    ctx = run(EP_WORKER_READ, {"worker_id": worker_id})
    return ok(dump(ctx.row("worker_id")))


# ------------------------------------------------------------------ patients
@bp.post("/chw/patients")
def create_patient():
    def payload(ctx):
        s = ctx.state
        mrn = v.req_str(ctx.body, "mrn")
        s["mrn"] = mrn
        s["full_name"] = v.req_str(ctx.body, "full_name")
        s["household_size"] = v.req_int(ctx.body, "household_size", minimum=1)
        s["monthly_income_cents"] = v.req_int(ctx.body, "monthly_income_cents", minimum=0)
        s["residence_zip"] = v.req_zip(ctx.body, "residence_zip")
        s["program_enrollments"] = v.code_array(
            "program_enrollments", v.opt_list(ctx.body, "program_enrollments", []) or [])
        s["categorical_exclusions"] = v.code_array(
            "categorical_exclusions", v.opt_list(ctx.body, "categorical_exclusions", []) or [])
        s["child_in_household"] = v.opt_bool(ctx.body, "child_in_household", False)
        s["address_safety_flag"] = v.opt_bool(ctx.body, "address_safety_flag", False)
        for existing in store.all_rows("patient"):
            if existing.get("mrn") == mrn:
                v.bad("mrn must be unique")

    ctx = run(EP_PATIENT_CREATE, steps={5: [payload]})
    s = ctx.state
    row = store.insert("patient", {
        "mrn": s["mrn"],
        "full_name": s["full_name"],
        "household_size": s["household_size"],
        "monthly_income_cents": s["monthly_income_cents"],
        "residence_zip": s["residence_zip"],
        "program_enrollments": s["program_enrollments"],
        "categorical_exclusions": s["categorical_exclusions"],
        "child_in_household": s["child_in_household"],
        "address_safety_flag": s["address_safety_flag"],
        "enrollment_status": "PROSPECTIVE",
        "gate_status": "OPEN",
        "gate_reason": None,
        "risk_score": 0,
        "risk_tier": "NONE",
        "risk_tier_effective_at": None,
        "unfulfilled_referral_count": 0,
    })
    return created(dump(row))


@bp.get("/chw/patients/<patient_id>")
def read_patient(patient_id):
    ctx = run(EP_PATIENT_READ, {"patient_id": patient_id})
    return ok(dump(ctx.row("patient_id")))


@bp.patch("/chw/patients/<patient_id>")
def update_patient(patient_id):
    def payload(ctx):
        s = ctx.state
        body = ctx.body
        updates = {}
        if v.present(body, "household_size"):
            updates["household_size"] = v.req_int(body, "household_size", minimum=1)
        if v.present(body, "monthly_income_cents"):
            updates["monthly_income_cents"] = v.req_int(body, "monthly_income_cents", minimum=0)
        if v.present(body, "residence_zip"):
            updates["residence_zip"] = v.req_zip(body, "residence_zip")
        if v.present(body, "program_enrollments"):
            updates["program_enrollments"] = v.code_array(
                "program_enrollments", v.req_list(body, "program_enrollments"))
        if v.present(body, "categorical_exclusions"):
            updates["categorical_exclusions"] = v.code_array(
                "categorical_exclusions", v.req_list(body, "categorical_exclusions"))
        if v.present(body, "child_in_household"):
            updates["child_in_household"] = v.opt_bool(body, "child_in_household")
        if v.present(body, "address_safety_flag"):
            updates["address_safety_flag"] = v.opt_bool(body, "address_safety_flag")
        s["updates"] = updates
        s["action"] = v.opt_enum(body, "enrollment_action", ENROLLMENT_ACTIONS)

    def target_state(ctx):
        action = ctx.state.get("action")
        if action is None:
            return
        current = ctx.row("patient_id")["enrollment_status"]
        allowed = {"ENROLL": "PROSPECTIVE", "DISENROLL": "ENROLLED", "REENROLL": "DISENROLLED"}
        if current != allowed[action]:
            raise ApiError(ERR_INVALID_STATE,
                           "enrollment_action %s is not permitted from %s" % (action, current))

    ctx = run(EP_PATIENT_UPDATE, {"patient_id": patient_id},
              steps={5: [payload], 8: [target_state]})
    patient = ctx.row("patient_id")
    patient.update(ctx.state["updates"])
    action = ctx.state.get("action")
    if action == "ENROLL":
        patient["enrollment_status"] = "ENROLLED"
    elif action == "REENROLL":
        patient["enrollment_status"] = "ENROLLED"
    elif action == "DISENROLL":
        patient["enrollment_status"] = "DISENROLLED"
        for goal in store.all_rows("goal"):
            if goal.get("patient_id") == patient["id"] and goal.get("status") == "ACTIVE":
                goal["status"] = "DEFERRED"
                goal["closed_at"] = clock.now_raw()
                store.touch(goal)
    store.touch(patient)
    return ok(dump(patient))


@bp.post("/chw/patients/<patient_id>/records-hold")
def records_hold(patient_id):
    def payload(ctx):
        ctx.state["action"] = v.req_enum(ctx.body, "action", HOLD_ACTIONS)
        ctx.state["reason"] = v.opt_str(ctx.body, "reason")

    def target_state(ctx):
        patient = ctx.row("patient_id")
        action = ctx.state["action"]
        if action == "PLACE" and patient["gate_status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "Patient is already on a records hold")
        if action == "RELEASE" and patient["gate_status"] != "RECORDS_HOLD":
            raise ApiError(ERR_INVALID_STATE, "Patient is not on a records hold")

    ctx = run(EP_RECORDS_HOLD, {"patient_id": patient_id},
              steps={5: [payload], 8: [target_state]})
    patient = ctx.row("patient_id")
    if ctx.state["action"] == "PLACE":
        patient["gate_status"] = "RECORDS_HOLD"
        patient["gate_reason"] = ctx.state["reason"]
        store.touch(patient)
        for referral in store.all_rows("referral"):
            if referral.get("patient_id") != patient["id"]:
                continue
            if referral.get("status") != "SENT":
                continue
            cascades.lapse_referral(referral, "RECORDS_HOLD", "released_units")
    else:
        patient["gate_status"] = "OPEN"
        patient["gate_reason"] = None
        store.touch(patient)
    return ok(dump(patient))


# ------------------------------------------------------- screening instruments
@bp.post("/chw/screening-instruments")
def create_instrument():
    def payload(ctx):
        s = ctx.state
        name = v.req_str(ctx.body, "name")
        label = v.req_str(ctx.body, "version_label")
        s["name"] = name
        s["version_label"] = label
        weights = v.req_obj(ctx.body, "domain_weights")
        if not weights:
            v.bad("domain_weights must carry at least one domain")
        total = 0
        for key, value in weights.items():
            if key not in calc.SDOH_DOMAINS:
                v.bad("domain_weights key %s is not an SDOH domain" % key)
            if not v.is_int(value) or value < 0:
                v.bad("domain_weights values must be integers >= 0")
            total += value
        if total != calc.SCREENING_WEIGHT_SUM_REQUIRED:
            v.bad("domain_weights must sum to 100")
        s["domain_weights"] = dict(weights)
        s["effective_from"] = v.req_instant(ctx.body, "effective_from")
        s["rescreen_cadence_days"] = v.opt_int(
            ctx.body, "rescreen_cadence_days", calc.DEFAULT_RESCREEN_CADENCE_DAYS, minimum=1)
        for existing in store.all_rows("instrument"):
            if existing.get("name") == name and existing.get("version_label") == label:
                v.bad("(name, version_label) must be unique")

    ctx = run(EP_INSTRUMENT_CREATE, steps={5: [payload]})
    s = ctx.state
    row = store.insert("instrument", {
        "name": s["name"],
        "version_label": s["version_label"],
        "domain_weights": s["domain_weights"],
        "rescreen_cadence_days": s["rescreen_cadence_days"],
        "effective_from": s["effective_from"],
        "status": "DRAFT",
    })
    return created(dump(row))


@bp.get("/chw/screening-instruments/<instrument_id>")
def read_instrument(instrument_id):
    ctx = run(EP_INSTRUMENT_READ, {"instrument_id": instrument_id})
    return ok(dump(ctx.row("instrument_id")))


@bp.post("/chw/screening-instruments/<instrument_id>/publish")
def publish_instrument(instrument_id):
    def target_state(ctx):
        if ctx.row("instrument_id")["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Only a DRAFT instrument may be published")

    ctx = run(EP_INSTRUMENT_PUBLISH, {"instrument_id": instrument_id},
              steps={8: [target_state]})
    instrument = ctx.row("instrument_id")
    instrument["status"] = "PUBLISHED"
    store.touch(instrument)
    return ok(dump(instrument))


@bp.post("/chw/screening-instruments/<instrument_id>/retire")
def retire_instrument(instrument_id):
    def target_state(ctx):
        if ctx.row("instrument_id")["status"] != "PUBLISHED":
            raise ApiError(ERR_INVALID_STATE, "Only a PUBLISHED instrument may be retired")

    ctx = run(EP_INSTRUMENT_RETIRE, {"instrument_id": instrument_id},
              steps={8: [target_state]})
    instrument = ctx.row("instrument_id")
    instrument["status"] = "RETIRED"
    store.touch(instrument)
    return ok(dump(instrument))

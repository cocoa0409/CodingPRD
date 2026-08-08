"""Appliances: fabrication, delivery, proof of delivery, plateau, remediation,
the patient recall check and the adherence summary."""

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_device, gate_frozen, in_scope, new_row,
                    ordered, path_row, require_scope, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, add_days, add_months, clock_date, num

bp = Blueprint("appliances", __name__)


@bp.post("/appliances")
def create_appliance():
    uid, role = actor(["Dentist"])
    body = v.read_body()
    refs = body_refs(body, ["lab_order_id", "lot_id", "replaces_appliance_id"])
    lab_order = refs["lab_order_id"]
    referral = DB["referrals"].get(lab_order["referral_id"]) if lab_order else None
    patient = DB["patients"].get(referral["patient_id"]) if referral else None
    gate_frozen(patient)
    if referral is not None:
        require_scope(role, uid, referral["patient_id"])
    fields = [
        v.S("lab_order_id", required=True),
        v.S("lot_id", required=True),
        v.S("serial_number", required=True),
        v.B("has_microrecorder"),
        v.S("replaces_appliance_id"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    for existing in DB["appliances"].values():
        if existing["serial_number"] == body["serial_number"]:
            fail("ERR_DUPLICATE_IDENTIFIER", "serial_number is already registered.")
    if lab_order["status"] != "RECEIVED_ACCEPTED":
        fail("ERR_INVALID_STATE", "An appliance may only be founded on an accepted lab order.")
    domain.live_appliance_conflict(referral["patient_id"], None, body.get("replaces_appliance_id"))

    kind = lab_order["appliance_kind"]
    row = new_row("appliances", {
        "patient_id": referral["patient_id"],
        "lab_order_id": lab_order["id"],
        "lot_id": body["lot_id"],
        "replaces_appliance_id": body.get("replaces_appliance_id"),
        "serial_number": body["serial_number"],
        "has_microrecorder": v.get(body, "has_microrecorder", True),
        "appliance_kind": kind,
        "hcpcs_code": "E0486" if kind == "CUSTOM_FABRICATED" else "A9270",
        "max_protrusive_mm": lab_order["max_protrusive_mm"],
        "delivered_on": None,
        "written_order_id": None,
        "pod_signed_on": None,
        "pod_method": None,
        "warranty_end_date": None,
        "useful_lifetime_end_date": None,
        "starting_advancement_mm": None,
        "current_advancement_mm": None,
        "applied_visit_count": 0,
        "plateau_declared_on": None,
        "next_recall_due_on": None,
        "recall_cycle_index": 0,
        "lifecycle_status": "FABRICATED",
        "device_hold_status": "NONE",
        "recall_status": "NOT_SCHEDULED",
    })
    predecessor = refs["replaces_appliance_id"]
    if predecessor is not None and predecessor["lifecycle_status"] == "ACTIVE_THERAPY":
        predecessor["lifecycle_status"] = "REPLACED"
        predecessor["recall_status"] = "NOT_SCHEDULED"
        predecessor["next_recall_due_on"] = None
        touch(predecessor)
    return created(dump("appliance", row))


@bp.get("/appliances/<appliance_id>")
def read_appliance(appliance_id):
    uid, role = actor(["Dentist", "SleepPhysician", "ClinicCoordinator",
                       "BillingSpecialist", "PlatformAdmin", "Patient"])
    row = path_row("appliance_id", appliance_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("appliance", row))


@bp.get("/appliances")
def list_appliances():
    uid, role = actor(["Dentist", "SleepPhysician", "ClinicCoordinator",
                       "BillingSpecialist", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "lab_order_id": request.args.get("lab_order_id"),
        "lot_id": request.args.get("lot_id"),
        "replaces_appliance_id": request.args.get("replaces_appliance_id"),
        "written_order_id": request.args.get("written_order_id"),
        "lifecycle_status": request.args.get("lifecycle_status"),
    }
    return domain.paginate("appliance", "appliances", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/appliances/<appliance_id>/deliver")
def deliver_appliance(appliance_id):
    uid, role = actor(["Dentist"])
    appliance = path_row("appliance_id", appliance_id)
    body = v.read_body()
    body_refs(body, ["written_order_id"])
    gate_frozen(DB["patients"].get(appliance["patient_id"]))
    require_scope(role, uid, appliance["patient_id"])
    fields = [
        v.D("delivered_on", required=True),
        v.S("written_order_id", required=True),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    delivered_on = v.date_of(body, "delivered_on")
    if appliance["lifecycle_status"] != "FABRICATED":
        fail("ERR_INVALID_STATE", "Only a FABRICATED device may be delivered.")
    gate_device(appliance)
    domain.live_appliance_conflict(appliance["patient_id"], appliance["id"],
                                   appliance.get("replaces_appliance_id"))
    domain.swo_ladder(appliance["patient_id"], appliance["hcpcs_code"], delivered_on)

    patient = DB["patients"].get(appliance["patient_id"])
    payer = domain.medical_payer_of(patient)
    months = payer["useful_lifetime_months"] if payer else 60
    appliance["delivered_on"] = delivered_on
    appliance["written_order_id"] = body["written_order_id"]
    appliance["warranty_end_date"] = add_months(delivered_on, calc.WARRANTY_MONTHS)
    appliance["useful_lifetime_end_date"] = add_months(delivered_on, months)
    start = calc.starting_advancement(appliance["appliance_kind"], appliance["max_protrusive_mm"])
    appliance["starting_advancement_mm"] = start
    appliance["current_advancement_mm"] = start
    appliance["lifecycle_status"] = "DELIVERED"
    touch(appliance)
    return ok(dump("appliance", appliance))


@bp.post("/appliances/<appliance_id>/proof-of-delivery")
def proof_of_delivery(appliance_id):
    uid, role = actor(["Dentist", "ClinicCoordinator"])
    appliance = path_row("appliance_id", appliance_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(appliance["patient_id"]))
    require_scope(role, uid, appliance["patient_id"])
    fields = [
        v.D("pod_signed_on", required=True),
        v.S("pod_method", required=True, enum=v.ENUM_POD_METHOD),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    pod_signed_on = v.date_of(body, "pod_signed_on")
    if appliance["lifecycle_status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", "Proof of delivery is captured on a DELIVERED device.")
    gate_device(appliance)
    appliance["pod_signed_on"] = pod_signed_on
    appliance["pod_method"] = body["pod_method"]
    touch(appliance)
    return ok(dump("appliance", appliance))


@bp.post("/appliances/<appliance_id>/plateau")
def declare_plateau(appliance_id):
    uid, role = actor(["Dentist"])
    appliance = path_row("appliance_id", appliance_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(appliance["patient_id"]))
    require_scope(role, uid, appliance["patient_id"])
    v.rung7(body, [])
    if appliance["lifecycle_status"] != "IN_TITRATION":
        fail("ERR_INVALID_STATE", "Plateau is declared from IN_TITRATION.")
    gate_device(appliance)
    if appliance["applied_visit_count"] < calc.PLATEAU_MIN_VISITS:
        fail("ERR_PLATEAU_REQUIRED", "At least three applied visits are required.")
    appliance["lifecycle_status"] = "TITRATION_PLATEAU"
    appliance["plateau_declared_on"] = clock_date()
    touch(appliance)
    for visit in domain.open_visits_of(appliance["id"]):
        visit["status"] = "SUPERSEDED"
        touch(visit)
    return ok(dump("appliance", appliance))


@bp.post("/appliances/<appliance_id>/recall-remediate")
def recall_remediate(appliance_id):
    uid, role = actor(["Dentist"])
    appliance = path_row("appliance_id", appliance_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(appliance["patient_id"]))
    require_scope(role, uid, appliance["patient_id"])
    fields = [v.S("remediation_action", required=True)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    lot = DB["appliance_lots"].get(appliance["lot_id"])
    if appliance["device_hold_status"] != "RECALL_HOLD":
        fail("ERR_INVALID_STATE", "The device is not on a recall hold.")
    if lot is None or lot["status"] != "RECALL_ISSUED":
        fail("ERR_INVALID_STATE", "The device's lot is not under an issued recall.")
    appliance["device_hold_status"] = "NONE"
    if appliance["lifecycle_status"] == "TITRATION_SUSPENDED":
        appliance["lifecycle_status"] = "IN_TITRATION"
    touch(appliance)
    lot["remediated_count"] = lot["remediated_count"] + 1
    lot["pending_remediation_count"] = lot["pending_remediation_count"] - 1
    if lot["pending_remediation_count"] <= 0:
        lot["status"] = "REMEDIATION_COMPLETE"
    touch(lot)
    return ok(dump("appliance", appliance))


@bp.post("/appliances/<appliance_id>/recall-check")
def recall_check(appliance_id):
    uid, role = actor(["Dentist"])
    appliance = path_row("appliance_id", appliance_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(appliance["patient_id"]))
    require_scope(role, uid, appliance["patient_id"])
    fields = [v.S("notes")]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if appliance["lifecycle_status"] != "ACTIVE_THERAPY":
        fail("ERR_INVALID_STATE", "A recall check requires a device in ACTIVE_THERAPY.")
    if appliance["recall_status"] not in ("DUE", "LAPSED"):
        fail("ERR_INVALID_STATE", "No recall check is outstanding on this device.")
    gate_device(appliance)
    appliance["recall_status"] = "NOT_DUE"
    appliance["recall_cycle_index"] = appliance["recall_cycle_index"] + 1
    appliance["next_recall_due_on"] = add_days(clock_date(), calc.SUBSEQUENT_RECALL_DAYS)
    touch(appliance)
    return ok(dump("appliance", appliance))


@bp.get("/appliances/<appliance_id>/adherence-summary")
def adherence_summary(appliance_id):
    uid, role = actor(["Dentist", "SleepPhysician", "BillingSpecialist", "PlatformAdmin"])
    appliance = path_row("appliance_id", appliance_id)
    require_scope(role, uid, appliance["patient_id"])
    rows = [d for d in DB["adherence_downloads"].values() if d["appliance_id"] == appliance["id"]]
    objective = None
    attested = None
    for row in ordered(rows):
        if row["source"] == "OBJECTIVE_MICRORECORDER":
            objective = row
        else:
            attested = row
    window = objective if objective is not None else attested
    return ok({
        "appliance_id": appliance["id"],
        "objective_rate_of_window": num(objective["rate_of_window"], 4) if objective else None,
        "objective_rate_of_recorded": num(objective["rate_of_recorded"], 4) if objective else None,
        "objective_compliant": objective["compliant"] if objective else None,
        "attested_rate_of_window": num(attested["rate_of_window"], 4) if attested else None,
        "attested_compliant": attested["compliant"] if attested else None,
        "window_start": window["window_start"].isoformat() if window else None,
        "window_end": window["window_end"].isoformat() if window else None,
    })

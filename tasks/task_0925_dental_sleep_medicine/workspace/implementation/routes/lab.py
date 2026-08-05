"""Lab work orders, manufacturing lots and the lot recall."""

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_frozen, in_scope, new_row, path_row,
                    require_identity, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, add_days, clock_date

bp = Blueprint("lab", __name__)


def _lab_order_patient(lab_order):
    referral = DB["referrals"].get(lab_order["referral_id"])
    if referral is None:
        return None, None
    return referral, DB["patients"].get(referral["patient_id"])


# -------------------------------------------------------------- lab orders

@bp.post("/lab-orders")
def create_lab_order():
    uid, role = actor(["Dentist"])
    body = v.read_body()
    refs = body_refs(body, ["referral_id", "lab_provider_id"])
    referral = refs["referral_id"]
    if referral is not None:
        gate_frozen(DB["patients"].get(referral["patient_id"]))
        require_identity(uid, referral["treating_dentist_id"])
    fields = [
        v.S("referral_id", required=True),
        v.S("lab_provider_id", required=True),
        v.S("appliance_kind", required=True, enum=v.ENUM_APPLIANCE_KIND),
        v.S("capture_method", required=True, enum=v.ENUM_CAPTURE_METHOD),
        v.N("max_protrusive_mm", required=True),
        v.N("retruded_position_mm"),
        v.I("promised_turnaround_days"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    v.between(body, "max_protrusive_mm", 4.00, 12.00)
    v.multiple_of_quarter(body, "max_protrusive_mm")
    v.between(body, "promised_turnaround_days", 1, 60)
    if referral["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "A lab order requires an ACCEPTED referral.")
    lab = refs["lab_provider_id"]
    if lab["provider_type"] != "DENTAL_LAB" or lab["status"] != "ACTIVE":
        fail("ERR_PROVIDER_TYPE_MISMATCH", "lab_provider_id must be an ACTIVE DENTAL_LAB.")
    domain.rung18_diagnosis_currency(referral)
    row = new_row("lab_orders", {
        "referral_id": referral["id"],
        "lab_provider_id": lab["id"],
        "appliance_kind": body["appliance_kind"],
        "capture_method": body["capture_method"],
        "max_protrusive_mm": body["max_protrusive_mm"],
        "retruded_position_mm": v.get(body, "retruded_position_mm", 0.00),
        "promised_turnaround_days": v.get(body, "promised_turnaround_days", 14),
        "submitted_on": None,
        "promised_ship_date": None,
        "shipped_on": None,
        "turnaround_on_time": None,
        "remake_count": 0,
        "status": "RECORDS_CAPTURED",
    })
    return created(dump("lab_order", row))


@bp.get("/lab-orders/<lab_order_id>")
def read_lab_order(lab_order_id):
    uid, role = actor(["Dentist", "LabTechnician", "ClinicCoordinator", "PlatformAdmin"])
    row = path_row("lab_order_id", lab_order_id)
    referral, _patient = _lab_order_patient(row)
    if role == "LabTechnician":
        require_identity(uid, row["lab_provider_id"])
    elif referral is not None and not in_scope(role, uid, referral["patient_id"]):
        fail("ERR_NOT_CARE_TEAM", "The acting user is outside this patient's care team.")
    return ok(dump("lab_order", row))


@bp.get("/lab-orders")
def list_lab_orders():
    uid, role = actor(["Dentist", "LabTechnician", "ClinicCoordinator", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "referral_id": request.args.get("referral_id"),
        "lab_provider_id": request.args.get("lab_provider_id"),
        "status": request.args.get("status"),
    }

    def scope_pred(row):
        if role == "LabTechnician":
            return row["lab_provider_id"] == uid
        referral = DB["referrals"].get(row["referral_id"])
        return referral is not None and in_scope(role, uid, referral["patient_id"])

    return domain.paginate("lab_order", "lab_orders", filters, limit, offset, scope_pred)


@bp.post("/lab-orders/<lab_order_id>/submit")
def submit_lab_order(lab_order_id):
    uid, role = actor(["Dentist"])
    lab_order = path_row("lab_order_id", lab_order_id)
    body = v.read_body()
    referral, patient = _lab_order_patient(lab_order)
    gate_frozen(patient)
    require_identity(uid, referral["treating_dentist_id"] if referral else None)
    fields = [v.I("promised_turnaround_days")]
    v.rung7(body, fields)
    v.rung8(body, fields)
    v.between(body, "promised_turnaround_days", 1, 60)
    if lab_order["status"] not in ("RECORDS_CAPTURED", "REMAKE_REQUIRED"):
        fail("ERR_INVALID_STATE", "Only a captured or remake lab order may be submitted.")
    if referral is None or referral["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "A lab order submission requires an ACCEPTED referral.")
    if body.get("promised_turnaround_days") is not None:
        lab_order["promised_turnaround_days"] = body["promised_turnaround_days"]
    if lab_order["status"] == "REMAKE_REQUIRED":
        lab_order["remake_count"] = lab_order["remake_count"] + 1
    lab_order["submitted_on"] = clock_date()
    lab_order["promised_ship_date"] = add_days(lab_order["submitted_on"],
                                               lab_order["promised_turnaround_days"])
    lab_order["status"] = "IN_FABRICATION"
    touch(lab_order)
    return ok(dump("lab_order", lab_order))


@bp.post("/lab-orders/<lab_order_id>/ship")
def ship_lab_order(lab_order_id):
    uid, role = actor(["LabTechnician"])
    lab_order = path_row("lab_order_id", lab_order_id)
    body = v.read_body()
    _referral, patient = _lab_order_patient(lab_order)
    gate_frozen(patient)
    require_identity(uid, lab_order["lab_provider_id"])
    fields = [v.D("shipped_on", required=True)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    shipped_on = v.date_of(body, "shipped_on")
    if lab_order["status"] != "IN_FABRICATION":
        fail("ERR_INVALID_STATE", "Only a case in fabrication may be shipped.")
    lab_order["shipped_on"] = shipped_on
    lab_order["turnaround_on_time"] = shipped_on <= lab_order["promised_ship_date"]
    lab_order["status"] = "SHIPPED"
    touch(lab_order)
    return ok(dump("lab_order", lab_order))


@bp.post("/lab-orders/<lab_order_id>/receive")
def receive_lab_order(lab_order_id):
    uid, role = actor(["Dentist"])
    lab_order = path_row("lab_order_id", lab_order_id)
    body = v.read_body()
    referral, patient = _lab_order_patient(lab_order)
    gate_frozen(patient)
    require_identity(uid, referral["treating_dentist_id"] if referral else None)
    fields = [v.S("fit_outcome", required=True, enum=v.ENUM_FIT_OUTCOME)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if lab_order["status"] != "SHIPPED":
        fail("ERR_INVALID_STATE", "Only a shipped case may be received.")
    if body["fit_outcome"] == "ACCEPTED":
        lab_order["status"] = "RECEIVED_ACCEPTED"
    else:
        lab_order["status"] = "REMAKE_REQUIRED"
        lab_order["shipped_on"] = None
        lab_order["turnaround_on_time"] = None
    touch(lab_order)
    return ok(dump("lab_order", lab_order))


# ----------------------------------------------------------- appliance lots

@bp.post("/appliance-lots")
def create_lot():
    actor(["PlatformAdmin"])
    body = v.read_body()
    fields = [
        v.S("manufacturer", required=True),
        v.S("lot_code", required=True),
        v.S("material"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    for existing in DB["appliance_lots"].values():
        if existing["lot_code"] == body["lot_code"]:
            fail("ERR_DUPLICATE_IDENTIFIER", "lot_code is already registered.")
    row = new_row("appliance_lots", {
        "manufacturer": body["manufacturer"],
        "lot_code": body["lot_code"],
        "material": v.get(body, "material", "NYLON_COPOLYMER"),
        "notice_reference": None,
        "recall_severity": None,
        "recall_issued_on": None,
        "affected_device_count": 0,
        "remediated_count": 0,
        "pending_remediation_count": 0,
        "retired_count": 0,
        "status": "ACTIVE",
    })
    return created(dump("appliance_lot", row))


@bp.get("/appliance-lots/<lot_id>")
def read_lot(lot_id):
    actor(["PlatformAdmin", "Dentist", "LabTechnician"])
    row = path_row("lot_id", lot_id)
    return ok(dump("appliance_lot", row))


@bp.post("/appliance-lots/<lot_id>/recall")
def recall_lot(lot_id):
    actor(["PlatformAdmin"])
    lot = path_row("lot_id", lot_id)
    body = v.read_body()
    fields = [
        v.S("notice_reference", required=True),
        v.S("recall_severity", required=True, enum=v.ENUM_RECALL_SEVERITY),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if lot["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE lot may be recalled.")
    lot["notice_reference"] = body["notice_reference"]
    lot["recall_severity"] = body["recall_severity"]
    lot["recall_issued_on"] = clock_date()
    lot["status"] = "RECALL_ISSUED"
    domain.recall_cascade(lot)
    touch(lot)
    return ok(dump("appliance_lot", lot))

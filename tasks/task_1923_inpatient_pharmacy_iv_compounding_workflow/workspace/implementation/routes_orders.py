"""Medication orders: create (supersede + OCC), verify, resume, discontinue,
administer, interventions, substitution."""

from flask import Blueprint, request

import db
import validate as V
import calc
import ops
from auth import authenticate, ALL_ROLES
from errors import (
    err_not_found, err_stale_version, err_order_terminal, err_invalid_state,
    err_allergy, err_drug_discontinued, err_not_order_prescriber,
    err_substitution_not_pending, err_no_active_protocol,
    err_no_eligible_substitute,
)
from response import ok, ok_list, serialize, paginate

bp = Blueprint("orders", __name__)

ROUTES = {"IV", "PO", "IM"}
INTERVENTION_TYPES = {"DOSE_CLARIFICATION", "ALLERGY", "RENAL", "SHORTAGE", "OTHER"}


def _get_order(oid):
    order = db.orders.get(oid)
    if order is None:
        raise err_not_found("Medication order not found")
    return order


def _check_order_occ(d, order):
    expected = V.occ_field(d, "expected_order_version", required=False)
    if expected is not None and expected != order["version"]:
        raise err_stale_version("expected_order_version does not match the order version")


def _check_not_terminal(order):
    if ops.order_is_terminal(order):
        raise err_order_terminal()


def _run_renal_and_rounding(order):
    """Compute renal_dose_adjustment + dose rounding for the order's drug."""
    patient = db.patients[order["patient_id"]]
    drug = db.drugs[order["drug_product_id"]]
    crcl, adjusted = calc.renal_dose_adjustment(order, patient, drug, db.now())
    order["crcl_used_ml_min"] = crcl
    order["renal_adjusted_dose_mg"] = adjusted
    order["final_dose_ml"] = calc.final_dose_ml(adjusted, drug["concentration_mg_per_ml"])


def _route_fulfillment_from_none(order):
    if order["fulfillment_status"] == "NONE":
        order["fulfillment_status"] = "QUEUED" if order["route"] == "IV" else "READY"


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/medication-orders")
def create_order():
    uid, _, _ = authenticate(["Prescriber"])
    d = V.body()
    patient_id = V.req_str(d, "patient_id")
    drug_product_id = V.req_str(d, "drug_product_id")
    route = V.req_enum(d, "route", ROUTES)
    ordered_dose_mg = V.req_number(d, "ordered_dose_mg")
    frequency_per_day = V.req_int(d, "frequency_per_day")
    duration_days = V.opt_int(d, "duration_days", 1)
    expected_patient_version = V.occ_field(d, "expected_patient_version", required=True)

    patient = db.patients.get(patient_id)
    if patient is None:
        raise err_not_found("Patient not found")
    if drug_product_id not in db.drugs:
        raise err_not_found("Drug product not found")
    if expected_patient_version != patient["version"]:
        raise err_stale_version("expected_patient_version does not match the patient version")

    order = db.base_fields()
    order.update({
        "patient_id": patient_id,
        "prescriber_staff_id": uid,
        "drug_product_id": drug_product_id,
        "substituted_by_protocol_id": None,
        "route": route,
        "ordered_dose_mg": ordered_dose_mg,
        "frequency_per_day": frequency_per_day,
        "duration_days": duration_days,
        "verification_status": "PENDING",
        "fulfillment_status": "NONE",
        "substitution_pending": False,
        "crcl_used_ml_min": None,
        "renal_adjusted_dose_mg": None,
        "final_dose_ml": None,
        "discontinue_reason": None,
    })
    db.orders[order["id"]] = order

    # Implicit replacement: supersede the same prescriber's prior open order
    # for the same patient and drug, with the full L1-L3 cascade.
    for prior in sorted(
        db.orders.values(), key=lambda o: (o["created_at"], o["_seq"])
    ):
        if prior["id"] == order["id"]:
            continue
        if (
            prior["patient_id"] == patient_id
            and prior["drug_product_id"] == drug_product_id
            and prior["prescriber_staff_id"] == uid
            and ops.open_order(prior)
        ):
            prior["verification_status"] = "SUPERSEDED"
            db.touch(prior)
            ops.order_cancellation_cascade(prior)

    # A successful create increments the patient's version by 1.
    db.touch(patient)
    return ok(serialize(order), 201)


@bp.get("/pharmacy/medication-orders/<oid>")
def get_order(oid):
    authenticate(ALL_ROLES)
    return ok(serialize(_get_order(oid)))


@bp.get("/pharmacy/medication-orders")
def list_orders():
    authenticate(ALL_ROLES)
    items = list(db.orders.values())
    for param in ("patient_id", "prescriber_staff_id", "drug_product_id",
                  "verification_status", "fulfillment_status",
                  "substituted_by_protocol_id"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Verification / review loop
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/medication-orders/<oid>/verify")
def verify_order(oid):
    authenticate(["Pharmacist"])
    d = V.body()
    V.occ_field(d, "expected_order_version", required=False)
    order = _get_order(oid)
    _check_order_occ(d, order)
    _check_not_terminal(order)
    if order["verification_status"] != "PENDING":
        raise err_invalid_state("Order verification_status is not PENDING")
    patient = db.patients[order["patient_id"]]
    drug = db.drugs[order["drug_product_id"]]
    if drug["id"] in patient["allergy_drug_product_ids"]:
        raise err_allergy()
    if drug["status"] != "ACTIVE":
        raise err_drug_discontinued()
    _run_renal_and_rounding(order)
    order["verification_status"] = "VERIFIED"
    _route_fulfillment_from_none(order)
    db.touch(order)
    return ok(serialize(order))


@bp.post("/pharmacy/medication-orders/<oid>/resume")
def resume_order(oid):
    authenticate(["Pharmacist"])
    d = V.body()
    V.occ_field(d, "expected_order_version", required=False)
    order = _get_order(oid)
    _check_order_occ(d, order)
    _check_not_terminal(order)
    if order["verification_status"] != "ON_HOLD":
        raise err_invalid_state("Order verification_status is not ON_HOLD")
    patient = db.patients[order["patient_id"]]
    if order["drug_product_id"] in patient["allergy_drug_product_ids"]:
        raise err_allergy()
    _run_renal_and_rounding(order)
    order["verification_status"] = "VERIFIED"
    _route_fulfillment_from_none(order)
    db.touch(order)
    return ok(serialize(order))


@bp.post("/pharmacy/medication-orders/<oid>/discontinue")
def discontinue_order(oid):
    uid, _, _ = authenticate(["Prescriber"])
    d = V.body()
    reason = V.req_str(d, "reason")
    order = _get_order(oid)
    _check_not_terminal(order)
    if order["verification_status"] not in ("PENDING", "VERIFIED", "ON_HOLD"):
        raise err_invalid_state("Order verification_status does not allow discontinuation")
    if order["fulfillment_status"] in ("DISPENSED", "ADMINISTERED"):
        raise err_invalid_state("Order fulfillment is too far along to discontinue")
    if uid != order["prescriber_staff_id"]:
        raise err_not_order_prescriber()
    order["discontinue_reason"] = reason
    order["verification_status"] = "DISCONTINUED"
    db.touch(order)
    ops.order_cancellation_cascade(order)
    return ok(serialize(order))


@bp.post("/pharmacy/medication-orders/<oid>/administer")
def administer_order(oid):
    authenticate(["Nurse"])
    V.body()
    order = _get_order(oid)
    _check_not_terminal(order)
    if order["fulfillment_status"] != "DISPENSED":
        raise err_invalid_state("Order fulfillment_status is not DISPENSED")
    order["fulfillment_status"] = "ADMINISTERED"
    db.touch(order)
    return ok(serialize(order))


# ---------------------------------------------------------------------------
# Interventions
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/medication-orders/<oid>/interventions")
def create_intervention(oid):
    uid, _, _ = authenticate(["Pharmacist"])
    d = V.body()
    intervention_type = V.req_enum(d, "intervention_type", INTERVENTION_TYPES)
    note = V.req_str(d, "note")
    placed_on_hold = V.opt_bool(d, "placed_on_hold", False)
    order = _get_order(oid)
    if placed_on_hold:
        _check_not_terminal(order)
        if order["verification_status"] not in ("PENDING", "VERIFIED"):
            raise err_invalid_state("Order cannot be placed on hold from its current state")
    row = db.append_fields()
    row.update({
        "order_id": order["id"],
        "pharmacist_staff_id": uid,
        "intervention_type": intervention_type,
        "note": note,
        "placed_on_hold": placed_on_hold,
    })
    db.interventions[row["id"]] = row
    if placed_on_hold:
        order["verification_status"] = "ON_HOLD"
        db.touch(order)
    return ok(serialize(row), 201)


@bp.get("/pharmacy/medication-orders/<oid>/interventions")
def list_order_interventions(oid):
    authenticate(ALL_ROLES)
    order = _get_order(oid)
    items = [i for i in db.interventions.values() if i["order_id"] == order["id"]]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.get("/pharmacy/interventions/<iid>")
def get_intervention(iid):
    authenticate(ALL_ROLES)
    row = db.interventions.get(iid)
    if row is None:
        raise err_not_found("Intervention not found")
    return ok(serialize(row))


@bp.get("/pharmacy/interventions")
def list_interventions():
    authenticate(ALL_ROLES)
    items = list(db.interventions.values())
    pharmacist = request.args.get("pharmacist_staff_id")
    if pharmacist is not None:
        items = [i for i in items if i["pharmacist_staff_id"] == pharmacist]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Substitution (guards fire in the PRD Section 3.8 priority order)
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/medication-orders/<oid>/substitute")
def substitute_order(oid):
    authenticate(["Pharmacist"])
    d = V.body()
    protocol_id = V.req_str(d, "protocol_id")
    V.occ_field(d, "expected_order_version", required=False)
    order = _get_order(oid)
    protocol = db.protocols.get(protocol_id)
    if protocol is None:
        raise err_not_found("Substitution protocol not found")
    _check_order_occ(d, order)
    _check_not_terminal(order)
    if order["verification_status"] != "VERIFIED":
        raise err_invalid_state("Order verification_status is not VERIFIED")
    if not order["substitution_pending"]:
        raise err_substitution_not_pending()
    if (
        protocol["status"] != "ACTIVE"
        or protocol["shortage_drug_product_id"] != order["drug_product_id"]
    ):
        raise err_no_active_protocol()
    substitute = db.drugs[protocol["substitute_drug_product_id"]]
    if substitute["status"] != "ACTIVE":
        raise err_no_eligible_substitute()
    patient = db.patients[order["patient_id"]]
    if substitute["id"] in patient["allergy_drug_product_ids"]:
        raise err_allergy()
    if order["fulfillment_status"] not in ("QUEUED", "COMPOUNDING"):
        raise err_invalid_state("Order fulfillment_status must be QUEUED or COMPOUNDING")

    order["drug_product_id"] = substitute["id"]
    order["ordered_dose_mg"] = calc.substitution_equivalent_dose(
        order["ordered_dose_mg"], protocol
    )
    order["substituted_by_protocol_id"] = protocol["id"]
    order["substitution_pending"] = False
    _run_renal_and_rounding(order)
    db.touch(order)
    return ok(serialize(order))

"""Prescription endpoints and the EPCS signing protocol (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from db import stamp_create, touch
from errors import (
    APIError,
    ERR_EPCS_REQUIREMENTS_NOT_MET,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import require
from response import ok_array, ok_object
from routes.common import lookup_or_404, paginate, parse_pagination, sort_by_created
from services import calc, derive
from validation import get_body, optional_enum, optional_str, require_str

bp = Blueprint("prescriptions", __name__)

SCHEDULES = {"NON_CONTROLLED", "C_II", "C_III", "C_IV", "C_V"}
NON_TERMINAL_VOIDABLE = {"DRAFT", "PENDING_SIGNATURE", "SIGNED", "TRANSMITTED"}
SUBMIT_VISIT_STATES = {"IN_PROGRESS", "CODED", "FINALIZED"}


@bp.route("/prescriptions", methods=["POST"])
def create_prescription():
    require(["Provider"])
    body = get_body()

    # Priority 4: body FK existence (patient_id, provider_id, visit_id).
    for fk, store in (("patient_id", db.patients), ("provider_id", db.providers),
                      ("visit_id", db.visits)):
        raw = body.get(fk)
        if isinstance(raw, str) and raw not in store:
            raise APIError(ERR_REFERENCE_NOT_FOUND, 404, f"{fk} does not resolve")

    patient_id = require_str(body, "patient_id")
    provider_id = require_str(body, "provider_id")
    visit_id = require_str(body, "visit_id")
    drug_name = require_str(body, "drug_name")
    schedule = optional_enum(body, "schedule", SCHEDULES, default="NON_CONTROLLED")

    for fk, val, store in (("patient_id", patient_id, db.patients),
                           ("provider_id", provider_id, db.providers),
                           ("visit_id", visit_id, db.visits)):
        if val not in store:
            raise APIError(ERR_REFERENCE_NOT_FOUND, 404, f"{fk} does not resolve")

    rec = stamp_create({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "visit_id": visit_id,
        "drug_name": drug_name,
        "schedule": schedule,
        "two_factor_token": None,
        "status": "DRAFT",
    })
    db.prescriptions[rec["id"]] = rec
    return ok_object(derive.serialize_prescription(rec), 201)


@bp.route("/prescriptions/<rxid>", methods=["GET"])
def get_prescription(rxid):
    require(["Provider", "Patient", "FrontDesk"])
    rec = lookup_or_404(db.prescriptions, rxid, "Prescription")
    if g.user_role == "Patient" and g.user_id != rec["patient_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Patient may only read own prescriptions")
    return ok_object(derive.serialize_prescription(rec), 200)


@bp.route("/prescriptions", methods=["GET"])
def list_prescriptions():
    require(["Provider", "FrontDesk"])
    limit, offset = parse_pagination()
    items = list(db.prescriptions.values())
    for key in ("patient_id", "provider_id", "visit_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [rx for rx in items if rx[key] == val]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_prescription(rx) for rx in window], limit, offset, total)


@bp.route("/prescriptions/<rxid>/submit", methods=["POST"])
def submit_prescription(rxid):
    require(["Provider"])
    rx = lookup_or_404(db.prescriptions, rxid, "Prescription")
    if rx["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Prescription is not DRAFT")
    visit = db.visits.get(rx["visit_id"])
    if not visit or visit["status"] not in SUBMIT_VISIT_STATES:
        raise APIError(ERR_INVALID_STATE, 409, "Visit not in a submittable state")
    rx["status"] = "PENDING_SIGNATURE"
    touch(rx)
    return ok_object(derive.serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rxid>/revise", methods=["POST"])
def revise_prescription(rxid):
    require(["Provider"])
    rx = lookup_or_404(db.prescriptions, rxid, "Prescription")
    if rx["status"] != "PENDING_SIGNATURE":
        raise APIError(ERR_INVALID_STATE, 409, "Prescription is not PENDING_SIGNATURE")
    rx["status"] = "DRAFT"
    touch(rx)
    return ok_object(derive.serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rxid>/sign", methods=["POST"])
def sign_prescription(rxid):
    require(["Provider"])
    rx = lookup_or_404(db.prescriptions, rxid, "Prescription")
    body = get_body()
    two_factor_token = optional_str(body, "two_factor_token", default=None)

    # Priority 6: state.
    if rx["status"] != "PENDING_SIGNATURE":
        raise APIError(ERR_INVALID_STATE, 409, "Prescription is not PENDING_SIGNATURE")
    # Priority 7: acting provider owns the prescription.
    if g.user_id != rx["provider_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Only the prescriber may sign")

    # Priority 8: EPCS safety for controlled substances.
    if rx["schedule"] != "NON_CONTROLLED":
        provider = db.providers.get(rx["provider_id"])
        token_ok = isinstance(two_factor_token, str) and two_factor_token.strip() != ""
        if (not provider or not provider.get("epcs_enrolled")
                or not provider.get("dea_number") or not token_ok):
            raise APIError(ERR_EPCS_REQUIREMENTS_NOT_MET, 422, "EPCS requirements not met")

    if two_factor_token is not None:
        rx["two_factor_token"] = two_factor_token
    rx["status"] = "SIGNED"
    touch(rx)

    if rx["schedule"] != "NON_CONTROLLED":
        provider = db.providers.get(rx["provider_id"])
        if provider:
            provider["controlled_rx_count"] = derive.compute_provider_controlled_rx_count(provider["id"])
    return ok_object(derive.serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rxid>/transmit", methods=["POST"])
def transmit_prescription(rxid):
    require(["Provider"])
    rx = lookup_or_404(db.prescriptions, rxid, "Prescription")
    if rx["status"] != "SIGNED":
        raise APIError(ERR_INVALID_STATE, 409, "Prescription is not SIGNED")
    rx["status"] = "TRANSMITTED"
    touch(rx)
    return ok_object(derive.serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rxid>/dispense", methods=["POST"])
def dispense_prescription(rxid):
    require(["Provider"])
    rx = lookup_or_404(db.prescriptions, rxid, "Prescription")
    if rx["status"] != "TRANSMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Prescription is not TRANSMITTED")
    rx["status"] = "DISPENSED"
    touch(rx)

    patient = db.patients.get(rx["patient_id"])
    if patient is not None:
        # CHAIN-2 link 1: active_medication_count recomputed (incremented).
        derive.recompute_patient_active_medication_count(patient)
        # CHAIN-2 link 2: MED_ADHERENCE GAP flip when threshold met.
        flipped = False
        if patient["active_medication_count"] >= calc.MED_ADHERENCE_MIN_FILLS:
            for m in db.hedis_measures.values():
                if m["patient_id"] != patient["id"]:
                    continue
                if m["measure_type"] != "MED_ADHERENCE":
                    continue
                if m["status"] != "GAP":
                    continue
                if m["measurement_year"] != calc.CURRENT_MEASUREMENT_YEAR:
                    continue
                m["status"] = "NUMERATOR_COMPLIANT"
                touch(m)
                flipped = True
        derive.recompute_patient_open_care_gaps(patient)
        touch(patient)

    return ok_object(derive.serialize_prescription(rx), 200)


@bp.route("/prescriptions/<rxid>/void", methods=["POST"])
def void_prescription(rxid):
    require(["Provider"])
    rx = lookup_or_404(db.prescriptions, rxid, "Prescription")
    if rx["status"] not in NON_TERMINAL_VOIDABLE:
        raise APIError(ERR_INVALID_STATE, 409, "Prescription is not in a voidable state")
    was_controlled = rx["schedule"] != "NON_CONTROLLED"
    rx["status"] = "VOIDED"
    touch(rx)
    if was_controlled:
        provider = db.providers.get(rx["provider_id"])
        if provider:
            provider["controlled_rx_count"] = derive.compute_provider_controlled_rx_count(provider["id"])
    return ok_object(derive.serialize_prescription(rx), 200)

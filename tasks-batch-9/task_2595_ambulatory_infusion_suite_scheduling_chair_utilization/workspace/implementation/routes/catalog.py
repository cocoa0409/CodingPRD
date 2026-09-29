"""Drugs and drug lots (PRD 3.2)."""

from flask import Blueprint

import db
from db import must, new_row, rows
from errors import ApiError
from middleware import authenticate
from response import created, ok
from routes.common import paged
from services import derive, present
from validators import (
    bad,
    body,
    opt_bool,
    opt_int,
    opt_num,
    opt_str,
    q_bool,
    q_enum,
    q_str,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("catalog", __name__)

ALL_STAFF = ("Scheduler", "InfusionNurse", "Pharmacist", "AuthorizationSpecialist", "MedicalDirector")
LOT_STATUSES = ("AVAILABLE", "DEPLETED", "EXPIRED")


# ------------------------------------------------------------------ drugs
@bp.post("/drugs")
def create_drug():
    authenticate("Pharmacist")
    data = body()
    name = req_str(data, "name", 1, 120)
    is_biosimilar = opt_bool(data, "is_biosimilar", False)
    reference_drug_id = opt_str(data, "reference_drug_id", 1, None, None, allow_null=True)
    base_admin = req_int(data, "base_administration_minutes", 5, 480)
    min_admin = req_int(data, "min_administration_minutes", 5, 480)
    premed = opt_int(data, "premedication_minutes", 0, 120, 0)
    obs_first = req_int(data, "observation_minutes_first_dose", 0, 240)
    obs_subsequent = req_int(data, "observation_minutes_subsequent", 0, 240)
    acuity = req_int(data, "acuity_points", 1, 10)
    stability = req_int(data, "prep_stability_minutes", 15, 1440)
    unit_cost = req_int(data, "unit_cost_cents", 0, None)
    requires_lab_gate = opt_bool(data, "requires_lab_gate", False)
    lab_min_anc = opt_num(data, "lab_min_anc", 0, None, None, allow_null=True)
    lab_min_platelets = opt_int(data, "lab_min_platelets", 0, None, None, allow_null=True)
    for drug in rows("drugs"):
        if drug["name"] == name:
            bad("A drug with this name already exists.")
    if reference_drug_id is not None:
        must("drugs", reference_drug_id)
    row = new_row(
        "drugs",
        {
            "name": name,
            "is_biosimilar": is_biosimilar,
            "reference_drug_id": reference_drug_id,
            "base_administration_minutes": base_admin,
            "min_administration_minutes": min_admin,
            "premedication_minutes": premed,
            "observation_minutes_first_dose": obs_first,
            "observation_minutes_subsequent": obs_subsequent,
            "acuity_points": acuity,
            "prep_stability_minutes": stability,
            "unit_cost_cents": unit_cost,
            "requires_lab_gate": requires_lab_gate,
            "lab_min_anc": float(lab_min_anc) if lab_min_anc is not None else None,
            "lab_min_platelets": lab_min_platelets,
        },
    )
    return created(present.plain(row))


@bp.get("/drugs/<drug_id>")
def read_drug(drug_id):
    authenticate(*ALL_STAFF)
    return ok(present.plain(must("drugs", drug_id)))


@bp.get("/drugs")
def list_drugs():
    authenticate(*ALL_STAFF)
    reference_drug_id = q_str("reference_drug_id")
    is_biosimilar = q_bool("is_biosimilar")
    name = q_str("name")
    items = []
    for drug in rows("drugs"):
        if reference_drug_id is not None and drug["reference_drug_id"] != reference_drug_id:
            continue
        if is_biosimilar is not None and bool(drug["is_biosimilar"]) != is_biosimilar:
            continue
        if name is not None and drug["name"] != name:
            continue
        items.append(drug)
    return paged("drugs", items)


# ------------------------------------------------------------------ lots
@bp.post("/drug-lots")
def create_lot():
    authenticate("Pharmacist")
    data = body()
    drug_id = req_str(data, "drug_id", 1, None)
    lot_number = req_str(data, "lot_number", 1, 32)
    units_received = req_int(data, "units_received", 0, None)
    expires_dt, expires_raw = req_instant(data, "expires_on")
    must("drugs", drug_id)
    for lot in rows("lots"):
        if lot["drug_id"] == drug_id and lot["lot_number"] == lot_number:
            bad("This lot number already exists for the drug.")
    row = new_row(
        "lots",
        {
            "drug_id": drug_id,
            "lot_number": lot_number,
            "units_received": units_received,
            "expires_on": expires_raw,
            "units_committed": 0,
            "units_administered": 0,
            "units_wasted": 0,
            "units_returned": 0,
            "units_available": units_received,
            "status": "AVAILABLE",
        },
    )
    row["_expires_dt"] = expires_dt
    derive.recompute_lot(row)
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return created(present.plain(row))


@bp.get("/drug-lots/<lot_id>")
def read_lot(lot_id):
    authenticate("Pharmacist", "Scheduler", "MedicalDirector")
    return ok(present.plain(must("lots", lot_id)))


@bp.get("/drug-lots")
def list_lots():
    authenticate("Pharmacist", "Scheduler", "MedicalDirector")
    drug_id = q_str("drug_id")
    status = q_enum("status", LOT_STATUSES)
    items = []
    for lot in rows("lots"):
        if drug_id is not None and lot["drug_id"] != drug_id:
            continue
        if status is not None and lot["status"] != status:
            continue
        items.append(lot)
    items.sort(key=lambda lot: (lot["_expires_dt"], lot["_seq"]))
    return paged("lots", items)


@bp.post("/drug-lots/<lot_id>/adjustments")
def adjust_lot(lot_id):
    authenticate("Pharmacist")
    data = body()
    units_delta = req_int(data, "units_delta", None, None)
    req_str(data, "reason", 1, None)
    expected_version = req_int(data, "expected_drug_lot_version", None, None)
    lot = must("lots", lot_id)
    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION")
    if lot["status"] != "AVAILABLE":
        raise ApiError("ERR_LOT_NOT_AVAILABLE")
    new_received = int(lot["units_received"]) + units_delta
    projected = (
        new_received
        - int(lot["units_committed"])
        - int(lot["units_administered"])
        - int(lot["units_wasted"])
    )
    if projected < 0:
        raise ApiError("ERR_INSUFFICIENT_DRUG_UNITS")
    derive.recompute_lot(lot, {"units_received": new_received})
    return ok(present.plain(lot))

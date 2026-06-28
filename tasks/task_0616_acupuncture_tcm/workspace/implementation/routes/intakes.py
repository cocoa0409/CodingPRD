"""Intake / TCM diagnosis routes (PRD 3.2)."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_intake, get_patient
from middleware import get_auth, require_role
from response import success

bp = Blueprint("intakes", __name__)

TONGUE_FINDINGS = ("PALE", "RED", "PURPLE", "NORMAL")
TONGUE_COATINGS = ("THIN_WHITE", "THICK_YELLOW", "NONE", "GREASY")
PULSE_FINDINGS = ("WIRY", "SLIPPERY", "THREADY", "RAPID", "DEEP", "FLOATING")
TCM_PATTERNS = (
    "QI_STAGNATION",
    "BLOOD_DEFICIENCY",
    "DAMP_HEAT",
    "YANG_DEFICIENCY",
    "YIN_DEFICIENCY",
)


@bp.route("/intakes", methods=["POST"])
def create_intake():
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    body = get_json_body()
    require_fields(
        body,
        [
            "patient_id",
            "chief_complaint",
            "tongue_finding",
            "tongue_coating",
            "pulse_finding",
            "tcm_pattern",
        ],
    )
    # Body FK existence (priority 5) before well-formedness of enums.
    patient = get_patient(body["patient_id"])

    chief_complaint = require_string(body, "chief_complaint")
    tongue_finding = body["tongue_finding"]
    tongue_coating = body["tongue_coating"]
    pulse_finding = body["pulse_finding"]
    tcm_pattern = body["tcm_pattern"]
    if tongue_finding not in TONGUE_FINDINGS:
        raise err("ERR_INVALID_REQUEST", "Invalid tongue_finding.")
    if tongue_coating not in TONGUE_COATINGS:
        raise err("ERR_INVALID_REQUEST", "Invalid tongue_coating.")
    if pulse_finding not in PULSE_FINDINGS:
        raise err("ERR_INVALID_REQUEST", "Invalid pulse_finding.")
    if tcm_pattern not in TCM_PATTERNS:
        raise err("ERR_INVALID_REQUEST", "Invalid tcm_pattern.")

    rec = {
        "patient_id": patient["id"],
        "chief_complaint": chief_complaint,
        "tongue_finding": tongue_finding,
        "tongue_coating": tongue_coating,
        "pulse_finding": pulse_finding,
        "tcm_pattern": tcm_pattern,
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.intakes[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/intakes", methods=["GET"])
def list_intakes():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = list(db.intakes.values())
    patient_filter = request.args.get("patient_id")
    if role == "Patient":
        # A patient may read only their own intakes.
        patient_filter = user_id
    if patient_filter is not None:
        items = [i for i in items if i["patient_id"] == patient_filter]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/intakes/<rid>", methods=["GET"])
def get_intake_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_intake(rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own intakes.")
    return success(public(rec), status=200)


@bp.route("/intakes/<rid>/finalize", methods=["POST"])
def finalize_intake(rid):
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    rec = get_intake(rid)
    # State precondition.
    if rec["status"] != "DRAFT":
        raise err("ERR_INTAKE_NOT_DRAFT", "Finalize requires Intake.status == DRAFT.")
    # Completeness: tcm_pattern, tongue_finding, pulse_finding all non-null.
    if not rec.get("tcm_pattern") or not rec.get("tongue_finding") or not rec.get("pulse_finding"):
        raise err(
            "ERR_INTAKE_INCOMPLETE",
            "Finalize requires tcm_pattern, tongue_finding, pulse_finding non-null.",
        )
    rec["status"] = "FINALIZED"
    touch(rec)
    # Cross-entity: flip the patient's intake_status to INTAKE_COMPLETE.
    patient = db.patients.get(rec["patient_id"])
    if patient is not None:
        patient["intake_status"] = "INTAKE_COMPLETE"
        touch(patient)
    return success(public(rec), status=200)

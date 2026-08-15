"""Deficiency endpoints: findings, remediation axis transitions, and the
independent verification axis."""

from flask import Blueprint, request

import db
from errors import (
    ERR_CODE_SEVERITY_TOO_LOW,
    ERR_INVALID_STATE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENTIAL_CONFLICT,
    ERR_YEAR_OUT_OF_RANGE,
    raise_error,
)
from middleware import auth
from response import ok_object
from services.core import (
    append_snapshot,
    compute_priority_score,
    current_epoch,
    get_or_404,
    list_response,
    new_record,
    pub,
    recompute_facility,
    touch,
)
from util import body, bool_param, is_int, v_bool, v_int, v_str

bp = Blueprint("deficiencies", __name__)


def _facility_of(deficiency):
    system = db.asset_systems[deficiency["asset_system_id"]]
    return db.facilities[system["facility_id"]]


@bp.post("/fca/deficiencies")
def create_deficiency():
    auth("Consultant")
    data = body()
    # Priority 4: body FK existence
    asset_system_id = data.get("asset_system_id")
    if asset_system_id is not None and asset_system_id not in db.asset_systems:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"asset_system_id does not reference an existing asset system: {asset_system_id}",
        )
    # Priority 8: code/accessibility hygiene — flagged findings need
    # severity >= 3
    severity_raw = data.get("severity")
    if (
        data.get("is_code_violation") is True
        or data.get("is_accessibility_violation") is True
    ) and is_int(severity_raw) and severity_raw < 3:
        raise_error(
            ERR_CODE_SEVERITY_TOO_LOW,
            "Code or accessibility violation requires severity >= 3",
        )
    # Priority 9: temporal range — recommended_year must be >= 2026
    recommended_year_raw = data.get("recommended_year")
    if is_int(recommended_year_raw) and recommended_year_raw < 2026:
        raise_error(
            ERR_YEAR_OUT_OF_RANGE,
            "recommended_year must be >= 2026",
        )
    # Priority 10: field shape
    description = v_str(data, "description")
    cost_estimate_cents = v_int(data, "cost_estimate_cents", minimum=1)
    severity = v_int(data, "severity", minimum=1, maximum=5)
    urgency = v_int(data, "urgency", minimum=1, maximum=5)
    is_code_violation = v_bool(data, "is_code_violation", False)
    is_accessibility_violation = v_bool(data, "is_accessibility_violation", False)
    recommended_year = v_int(data, "recommended_year", minimum=2000, maximum=2200)
    asset_system_id = v_str(data, "asset_system_id")
    # Priority 12: no deficiency on a RETIRED system
    system = db.asset_systems[asset_system_id]
    if system["status"] == "RETIRED":
        raise_error(
            ERR_REFERENTIAL_CONFLICT,
            "Cannot record a deficiency on a RETIRED asset system",
        )
    rec = new_record()
    rec.update(
        {
            "asset_system_id": asset_system_id,
            "description": description,
            "cost_estimate_cents": cost_estimate_cents,
            "severity": severity,
            "urgency": urgency,
            "is_code_violation": is_code_violation,
            "is_accessibility_violation": is_accessibility_violation,
            "recommended_year": recommended_year,
            "priority_score": compute_priority_score(
                severity, urgency, is_code_violation, is_accessibility_violation
            ),
            "remediation_status": "OPEN",
            "verification_status": "UNVERIFIED",
        }
    )
    db.deficiencies[rec["id"]] = rec
    recompute_facility(db.facilities[system["facility_id"]])
    return ok_object(pub(rec), 201)


@bp.get("/fca/deficiencies")
def list_deficiencies():
    auth()
    records = list(db.deficiencies.values())
    asset_system_id = request.args.get("asset_system_id")
    if asset_system_id is not None:
        records = [r for r in records if r["asset_system_id"] == asset_system_id]
    remediation_status = request.args.get("remediation_status")
    if remediation_status is not None:
        records = [
            r for r in records if r["remediation_status"] == remediation_status
        ]
    is_code = bool_param("is_code_violation")
    if is_code is not None:
        records = [r for r in records if r["is_code_violation"] is is_code]
    is_acc = bool_param("is_accessibility_violation")
    if is_acc is not None:
        records = [r for r in records if r["is_accessibility_violation"] is is_acc]
    return list_response(records)


@bp.get("/fca/deficiencies/<deficiency_id>")
def get_deficiency(deficiency_id):
    auth()
    return ok_object(pub(get_or_404(db.deficiencies, deficiency_id, "Deficiency")))


@bp.post("/fca/deficiencies/<deficiency_id>/start-remediation")
def start_remediation(deficiency_id):
    auth("FacilityManager")
    d = get_or_404(db.deficiencies, deficiency_id, "Deficiency")
    if d["remediation_status"] != "OPEN":
        raise_error(
            ERR_INVALID_STATE,
            f"remediation_status {d['remediation_status']} does not permit start-remediation",
        )
    d["remediation_status"] = "IN_PROGRESS"
    touch(d)
    recompute_facility(_facility_of(d))
    return ok_object(pub(d))


@bp.post("/fca/deficiencies/<deficiency_id>/complete-remediation")
def complete_remediation(deficiency_id):
    auth("FacilityManager")
    d = get_or_404(db.deficiencies, deficiency_id, "Deficiency")
    if d["remediation_status"] != "IN_PROGRESS":
        raise_error(
            ERR_INVALID_STATE,
            f"remediation_status {d['remediation_status']} does not permit complete-remediation",
        )
    system = db.asset_systems[d["asset_system_id"]]
    if system["status"] == "RETIRED":
        raise_error(
            ERR_INVALID_STATE,
            "Cannot complete remediation on a RETIRED asset system",
        )
    d["remediation_status"] = "CORRECTED"
    touch(d)
    recompute_facility(_facility_of(d))
    return ok_object(pub(d))


@bp.post("/fca/deficiencies/<deficiency_id>/defer")
def defer_deficiency(deficiency_id):
    auth("FacilityManager")
    d = get_or_404(db.deficiencies, deficiency_id, "Deficiency")
    if d["remediation_status"] != "OPEN":
        raise_error(
            ERR_INVALID_STATE,
            f"remediation_status {d['remediation_status']} does not permit defer",
        )
    # DEFERRED remains in the backlog set: no facility recomputation occurs.
    d["remediation_status"] = "DEFERRED"
    touch(d)
    return ok_object(pub(d))


@bp.post("/fca/deficiencies/<deficiency_id>/reopen")
def reopen_deficiency(deficiency_id):
    auth("FacilityManager")
    d = get_or_404(db.deficiencies, deficiency_id, "Deficiency")
    if d["remediation_status"] != "DEFERRED":
        raise_error(
            ERR_INVALID_STATE,
            f"remediation_status {d['remediation_status']} does not permit reopen",
        )
    d["remediation_status"] = "OPEN"
    touch(d)
    return ok_object(pub(d))


@bp.post("/fca/deficiencies/<deficiency_id>/verify")
def verify_deficiency(deficiency_id):
    auth("Consultant")
    d = get_or_404(db.deficiencies, deficiency_id, "Deficiency")
    if d["remediation_status"] != "CORRECTED" or d["verification_status"] != "UNVERIFIED":
        raise_error(
            ERR_INVALID_STATE,
            "verify requires remediation_status CORRECTED with verification_status UNVERIFIED",
        )
    d["verification_status"] = "VERIFIED"
    touch(d)
    system = db.asset_systems[d["asset_system_id"]]
    fac = db.facilities[system["facility_id"]]
    append_snapshot(system, current_epoch(fac), None)
    return ok_object(pub(d))


@bp.post("/fca/deficiencies/<deficiency_id>/reject-verification")
def reject_verification(deficiency_id):
    auth("Consultant")
    d = get_or_404(db.deficiencies, deficiency_id, "Deficiency")
    if d["remediation_status"] != "CORRECTED" or d["verification_status"] != "UNVERIFIED":
        raise_error(
            ERR_INVALID_STATE,
            "reject-verification requires remediation_status CORRECTED with verification_status UNVERIFIED",
        )
    d["verification_status"] = "REJECTED"
    # Compensation: the finding re-enters the backlog set.
    d["remediation_status"] = "IN_PROGRESS"
    touch(d)
    recompute_facility(_facility_of(d))
    return ok_object(pub(d))

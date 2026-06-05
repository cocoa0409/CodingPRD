"""Result CRUD + release + amend + invalidate."""
from __future__ import annotations

from typing import Optional

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SPECIMEN_ORDER_MISMATCH, ERR_RUN_SPECIMEN_MISMATCH,
    ERR_INVALID_RANGE, ERR_STALE_LAB_ORDER_VERSION, ERR_STALE_RESULT_VERSION,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_enum, require_number, require_int,
    lookup_or_404,
)
from services.calculations import (
    classify_criticality, compute_age_band, recompute_patient_release_count,
)
from services.cascades import (
    cascade_result_release, void_pending_or_sent_notifications_for_result,
)


bp = Blueprint("results", __name__)

ANALYTES = {"K", "GLUCOSE", "TROPONIN", "HGB"}
ANALYTE_UNIT = {
    "K": "mmol/L",
    "GLUCOSE": "mg/dL",
    "TROPONIN": "ng/mL",
    "HGB": "g/dL",
}


from typing import Dict, Any


def _round2(v: float) -> float:
    return round(float(v) + 1e-12, 2)


def _create_critical_notification_if_needed(result: Dict[str, Any], order: Dict[str, Any]) -> None:
    """If Result.criticality is critical, auto-create a CriticalNotification.

    PENDING. recipient_clinician_id = order.ordering_clinician_id at this moment.
    channel: scaffold says "selected per panel rule" — PRD §3.5 says the
    integration tier selects it, but the auto-created notification's channel
    must be sent later. Default channel: PHONE for STAT priority orders,
    otherwise SMS (a safe default). The send step will re-validate the
    STAT→PHONE rule.
    """
    crit = result.get("criticality")
    if crit not in ("CRITICAL_LOW", "CRITICAL_HIGH", "PANIC"):
        return
    channel = "PHONE" if order.get("priority") == "STAT" else "SMS"
    note = {
        "result_id": result["id"],
        "recipient_clinician_id": order.get("ordering_clinician_id"),
        "channel": channel,
        "status": "PENDING",
        "sent_at": None,
        "ack_deadline_at": None,
        "attempt_count": 0,
        "escalation_target_clinician_id": None,
    }
    db.stamp_common(note)
    db.critical_notifications[note["id"]] = note


# ---------- POST /results -------------------------------------------------

@bp.post("/results")
def create_result():
    require_auth(["LabTech"])()
    body = get_json_body()
    required = ["lab_order_id", "specimen_id", "run_id", "analyte_code",
                "numeric_value", "unit", "reference_low", "reference_high",
                "critical_low", "critical_high"]
    require_fields(body, required)

    lab_order_id = body["lab_order_id"]
    specimen_id = body["specimen_id"]
    run_id = body["run_id"]
    analyte = body["analyte_code"]
    nv = body["numeric_value"]
    unit = body["unit"]
    ref_lo = body["reference_low"]
    ref_hi = body["reference_high"]
    crit_lo = body["critical_low"]
    crit_hi = body["critical_high"]

    require_string(lab_order_id, "lab_order_id")
    require_string(specimen_id, "specimen_id")
    require_string(run_id, "run_id")
    require_enum(analyte, ANALYTES, "analyte_code")
    nv = require_number(nv, "numeric_value")
    require_string(unit, "unit")
    ref_lo = require_number(ref_lo, "reference_low")
    ref_hi = require_number(ref_hi, "reference_high")
    crit_lo = require_number(crit_lo, "critical_low")
    crit_hi = require_number(crit_hi, "critical_high")

    # FK existence (left-to-right body order).
    order = lookup_or_404(db.lab_orders, lab_order_id, "LabOrder")
    spec = lookup_or_404(db.specimens, specimen_id, "Specimen")
    run = lookup_or_404(db.instrument_runs, run_id, "InstrumentRun")

    # Cross-reference validations.
    if spec.get("lab_order_id") != lab_order_id:
        raise APIError(ERR_SPECIMEN_ORDER_MISMATCH, 422,
                       "Specimen's lab_order_id does not match supplied lab_order_id")
    if run.get("specimen_id") != specimen_id:
        raise APIError(ERR_RUN_SPECIMEN_MISMATCH, 422,
                       "InstrumentRun's specimen_id does not match Result.specimen_id")

    # Range sanity.
    if ref_hi <= ref_lo or crit_hi <= crit_lo:
        raise APIError(ERR_INVALID_RANGE, 422,
                       "reference_high>reference_low and critical_high>critical_low required")

    # Unit consistency (canonical unit per analyte; PRD §3.5).
    canonical = ANALYTE_UNIT.get(analyte)
    if canonical and unit != canonical:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"unit for {analyte} must be '{canonical}'")

    result = {
        "lab_order_id": lab_order_id,
        "specimen_id": specimen_id,
        "run_id": run_id,
        "analyte_code": analyte,
        "numeric_value": _round2(nv),
        "unit": unit,
        "reference_low": _round2(ref_lo),
        "reference_high": _round2(ref_hi),
        "critical_low": _round2(crit_lo),
        "critical_high": _round2(crit_hi),
        "criticality": None,
        "status": "PROVISIONAL",
        "released_at": None,
        "amended_from_result_id": None,
    }
    db.stamp_common(result)
    db.results[result["id"]] = result
    return ok_object(result, http_status=201)


# ---------- GET /results/{id} ---------------------------------------------

@bp.get("/results/<rid>")
def get_result(rid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    r = lookup_or_404(db.results, rid, "Result")
    return ok_object(r)


# ---------- GET /results --------------------------------------------------

@bp.get("/results")
def list_results():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    items = list(db.results.values())
    for key in ("lab_order_id", "specimen_id", "run_id", "amended_from_result_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /results/{id}/release ------------------------------------

@bp.post("/results/<rid>/release")
def release_result(rid):
    require_auth(["LabTech"])()
    r = lookup_or_404(db.results, rid, "Result")
    body = get_json_body()
    require_fields(body, ["expected_lab_order_version"])
    expected = body["expected_lab_order_version"]
    expected = require_int(expected, "expected_lab_order_version", min_v=0)

    if r.get("status") != "PROVISIONAL":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Result.status '{r.get('status')}' is not PROVISIONAL")

    order = lookup_or_404(db.lab_orders, r["lab_order_id"], "LabOrder")
    spec = lookup_or_404(db.specimens, r["specimen_id"], "Specimen")
    run = lookup_or_404(db.instrument_runs, r["run_id"], "InstrumentRun")

    if spec.get("status") != "ACCESSIONED":
        raise APIError(ERR_INVALID_STATE, 409, "Specimen must be ACCESSIONED")
    if run.get("status") != "COMPLETED":
        raise APIError(ERR_INVALID_STATE, 409, "InstrumentRun must be COMPLETED")

    # OCC against parent LabOrder.
    if expected != order.get("version"):
        raise APIError(ERR_STALE_LAB_ORDER_VERSION, 412,
                       "expected_lab_order_version does not match")

    # Recompute Patient.age_band at this moment of release.
    patient = db.patients.get(order["patient_id"])
    if patient:
        patient["age_band"] = compute_age_band(patient["date_of_birth"], db.get_current_utc_dt())

    crit = classify_criticality(
        numeric_value=r["numeric_value"],
        critical_low=r["critical_low"], critical_high=r["critical_high"],
        reference_low=r["reference_low"], reference_high=r["reference_high"],
        age_band=patient.get("age_band") if patient else "ADULT",
        analyte_code=r["analyte_code"],
    )

    r["status"] = "RELEASED"
    r["released_at"] = db.get_current_utc_iso()
    r["criticality"] = crit
    db.bump(r)

    # Recompute patient.results_release_count.
    if patient:
        recompute_patient_release_count(patient)
        db.bump(patient)

    # Auto-create CriticalNotification if criticality is critical.
    _create_critical_notification_if_needed(r, order)

    # Cascade to LabOrder: first release ⇒ ACCESSIONED->RESULTED + TAT pin,
    # always bump version.
    cascade_result_release(order, r)

    return ok_object(r)


# ---------- POST /results/{id}/amend --------------------------------------

@bp.post("/results/<rid>/amend")
def amend_result(rid):
    require_auth(["LabTech"])()
    r = lookup_or_404(db.results, rid, "Result")
    body = get_json_body()
    require_fields(body, ["expected_result_version", "numeric_value"])
    expected = require_int(body["expected_result_version"], "expected_result_version", min_v=0)
    nv = require_number(body["numeric_value"], "numeric_value")

    if r.get("status") != "RELEASED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Result.status '{r.get('status')}' is not RELEASED")

    if expected != r.get("version"):
        raise APIError(ERR_STALE_RESULT_VERSION, 412,
                       "expected_result_version does not match")

    order = db.lab_orders.get(r["lab_order_id"])
    patient = db.patients.get(order["patient_id"]) if order else None

    # Mark old row AMENDED.
    r["status"] = "AMENDED"
    db.bump(r)

    # Recompute age_band on the patient at this moment.
    if patient:
        patient["age_band"] = compute_age_band(patient["date_of_birth"], db.get_current_utc_dt())

    # Build the new RELEASED descendant.
    new_crit = classify_criticality(
        numeric_value=nv,
        critical_low=r["critical_low"], critical_high=r["critical_high"],
        reference_low=r["reference_low"], reference_high=r["reference_high"],
        age_band=patient.get("age_band") if patient else "ADULT",
        analyte_code=r["analyte_code"],
    )
    new_row = {
        "lab_order_id": r["lab_order_id"],
        "specimen_id": r["specimen_id"],
        "run_id": r["run_id"],
        "analyte_code": r["analyte_code"],
        "numeric_value": _round2(nv),
        "unit": r["unit"],
        "reference_low": r["reference_low"],
        "reference_high": r["reference_high"],
        "critical_low": r["critical_low"],
        "critical_high": r["critical_high"],
        "criticality": new_crit,
        "status": "RELEASED",
        "released_at": db.get_current_utc_iso(),
        "amended_from_result_id": r["id"],
    }
    db.stamp_common(new_row)
    db.results[new_row["id"]] = new_row

    # Void any PRIOR notification on the old row that is still in
    # {PENDING, SENT, ACKNOWLEDGED}.
    for n in db.critical_notifications.values():
        if n.get("result_id") != r["id"]:
            continue
        if n.get("status") in ("PENDING", "SENT", "ACKNOWLEDGED"):
            n["status"] = "VOIDED"
            db.bump(n)

    # Auto-create fresh notification on new row if recomputed criticality is critical.
    if order:
        _create_critical_notification_if_needed(new_row, order)

    # results_release_count net unchanged — but recompute for correctness.
    if patient:
        recompute_patient_release_count(patient)
        db.bump(patient)

    return ok_object(new_row, http_status=201)


# ---------- POST /results/{id}/invalidate ---------------------------------

@bp.post("/results/<rid>/invalidate")
def invalidate_result(rid):
    require_auth(["LabDirector"])()
    r = lookup_or_404(db.results, rid, "Result")
    if r.get("status") != "RELEASED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Result.status '{r.get('status')}' is not RELEASED")

    # The actor MUST be a clinician with role_type=LAB_DIRECTOR. The header role
    # is already LabDirector. Verify the X-User-ID maps to a LAB_DIRECTOR clinician.
    actor_id = current_user_id()
    actor = db.clinicians.get(actor_id)
    if actor is None or actor.get("role_type") != "LAB_DIRECTOR":
        raise APIError(ERR_UNAUTHORIZED, 403,
                       "Acting clinician must have role_type=LAB_DIRECTOR")

    r["status"] = "INVALIDATED"
    db.bump(r)

    # Void any PENDING|SENT notification on this Result.
    void_pending_or_sent_notifications_for_result(r["id"])

    # Decrement patient.results_release_count (rule 9b).
    order = db.lab_orders.get(r["lab_order_id"])
    if order:
        patient = db.patients.get(order["patient_id"])
        if patient:
            recompute_patient_release_count(patient)
            db.bump(patient)

    return ok_object(r)

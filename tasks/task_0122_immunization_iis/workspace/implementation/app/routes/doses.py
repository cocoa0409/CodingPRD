"""AdministeredDose routes: schedule, administer, cancel, invalidate, read, list."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from .. import store
from ..auth import require_roles
from ..clock import format_iso, now, parse_iso
from ..errors import APIError
from ..helpers import (
    check_version_conflict,
    ensure_enum,
    parse_iso_or_400,
    parse_json_body,
    paginate,
    parse_pagination,
    require_field,
)
from ..responses import build_envelope
from ..services.calculations import (
    compute_catchup_flag_for_dose,
    patient_age_days,
)
from ..services.cascades import (
    recompute_certs_after_admin,
    recompute_certs_after_dose_invalidation,
    recompute_provider_compliance,
)


bp = Blueprint("doses", __name__)


DOSE_STATES = {"SCHEDULED", "ADMINISTERED", "INVALIDATED", "CANCELLED"}


def _serialize(d: dict) -> dict:
    return {
        "id": d["id"],
        "patient_id": d["patient_id"],
        "vaccine_product_id": d["vaccine_product_id"],
        "lot_id": d["lot_id"],
        "provider_organization_id": d["provider_organization_id"],
        "administering_clinician_id": d["administering_clinician_id"],
        "administered_at": d.get("administered_at"),
        "dose_state": d["dose_state"],
        "invalidation_reason": d.get("invalidation_reason"),
        "reported_at": d.get("reported_at"),
        "catchup_flag": d.get("catchup_flag", False),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def _require_patient(patient_id: str) -> dict:
    p = store.patients.get(patient_id)
    if not p:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")
    return p


def _require_dose_under_patient(patient_id: str, dose_id: str) -> dict:
    _require_patient(patient_id)
    d = store.administered_doses.get(dose_id)
    if not d or d.get("patient_id") != patient_id:
        raise APIError("ERR_DOSE_NOT_FOUND", f"Dose {dose_id} not found under patient {patient_id}.")
    return d


# -----------------------------------------------------------------------------
# POST /patients/{patient_id}/doses  (schedule)
# -----------------------------------------------------------------------------
@bp.post("/patients/<patient_id>/doses")
@require_roles(["ProviderClinician"])
def schedule_dose(patient_id: str):
    body = parse_json_body()
    patient = _require_patient(patient_id)
    product_id = require_field(body, "vaccine_product_id")
    if product_id not in store.vaccine_products:
        raise APIError("ERR_PRODUCT_NOT_FOUND", f"VaccineProduct {product_id} not found.")
    lot_id = require_field(body, "lot_id")
    lot = store.vaccine_lots.get(lot_id)
    if not lot:
        raise APIError("ERR_LOT_NOT_FOUND", f"VaccineLot {lot_id} not found.")
    provider_org_id = require_field(body, "provider_organization_id")
    provider = store.provider_organizations.get(provider_org_id)
    if not provider:
        raise APIError("ERR_PROVIDER_NOT_FOUND", f"ProviderOrganization {provider_org_id} not found.")
    administering_clinician_id = require_field(body, "administering_clinician_id")
    if not isinstance(administering_clinician_id, str) or not administering_clinician_id:
        raise APIError("ERR_VALIDATION", "administering_clinician_id must be a non-empty string.")

    # Priority 95: provider must be ACTIVE.
    if provider["status"] == "SUSPENDED":
        raise APIError("ERR_PROVIDER_SUSPENDED", "Provider is SUSPENDED and cannot record new doses.")

    with store.lock:
        rec = {
            "patient_id": patient_id,
            "vaccine_product_id": product_id,
            "lot_id": lot_id,
            "provider_organization_id": provider_org_id,
            "administering_clinician_id": administering_clinician_id,
            "administered_at": None,
            "dose_state": "SCHEDULED",
            "invalidation_reason": None,
            "reported_at": format_iso(now()),
            "catchup_flag": False,
        }
        store.stamp_create(rec)
        store.administered_doses[rec["id"]] = rec

    return jsonify(build_envelope(_serialize(rec), "object")), 201


# -----------------------------------------------------------------------------
# POST /patients/{patient_id}/doses/{dose_id}/administer
# -----------------------------------------------------------------------------
@bp.post("/patients/<patient_id>/doses/<dose_id>/administer")
@require_roles(["ProviderClinician"])
def administer_dose(patient_id: str, dose_id: str):
    body = parse_json_body()
    patient = _require_patient(patient_id)
    dose = _require_dose_under_patient(patient_id, dose_id)

    # Priority 50: lot must be AVAILABLE
    lot = store.vaccine_lots.get(dose["lot_id"])
    if not lot:
        raise APIError("ERR_LOT_NOT_FOUND", "Lot referenced by dose no longer exists.")
    if lot["status"] == "RECALLED":
        raise APIError("ERR_LOT_RECALLED", "Lot has been recalled.")

    # Priority 51: dose must be SCHEDULED
    if dose["dose_state"] != "SCHEDULED":
        raise APIError("ERR_INVALID_STATE", f"Dose is in state {dose['dose_state']}.")

    # Priority 53: doses_on_hand >= 1
    if lot["doses_on_hand"] < 1:
        raise APIError("ERR_LOT_EXHAUSTED", "Lot is EXHAUSTED.")

    product = store.vaccine_products.get(dose["vaccine_product_id"])
    if not product:
        raise APIError("ERR_PRODUCT_NOT_FOUND", "Product referenced by dose no longer exists.")

    administered_at_raw = require_field(body, "administered_at")
    administered_at = parse_iso_or_400(administered_at_raw, "administered_at")

    # Priority 60: allergy contraindication check (safety supersedes age/interval/temporal).
    contraindication_codes = set(product.get("contraindication_flags") or [])
    if contraindication_codes:
        for allergy in store.allergy_records.values():
            if allergy.get("patient_id") != patient_id:
                continue
            if allergy.get("allergen_code") in contraindication_codes and allergy.get("severity") in {"SEVERE", "ANAPHYLAXIS"}:
                raise APIError(
                    "ERR_ALLERGY_CONTRAINDICATION",
                    "Patient has a SEVERE/ANAPHYLAXIS allergy against this product.",
                )

    # Priority 70: age range.
    age_days = patient_age_days(patient["date_of_birth"], administered_at)
    if age_days < product["min_age_days"]:
        raise APIError("ERR_AGE_OUT_OF_RANGE", "Patient age below product min_age_days.")
    if product["max_age_days"] is not None and age_days > product["max_age_days"]:
        raise APIError("ERR_AGE_OUT_OF_RANGE", "Patient age above product max_age_days.")

    # Priority 71: minimum interval against prior administered dose for the antigen.
    # We check, for each antigen this product covers, whether the dose_sequence
    # number is > 1 — and if so, that the most recent prior ADMINISTERED dose
    # in that antigen series is at least catchup_min_interval_days earlier.
    for antigen in product.get("antigens", []):
        prior = []
        for other in store.administered_doses.values():
            if other["id"] == dose["id"]:
                continue
            if other.get("patient_id") != patient_id:
                continue
            if other.get("dose_state") != "ADMINISTERED":
                continue
            other_product = store.vaccine_products.get(other.get("vaccine_product_id"))
            if not other_product or antigen not in (other_product.get("antigens") or []):
                continue
            prior.append(other)
        prior.sort(key=lambda d: (d["administered_at"], d["id"]))
        next_seq = len(prior) + 1
        if next_seq <= 1:
            continue
        # Find matching schedule rule.
        rule = None
        for r in store.antigen_schedule_rules.values():
            if r["antigen"] == antigen and r["dose_sequence_number"] == next_seq:
                rule = r
                break
        if rule is None:
            # No catchup rule configured -> nothing to enforce.
            continue
        last_admin_at = parse_iso(prior[-1]["administered_at"])
        elapsed_days = (administered_at - last_admin_at).total_seconds() / 86400.0
        if elapsed_days < rule["catchup_min_interval_days"]:
            raise APIError("ERR_MIN_INTERVAL_VIOLATION", "Minimum interval to prior dose not met.")

    # Priority 72: temporal sanity.
    server_now = now()
    if administered_at > server_now:
        raise APIError("ERR_ADMIN_TIME_OUT_OF_RANGE", "administered_at is in the future.")
    dob = date.fromisoformat(patient["date_of_birth"])
    # administered_at must be strictly after date_of_birth.
    admin_date = administered_at.date()
    if admin_date <= dob:
        # Strict > comparison per scaffold; "strictly after date_of_birth" — we
        # interpret as comparing the *date*; if equal day, accept; PRD says
        # "must be ... strictly after the patient's date_of_birth" — we use date
        # equality is technically same day -> reject.
        raise APIError("ERR_ADMIN_TIME_OUT_OF_RANGE", "administered_at must be after date_of_birth.")

    # Priority 80: lot/product correspondence.
    if lot["vaccine_product_id"] != dose["vaccine_product_id"]:
        raise APIError("ERR_LOT_PRODUCT_MISMATCH", "Lot is not for the dose's vaccine_product_id.")

    # Priority 130: OCC.
    check_version_conflict(body, dose)

    # ---- All checks passed; perform the transition + side effects atomically.
    with store.lock:
        # Decrement lot inventory.
        lot["doses_on_hand"] = lot["doses_on_hand"] - 1
        if lot["doses_on_hand"] == 0 and lot["status"] == "AVAILABLE":
            lot["status"] = "EXHAUSTED"
        store.stamp_update(lot)

        # Update the dose.
        dose["dose_state"] = "ADMINISTERED"
        dose["administered_at"] = format_iso(administered_at)
        # Note: reported_at is left as the value stamped at schedule time.
        # Compute catchup_flag now that the dose is administered.
        dose["catchup_flag"] = compute_catchup_flag_for_dose(patient, dose)
        store.stamp_update(dose)

        # Cascades.
        recompute_provider_compliance(dose["provider_organization_id"])
        recompute_certs_after_admin(patient)

    return jsonify(build_envelope(_serialize(dose), "object")), 200


# -----------------------------------------------------------------------------
# POST /patients/{patient_id}/doses/{dose_id}/cancel
# -----------------------------------------------------------------------------
@bp.post("/patients/<patient_id>/doses/<dose_id>/cancel")
@require_roles(["ProviderClinician"])
def cancel_dose(patient_id: str, dose_id: str):
    body = parse_json_body(required=False)
    dose = _require_dose_under_patient(patient_id, dose_id)
    if dose["dose_state"] != "SCHEDULED":
        raise APIError("ERR_INVALID_STATE", f"Dose is in state {dose['dose_state']}.")
    check_version_conflict(body, dose)
    with store.lock:
        dose["dose_state"] = "CANCELLED"
        store.stamp_update(dose)
    return jsonify(build_envelope(_serialize(dose), "object")), 200


# -----------------------------------------------------------------------------
# POST /patients/{patient_id}/doses/{dose_id}/invalidate
# -----------------------------------------------------------------------------
@bp.post("/patients/<patient_id>/doses/<dose_id>/invalidate")
@require_roles(["PublicHealthOfficer"])
def invalidate_dose(patient_id: str, dose_id: str):
    body = parse_json_body()
    patient = _require_patient(patient_id)
    dose = _require_dose_under_patient(patient_id, dose_id)
    if dose["dose_state"] != "ADMINISTERED":
        raise APIError("ERR_INVALID_STATE", f"Dose is in state {dose['dose_state']}.")
    reason = ensure_enum(require_field(body, "reason"), {"DATA_ERROR"}, "reason")
    check_version_conflict(body, dose)
    with store.lock:
        dose["dose_state"] = "INVALIDATED"
        dose["invalidation_reason"] = "DATA_ERROR"
        store.stamp_update(dose)
        # Restore lot inventory.
        lot = store.vaccine_lots.get(dose["lot_id"])
        if lot:
            lot["doses_on_hand"] = lot.get("doses_on_hand", 0) + 1
            # If lot was EXHAUSTED and now has inventory and it's not RECALLED, flip back.
            if lot["status"] == "EXHAUSTED" and lot["doses_on_hand"] >= 1:
                lot["status"] = "AVAILABLE"
            store.stamp_update(lot)
        # Recompute school certificates (demote ISSUED -> DEFICIENT if uncovered).
        recompute_certs_after_dose_invalidation(patient)
        # Recompute provider compliance — invalidated doses drop from window.
        recompute_provider_compliance(dose["provider_organization_id"])
    return jsonify(build_envelope(_serialize(dose), "object")), 200


# -----------------------------------------------------------------------------
# GET /patients/{patient_id}/doses
# -----------------------------------------------------------------------------
@bp.get("/patients/<patient_id>/doses")
@require_roles(["ProviderClinician", "SchoolRegistrar", "ReviewingClinician", "PublicHealthOfficer"])
def list_doses(patient_id: str):
    _require_patient(patient_id)
    limit, offset = parse_pagination()
    state_q = request.args.get("dose_state")
    antigen_q = request.args.get("antigen")
    if state_q is not None and state_q not in DOSE_STATES:
        raise APIError("ERR_VALIDATION", "dose_state filter invalid.")
    rows = [d for d in store.administered_doses.values() if d.get("patient_id") == patient_id]
    if state_q is not None:
        rows = [r for r in rows if r["dose_state"] == state_q]
    if antigen_q is not None:
        filtered = []
        for r in rows:
            prod = store.vaccine_products.get(r["vaccine_product_id"])
            if prod and antigen_q in (prod.get("antigens") or []):
                filtered.append(r)
        rows = filtered
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize(r) for r in page], "array", meta)), 200


@bp.get("/patients/<patient_id>/doses/<dose_id>")
@require_roles(["ProviderClinician", "SchoolRegistrar", "ReviewingClinician", "PublicHealthOfficer"])
def read_dose(patient_id: str, dose_id: str):
    d = _require_dose_under_patient(patient_id, dose_id)
    return jsonify(build_envelope(_serialize(d), "object")), 200

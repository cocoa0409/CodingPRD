"""Encounters: parallel clinical x billing dimensions (PRD 3.3, 3.8)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
import services
from middleware import require

bp = Blueprint("encounters", __name__)

VISIT_TYPES = {"MEDICAL", "SKIN_CHECK", "COSMETIC"}
PAY_PATHS = {"INSURANCE", "CASH"}


@bp.post("/encounters")
@require("FrontDesk", "PracticeAdmin")
def create_encounter():
    data = helpers.body()
    patient_id = helpers.require_str(data, "patient_id")
    provider_id = helpers.require_str(data, "provider_id")
    visit_type = helpers.require_enum(data, "visit_type", VISIT_TYPES)
    scheduled_at = helpers.require_dt(data, "scheduled_at")

    # Body FK existence (priority 4).
    patient = helpers.get_or_404(db.patients, patient_id, "patient")
    provider = helpers.get_or_404(db.providers, provider_id, "provider")

    # PRD 3.3: an encounter may only reference a provider active at creation.
    if not provider["active"]:
        raise errors.invalid_request("provider must be active")

    # pay_path resolution (PRD 2.9).
    if visit_type == "COSMETIC":
        pay_path = "CASH"  # always forced to CASH for COSMETIC visits
    else:
        if "pay_path" in data and data["pay_path"] is not None:
            pay_path = helpers.require_enum(data, "pay_path", PAY_PATHS)
        else:
            pay_path = "INSURANCE" if patient["has_active_insurance"] else "CASH"

    row = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "visit_type": visit_type,
        "scheduled_at": db.iso(scheduled_at),
        "clinical_status": "SCHEDULED",
        "billing_status": "BILLING_OPEN",
        "pay_path": pay_path,
        "open_biopsy_count": 0,
    }
    db.stamp_new(row)
    db.encounters[row["id"]] = row
    return response.created(row)


@bp.get("/encounters/<eid>")
@require("FrontDesk", "PracticeAdmin", "Provider", "BillingSpecialist")
def get_encounter(eid):
    row = helpers.get_or_404(db.encounters, eid, "encounter")
    return response.ok(row)


@bp.get("/encounters")
@require("FrontDesk", "PracticeAdmin", "Provider", "BillingSpecialist")
def list_encounters():
    rows = list(db.encounters.values())
    pid = request.args.get("patient_id")
    if pid is not None:
        rows = [e for e in rows if e["patient_id"] == pid]
    prov = request.args.get("provider_id")
    if prov is not None:
        rows = [e for e in rows if e["provider_id"] == prov]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


# --- clinical dimension transitions ----------------------------------------
@bp.post("/encounters/<eid>/check-in")
@require("FrontDesk")
def check_in(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    if enc["clinical_status"] != "SCHEDULED":
        raise errors.bad_state("ERR_ENCOUNTER_BAD_CLINICAL_STATE")
    enc["clinical_status"] = "CHECKED_IN"
    db.touch(enc)
    return response.ok(enc)


@bp.post("/encounters/<eid>/start")
@require("Provider")
def start(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    if enc["clinical_status"] != "CHECKED_IN":
        raise errors.bad_state("ERR_ENCOUNTER_BAD_CLINICAL_STATE")
    enc["clinical_status"] = "IN_PROGRESS"
    db.touch(enc)
    return response.ok(enc)


@bp.post("/encounters/<eid>/clinical-close")
@require("Provider")
def clinical_close(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    if enc["clinical_status"] != "IN_PROGRESS":
        raise errors.bad_state("ERR_ENCOUNTER_BAD_CLINICAL_STATE")
    if enc["open_biopsy_count"] != 0:
        raise errors.open_biopsy_blocks_close()
    enc["clinical_status"] = "CLINICALLY_CLOSED"
    db.touch(enc)
    # SKIN_CHECK side effects (PRD 3.2/3.3).
    if enc["visit_type"] == "SKIN_CHECK":
        patient = db.patients.get(enc["patient_id"])
        now = clock.now()
        if patient is not None:
            patient["last_skin_check_at"] = db.iso(now)
            db.touch(patient)
        due = helpers.add_months(now, services.ROUTINE_RECALL_MONTHS)
        services.spawn_recall(enc["patient_id"], "ROUTINE_SKIN_CHECK", due, biopsy_id=None)
    return response.ok(enc)


@bp.post("/encounters/<eid>/cancel")
@require("FrontDesk")
def cancel(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    if enc["clinical_status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise errors.bad_state("ERR_ENCOUNTER_BAD_CLINICAL_STATE")
    enc["clinical_status"] = "CANCELLED"
    db.touch(enc)
    return response.ok(enc)


# --- billing dimension transitions -----------------------------------------
@bp.post("/encounters/<eid>/finalize-billing")
@require("BillingSpecialist")
def finalize_billing(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    # PRD 2.8 / 3.3: state check ordering. billing_status must be BILLING_OPEN.
    if enc["billing_status"] != "BILLING_OPEN":
        raise errors.bad_state("ERR_ENCOUNTER_BAD_BILLING_STATE")
    if enc["clinical_status"] != "CLINICALLY_CLOSED":
        raise errors.bad_state("ERR_ENCOUNTER_NOT_CLINICALLY_CLOSED")
    enc["billing_status"] = "BILLING_FINALIZED"
    db.touch(enc)
    return response.ok(enc)


@bp.post("/encounters/<eid>/void-billing")
@require("BillingSpecialist")
def void_billing(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    if enc["billing_status"] != "BILLING_OPEN":
        raise errors.bad_state("ERR_ENCOUNTER_BAD_BILLING_STATE")
    if enc["clinical_status"] != "CANCELLED":
        raise errors.bad_state("ERR_ENCOUNTER_NOT_CANCELLED")
    enc["billing_status"] = "BILLING_VOID"
    db.touch(enc)
    # Cascade-void every child POSTED charge (PRD 3.8).
    children = [c for c in db.charges.values()
                if c["encounter_id"] == eid and c["status"] == "POSTED"]
    for charge in helpers.sort_created(children):
        _void_charge_compensations(charge)
        charge["status"] = "VOIDED"
        db.touch(charge)
    return response.ok(enc)


def _void_charge_compensations(charge):
    """Shared void compensations (PRD 3.8). Caller sets status + touch."""
    # Compensation A: deductible conservation (INSURANCE path).
    if charge["pay_path"] == "INSURANCE":
        patient = db.patients.get(charge["patient_id"])
        if patient is not None:
            patient["insurance_deductible_remaining_cents"] += charge["deductible_applied_cents"]
            db.touch(patient)
    # Compensation B: wallet conservation (COSMETIC_TREATMENT source).
    if charge["source_kind"] == "COSMETIC_TREATMENT" and charge.get("cosmetic_treatment_id"):
        treatment = db.cosmetic_treatments.get(charge["cosmetic_treatment_id"])
        if treatment is not None:
            membership = db.cosmetic_memberships.get(treatment["membership_id"])
            if membership is not None:
                membership["unit_balance_cents"] += treatment["redeemed_cents"]
                db.touch(membership)


@bp.get("/encounters/<eid>/cosmetic-summary")
@require("FrontDesk", "PracticeAdmin", "BillingSpecialist")
def cosmetic_summary(eid):
    enc = helpers.get_or_404(db.encounters, eid, "encounter")
    # cosmetic_total_due: re-resolve each treatment against a running wallet in
    # created_at ASC order (PRD 3.6). Treatments already carry out_of_pocket_cents
    # computed at redemption time in the same order, so the stored values are the
    # pinned-order result.
    treatments = [t for t in db.cosmetic_treatments.values() if t["encounter_id"] == eid]
    treatments = helpers.sort_created(treatments)
    total_due = sum(t["out_of_pocket_cents"] for t in treatments)
    return response.ok({
        "encounter_id": eid,
        "total_due_cents": total_due,
        "treatment_count": len(treatments),
    })

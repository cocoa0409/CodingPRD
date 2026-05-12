"""Treatment Records (PRD §3.5)."""
from __future__ import annotations

import re

from flask import Blueprint, g, request

import db
from audit import write_audit
from clock import now_iso
from errors import err
from middleware import authenticate, require_roles
from response import success_object
from services.common import bump, init_full
from validators import (
    require_str,
    _DIAGNOSIS_CODE_RE,
)

bp = Blueprint("treatment_records", __name__)


CONSULT_UNIT_PRICE_CENTS = 5_000  # 50.00 default — gives a meaningful nonzero gross


@bp.before_request
def _auth():
    authenticate()


@bp.post("/treatment-records")
def create_tr():
    require_roles("DraftingVet")
    payload = request.get_json(silent=True) or {}
    visit_id = payload.get("visit_id")
    if not isinstance(visit_id, str):
        raise err("ERR_VALIDATION_FAILED", "visit_id is required")
    notes = require_str(payload, "consultation_notes", min_len=1, max_len=4000)
    diag = require_str(payload, "diagnosis_code", min_len=1, max_len=16,
                       pattern=_DIAGNOSIS_CODE_RE)
    plan = require_str(payload, "treatment_plan", min_len=1, max_len=2000)
    consent = payload.get("consent_recorded", False)
    if not isinstance(consent, bool):
        raise err("ERR_VALIDATION_FAILED", "consent_recorded must be bool")

    with db.GLOBAL_LOCK:
        v = db.visits.get(visit_id)
        if not v:
            raise err("ERR_REFERENCE_NOT_FOUND", f"visit_id {visit_id} not found")
        if v.get("status") != "IN_CONSULT":
            raise err("ERR_INVALID_STATE", "Visit must be IN_CONSULT")
        tr = {
            "visit_id": visit_id,
            "consultation_notes": notes,
            "diagnosis_code": diag,
            "treatment_plan": plan,
            "consent_recorded": consent,
            "consent_recorded_at": now_iso() if consent else None,
            "status": "DRAFT",
        }
        init_full(tr)
        db.treatment_records[tr["id"]] = tr
        return success_object(tr_view(tr), status=201)


@bp.patch("/treatment-records/<tr_id>")
def amend_tr(tr_id):
    require_roles("DraftingVet")
    payload = request.get_json(silent=True) or {}
    with db.GLOBAL_LOCK:
        tr = db.treatment_records.get(tr_id)
        if not tr:
            raise err("ERR_NOT_FOUND", f"TreatmentRecord {tr_id} not found")
        v = db.visits.get(tr["visit_id"])
        if not v:
            raise err("ERR_NOT_FOUND", "Visit not found")
        if v.get("status") not in {"IN_CONSULT", "CONSULT_DONE"}:
            raise err("ERR_INVALID_STATE", "Visit must be IN_CONSULT or CONSULT_DONE")
        if tr.get("status") not in {"FINALIZED", "AMENDED"}:
            raise err("ERR_INVALID_STATE", "TR must be FINALIZED or AMENDED to amend")
        if v.get("assigned_vet_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Caller must equal Visit.assigned_vet_id")
        # OCC check
        ver = payload.get("version")
        if ver is None or not isinstance(ver, int):
            raise err("ERR_VALIDATION_FAILED", "version is required for amend")
        if ver != tr.get("version"):
            raise err("ERR_STALE_VERSION", "version mismatch")
        if "consultation_notes" in payload:
            n = payload["consultation_notes"]
            if not isinstance(n, str) or not (1 <= len(n) <= 4000):
                raise err("ERR_VALIDATION_FAILED", "consultation_notes invalid")
            tr["consultation_notes"] = n
        if "treatment_plan" in payload:
            p = payload["treatment_plan"]
            if not isinstance(p, str) or not (1 <= len(p) <= 2000):
                raise err("ERR_VALIDATION_FAILED", "treatment_plan invalid")
            tr["treatment_plan"] = p
        from_state = tr["status"]
        tr["status"] = "AMENDED"
        bump(tr)
        write_audit(
            subject_type="TREATMENT_RECORD",
            subject_id=tr["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="AMEND",
            from_state=from_state,
            to_state="AMENDED",
            payload={
                "consultation_notes": tr.get("consultation_notes"),
                "treatment_plan": tr.get("treatment_plan"),
            },
        )
        return success_object(tr_view(tr))


@bp.post("/treatment-records/<tr_id>/finalize")
def finalize_tr(tr_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        tr = db.treatment_records.get(tr_id)
        if not tr:
            raise err("ERR_NOT_FOUND", f"TreatmentRecord {tr_id} not found")
        v = db.visits.get(tr["visit_id"])
        if not v:
            raise err("ERR_NOT_FOUND", "Visit not found")
        if tr.get("status") != "DRAFT":
            raise err("ERR_INVALID_STATE", "TR must be DRAFT to finalize")
        if v.get("status") != "IN_CONSULT":
            raise err("ERR_INVALID_STATE", "Visit must be IN_CONSULT")
        if v.get("assigned_vet_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Caller must equal Visit.assigned_vet_id")
        if not tr.get("consent_recorded"):
            raise err("ERR_INVALID_STATE", "consent_recorded must be true")
        from_state = "DRAFT"
        tr["status"] = "FINALIZED"
        finalized_at = now_iso()
        bump(tr)
        # Cascade hop 1: append snapshot to Pet.medical_history.
        pet = db.pets.get(v.get("pet_id"))
        if pet:
            history = pet.setdefault("medical_history", [])
            history.append({
                "visit_id": v["id"],
                "diagnosis_code": tr["diagnosis_code"],
                "finalized_at": finalized_at,
            })
            bump(pet)
        # Cascade hop 2: append CONSULT line item to bill (if exists), recompute provisional.
        bill = db.bill_for_visit(v["id"])
        if bill:
            from services.bill_calc import per_line_total_cents, recompute_provisional
            qty = 1
            unit = CONSULT_UNIT_PRICE_CENTS
            line = {
                "kind": "CONSULT",
                "ref_id": tr["id"],
                "qty": qty,
                "unit_price_cents": unit,
                "line_total_cents": per_line_total_cents(qty, unit),
            }
            bill.setdefault("line_items", []).append(line)
            recompute_provisional(bill)
            bump(bill)
        # Audit log entry.
        write_audit(
            subject_type="TREATMENT_RECORD",
            subject_id=tr["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="FINALIZE",
            from_state=from_state,
            to_state="FINALIZED",
            payload={
                "visit_id": v["id"],
                "diagnosis_code": tr["diagnosis_code"],
                "finalized_at": finalized_at,
            },
        )
        return success_object(tr_view(tr))


def tr_view(tr):
    return {
        "id": tr["id"],
        "visit_id": tr["visit_id"],
        "consultation_notes": tr["consultation_notes"],
        "diagnosis_code": tr["diagnosis_code"],
        "treatment_plan": tr["treatment_plan"],
        "consent_recorded": tr["consent_recorded"],
        "consent_recorded_at": tr.get("consent_recorded_at"),
        "status": tr["status"],
        "created_at": tr["created_at"],
        "updated_at": tr["updated_at"],
        "version": tr["version"],
    }

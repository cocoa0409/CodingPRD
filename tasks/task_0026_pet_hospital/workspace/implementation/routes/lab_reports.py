"""Lab Reports (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from clock import now_iso
from errors import err
from middleware import authenticate, require_roles
from response import success_object
from services.common import bump, init_full
from validators import (
    parse_iso8601,
    require_str,
    _EXT_LAB_REF_RE,
)

bp = Blueprint("lab_reports", __name__)

LAB_UNIT_PRICE_CENTS = 3_000  # 30.00 default per LAB line item


@bp.before_request
def _auth():
    authenticate()


@bp.post("/lab-reports")
def create_lab_report():
    require_roles("DraftingVet")
    payload = request.get_json(silent=True) or {}
    visit_id = payload.get("visit_id")
    if not isinstance(visit_id, str):
        raise err("ERR_VALIDATION_FAILED", "visit_id is required")
    test_items = payload.get("test_items")
    if not isinstance(test_items, list) or not (0 <= len(test_items) <= 50):
        raise err("ERR_LAB_ITEMS_INVALID", "test_items must be a list of 1..50 items")
    if len(test_items) == 0:
        raise err("ERR_LAB_ITEMS_INVALID", "test_items must not be empty")
    if len(test_items) > 50:
        raise err("ERR_LAB_ITEMS_INVALID", "test_items exceeds 50")
    seen_codes = set()
    for it in test_items:
        if not isinstance(it, dict):
            raise err("ERR_LAB_ITEMS_INVALID", "test_items entries must be objects")
        code = it.get("code")
        name = it.get("name")
        ref_low = it.get("ref_low")
        ref_high = it.get("ref_high")
        if not isinstance(code, str) or not code:
            raise err("ERR_LAB_ITEMS_INVALID", "test_items[].code missing")
        if code in seen_codes:
            raise err("ERR_LAB_ITEMS_INVALID", "duplicate code in test_items")
        seen_codes.add(code)
        if not isinstance(name, str) or not name:
            raise err("ERR_LAB_ITEMS_INVALID", "test_items[].name missing")
        if isinstance(ref_low, bool) or not isinstance(ref_low, (int, float)):
            raise err("ERR_LAB_ITEMS_INVALID", "ref_low must be a number")
        if isinstance(ref_high, bool) or not isinstance(ref_high, (int, float)):
            raise err("ERR_LAB_ITEMS_INVALID", "ref_high must be a number")
        if float(ref_low) < 0:
            raise err("ERR_LAB_ITEMS_INVALID", "ref_low must be >= 0")
        if float(ref_low) >= float(ref_high):
            raise err("ERR_LAB_ITEMS_INVALID", "ref_low must be < ref_high")

    with db.GLOBAL_LOCK:
        v = db.visits.get(visit_id)
        if not v:
            raise err("ERR_REFERENCE_NOT_FOUND", f"visit_id {visit_id} not found")
        if v.get("status") not in {"IN_CONSULT", "CONSULT_DONE"}:
            raise err("ERR_INVALID_STATE", "Visit must be IN_CONSULT or CONSULT_DONE")
        if v.get("assigned_vet_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Caller must equal Visit.assigned_vet_id")
        lr = {
            "visit_id": visit_id,
            "test_items": [dict(it) for it in test_items],
            "sample_collected_at": None,
            "external_lab_ref": None,
            "results": [],
            "abnormal_codes": [],
            "status": "ORDERED",
        }
        init_full(lr)
        db.lab_reports[lr["id"]] = lr
        return success_object(lr_view(lr), status=201)


@bp.post("/lab-reports/<lr_id>/collect-sample")
def collect_sample(lr_id):
    require_roles("TriageNurse")
    payload = request.get_json(silent=True) or {}
    s_at = payload.get("sample_collected_at")
    if not isinstance(s_at, str):
        raise err("ERR_VALIDATION_FAILED", "sample_collected_at is required")
    parse_iso8601(s_at)
    with db.GLOBAL_LOCK:
        lr = db.lab_reports.get(lr_id)
        if not lr:
            raise err("ERR_NOT_FOUND", f"LabReport {lr_id} not found")
        if lr["status"] != "ORDERED":
            raise err("ERR_INVALID_STATE", "Must be ORDERED")
        lr["sample_collected_at"] = s_at
        lr["status"] = "SAMPLE_COLLECTED"
        bump(lr)
        return success_object(lr_view(lr))


@bp.post("/lab-reports/<lr_id>/send-to-lab")
def send_to_lab(lr_id):
    require_roles("TriageNurse")
    payload = request.get_json(silent=True) or {}
    ref = payload.get("external_lab_ref")
    if not isinstance(ref, str) or not _EXT_LAB_REF_RE.match(ref):
        raise err("ERR_VALIDATION_FAILED", "external_lab_ref invalid")
    with db.GLOBAL_LOCK:
        lr = db.lab_reports.get(lr_id)
        if not lr:
            raise err("ERR_NOT_FOUND", f"LabReport {lr_id} not found")
        if lr["status"] != "SAMPLE_COLLECTED":
            raise err("ERR_INVALID_STATE", "Must be SAMPLE_COLLECTED")
        lr["external_lab_ref"] = ref
        lr["status"] = "SENT_TO_LAB"
        bump(lr)
        # Track the ref → lr mapping for the external-lab-result event.
        return success_object(lr_view(lr))


@bp.post("/lab-reports/<lr_id>/finalize")
def finalize_lab_report(lr_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        lr = db.lab_reports.get(lr_id)
        if not lr:
            raise err("ERR_NOT_FOUND", f"LabReport {lr_id} not found")
        if lr["status"] != "RESULT_RECEIVED":
            raise err("ERR_INVALID_STATE", "Must be RESULT_RECEIVED to finalize")
        v = db.visits.get(lr["visit_id"])
        if not v:
            raise err("ERR_NOT_FOUND", "Visit not found")
        if v.get("status") not in {"IN_CONSULT", "CONSULT_DONE"}:
            raise err("ERR_INVALID_STATE", "Visit must be IN_CONSULT or CONSULT_DONE")
        if v.get("assigned_vet_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Caller must equal Visit.assigned_vet_id")
        lr["status"] = "FINALIZED"
        bump(lr)
        # Append LAB line item to bill if it exists.
        bill = db.bill_for_visit(v["id"])
        if bill:
            from services.bill_calc import per_line_total_cents, recompute_provisional
            qty = max(1, len(lr.get("test_items", [])))
            unit = LAB_UNIT_PRICE_CENTS
            line = {
                "kind": "LAB",
                "ref_id": lr["id"],
                "qty": qty,
                "unit_price_cents": unit,
                "line_total_cents": per_line_total_cents(qty, unit),
            }
            bill.setdefault("line_items", []).append(line)
            recompute_provisional(bill)
            bump(bill)
        return success_object(lr_view(lr))


@bp.get("/lab-reports/<lr_id>/history")
def lab_history(lr_id):
    require_roles("DraftingVet", "OwnerService")
    with db.GLOBAL_LOCK:
        lr = db.lab_reports.get(lr_id)
        if not lr:
            raise err("ERR_NOT_FOUND", f"LabReport {lr_id} not found")
        v = db.visits.get(lr["visit_id"])
        pet_id = v.get("pet_id") if v else None
        # Find prior FINALIZED lab report for the same pet.
        prior = None
        if pet_id:
            candidates = []
            for other in db.lab_reports.values():
                if other["id"] == lr_id:
                    continue
                if other.get("status") != "FINALIZED":
                    continue
                ov = db.visits.get(other.get("visit_id"))
                if ov and ov.get("pet_id") == pet_id:
                    candidates.append(other)
            candidates.sort(key=lambda x: x.get("created_at", ""))
            if candidates:
                prior = candidates[-1]
        return success_object({
            "current": lr_view(lr),
            "previous": lr_view(prior) if prior else None,
        })


@bp.post("/lab-reports/<lr_id>/cancel")
def cancel_lab_report(lr_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        lr = db.lab_reports.get(lr_id)
        if not lr:
            raise err("ERR_NOT_FOUND", f"LabReport {lr_id} not found")
        if lr["status"] not in {"ORDERED", "SAMPLE_COLLECTED"}:
            raise err("ERR_INVALID_STATE", "Cancel allowed only from ORDERED/SAMPLE_COLLECTED")
        lr["status"] = "CANCELLED"
        bump(lr)
        return success_object(lr_view(lr))


def lr_view(lr):
    if not lr:
        return None
    return {
        "id": lr["id"],
        "visit_id": lr["visit_id"],
        "test_items": list(lr.get("test_items", [])),
        "sample_collected_at": lr.get("sample_collected_at"),
        "external_lab_ref": lr.get("external_lab_ref"),
        "results": list(lr.get("results", [])),
        "abnormal_codes": list(lr.get("abnormal_codes", [])),
        "status": lr["status"],
        "created_at": lr["created_at"],
        "updated_at": lr["updated_at"],
        "version": lr["version"],
    }

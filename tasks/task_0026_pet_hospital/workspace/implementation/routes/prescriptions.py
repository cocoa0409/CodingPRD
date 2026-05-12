"""Prescriptions (PRD §3.7)."""
from __future__ import annotations

import math
from typing import Any, Dict, List

from flask import Blueprint, g, request

import db
from audit import write_audit
from clock import now_iso
from errors import err
from middleware import authenticate, require_roles
from response import success_object
from services.common import bump, init_full
from validators import require_str

bp = Blueprint("prescriptions", __name__)

DRUG_UNIT_PRICE_CENTS = 100  # 1.00 per unit


SEVERITY_RANK = {None: 0, "NONE": 0, "MILD": 1, "MODERATE": 2, "SEVERE": 3}
RANK_TO_SEVERITY = {0: "NONE", 1: "MILD", 2: "MODERATE", 3: "SEVERE"}


@bp.before_request
def _auth():
    authenticate()


@bp.post("/prescriptions")
def create_rx():
    require_roles("DraftingVet")
    payload = request.get_json(silent=True) or {}
    visit_id = payload.get("visit_id")
    if not isinstance(visit_id, str):
        raise err("ERR_VALIDATION_FAILED", "visit_id is required")
    items = payload.get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= 20):
        raise err("ERR_VALIDATION_FAILED", "items must be a list of 1..20")
    for it in items:
        _validate_item_shape(it)

    with db.GLOBAL_LOCK:
        v = db.visits.get(visit_id)
        if not v:
            raise err("ERR_REFERENCE_NOT_FOUND", f"visit_id {visit_id} not found")
        # Validate every drug exists by code.
        for it in items:
            if not db.drug_by_code(it["drug_code"]):
                raise err(
                    "ERR_REFERENCE_NOT_FOUND",
                    f"drug_code {it['drug_code']} not found",
                )
        rx = {
            "visit_id": visit_id,
            "drafting_vet_id": g.user_id,
            "reviewing_vet_id": None,
            "items": [dict(i) for i in items],
            "interaction_risk": "NONE",
            "status": "DRAFT",
            "rejection_reason": None,
            "dispensed_at": None,
        }
        init_full(rx)
        db.prescriptions[rx["id"]] = rx
        return success_object(rx_view(rx), status=201)


@bp.post("/prescriptions/<rx_id>/submit")
def submit_rx(rx_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        rx = db.prescriptions.get(rx_id)
        if not rx:
            raise err("ERR_NOT_FOUND", f"Prescription {rx_id} not found")
        if rx["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Submit requires DRAFT")
        v = db.visits.get(rx["visit_id"])
        if not v:
            raise err("ERR_NOT_FOUND", "Visit not found")
        if v.get("status") != "IN_CONSULT":
            raise err("ERR_INVALID_STATE", "Visit must be IN_CONSULT to submit")
        if rx.get("drafting_vet_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Caller must equal drafting_vet_id")
        # Owner contact verification.
        pet = db.pets.get(v.get("pet_id")) or {}
        owner = db.owners.get(pet.get("owner_id")) or {}
        if not owner.get("contact_verified"):
            raise err(
                "ERR_OWNER_NOT_VERIFIED",
                "Owner must be verified to submit prescription",
            )
        # Dosage rationality / range check.
        _validate_dosage(rx, pet)
        # Compute interaction risk.
        rx["interaction_risk"] = _compute_interaction_risk(rx["items"])
        from_state = "DRAFT"
        rx["status"] = "PENDING_REVIEW"
        bump(rx)
        write_audit(
            subject_type="PRESCRIPTION",
            subject_id=rx["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="SUBMIT",
            from_state=from_state,
            to_state="PENDING_REVIEW",
            payload={"items": rx["items"], "interaction_risk": rx["interaction_risk"]},
        )
        return success_object(rx_view(rx))


@bp.post("/prescriptions/<rx_id>/approve")
def approve_rx(rx_id):
    require_roles("ReviewingVet")
    payload = request.get_json(silent=True) or {}
    with db.GLOBAL_LOCK:
        rx = db.prescriptions.get(rx_id)
        if not rx:
            raise err("ERR_NOT_FOUND", f"Prescription {rx_id} not found")
        if rx["status"] != "PENDING_REVIEW":
            # Distinguish: if rx already moved past PENDING_REVIEW into a
            # reviewed state by another concurrent approve, surface
            # ERR_PRESCRIPTION_ALREADY_REVIEWED. Otherwise generic state.
            if rx["status"] in {"APPROVED", "REJECTED"}:
                raise err(
                    "ERR_PRESCRIPTION_ALREADY_REVIEWED",
                    "Prescription has already been reviewed",
                )
            raise err("ERR_INVALID_STATE", "Approve requires PENDING_REVIEW")
        v = db.visits.get(rx["visit_id"]) or {}
        pet = db.pets.get(v.get("pet_id")) or {}
        # Segregation of duties for controlled drugs.
        if any(_drug_is_controlled(it["drug_code"]) for it in rx["items"]):
            if g.user_id == rx.get("drafting_vet_id"):
                raise err(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "Reviewing vet must differ from drafting vet for controlled drugs",
                )
        # Severe interaction guard.
        if rx.get("interaction_risk") == "SEVERE":
            if not bool(payload.get("override_acknowledged")):
                raise err(
                    "ERR_SEVERE_INTERACTION",
                    "SEVERE interaction requires override_acknowledged=true",
                )
        # Dosage rationality check (range only, since units may have been chosen at draft).
        _validate_dosage_range(rx)
        from_state = "PENDING_REVIEW"
        rx["status"] = "APPROVED"
        rx["reviewing_vet_id"] = g.user_id
        bump(rx)
        write_audit(
            subject_type="PRESCRIPTION",
            subject_id=rx["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="APPROVE",
            from_state=from_state,
            to_state="APPROVED",
            payload={"items": rx["items"]},
        )
        return success_object(rx_view(rx))


@bp.post("/prescriptions/<rx_id>/reject")
def reject_rx(rx_id):
    require_roles("ReviewingVet")
    payload = request.get_json(silent=True) or {}
    reason = payload.get("rejection_reason")
    if not isinstance(reason, str) or not (1 <= len(reason) <= 500):
        raise err("ERR_VALIDATION_FAILED", "rejection_reason 1..500 chars required")
    with db.GLOBAL_LOCK:
        rx = db.prescriptions.get(rx_id)
        if not rx:
            raise err("ERR_NOT_FOUND", f"Prescription {rx_id} not found")
        if rx["status"] != "PENDING_REVIEW":
            raise err("ERR_INVALID_STATE", "Reject requires PENDING_REVIEW")
        from_state = "PENDING_REVIEW"
        rx["status"] = "REJECTED"
        rx["reviewing_vet_id"] = g.user_id
        rx["rejection_reason"] = reason
        bump(rx)
        write_audit(
            subject_type="PRESCRIPTION",
            subject_id=rx["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="REJECT",
            from_state=from_state,
            to_state="REJECTED",
            payload={"rejection_reason": reason},
        )
        return success_object(rx_view(rx))


@bp.post("/prescriptions/<rx_id>/redraft")
def redraft_rx(rx_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        rx = db.prescriptions.get(rx_id)
        if not rx:
            raise err("ERR_NOT_FOUND", f"Prescription {rx_id} not found")
        if rx["status"] != "REJECTED":
            raise err("ERR_INVALID_STATE", "Redraft requires REJECTED")
        if rx.get("drafting_vet_id") != g.user_id:
            raise err("ERR_FORBIDDEN", "Caller must equal drafting_vet_id")
        rx["status"] = "DRAFT"
        rx["reviewing_vet_id"] = None
        rx["rejection_reason"] = None
        bump(rx)
        return success_object(rx_view(rx))


@bp.post("/prescriptions/<rx_id>/dispense")
def dispense_rx(rx_id):
    require_roles("Pharmacist")
    with db.GLOBAL_LOCK:
        rx = db.prescriptions.get(rx_id)
        if not rx:
            raise err("ERR_NOT_FOUND", f"Prescription {rx_id} not found")
        if rx["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "Dispense requires APPROVED")
        v = db.visits.get(rx["visit_id"])
        if not v:
            raise err("ERR_NOT_FOUND", "Visit not found")
        if v.get("status") not in {"IN_CONSULT", "CONSULT_DONE", "HOSPITALIZED"}:
            raise err("ERR_INVALID_STATE", "Visit state forbids dispense")
        # Stock check.
        drug_lookup = {}
        for it in rx["items"]:
            d = db.drug_by_code(it["drug_code"])
            if not d:
                raise err("ERR_REFERENCE_NOT_FOUND", "drug_code not found")
            if int(it["units"]) > int(d.get("stock_units", 0)):
                raise err("ERR_INVALID_STATE", "Insufficient drug stock")
            drug_lookup[it["drug_code"]] = d
        # Decrement stock.
        for it in rx["items"]:
            d = drug_lookup[it["drug_code"]]
            d["stock_units"] = int(d["stock_units"]) - int(it["units"])
            bump(d)
        from_state = "APPROVED"
        rx["status"] = "DISPENSED"
        rx["dispensed_at"] = now_iso()
        bump(rx)
        # Cascade: append DRUG line item to bill, recompute, possibly revert ISSUED→DRAFT.
        bill = db.bill_for_visit(v["id"])
        if bill:
            from services.bill_calc import per_line_total_cents, recompute_provisional
            for it in rx["items"]:
                qty = int(it["units"])
                unit = DRUG_UNIT_PRICE_CENTS
                line = {
                    "kind": "DRUG",
                    "ref_id": rx["id"],
                    "qty": qty,
                    "unit_price_cents": unit,
                    "line_total_cents": per_line_total_cents(qty, unit),
                }
                bill.setdefault("line_items", []).append(line)
            recompute_provisional(bill)
            # If ISSUED, revert to DRAFT (cascade hop 2).
            if bill.get("status") == "ISSUED":
                bill["status"] = "DRAFT"
            bump(bill)
        write_audit(
            subject_type="PRESCRIPTION",
            subject_id=rx["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="DISPENSE",
            from_state=from_state,
            to_state="DISPENSED",
            payload={"items": rx["items"]},
        )
        return success_object(rx_view(rx))


@bp.post("/prescriptions/<rx_id>/cancel")
def cancel_rx(rx_id):
    require_roles("DraftingVet")
    with db.GLOBAL_LOCK:
        rx = db.prescriptions.get(rx_id)
        if not rx:
            raise err("ERR_NOT_FOUND", f"Prescription {rx_id} not found")
        if rx["status"] not in {"DRAFT", "PENDING_REVIEW"}:
            raise err("ERR_INVALID_STATE", "Cancel allowed only from DRAFT/PENDING_REVIEW")
        from_state = rx["status"]
        rx["status"] = "CANCELLED"
        bump(rx)
        write_audit(
            subject_type="PRESCRIPTION",
            subject_id=rx["id"],
            actor_role=g.user_role,
            actor_id=g.user_id,
            action="CANCEL",
            from_state=from_state,
            to_state="CANCELLED",
            payload={},
        )
        return success_object(rx_view(rx))


# ----------------------------------------------------------------------
def _validate_item_shape(it):
    if not isinstance(it, dict):
        raise err("ERR_VALIDATION_FAILED", "items[] must be objects")
    code = it.get("drug_code")
    if not isinstance(code, str) or not code:
        raise err("ERR_VALIDATION_FAILED", "drug_code required")
    dose = it.get("dose_mg_per_kg")
    if isinstance(dose, bool) or not isinstance(dose, (int, float)) or float(dose) <= 0:
        raise err("ERR_VALIDATION_FAILED", "dose_mg_per_kg must be > 0")
    fpd = it.get("frequency_per_day")
    if isinstance(fpd, bool) or not isinstance(fpd, int) or fpd <= 0:
        raise err("ERR_VALIDATION_FAILED", "frequency_per_day must be a positive int")
    dd = it.get("duration_days")
    if isinstance(dd, bool) or not isinstance(dd, int) or dd <= 0:
        raise err("ERR_VALIDATION_FAILED", "duration_days must be a positive int")
    units = it.get("units")
    if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
        raise err("ERR_VALIDATION_FAILED", "units must be a positive int")


def _drug_is_controlled(code: str) -> bool:
    d = db.drug_by_code(code)
    return bool(d and d.get("controlled"))


def _validate_dosage(rx, pet):
    """Range + units==ceil(dose*weight*freq*duration)."""
    weight = float(pet.get("weight_kg") or 0)
    for it in rx["items"]:
        d = db.drug_by_code(it["drug_code"])
        if not d:
            raise err("ERR_REFERENCE_NOT_FOUND", f"drug not found: {it['drug_code']}")
        dose = float(it["dose_mg_per_kg"])
        if dose < float(d["dosage_min_mg_per_kg"]) or dose > float(d["dosage_max_mg_per_kg"]):
            raise err("ERR_DOSAGE_OUT_OF_RANGE", "dose outside drug's range")
        expected = math.ceil(dose * weight * int(it["frequency_per_day"]) * int(it["duration_days"]))
        if int(it["units"]) != expected:
            raise err("ERR_VALIDATION_FAILED", "units != ceil(dose*weight*freq*duration)")


def _validate_dosage_range(rx):
    for it in rx["items"]:
        d = db.drug_by_code(it["drug_code"])
        if not d:
            raise err("ERR_REFERENCE_NOT_FOUND", "drug not found")
        dose = float(it["dose_mg_per_kg"])
        if dose < float(d["dosage_min_mg_per_kg"]) or dose > float(d["dosage_max_mg_per_kg"]):
            raise err("ERR_DOSAGE_OUT_OF_RANGE", "dose outside drug's range")


def _compute_interaction_risk(items):
    best = 0
    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            d_i = db.drug_by_code(items[i]["drug_code"]) or {}
            d_j = db.drug_by_code(items[j]["drug_code"]) or {}
            for ix in d_i.get("interactions", []) or []:
                if ix.get("with_drug_code") == d_j.get("code"):
                    rank = SEVERITY_RANK.get(ix.get("severity"), 0)
                    if rank > best:
                        best = rank
            for ix in d_j.get("interactions", []) or []:
                if ix.get("with_drug_code") == d_i.get("code"):
                    rank = SEVERITY_RANK.get(ix.get("severity"), 0)
                    if rank > best:
                        best = rank
    return RANK_TO_SEVERITY[best]


def rx_view(rx):
    return {
        "id": rx["id"],
        "visit_id": rx["visit_id"],
        "drafting_vet_id": rx["drafting_vet_id"],
        "reviewing_vet_id": rx.get("reviewing_vet_id"),
        "items": list(rx.get("items", [])),
        "interaction_risk": rx.get("interaction_risk", "NONE"),
        "status": rx["status"],
        "rejection_reason": rx.get("rejection_reason"),
        "dispensed_at": rx.get("dispensed_at"),
        "created_at": rx["created_at"],
        "updated_at": rx["updated_at"],
        "version": rx["version"],
    }

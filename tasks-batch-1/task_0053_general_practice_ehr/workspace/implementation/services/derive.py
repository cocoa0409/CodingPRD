"""Derived-field recomputation and entity serialization.

Derived fields are never written by clients — always recomputed from source rows
(PRD §2.5). When a recompute changes an owning resource, that resource is mutated
(updated_at advances, version increments) per PRD §2.4/§2.5.
"""
from __future__ import annotations

from typing import Any, Dict, List

import db
from db import touch
from services import calc

CONTROLLED_SCHEDULES = {"C_II", "C_III", "C_IV", "C_V"}
CONTROLLED_LIVE_STATUSES = {"SIGNED", "TRANSMITTED", "DISPENSED"}


# ---------------------------------------------------------------------------
# Provider derived fields
# ---------------------------------------------------------------------------

def compute_provider_panel_size(provider_id: str) -> int:
    return sum(
        1 for p in db.patients.values()
        if p.get("pcp_id") == provider_id and p.get("status") == "ACTIVE"
    )


def compute_provider_controlled_rx_count(provider_id: str) -> int:
    return sum(
        1 for rx in db.prescriptions.values()
        if rx.get("provider_id") == provider_id
        and rx.get("schedule") in CONTROLLED_SCHEDULES
        and rx.get("status") in CONTROLLED_LIVE_STATUSES
    )


def recompute_provider_panel_size(provider: Dict[str, Any], *, bump: bool = False) -> None:
    new_val = compute_provider_panel_size(provider["id"])
    changed = provider.get("panel_size") != new_val
    provider["panel_size"] = new_val
    if bump and changed:
        touch(provider)


def recompute_provider_controlled_rx_count(provider: Dict[str, Any]) -> None:
    provider["controlled_rx_count"] = compute_provider_controlled_rx_count(provider["id"])


# ---------------------------------------------------------------------------
# Patient derived fields
# ---------------------------------------------------------------------------

def compute_patient_lifetime_charges(patient_id: str) -> int:
    return sum(
        int(v.get("billed_total_cents", 0))
        for v in db.visits.values()
        if v.get("patient_id") == patient_id and v.get("status") == "FINALIZED"
    )


def compute_patient_active_medication_count(patient_id: str) -> int:
    return sum(
        1 for rx in db.prescriptions.values()
        if rx.get("patient_id") == patient_id and rx.get("status") == "DISPENSED"
    )


def compute_patient_open_care_gaps(patient_id: str) -> int:
    return sum(
        1 for m in db.hedis_measures.values()
        if m.get("patient_id") == patient_id
        and m.get("status") == "GAP"
        and m.get("measurement_year") == calc.CURRENT_MEASUREMENT_YEAR
        and m.get("eligible") is True
    )


def recompute_patient_ledger(patient: Dict[str, Any]) -> None:
    """Recompute lifetime charges and outstanding balance from source rows."""
    lifetime = compute_patient_lifetime_charges(patient["id"])
    payments = db.patient_payments.get(patient["id"], 0)
    patient["lifetime_charges_cents"] = lifetime
    patient["outstanding_balance_cents"] = lifetime - payments


def recompute_patient_active_medication_count(patient: Dict[str, Any]) -> None:
    patient["active_medication_count"] = compute_patient_active_medication_count(patient["id"])


def recompute_patient_open_care_gaps(patient: Dict[str, Any]) -> None:
    patient["open_care_gaps"] = compute_patient_open_care_gaps(patient["id"])


# ---------------------------------------------------------------------------
# Serialization — derived/read fields refreshed lazily on read
# ---------------------------------------------------------------------------

def serialize_provider(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "npi": p["npi"],
        "full_name": p["full_name"],
        "specialty": p["specialty"],
        "dea_number": p["dea_number"],
        "epcs_enrolled": p["epcs_enrolled"],
        "panel_capacity": p["panel_capacity"],
        "status": p["status"],
        "panel_size": compute_provider_panel_size(p["id"]),
        "controlled_rx_count": compute_provider_controlled_rx_count(p["id"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_patient(p: Dict[str, Any]) -> Dict[str, Any]:
    lifetime = compute_patient_lifetime_charges(p["id"])
    payments = db.patient_payments.get(p["id"], 0)
    return {
        "id": p["id"],
        "first_name": p["first_name"],
        "last_name": p["last_name"],
        "date_of_birth": p["date_of_birth"],
        "sex": p["sex"],
        "pcp_id": p["pcp_id"],
        "status": p["status"],
        "lifetime_charges_cents": lifetime,
        "outstanding_balance_cents": lifetime - payments,
        "active_medication_count": compute_patient_active_medication_count(p["id"]),
        "open_care_gaps": compute_patient_open_care_gaps(p["id"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_cpt_code(c: Dict[str, Any]) -> Dict[str, Any]:
    # CptCode carries only id and created_at (no updated_at / version) — PRD §2.4.
    return {
        "id": c["id"],
        "code": c["code"],
        "short_description": c["short_description"],
        "category": c["category"],
        "base_fee_cents": c["base_fee_cents"],
        "requires_em_level": c["requires_em_level"],
        "created_at": c["created_at"],
    }


def serialize_visit(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": v["id"],
        "patient_id": v["patient_id"],
        "provider_id": v["provider_id"],
        "visit_type": v["visit_type"],
        "scheduled_start": v["scheduled_start"],
        "scheduled_end": v["scheduled_end"],
        "vaccine_code": v["vaccine_code"],
        "status": v["status"],
        "billed_total_cents": v["billed_total_cents"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_charge_line(cl: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": cl["id"],
        "visit_id": cl["visit_id"],
        "cpt_code": cl["cpt_code"],
        "units": cl["units"],
        "em_level": cl["em_level"],
        "amount_cents": cl["amount_cents"],
        "created_at": cl["created_at"],
        "updated_at": cl["updated_at"],
        "version": cl["version"],
    }


def serialize_prescription(rx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": rx["id"],
        "patient_id": rx["patient_id"],
        "provider_id": rx["provider_id"],
        "visit_id": rx["visit_id"],
        "drug_name": rx["drug_name"],
        "schedule": rx["schedule"],
        "two_factor_token": rx["two_factor_token"],
        "status": rx["status"],
        "created_at": rx["created_at"],
        "updated_at": rx["updated_at"],
        "version": rx["version"],
    }


def serialize_referral(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "patient_id": r["patient_id"],
        "referring_provider_id": r["referring_provider_id"],
        "target_specialty": r["target_specialty"],
        "priority": r["priority"],
        "status": r["status"],
        "authorization_expires_at": r["authorization_expires_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_portal_account(pa: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": pa["id"],
        "patient_id": pa["patient_id"],
        "login_email": pa["login_email"],
        "status": pa["status"],
        "activation_token": pa["activation_token"],
        "failed_login_count": pa["failed_login_count"],
        "created_at": pa["created_at"],
        "updated_at": pa["updated_at"],
        "version": pa["version"],
    }


def serialize_hedis_measure(m: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": m["id"],
        "patient_id": m["patient_id"],
        "measure_type": m["measure_type"],
        "measurement_year": m["measurement_year"],
        "method": m["method"],
        "eligible": m["eligible"],
        "status": m["status"],
        "chart_confirmed": m["chart_confirmed"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }

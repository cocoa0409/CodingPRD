"""In-memory data store with global lock for atomicity.

All entities live as dicts keyed by id. We hold a single global mutex
to serialize requests — necessary for race-condition tests (concurrent
approve / dispense / capacity etc.) which expect first-writer-wins.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List


GLOBAL_LOCK = threading.RLock()


def new_uuid() -> str:
    return str(uuid.uuid4())


# Top-level tables.
owners: Dict[str, Dict[str, Any]] = {}
pets: Dict[str, Dict[str, Any]] = {}
visits: Dict[str, Dict[str, Any]] = {}
treatment_records: Dict[str, Dict[str, Any]] = {}
lab_reports: Dict[str, Dict[str, Any]] = {}
drugs: Dict[str, Dict[str, Any]] = {}
prescriptions: Dict[str, Dict[str, Any]] = {}
cages: Dict[str, Dict[str, Any]] = {}
hospitalizations: Dict[str, Dict[str, Any]] = {}
bills: Dict[str, Dict[str, Any]] = {}
vaccine_schedules: Dict[str, Dict[str, Any]] = {}
vaccination_records: Dict[str, Dict[str, Any]] = {}

# Append-only event logs.
audit_logs: List[Dict[str, Any]] = []
im_emissions: List[Dict[str, Any]] = []

# Idempotency keys per event class — value is the first-arrival response payload.
processed_payment_event_ids: set = set()
processed_refund_event_ids: set = set()
processed_recall_event_ids: set = set()
processed_lab_refs: Dict[str, str] = {}  # external_lab_ref → lab_report_id

# Recalled (batch_id, vaccine_code) pairs (also recalled batch_id alone for any vaccine).
recalled_batches: set = set()  # set of batch_id strings (recalled — blocks new doses)

# Invoice number sequence — per-day counter.
invoice_seq_per_day: Dict[str, int] = {}


# Indexes ----------------------------------------------------------------
def owner_by_phone(phone: str):
    for o in owners.values():
        if o.get("phone_e164") == phone:
            return o
    return None


def owner_by_email(email: str):
    target = email.lower()
    for o in owners.values():
        if (o.get("email") or "").lower() == target:
            return o
    return None


def cage_by_code(code: str):
    for c in cages.values():
        if c.get("cage_code") == code:
            return c
    return None


def drug_by_code(code: str):
    for d in drugs.values():
        if d.get("code") == code:
            return d
    return None


def schedule_by_species_and_vaccine(species: str, vaccine_code: str):
    for s in vaccine_schedules.values():
        if s.get("species") == species and s.get("vaccine_code") == vaccine_code:
            return s
    return None


def schedule_unique(species: str, vaccine_code: str, age_min_days: int):
    for s in vaccine_schedules.values():
        if (
            s.get("species") == species
            and s.get("vaccine_code") == vaccine_code
            and s.get("age_min_days") == age_min_days
        ):
            return s
    return None


def lab_report_by_external_ref(ref: str):
    for lr in lab_reports.values():
        if lr.get("external_lab_ref") == ref:
            return lr
    return None


def visits_for_pet(pet_id: str):
    return [v for v in visits.values() if v.get("pet_id") == pet_id]


def treatment_records_for_visit(visit_id: str):
    return [tr for tr in treatment_records.values() if tr.get("visit_id") == visit_id]


def lab_reports_for_visit(visit_id: str):
    return [lr for lr in lab_reports.values() if lr.get("visit_id") == visit_id]


def prescriptions_for_visit(visit_id: str):
    return [rx for rx in prescriptions.values() if rx.get("visit_id") == visit_id]


def hospitalizations_for_visit(visit_id: str):
    return [h for h in hospitalizations.values() if h.get("visit_id") == visit_id]


def bill_for_visit(visit_id: str):
    for b in bills.values():
        if b.get("visit_id") == visit_id:
            return b
    return None


def vaccinations_for_pet(pet_id: str):
    return [v for v in vaccination_records.values() if v.get("pet_id") == pet_id]

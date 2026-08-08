"""Conserved ledgers, the authority selector and the four declared cascades
(PRD 2.9, 2.10, 3.2, 3.4).

Ledgers are maintained as exact aggregates of the rows they summarise, which is
what makes an operation and its compensating reversal return every counter to
precisely its prior value.
"""

from decimal import Decimal

import calc
import config
from ladder import touch
from store import store

ZERO_MME = Decimal("0.0")


# ------------------------------------------------------------------- lookups
def rows_for_patient(table, patient_id):
    return [r for r in table.values() if r.get("patient_id") == patient_id]


def patient_of(row):
    return store.patients.get(row.get("patient_id"))


def _set(row, key, value):
    if row.get(key) != value:
        row[key] = value
        touch(row)
        return True
    return False


# ------------------------------------------------------------------- ledgers
def recompute_active_daily_mme(patient):
    total = ZERO_MME
    for order in rows_for_patient(store.medication_orders, patient["id"]):
        if order["status"] == "ACTIVE":
            total += order["mme_daily"]
    _set(patient, "active_daily_mme", total)


def recompute_breakthrough(patient):
    """PRD 3.8 — round per order first, sum, take 15% of the sum, convert once."""
    active = [o for o in rows_for_patient(store.medication_orders, patient["id"])
              if o["status"] == "ACTIVE"]
    values = [o["mme_daily"] for o in active]
    for order in active:
        if order["breakthrough_drug"] is None:
            continue
        dose = calc.breakthrough_dose_mg(values, order["breakthrough_drug"])
        _set(order, "breakthrough_dose_mg", dose)


def recompute_open_symptom_count(patient):
    count = 0
    for row in rows_for_patient(store.symptom_assessments, patient["id"]):
        if row["triage_status"] in ("OPEN", "ACKNOWLEDGED"):
            count += 1
    _set(patient, "open_symptom_count", count)


def recompute_claim_ledgers(patient):
    minutes_total = 0
    paid_cents = 0
    for claim in rows_for_patient(store.claims, patient["id"]):
        if claim["status"] in ("SUBMITTED", "PAID"):
            minutes_total += claim["documented_minutes"]
        if claim["status"] == "PAID":
            paid_cents += claim["net_payable_cents"]
    _set(patient, "acp_minutes_claimed", minutes_total)
    _set(patient, "acp_paid_cents_ytd", paid_cents)


def recompute_inventory(item):
    """Conserved: total_units == available + reserved + delivered, always."""
    reserved = 0
    delivered = 0
    for order in store.dme_orders.values():
        if order["inventory_item_id"] != item["id"]:
            continue
        if order["status"] in ("REQUESTED", "PENDING_AUTH", "SCHEDULED"):
            reserved += order["quantity"]
        elif order["status"] == "DELIVERED":
            delivered += order["quantity"]
    changed = False
    changed |= item["reserved_units"] != reserved
    changed |= item["delivered_units"] != delivered
    available = item["total_units"] - reserved - delivered
    changed |= item["available_units"] != available
    item["reserved_units"] = reserved
    item["delivered_units"] = delivered
    item["available_units"] = available
    if changed:
        touch(item)


# ---------------------------------------------------------- authority selector
def authority_candidates(patient_id):
    rows = [r for r in store.surrogates.values()
            if r["patient_id"] == patient_id and r["status"] == "ACTIVE"]
    rows.sort(key=lambda r: (r["hierarchy_rank"], r["created_at"], r["_seq"]))
    return rows


def lawful_surrogate(patient_id):
    candidates = authority_candidates(patient_id)
    return candidates[0] if candidates else None


def lawful_decision_maker_kind(patient):
    if patient["capacity_status"] == "HAS_CAPACITY":
        return "PATIENT"
    return "SURROGATE" if lawful_surrogate(patient["id"]) else None


# ------------------------------------------------------------- code statuses
def most_recent_executed_status(patient_id):
    docs = [d for d in store.documents.values()
            if d["patient_id"] == patient_id and d["status"] == "EXECUTED"]
    if not docs:
        return "FULL_CODE"
    docs.sort(key=lambda d: (d["created_at"], d["_seq"]))
    docs.sort(key=lambda d: d["executed_at"], reverse=True)
    return docs[0]["stated_code_status"]


def park_in_flight_orders(patient_id):
    for order in rows_for_patient(store.code_status_orders, patient_id):
        if order["status"] in ("DRAFT", "ATTESTED"):
            order["status"] = "CONFLICT_HOLD"
            touch(order)


def rewrite_code_status(patient, new_status):
    """PRD 3.4 — whenever code_status is rewritten this way, in-flight orders park."""
    patient["code_status"] = new_status
    patient["code_status_rank"] = config.CODE_STATUS_RANKS[new_status]
    touch(patient)
    park_in_flight_orders(patient["id"])


def supersede_other_effective_orders(patient_id, keep_id=None):
    for order in rows_for_patient(store.code_status_orders, patient_id):
        if order["status"] == "EFFECTIVE" and order["id"] != keep_id:
            order["status"] = "SUPERSEDED"
            touch(order)


# ------------------------------------------------------- document cascades
def document_execution_cascade(document, patient):
    """Four hops (PRD 2.10)."""
    predecessor_id = document.get("supersedes_document_id")
    if predecessor_id:
        predecessor = store.documents.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "EXECUTED":
            # hop 1
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)
            # hop 2
            for order in rows_for_patient(store.code_status_orders, patient["id"]):
                if (order.get("source_document_id") == predecessor["id"]
                        and order["status"] == "EFFECTIVE"):
                    order["status"] = "SUPERSEDED"
                    touch(order)
    # hops 3 and 4
    rewrite_code_status(patient, document["stated_code_status"])


def document_revocation_cascade(document, patient):
    for order in rows_for_patient(store.code_status_orders, patient["id"]):
        if order.get("source_document_id") == document["id"] and order["status"] == "EFFECTIVE":
            order["status"] = "SUPERSEDED"
            touch(order)
    rewrite_code_status(patient, most_recent_executed_status(patient["id"]))


# ------------------------------------------------------- capacity cascade
def capacity_cascade(patient):
    new_kind = lawful_decision_maker_kind(patient)
    invalidated = []
    for conf in rows_for_patient(store.conferences, patient["id"]):
        if conf["conference_type"] != "FAMILY":
            continue
        if not conf["consent_recorded"]:
            continue
        if conf["status"] not in ("HELD", "ATTESTED"):
            continue
        if conf["decision_maker_kind"] == new_kind:
            continue
        conf["status"] = "CONSENT_INVALIDATED"
        conf["consent_recorded"] = False
        touch(conf)
        invalidated.append(conf)
    if not invalidated:
        return
    # hop 3
    for order in rows_for_patient(store.code_status_orders, patient["id"]):
        if order["status"] == "EFFECTIVE" and order.get("surrogate_stated"):
            order["status"] = "SUPERSEDED"
            touch(order)
    rewrite_code_status(patient, most_recent_executed_status(patient["id"]))
    # parallel leg — claims resting on an invalidated conference fall back to DRAFT
    ids = {c["id"] for c in invalidated}
    for claim in rows_for_patient(store.claims, patient["id"]):
        if claim.get("conference_id") in ids and claim["status"] in ("DRAFT", "ATTESTED"):
            claim["status"] = "DRAFT"
            claim["documentation_attested"] = False
            claim["attested_by_user_id"] = None
            touch(claim)


# ---------------------------------------------------------- death cascade
def death_cascade(patient):
    """Five hops (PRD 2.10). Delivered DME orders are deliberately left open."""
    pid = patient["id"]
    # hop 1 — hospice elections
    for election in rows_for_patient(store.hospice_elections, pid):
        if election["status"] in ("PENDING_CERT", "CERTIFIED", "ELECTED", "REVOKED"):
            election["status"] = "CLOSED_ON_DEATH"
            touch(election)
    # hop 2 — medication orders
    for order in rows_for_patient(store.medication_orders, pid):
        if order["status"] in ("PENDING_VERIFICATION", "ACTIVE", "REVIEW_REQUIRED"):
            order["status"] = "DISCONTINUED"
            touch(order)
    recompute_active_daily_mme(patient)
    # hop 3 — care plans
    closed_plan_ids = set()
    for plan in rows_for_patient(store.care_plans, pid):
        if plan["status"] in ("DRAFT", "ACTIVE", "UNDER_REVISION"):
            plan["status"] = "CLOSED"
            plan["closed_reason"] = "PATIENT_DEATH"
            touch(plan)
            closed_plan_ids.add(plan["id"])
    # hop 4 — symptom assessments filed under those plans
    resolved_ids = set()
    for row in store.symptom_assessments.values():
        if row["care_plan_id"] in closed_plan_ids and row["triage_status"] in ("OPEN", "ACKNOWLEDGED"):
            row["triage_status"] = "RESOLVED"
            row["resolution_reason"] = "PLAN_CLOSED"
            touch(row)
            resolved_ids.add(row["id"])
    recompute_open_symptom_count(patient)
    # hop 5 — escalations naming one of those assessments
    for esc in store.escalations.values():
        if (esc["symptom_assessment_id"] in resolved_ids
                and esc["status"] in ("TIER_NOTIFIED", "ACKNOWLEDGED", "DISPOSITIONED")):
            esc["status"] = "CLOSED"
            esc["disposition"] = "ADMINISTRATIVE_CLOSE"
            touch(esc)

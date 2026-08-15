"""Derived (computed) fields and the build-sequence calculation.

All aggregate fields are recomputed from live state on every read, so they can
never drift: Job.posture, CustomerAccount.credit_used_cents, Job.invoiced_cents,
Job.credit_issued_cents, DeliveryLoad.actual_total_weight_lbs.
"""

from decimal import Decimal

import db

OPEN_CLAIM_STATUSES = {"FILED", "TRIAGED", "APPROVED_REBUILD", "APPROVED_CREDIT", "REBUILD_IN_PROGRESS"}


# ---------------------------------------------------------------------------
# Job posture (PRD section 2.10): BLOCKED > AT_RISK > GREEN, first tier wins
# ---------------------------------------------------------------------------

def job_posture(job):
    customer = db.customers.get(job["customer_id"])
    if customer and customer["credit_hold"]:
        return "BLOCKED"
    jid = job["id"]
    for co in db.design_change_orders.values():
        if co["job_id"] == jid and co["status"] == "APPROVED":
            return "BLOCKED"
    for cl in db.cut_lists.values():
        if cl["job_id"] == jid and cl["status"] == "RECONCILING":
            return "BLOCKED"
    load_ids = {l["id"] for l in db.delivery_loads.values() if l["job_id"] == jid}
    for c in db.damage_claims.values():
        if c["delivery_load_id"] in load_ids and c["status"] in {"APPROVED_REBUILD", "REBUILD_IN_PROGRESS"}:
            return "BLOCKED"
    for b in db.production_batches.values():
        if b["job_id"] == jid and b["status"] in {"QC_FAILED", "REWORK"}:
            return "AT_RISK"
    for l in db.delivery_loads.values():
        if l["job_id"] == jid and l["status"] == "RETURNED":
            return "AT_RISK"
    for d in db.designs.values():
        if d["job_id"] == jid and d["status"] == "SEAL_REQUESTED":
            return "AT_RISK"
    return "GREEN"


# ---------------------------------------------------------------------------
# Customer credit exposure (PRD section 3.1)
# ---------------------------------------------------------------------------

def credit_used_cents(customer_id):
    total = 0
    for l in db.delivery_loads.values():
        job = db.jobs.get(l["job_id"])
        if not job or job["customer_id"] != customer_id:
            continue
        if l["status"] in ("PLANNED", "STAGED", "LOADING"):
            total += l["provisional_freight_cents"]
        elif l["status"] in ("DISPATCHED", "DELIVERED", "RETURNED", "RESCHEDULED", "CLAIM_HOLD", "CLOSED"):
            total += l["final_freight_cents"] or 0
        # CANCELLED contributes 0
    return total


# ---------------------------------------------------------------------------
# Job money fields (PRD section 3.2)
# ---------------------------------------------------------------------------

def job_invoiced_cents(job):
    total = job["contracted_value_cents"]
    for l in db.delivery_loads.values():
        if l["job_id"] == job["id"] and l["status"] == "CLOSED":
            total += l["final_freight_cents"] or 0
    return total


def job_credit_issued_cents(job):
    load_ids = {l["id"] for l in db.delivery_loads.values() if l["job_id"] == job["id"]}
    total = 0
    for c in db.damage_claims.values():
        if c["delivery_load_id"] in load_ids and c["status"] == "SETTLED":
            total += c["residual_credit_cents"] or 0
    return total


# ---------------------------------------------------------------------------
# DeliveryLoad.actual_total_weight_lbs — SUPERSEDED bundles excluded
# ---------------------------------------------------------------------------

def load_actual_weight(load):
    total = Decimal("0")
    for b in db.bundles.values():
        if b["delivery_load_id"] == load["id"] and b["status"] in (
            "PACKED", "LOADED", "DELIVERED", "RETURNED", "DAMAGED"
        ):
            total += b["weight_lbs"]
    return total


# ---------------------------------------------------------------------------
# Design currency (PRD section 3.3): the SEALED revision with the highest
# revision_no for its (job, component_ref) pair that is not SUPERSEDED.
# ---------------------------------------------------------------------------

def design_is_current(design):
    if design["status"] != "SEALED":
        return False
    best = None
    for d in db.designs.values():
        if (
            d["job_id"] == design["job_id"]
            and d["component_ref"] == design["component_ref"]
            and d["status"] == "SEALED"
        ):
            if best is None or d["revision_no"] > best:
                best = d["revision_no"]
    return best is not None and design["revision_no"] == best


# ---------------------------------------------------------------------------
# Build sequencing (calculation build_sequence_ordering): candidate set is the
# job's batches not in {CANCELLED, LOADED}; sort by requested_completion_at,
# then greedy changeover minimization within equal groups, created_at ties.
# ---------------------------------------------------------------------------

DEFAULT_CHANGEOVER_MINUTES = 60


def _changeover_minutes(prev_jig, target_jig):
    if prev_jig["setup_code"] == target_jig["setup_code"]:
        return 0
    entry = target_jig["changeover_minutes_from"].get(prev_jig["setup_code"])
    return entry if entry is not None else DEFAULT_CHANGEOVER_MINUTES


def resequence_job_batches(job_id):
    candidates = [
        b for b in db.production_batches.values()
        if b["job_id"] == job_id and b["status"] not in ("CANCELLED", "LOADED")
    ]
    # Group by exactly-equal requested_completion_at, groups ascending.
    by_rca = {}
    for b in candidates:
        by_rca.setdefault(b["requested_completion_at"], []).append(b)
    ordered = []
    for rca in sorted(by_rca):
        remaining = sorted(by_rca[rca], key=lambda b: b["_seq"])
        prev = None
        while remaining:
            if prev is None:
                pick = remaining[0]  # group anchor: earliest created_at
            else:
                prev_jig = db.jig_setups[prev["jig_setup_id"]]
                pick = min(
                    remaining,
                    key=lambda b: (
                        _changeover_minutes(prev_jig, db.jig_setups[b["jig_setup_id"]]),
                        b["_seq"],
                    ),
                )
            ordered.append(pick)
            remaining.remove(pick)
            prev = pick
    for index, batch in enumerate(ordered, start=1):
        if batch.get("build_sequence_no") != index:
            batch["build_sequence_no"] = index
            db.touch(batch)

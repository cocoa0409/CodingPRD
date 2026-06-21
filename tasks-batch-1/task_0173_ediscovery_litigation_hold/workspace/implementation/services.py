"""Business-logic services: computed-field recomputation, calculations, cascades.

All cross-entity recomputation and state-machine side effects live here so the
route handlers stay thin and the consistency rules stay in one place.
"""
from decimal import Decimal

import clock
import db
from helpers import round_half_up

PER_PAGE_RATE_CENTS = Decimal("7.3")
BATES_PAD_WIDTH = 6

# spoliation constants
PER_UNACK_WEIGHT = 15
PER_DAY_WEIGHT = 2
DAYS_CAP = 30
TIER_LOW = 100
TIER_HIGH = 1000
SCORE_CEILING = 100


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------
def custodians_of_matter(matter_id):
    return [c for c in db.custodians.values() if c["matter_id"] == matter_id]


def active_legal_hold(matter_id):
    """The matter's non-RELEASED hold, if any (the live hold notice).

    A matter has at most one active hold notice driving its hold_status. We
    consider any hold in DRAFT/ISSUED/ACKNOWLEDGED as candidate; the one that
    is ISSUED or ACKNOWLEDGED is the active issued hold.
    """
    holds = [h for h in db.legal_holds.values() if h["matter_id"] == matter_id]
    for h in holds:
        if h["status"] in ("ISSUED", "ACKNOWLEDGED"):
            return h
    return None


def documents_of_scope(scope_id):
    return [d for d in db.documents.values() if d["scope_id"] == scope_id]


def documents_of_matter(matter_id):
    return [d for d in db.documents.values() if d["matter_id"] == matter_id]


def reviews_of_batch(batch_id):
    return [r for r in db.document_reviews.values() if r["batch_id"] == batch_id]


def items_of_set(set_id):
    return [i for i in db.production_items.values() if i["set_id"] == set_id]


# --------------------------------------------------------------------------
# Matter computed rollups
# --------------------------------------------------------------------------
def recompute_custodian_count(matter):
    matter["custodian_count"] = len(custodians_of_matter(matter["id"]))


def recompute_ack_fields(matter):
    """acknowledged_count, ack_rate (PRD §3.2)."""
    custs = custodians_of_matter(matter["id"])
    acked = [c for c in custs if c["ack_state"] == "ACKNOWLEDGED"]
    matter["acknowledged_count"] = len(acked)
    if matter["custodian_count"] == 0:
        matter["ack_rate"] = round_half_up(0, 2)
    else:
        rate = Decimal(len(acked)) / Decimal(matter["custodian_count"])
        matter["ack_rate"] = round_half_up(rate, 2)
    # represent ack_rate as float for JSON (2dp)
    matter["ack_rate"] = float(matter["ack_rate"])


def recompute_responsive_doc_count(matter):
    """Count this matter's UNIQUE docs tagged RESPONSIVE across COMPLETED batches.

    A document is counted if it is UNIQUE, responsiveness_tag==RESPONSIVE, and it
    appears in at least one COMPLETED ReviewBatch on this matter.
    """
    completed_batch_ids = {
        b["id"] for b in db.review_batches.values()
        if b["matter_id"] == matter["id"] and b["status"] == "COMPLETED"
    }
    doc_ids_in_completed = set()
    for r in db.document_reviews.values():
        if r["batch_id"] in completed_batch_ids:
            doc_ids_in_completed.add(r["document_id"])
    count = 0
    for doc_id in doc_ids_in_completed:
        d = db.documents.get(doc_id)
        if d and d["status"] == "UNIQUE" and d["responsiveness_tag"] == "RESPONSIVE":
            count += 1
    matter["responsive_doc_count"] = count


def recompute_produced_counts(matter):
    """produced_document_count and clawed_back_document_count (PRD §3.8).

    produced_document_count: ProductionItems across this matter's PRODUCED sets
        whose status is not CLAWED_BACK.
    clawed_back_document_count: ProductionItems across this matter's sets that
        are CLAWED_BACK.
    """
    set_status = {}
    set_matter = {}
    for s in db.production_sets.values():
        set_status[s["id"]] = s["status"]
        set_matter[s["id"]] = s["matter_id"]
    produced = 0
    clawed = 0
    for item in db.production_items.values():
        if set_matter.get(item["set_id"]) != matter["id"]:
            continue
        if item["status"] == "CLAWED_BACK":
            clawed += 1
        elif set_status.get(item["set_id"]) == "PRODUCED" and item["status"] != "CLAWED_BACK":
            produced += 1
    matter["produced_document_count"] = produced
    matter["clawed_back_document_count"] = clawed


# --------------------------------------------------------------------------
# Spoliation risk (PRD §3.3)
# --------------------------------------------------------------------------
def _days_since_issued(matter):
    hold = active_legal_hold(matter["id"])
    if hold is None or not hold.get("issued_at"):
        return 0
    issued = clock.parse_iso(hold["issued_at"])
    if issued is None:
        return 0
    delta = clock.now() - issued
    days = delta.days
    if days < 0:
        days = 0
    return days


def _risk_from_u(matter, u):
    d = _days_since_issued(matter)
    base = (u * PER_UNACK_WEIGHT) + (min(d, DAYS_CAP) * PER_DAY_WEIGHT)
    r = matter["responsive_doc_count"]
    if r < TIER_LOW:
        mult = Decimal("1.0")
    elif r < TIER_HIGH:
        mult = Decimal("1.2")
    else:
        mult = Decimal("1.5")
    score = round_half_up(Decimal(base) * mult, 0)
    return min(SCORE_CEILING, score)


def provisional_risk(matter):
    """U = every custodian whose ack_state != ACKNOWLEDGED."""
    custs = custodians_of_matter(matter["id"])
    u = sum(1 for c in custs if c["ack_state"] != "ACKNOWLEDGED")
    return _risk_from_u(matter, u)


def final_risk(matter):
    """U = custodians with NO HoldAcknowledgement record at all on active hold."""
    hold = active_legal_hold(matter["id"])
    custs = custodians_of_matter(matter["id"])
    if hold is None:
        # No issued hold: every custodian has no ack record.
        u = len(custs)
        return _risk_from_u(matter, u)
    custs_with_ack = {
        a["custodian_id"] for a in db.hold_acknowledgements.values()
        if a["hold_id"] == hold["id"]
    }
    u = sum(1 for c in custs if c["id"] not in custs_with_ack)
    return _risk_from_u(matter, u)


def recompute_spoliation(matter):
    matter["spoliation_risk_score"] = final_risk(matter)


# --------------------------------------------------------------------------
# Collection volume (PRD §3.4)
# --------------------------------------------------------------------------
def recompute_scope_collected_count(scope):
    """collected_actual_count: docs under scope with status COLLECTED or later."""
    later = {"COLLECTED", "UNIQUE", "DUPLICATE", "PURGEABLE"}
    docs = documents_of_scope(scope["id"])
    scope["collected_actual_count"] = sum(1 for d in docs if d["status"] in later)


def collection_summary(matter_id):
    scopes = [s for s in db.collection_scopes.values() if s["matter_id"] == matter_id]
    estimate = sum(
        s["expected_doc_count"] for s in scopes
        if s["status"] in ("DEFINED", "COLLECTING")
    )
    actual = sum(
        s["collected_actual_count"] for s in scopes
        if s["status"] in ("COLLECTED", "PROCESSED", "RELEASED")
    )
    return estimate, actual


# --------------------------------------------------------------------------
# Dedup (PRD §3.5) — matter-wide content_hash dedup
# --------------------------------------------------------------------------
def run_dedup(job):
    """Process COLLECTED docs under job.scope_id in created_at ASC order.

    Dedup key is matter-wide: a hash already first-seen by an earlier COMPLETED
    job on the same matter makes a new document a DUPLICATE across scopes.
    """
    matter_id = job["matter_id"]
    # seed seen-map with hashes already UNIQUE on the matter from prior jobs.
    seen = {}
    prior_unique = [
        d for d in db.documents.values()
        if d["matter_id"] == matter_id and d["status"] == "UNIQUE"
    ]
    prior_unique.sort(key=lambda d: (d.get("created_at", ""), d.get("_seq", 0)))
    for d in prior_unique:
        if d["content_hash"] not in seen:
            seen[d["content_hash"]] = d["id"]

    docs = [d for d in documents_of_scope(job["scope_id"]) if d["status"] == "COLLECTED"]
    docs.sort(key=lambda d: (d.get("created_at", ""), d.get("_seq", 0)))

    unique = 0
    duplicate = 0
    for d in docs:
        h = d["content_hash"]
        if h in seen:
            d["status"] = "DUPLICATE"
            d["duplicate_of_id"] = seen[h]
            db.touch(d)
            duplicate += 1
        else:
            d["status"] = "UNIQUE"
            seen[h] = d["id"]
            db.touch(d)
            unique += 1
    job["unique_count"] = unique
    job["duplicate_count"] = duplicate


# --------------------------------------------------------------------------
# Production cost (PRD §2.7) — round per document then sum
# --------------------------------------------------------------------------
def production_cost_cents(item_docs):
    total = 0
    for d in item_docs:
        per_doc = round_half_up(Decimal(d["page_count"]) * PER_PAGE_RATE_CENTS, 0)
        total += per_doc
    return total


# --------------------------------------------------------------------------
# Bates allocation (PRD §2.7 / §3.7)
# --------------------------------------------------------------------------
def allocate_bates(matter, pset, items):
    """items must be the set's ProductionItems; allocate sequential Bates labels
    in ascending Document.created_at order (tie-break created_at then seq)."""
    def doc_key(item):
        d = db.documents.get(item["document_id"])
        return (d.get("created_at", ""), d.get("_seq", 0))

    ordered = sorted(items, key=doc_key)
    start = matter["next_bates_seq"]
    seq = start
    prefix = matter["bates_prefix"]
    for item in ordered:
        item["bates_number"] = prefix + str(seq).zfill(BATES_PAD_WIDTH)
        seq += 1
    pset["bates_start"] = start
    pset["bates_end"] = seq - 1
    matter["next_bates_seq"] = seq

    docs = [db.documents.get(i["document_id"]) for i in ordered]
    pset["produced_page_count"] = production_cost_cents([d for d in docs if d])


# --------------------------------------------------------------------------
# Hold-release cascade (PRD §2.5) — three numbered hops, atomic
# --------------------------------------------------------------------------
def cascade_release_hold(matter):
    """Hop 1: active hold notice -> RELEASED.
    Hop 2: every COLLECTED/PROCESSED scope on matter -> RELEASED.
    Hop 3: every non-PURGEABLE doc under released scope -> PURGEABLE;
           owning custodian retention_released = true.
    """
    # hop 1
    hold = active_legal_hold(matter["id"])
    if hold is not None:
        hold["status"] = "RELEASED"
        db.touch(hold)

    # hop 2
    scopes = [
        s for s in db.collection_scopes.values()
        if s["matter_id"] == matter["id"] and s["status"] in ("COLLECTED", "PROCESSED")
    ]
    for scope in scopes:
        scope["status"] = "RELEASED"
        db.touch(scope)
        # hop 3
        for d in documents_of_scope(scope["id"]):
            if d["status"] != "PURGEABLE":
                d["status"] = "PURGEABLE"
                db.touch(d)
        cust = db.custodians.get(scope["custodian_id"])
        if cust is not None and not cust.get("retention_released"):
            cust["retention_released"] = True
            db.touch(cust)

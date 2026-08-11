"""Pricing and storage fee calculations per SCAFFOLD §1.3 / PRD §3.6."""

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db

STANDARD_PAGE_RATE = Decimal("0.45")
VOLUME_PAGE_RATE = Decimal("0.30")
MAX_REJECT_FRACTION = 0.10
RUSH_ADMISSION_LIMIT = 3
MIN_OCR_CONFIDENCE = 70

PROVISIONAL_STATUSES = {"SCANNED", "QA_FAILED", "INDEXED", "DELIVERED", "REJECTED"}
FINAL_STATUSES = {"SCANNED", "INDEXED", "DELIVERED"}
PRE_DELIVERY_STATES = {"INTAKE", "PREPPING", "SCANNING", "QA", "INDEXING"}


def page_rate(batch, agreement):
    base = VOLUME_PAGE_RATE if agreement["price_tier"] == "VOLUME" else STANDARD_PAGE_RATE
    if batch["priority"] == "RUSH":
        base = base * Decimal(str(agreement["rush_multiplier"]))
    return base


def document_charge_cents(doc_pages, rate):
    """Round each document's charge to cents FIRST (round-half-up), then sum."""
    cents = Decimal(doc_pages) * rate * Decimal(100)
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def batch_documents(batch_id):
    return [d for d in db.documents.values() if d["batch_id"] == batch_id]


def page_subtotal_cents(batch, agreement):
    """Variant selected by batch state: provisional pre-DELIVERED, final from delivery on."""
    rate = page_rate(batch, agreement)
    docs = batch_documents(batch["id"])
    if batch["status"] in PRE_DELIVERY_STATES:
        docset = [d for d in docs if d["status"] in PROVISIONAL_STATUSES]
    else:
        docset = [d for d in docs if d["status"] in FINAL_STATUSES]
    return sum(document_charge_cents(d["pages"], rate) for d in docset)


def chargeable_days(delivered_at_iso, as_of, free_days):
    delivered = _parse(delivered_at_iso)
    delta_seconds = (as_of - delivered).total_seconds()
    whole_days = math.floor(delta_seconds / 86400)
    return max(0, whole_days - free_days)


def storage_fee_total(batch, agreement, as_of):
    """Sum per-box fees over boxes in STORED / SCAN_COMPLETE / AWAITING_DISPOSITION."""
    if not batch.get("delivered_at"):
        return 0
    total = 0
    for box in db.boxes.values():
        if box["batch_id"] != batch["id"]:
            continue
        if box["status"] not in ("STORED", "SCAN_COMPLETE", "AWAITING_DISPOSITION"):
            continue
        days = chargeable_days(batch["delivered_at"], as_of, agreement["storage_free_days"])
        total += days * agreement["storage_daily_rate_cents"]
    return total


def compute_invoice_subtotals(inv):
    """(page_subtotal_cents, storage_subtotal_cents) for a DRAFT invoice read."""
    batch = db.batches.get(inv["batch_id"])
    agreement = None
    for a in db.service_agreements.values():
        if a["client_id"] == inv["client_id"]:
            agreement = a
            break
    if not batch or not agreement:
        return inv.get("page_subtotal_cents", 0), inv.get("storage_subtotal_cents", 0)
    page_sub = page_subtotal_cents(batch, agreement)
    storage_sub = storage_fee_total(batch, agreement, db.current_utc)
    return page_sub, storage_sub


def batch_indexable(batch):
    """PRD §3.6: >= 1 doc, all in INDEXED/DELIVERED/REJECTED, REJECTED <= max(1, floor(10%))."""
    docs = batch_documents(batch["id"])
    if len(docs) < 1:
        return False
    for d in docs:
        if d["status"] not in ("INDEXED", "DELIVERED", "REJECTED"):
            return False
    rejected = sum(1 for d in docs if d["status"] == "REJECTED")
    allowance = max(1, math.floor(MAX_REJECT_FRACTION * len(docs)))
    return rejected <= allowance


def admitted_rush_count():
    return sum(
        1
        for b in db.batches.values()
        if b["priority"] == "RUSH"
        and b["status"] in ("INTAKE", "PREPPING", "SCANNING", "QA", "INDEXING")
    )


def _parse(iso):
    s = iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

"""Pricing calculations: quote, final_payout, quality_deduction, tax."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from db import store
from services.common import round_half_up_cents

REP_TIER = {
    "NEW": 10000,
    "FUZZY": 6000,
    "TM_LEVERAGE": 3000,
    "EXACT_REPEAT": 1500,
}
URGENCY_MULT = {
    "STANDARD": 10000,
    "RUSH": 12500,
    "CRITICAL": 15000,
}
GRADE_MULT = {
    "JUNIOR": 8000,
    "INTERMEDIATE": 10000,
    "SENIOR": 12000,
    "EXPERT": 14000,
}

QUALITY_BAR = 90
QUALITY_DEDUCTION_PER_POINT_BPS = 50


def _unit_qty(seg: dict, mode: str) -> int:
    if mode == "PER_WORD":
        return int(seg["word_count"])
    if mode == "PER_SEGMENT":
        return 1
    if mode == "PER_FILE":
        return 1 if int(seg["ordinal"]) == 1 else 0
    return 0


def segments_for_project(project_id: str, *, only_split: bool = False, only_final_approved: bool = False):
    """Return segments under project, ordered by (document_id, ordinal)."""
    segs = []
    for seg in store.segments.values():
        if seg["project_id"] != project_id:
            continue
        doc = store.documents.get(seg["document_id"])
        if doc is None:
            continue
        if only_split and doc["state"] != "SPLIT":
            continue
        if only_final_approved and seg["state"] != "FINAL_APPROVED":
            continue
        segs.append(seg)
    segs.sort(key=lambda s: (s["document_id"], s["ordinal"]))
    return segs


def compute_quote(project: dict) -> tuple[int, list[dict]]:
    """Forward-looking quote assuming SENIOR multiplier. Returns (quoted_total_cents, per_segment)."""
    mode = project["unit_pricing_mode"]
    base = int(project["base_unit_price_cents"])
    urgency = project.get("urgency_tier") or "STANDARD"
    segs = segments_for_project(project["id"], only_split=True)

    per_segment = []
    subtotal = 0
    for seg in segs:
        qty = _unit_qty(seg, mode)
        rep_bps = REP_TIER[seg["repetition_class"]]
        grade_bps = 10000  # SENIOR baseline
        base_cents = Decimal(base) * Decimal(qty)
        rep_adj = round_half_up_cents(base_cents * Decimal(rep_bps) / Decimal(10000))
        graded = round_half_up_cents(Decimal(rep_adj) * Decimal(grade_bps) / Decimal(10000))
        subtotal += graded
        per_segment.append({"segment_id": seg["id"], "graded_cents": graded})

    urgency_bps = URGENCY_MULT[urgency]
    quoted = round_half_up_cents(Decimal(subtotal) * Decimal(urgency_bps) / Decimal(10000))
    return quoted, per_segment


def compute_translator_credit(segment_id: str) -> str | None:
    """Find the translator credited with the segment translation:
    assignee of the most recently COMPLETED TRANSLATOR-role Assignment covering the segment.
    Fallback: most recent ACCEPTED TRANSLATOR-role assignment.
    """
    candidates_completed = []
    candidates_accepted = []
    for a in store.assignments.values():
        if a["role"] != "TRANSLATOR":
            continue
        if segment_id not in a["segment_ids"]:
            continue
        if a["state"] == "COMPLETED":
            candidates_completed.append(a)
        elif a["state"] == "ACCEPTED":
            candidates_accepted.append(a)
    pool = candidates_completed or candidates_accepted
    if not pool:
        return None
    pool.sort(key=lambda x: x["updated_at"], reverse=True)
    return pool[0]["translator_id"]


def compute_final_payout(project: dict) -> tuple[int, list[dict]]:
    """Walks FINAL_APPROVED segments and computes final payout w/ grade & quality deduction."""
    mode = project["unit_pricing_mode"]
    base = int(project["base_unit_price_cents"])
    urgency = project.get("urgency_tier") or "STANDARD"
    segs = segments_for_project(project["id"], only_final_approved=True)

    per_segment = []
    subtotal = 0
    for seg in segs:
        qty = _unit_qty(seg, mode)
        rep_bps = REP_TIER[seg["repetition_class"]]
        translator_id = compute_translator_credit(seg["id"])
        grade = "SENIOR"
        if translator_id:
            tr = store.translators.get(translator_id)
            if tr:
                grade = tr["grade"]
        grade_bps = GRADE_MULT[grade]
        base_cents = Decimal(base) * Decimal(qty)
        rep_adj = round_half_up_cents(base_cents * Decimal(rep_bps) / Decimal(10000))
        graded = round_half_up_cents(Decimal(rep_adj) * Decimal(grade_bps) / Decimal(10000))
        subtotal += graded
        per_segment.append({"segment_id": seg["id"], "graded_cents": graded, "translator_id": translator_id})

    urgency_bps = URGENCY_MULT[urgency]
    urgency_cents = round_half_up_cents(Decimal(subtotal) * Decimal(urgency_bps) / Decimal(10000))

    # Quality deduction
    seg_id_to_graded = {ps["segment_id"]: ps["graded_cents"] for ps in per_segment}
    total_ded = 0
    for q in store.quality_scores.values():
        if q["state"] != "FINALIZED":
            continue
        if q["segment_id"] not in seg_id_to_graded:
            continue
        deficit = max(0, QUALITY_BAR - float(q["score"]))
        ded_bps = int(deficit * QUALITY_DEDUCTION_PER_POINT_BPS)
        if ded_bps <= 0:
            continue
        seg_cents = seg_id_to_graded[q["segment_id"]]
        seg_ded = round_half_up_cents(Decimal(seg_cents) * Decimal(ded_bps) / Decimal(10000))
        total_ded += seg_ded

    final_payout = max(0, urgency_cents - total_ded)
    return final_payout, per_segment


def compute_tax(final_payout_cents: int, tax_rate_bps: int) -> int:
    return round_half_up_cents(Decimal(final_payout_cents) * Decimal(tax_rate_bps) / Decimal(10000))


def repetition_rate(project_id: str) -> float:
    """Sum of word_count over EXACT_REPEAT segments / project word_count."""
    segs = segments_for_project(project_id, only_split=True)
    total = sum(s["word_count"] for s in segs)
    if total == 0:
        return 0.0
    repeat_total = sum(s["word_count"] for s in segs if s["repetition_class"] == "EXACT_REPEAT")
    return repeat_total / total


# Minimum unit price required when repetition rate reaches 75%
MIN_HIGH_REPETITION_PRICE_CENTS = 50
REPETITION_HIGH_THRESHOLD = 0.75

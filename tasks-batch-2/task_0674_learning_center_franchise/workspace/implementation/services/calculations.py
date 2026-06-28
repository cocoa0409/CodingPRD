"""Calculation rules (SCAFFOLD §1.3, PRD §3.4, §3.6, §3.7).

All monetary amounts are integer cents. Discounts floor after EACH step.
Royalty terms floor per-term before summing.
"""
import math

from db import db


# --------------------------------------------------------------------------
# Curriculum-level ordering helper
# --------------------------------------------------------------------------
def levels_for_subject(subject_id):
    """All CurriculumLevels for the subject, sorted by rank ASC, tie-break
    created_at ASC (insertion order via _seq)."""
    lvls = [l for l in db.levels.values() if l["subject_id"] == subject_id]
    lvls.sort(key=lambda l: (l["rank"], l["_seq"]))
    return lvls


# --------------------------------------------------------------------------
# diagnostic_placement (dual-variant #1) — PRD §3.3
# --------------------------------------------------------------------------
def diagnostic_placement(subject_id, diagnostic_raw_score, placement_policy):
    """Returns the placement_level dict, or None if subject has no levels."""
    levels = levels_for_subject(subject_id)
    n = len(levels)
    if n == 0:
        return None
    band_width = math.ceil(100 / n)
    target_index = min(diagnostic_raw_score // band_width, n - 1)
    if placement_policy == "SUPPORTIVE":
        idx = max(0, target_index - 1)
    else:  # STRICT (default)
        idx = target_index
    return levels[idx]


# --------------------------------------------------------------------------
# tuition_rate (combinatorial mode a) — PRD §3.6
# --------------------------------------------------------------------------
def _student_active_enrollments_ordered(student_id):
    """ACTIVE enrollments of a student, ordered by created_at ASC, tie-break by
    created_at alone (insertion order via _seq) — id tie-break FORBIDDEN."""
    enrs = [
        e for e in db.enrollments.values()
        if e["student_id"] == student_id and e["status"] == "ACTIVE"
    ]
    enrs.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return enrs


def family_sibling_count(family_id):
    """Number of Students in the family with >= 1 ACTIVE enrollment."""
    student_ids = {s["id"] for s in db.students.values() if s["family_id"] == family_id}
    count = 0
    for sid in student_ids:
        has_active = any(
            e["student_id"] == sid and e["status"] == "ACTIVE"
            for e in db.enrollments.values()
        )
        if has_active:
            count += 1
    return count


def _multi_subject_pct(subject_index):
    if subject_index == 1:
        return 0.0
    if subject_index == 2:
        return 0.10
    return 0.15  # >= 3


def _sibling_pct(sibling_count):
    if sibling_count <= 1:
        return 0.0
    if sibling_count == 2:
        return 0.05
    return 0.10  # >= 3


def compute_monthly_rate(enrollment, base_monthly_tuition_cents, sibling_count):
    """Per-enrollment monthly_rate_cents. Discounts applied multiplicatively in
    pinned order: multi-subject first, then sibling. Floor after each step."""
    ordered = _student_active_enrollments_ordered(enrollment["student_id"])
    subject_index = None
    for i, e in enumerate(ordered, start=1):
        if e["id"] == enrollment["id"]:
            subject_index = i
            break
    if subject_index is None:
        # Enrollment not ACTIVE -> no rate computed here.
        subject_index = 1

    multi_pct = _multi_subject_pct(subject_index)
    sib_pct = _sibling_pct(sibling_count)

    base = base_monthly_tuition_cents
    after_multi = math.floor(base * (1 - multi_pct))
    monthly_rate = math.floor(after_multi * (1 - sib_pct))
    return monthly_rate


# --------------------------------------------------------------------------
# royalty_owed (dual-variant #2) — PRD §3.7
# --------------------------------------------------------------------------
def royalty_owed(tuition_component_cents, agreement):
    """Royalty owed over tuition only. Floor each bps term before combining."""
    rate_bps = agreement["royalty_rate_bps"]
    mkt_bps = agreement["marketing_fee_bps"]
    minimum = agreement["minimum_monthly_royalty_cents"]
    basis = agreement["royalty_basis"]

    percentage_royalty = math.floor(tuition_component_cents * rate_bps / 10000)
    marketing = math.floor(tuition_component_cents * mkt_bps / 10000)

    if basis == "COMBINED_FLOOR":
        return max(percentage_royalty + marketing, minimum)
    # ROYALTY_FLOOR (default): floor applies to percentage royalty alone
    return max(percentage_royalty, minimum) + marketing
